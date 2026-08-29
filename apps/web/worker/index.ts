const PILOT_SENDER_ADDRESS = "pilot@ctrldoc.tech";
const MAX_BODY_BYTES = 4_096;
const SCENARIOS = new Set(["RFP", "RFI", "ТЗ", "Анкета по ИБ", "Другое"]);
const ALLOWED_FIELDS = new Set(["name", "email", "company", "scenario", "website"]);

type PilotApplication = {
  name: string;
  email: string;
  company: string;
  scenario: string;
};

class RequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function jsonResponse(status: number, body: unknown, extraHeaders: HeadersInit = {}) {
  return Response.json(body, {
    status,
    headers: {
      "cache-control": "no-store",
      ...extraHeaders,
    },
  });
}

async function readLimitedBody(request: Request) {
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null) {
    const parsedLength = Number(declaredLength);
    if (Number.isFinite(parsedLength) && parsedLength > MAX_BODY_BYTES) {
      throw new RequestError(413, "body_too_large", "Данные формы слишком длинные.");
    }
  }

  if (!request.body) {
    throw new RequestError(400, "invalid_json", "Тело запроса должно содержать JSON.");
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalBytes += value.byteLength;
    if (totalBytes > MAX_BODY_BYTES) {
      await reader.cancel();
      throw new RequestError(413, "body_too_large", "Данные формы слишком длинные.");
    }
    chunks.push(value);
  }

  const body = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }

  try {
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(body);
  } catch {
    throw new RequestError(400, "invalid_json", "Тело запроса содержит некорректный текст.");
  }
}

function requireField(
  source: Record<string, unknown>,
  field: string,
  label: string,
  maxLength: number,
) {
  const value = source[field];
  if (typeof value !== "string") {
    throw new RequestError(400, "invalid_fields", `Заполните поле «${label}».`);
  }

  const trimmed = value.trim();
  if (!trimmed) {
    throw new RequestError(400, "invalid_fields", `Заполните поле «${label}».`);
  }
  const containsControlCharacter = Array.from(trimmed).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint <= 31 || codePoint === 127;
  });
  if (trimmed.length > maxLength || containsControlCharacter) {
    throw new RequestError(400, "invalid_fields", `Проверьте поле «${label}».`);
  }
  return trimmed;
}

function validateApplication(value: unknown): PilotApplication {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new RequestError(400, "invalid_fields", "Проверьте заполнение формы.");
  }

  const source = value as Record<string, unknown>;
  if (Object.keys(source).some((key) => !ALLOWED_FIELDS.has(key))) {
    throw new RequestError(400, "invalid_fields", "Запрос содержит неизвестные поля.");
  }

  const honeypot = source.website;
  if (honeypot !== undefined && (typeof honeypot !== "string" || honeypot.trim())) {
    throw new RequestError(400, "invalid_fields", "Проверьте заполнение формы.");
  }

  const name = requireField(source, "name", "Имя", 120);
  const email = requireField(source, "email", "Рабочий email", 254).toLowerCase();
  const company = requireField(source, "company", "Компания", 160);
  const scenario = requireField(source, "scenario", "Что хотите проверить?", 32);

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/u.test(email)) {
    throw new RequestError(400, "invalid_email", "Укажите корректный рабочий email.");
  }
  if (!SCENARIOS.has(scenario)) {
    throw new RequestError(400, "invalid_scenario", "Выберите сценарий из списка.");
  }

  return { name, email, company, scenario };
}

async function parseApplication(request: Request) {
  const contentType = request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
  if (contentType !== "application/json") {
    throw new RequestError(415, "unsupported_media_type", "Отправьте данные в формате JSON.");
  }

  const rawBody = await readLimitedBody(request);
  let value: unknown;
  try {
    value = JSON.parse(rawBody);
  } catch {
    throw new RequestError(400, "invalid_json", "Не удалось прочитать данные формы.");
  }
  return validateApplication(value);
}

export async function handlePilotRequest(request: Request, env: Env) {
  if (request.method !== "POST") {
    return jsonResponse(
      405,
      { ok: false, error: { code: "method_not_allowed", message: "Используйте метод POST." } },
      { allow: "POST" },
    );
  }

  let application: PilotApplication;
  try {
    application = await parseApplication(request);
  } catch (error) {
    if (error instanceof RequestError) {
      return jsonResponse(error.status, {
        ok: false,
        error: { code: error.code, message: error.message },
      });
    }
    return jsonResponse(400, {
      ok: false,
      error: { code: "invalid_request", message: "Не удалось прочитать данные формы." },
    });
  }

  try {
    await env.PILOT_EMAIL.send({
      to: env.PILOT_DESTINATION_ADDRESS,
      from: { email: PILOT_SENDER_ADDRESS, name: "CTRL DOC" },
      subject: `Новая заявка на пилот CTRL DOC — ${application.company}`,
      text: [
        `Время (UTC): ${new Date().toISOString()}`,
        `Имя: ${application.name}`,
        `Рабочий email: ${application.email}`,
        `Компания: ${application.company}`,
        `Сценарий: ${application.scenario}`,
      ].join("\n"),
    });
  } catch {
    console.error(JSON.stringify({ event: "pilot_email_send_failed" }));
    return jsonResponse(502, {
      ok: false,
      error: { code: "email_delivery_failed", message: "Не удалось отправить заявку." },
    });
  }

  return jsonResponse(200, { ok: true });
}

export default {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/pilot") {
      return handlePilotRequest(request, env);
    }
    if (url.pathname.startsWith("/api/")) {
      return jsonResponse(404, {
        ok: false,
        error: { code: "not_found", message: "Маршрут API не найден." },
      });
    }
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;
