// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { handlePilotRequest } from "./index";

const validApplication = {
  name: "Анна Иванова",
  email: "anna@example.com",
  company: "Пример",
  scenario: "RFP",
  website: "",
};

function createHarness() {
  const send = vi.fn().mockResolvedValue({ messageId: "test-message" });
  const env = {
    PILOT_EMAIL: { send },
    PILOT_DESTINATION_ADDRESS: "verified-destination@example.com",
    ASSETS: { fetch: vi.fn() },
  } as unknown as Env;
  return { env, send };
}

function pilotRequest(body: unknown, init: { method?: string; contentType?: string } = {}) {
  return new Request("https://ctrldoc.tech/api/pilot", {
    method: init.method ?? "POST",
    headers: { "content-type": init.contentType ?? "application/json" },
    body: init.method === "GET" ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });
}

describe("POST /api/pilot", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-30T09:15:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("sends one restricted plain-text email for a valid application", async () => {
    const { env, send } = createHarness();

    const response = await handlePilotRequest(pilotRequest(validApplication), env);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true });
    expect(send).toHaveBeenCalledOnce();
    expect(send).toHaveBeenCalledWith({
      to: "verified-destination@example.com",
      from: { email: "pilot@ctrldoc.tech", name: "CTRL DOC" },
      subject: "Новая заявка на пилот CTRL DOC — Пример",
      text: [
        "Время (UTC): 2026-08-30T09:15:00.000Z",
        "Имя: Анна Иванова",
        "Рабочий email: anna@example.com",
        "Компания: Пример",
        "Сценарий: RFP",
      ].join("\n"),
    });
  });

  it.each([
    ["missing required field", { ...validApplication, name: "" }, 400],
    ["invalid email", { ...validApplication, email: "anna@example" }, 400],
    ["unknown scenario", { ...validApplication, scenario: "Анкета" }, 400],
    ["populated honeypot", { ...validApplication, website: "https://spam.invalid" }, 400],
    ["unknown field", { ...validApplication, message: "extra" }, 400],
  ])("rejects %s without sending email", async (_caseName, body, expectedStatus) => {
    const { env, send } = createHarness();

    const response = await handlePilotRequest(pilotRequest(body), env);

    expect(response.status).toBe(expectedStatus);
    expect(send).not.toHaveBeenCalled();
  });

  it("rejects malformed JSON without sending email", async () => {
    const { env, send } = createHarness();

    const response = await handlePilotRequest(pilotRequest("{broken"), env);

    expect(response.status).toBe(400);
    expect(send).not.toHaveBeenCalled();
  });

  it("rejects oversized bodies before parsing", async () => {
    const { env, send } = createHarness();

    const response = await handlePilotRequest(pilotRequest("x".repeat(4_097)), env);

    expect(response.status).toBe(413);
    expect(send).not.toHaveBeenCalled();
  });

  it("rejects non-POST requests", async () => {
    const { env, send } = createHarness();

    const response = await handlePilotRequest(pilotRequest(null, { method: "GET" }), env);

    expect(response.status).toBe(405);
    expect(response.headers.get("allow")).toBe("POST");
    expect(send).not.toHaveBeenCalled();
  });

  it("rejects non-JSON requests", async () => {
    const { env, send } = createHarness();

    const response = await handlePilotRequest(
      pilotRequest(JSON.stringify(validApplication), { contentType: "text/plain" }),
      env,
    );

    expect(response.status).toBe(415);
    expect(send).not.toHaveBeenCalled();
  });

  it("returns an error and never reports success when email delivery fails", async () => {
    const { env, send } = createHarness();
    send.mockRejectedValueOnce(new Error("provider unavailable"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const response = await handlePilotRequest(pilotRequest(validApplication), env);

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({ ok: false });
    expect(errorSpy).toHaveBeenCalledWith('{"event":"pilot_email_send_failed"}');
  });
});
