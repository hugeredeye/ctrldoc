import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { BrandLockup } from "./components/BrandLockup";
import { CtrlKeycap } from "./components/CtrlKeycap";
import { MismatchPreview } from "./components/MismatchPreview";
import "./landing.css";

type ProductTruthItem = {
  number: string;
  title: string;
  description: string;
  detail: ReactNode;
};

const productTruth: ProductTruthItem[] = [
  {
    number: "01",
    title: "Возможность",
    description: "Что продукт действительно умеет",
    detail: (
      <div className="truth-detail-grid">
        <div><span>Продукт</span><strong>Aegis Enterprise</strong></div>
        <div><span>Возможность</span><strong>Масштабирование пользователей</strong></div>
        <div><span>Контекст</span><strong>Синтетический пример</strong></div>
      </div>
    ),
  },
  {
    number: "02",
    title: "Версия",
    description: "Для какой версии это утверждение верно",
    detail: (
      <div className="truth-detail-grid">
        <div><span>Продукт</span><strong>Aegis Enterprise</strong></div>
        <div><span>Версия</span><strong>7.4 LTS</strong></div>
        <p>CTRL не переносит доказательство между версиями автоматически.</p>
      </div>
    ),
  },
  {
    number: "03",
    title: "Доказательство",
    description: "Где именно это подтверждено",
    detail: (
      <div className="truth-evidence-detail">
        <blockquote>«Поддерживается SAML 2.0 ...»</blockquote>
        <div><strong>Руководство администратора 7.4</strong><span>§ 8.12 · стр. 143</span></div>
        <p>Не пересказ модели.<br />Точный фрагмент первоисточника.</p>
      </div>
    ),
  },
  {
    number: "04",
    title: "Согласование",
    description: "Кто разрешил использовать это как обязательство",
    detail: (
      <div className="truth-detail-grid">
        <div><span>Роль</span><strong>Архитектор решения</strong></div>
        <div><span>Статус</span><strong>Проверено человеком</strong></div>
        <div><span>Решение</span><strong className="truth-decision">Соответствует · COMPLY</strong></div>
      </div>
    ),
  },
];

const workflow = [
  "Разобрать требования",
  "Проверить возможности",
  "Найти доказательства",
  "Выявить пробелы и конфликты",
  "Согласовать обязательства",
  "Собрать ответ",
];

const trustPrinciples = [
  "Точный первоисточник",
  "Версия продукта",
  "История решения",
  "Противоречащие данные",
  "Контроль происхождения",
  "Подтверждение человеком",
];

const inputSources = [
  "ТЗ заказчика",
  "RFP / RFI",
  "Анкета по ИБ",
  "Документация продукта",
  "Примечания к выпуску",
  "Технические спецификации",
];

const decisionOutputs = [
  "Атомарные требования",
  "Соответствует / Частично / Не покрыто / Недостаточно данных",
  "Точный первоисточник",
  "Версия продукта",
  "Конфликты и пробелы",
  "Пункты для проверки человеком",
  "Матрица соответствия",
];

const audiences = [
  ["01", "ПРЕСЕЙЛ", "Проверить, что продукт действительно закрывает требования заказчика."],
  ["02", "АРХИТЕКТОР РЕШЕНИЯ", "Увидеть технические ограничения, версии и условия применимости."],
  ["03", "ТЕНДЕРНАЯ КОМАНДА", "Собрать проверенную матрицу без ручной сверки десятков документов."],
];

const engineSteps = [
  ["01", "ДЕКОМПОЗИЦИЯ", "DECOMPOSE", "Разделить сложное требование на проверяемые части."],
  ["02", "ПОИСК", "RETRIEVE", "Найти кандидатов в корпоративных источниках."],
  ["03", "РАНЖИРОВАНИЕ", "RERANK", "Отделить действительно релевантные фрагменты."],
  ["04", "ПРОВЕРКА", "VERIFY", "Определить: доказывает / противоречит / недостаточно."],
  ["05", "ЗАЩИТНЫЕ ПРАВИЛА", "GUARD", "Проверить: версию · показатель · срок · источник · конфликт."],
  ["06", "ПОДТВЕРЖДЕНИЕ", "APPROVE", "Передать человеку то, что требует решения."],
];

const securityClaims = [
  ["01", "ИЗОЛЯЦИЯ", "Изоляция рабочих пространств и данных организаций."],
  ["02", "ДОСТУП", "Ролевой доступ к рабочим пространствам и действиям."],
  ["03", "ПРОИСХОЖДЕНИЕ", "Неизменяемая цепочка источников и доказательств."],
  ["04", "КЛАССИФИКАЦИЯ", "Политика обработки данных зависит от их класса."],
  ["05", "ВНЕШНИЕ МОДЕЛИ", "Закрытые классы данных не должны автоматически уходить во внешний модельный API."],
  ["06", "РЕШЕНИЕ ЧЕЛОВЕКА", "Модель не получает право самостоятельно принять обязательство от имени компании."],
];

function SceneLabel({ children }: { children: ReactNode }) {
  return <p className="landing-eyebrow">{children}</p>;
}

type PilotFormState = "idle" | "submitting" | "success" | "validation-error" | "server-error";

const pilotEmail = "pilot@ctrldoc.tech";

export function LandingPage() {
  const [expandedTruth, setExpandedTruth] = useState<string | null>("03");
  const [pilotFormState, setPilotFormState] = useState<PilotFormState>("idle");
  const [pilotStatus, setPilotStatus] = useState<string | null>(null);

  useEffect(() => {
    const targetId = window.location.hash.slice(1);
    if (!targetId) return;
    document.getElementById(targetId)?.scrollIntoView({ block: "start" });
  }, []);

  const submitPilotRequest = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setPilotFormState("submitting");
    setPilotStatus(null);

    try {
      const response = await fetch("/api/pilot", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: String(data.get("name") ?? ""),
          email: String(data.get("email") ?? ""),
          company: String(data.get("company") ?? ""),
          scenario: String(data.get("scenario") ?? ""),
          website: String(data.get("website") ?? ""),
        }),
      });

      if (response.ok) {
        form.reset();
        setPilotFormState("success");
        setPilotStatus("Заявка отправлена. Свяжемся с вами по рабочей почте.");
        return;
      }

      if ([400, 413, 415].includes(response.status)) {
        setPilotFormState("validation-error");
        setPilotStatus(
          response.status === 413
            ? "Данные формы слишком длинные. Сократите значения и попробуйте ещё раз."
            : "Проверьте заполнение формы и попробуйте ещё раз.",
        );
        return;
      }

      setPilotFormState("server-error");
      setPilotStatus("Не удалось отправить заявку. Попробуйте ещё раз или напишите нам на pilot@ctrldoc.tech.");
    } catch {
      setPilotFormState("server-error");
      setPilotStatus("Не удалось отправить заявку. Попробуйте ещё раз или напишите нам на pilot@ctrldoc.tech.");
    }
  };

  return (
    <div className="landing">
      <a className="landing-skip-link" href="#landing-main">Перейти к содержанию</a>

      <header className="landing-header">
        <a aria-label="CTRL DOC — на главную" className="landing-logo-link" href="#top">
          <BrandLockup compact inverse />
        </a>
        <nav className="landing-nav" aria-label="Основная навигация">
          <a href="#product">Продукт</a>
          <a href="#how-it-works">Как работает</a>
          <a href="#technology">Технология</a>
          <a href="#security">Безопасность</a>
          <a href="#company">Компания</a>
        </nav>
        <div className="landing-nav-actions">
          <a className="landing-demo-link" href="/demo/guided">Бесплатное демо</a>
          <a className="landing-access-link" href="#pilot">Обсудить пилот</a>
        </div>
      </header>

      <main id="landing-main">
        <section className="landing-hero" id="top" aria-labelledby="hero-title">
          <div className="landing-grid landing-hero-grid">
            <div className="hero-copy">
              <SceneLabel>CTRL DOC</SceneLabel>
              <h1 id="hero-title">
                Точно знайте,
                <br />
                что можно обещать заказчику.
              </h1>
              <p className="hero-support">
                CTRL DOC сверяет требования заказчика с документацией продукта, находит
                подтверждения, пробелы и конфликты. Человек проверяет результат — и компания
                видит, что можно обещать клиенту.
              </p>
              <div className="hero-actions">
                <a className="landing-button landing-button-primary" href="/demo/guided">
                  Проверить на примере
                  <span aria-hidden="true">↗</span>
                </a>
                <a className="landing-button landing-button-secondary" href="#pilot">
                  Обсудить пилот <span className="hero-secondary-arrow" aria-hidden="true">→</span>
                </a>
              </div>
            </div>

            <div className="hero-object">
              <CtrlKeycap />
              <div className="hero-object-caption">
                <span>Проверенные обязательства</span>
                <span>CTRL / 01</span>
              </div>
            </div>

            <div className="hero-sequence" aria-label="Процесс CTRL">
              <span>Примеры: ТЗ / RFP / RFI / анкета по ИБ</span><i>→</i>
              <span>Проверка документации продукта</span><i>→</i>
              <span>Подтверждения / пробелы / конфликты</span><i>→</i>
              <span>Решение проверяет человек</span>
            </div>
          </div>
          <div className="hero-index" aria-hidden="true">01</div>
        </section>

        <section className="landing-scene mismatch-scene" id="product" aria-labelledby="mismatch-title">
          <div className="landing-grid mismatch-layout">
            <div className="scene-copy mismatch-copy">
              <SceneLabel>02 / Проверка</SceneLabel>
              <h2 id="mismatch-title">Похоже —<br />не значит доказано.</h2>
              <p>
                Обычная модель нашла бы релевантный фрагмент. CTRL проверяет, достаточно ли его,
                чтобы взять обязательство перед заказчиком.
              </p>
              <div className="mismatch-logic" aria-label="Логика проверки">
                <span>Фрагмент похож по смыслу</span><i>→</i>
                <span>Показатели не совпадают</span><i>→</i>
                <span>Доказательства недостаточно</span><i>→</i>
                <strong>CTRL не обещает соответствие</strong>
              </div>
            </div>
            <div className="mismatch-product-frame">
              <div className="product-frame-label">
                <span>Рабочая область CTRL DOC</span>
                <span>Безопасное демо</span>
              </div>
              <MismatchPreview />
            </div>
          </div>
        </section>

        <section className="landing-scene worldview-scene" aria-labelledby="worldview-title">
          <div className="landing-grid">
            <SceneLabel>03 / Принцип</SceneLabel>
            <h2 id="worldview-title">Не очередной<br />генератор ответов.</h2>
            <div className="worldview-contrast">
              <div className="worldview-ai">
                <span>Обычный ИИ спрашивает</span>
                <p>«Что написать<br />в ответ?»</p>
              </div>
              <div className="worldview-divider" aria-hidden="true"><span>≠</span></div>
              <div className="worldview-ctrl">
                <span>CTRL спрашивает</span>
                <p>«Что мы действительно<br />можем подтвердить?»</p>
              </div>
            </div>
            <p className="worldview-note">
              Генерация текста начинается с ответа. CTRL — с проверки фактов; финальное
              обязательство подтверждает человек.
            </p>
          </div>
        </section>

        <section className="landing-scene exchange-scene" id="input-decision" aria-labelledby="exchange-title">
          <div className="landing-grid">
            <SceneLabel>04 / От документов к решению</SceneLabel>
            <h2 id="exchange-title">Сначала — требования.<br />Потом — доказательства.</h2>
            <div className="exchange-layout">
              <div className="exchange-territory">
                <span>01 / Передаёте CTRL</span>
                <ul>{inputSources.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
              <div className="exchange-trace">
                <div>
                  <span>02 / CTRL проверяет</span>
                  <p>
                    Разбирает требования, находит доказательства, сверяет версии и выявляет
                    конфликты.
                  </p>
                </div>
                <i aria-hidden="true" /><b aria-hidden="true">→</b>
              </div>
              <div className="exchange-territory exchange-output">
                <span>03 / Получаете</span>
                <ul>{decisionOutputs.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            </div>
            <p className="exchange-note">Документ — источник.<br />Требование — рабочая единица CTRL.</p>
          </div>
        </section>

        <section className="landing-scene truth-scene" id="product-model" aria-labelledby="truth-title">
          <div className="landing-grid">
            <SceneLabel>05 / Модель продукта</SceneLabel>
            <h2 id="truth-title">Возможности продукта меняются.<br />Доказательства тоже.</h2>
            <div className="truth-rows">
              {productTruth.map((item) => {
                const expanded = expandedTruth === item.number;
                const panelId = `truth-panel-${item.number}`;
                const buttonId = `truth-button-${item.number}`;
                return (
                  <div className={`truth-item${expanded ? " is-expanded" : ""}`} key={item.number}>
                    <button
                      aria-controls={panelId}
                      aria-expanded={expanded}
                      className="truth-row"
                      id={buttonId}
                      onClick={() => setExpandedTruth(expanded ? null : item.number)}
                      type="button"
                    >
                      <span>{item.number}</span>
                      <strong>{item.title}</strong>
                      <p>{item.description}</p>
                      <i aria-hidden="true">{expanded ? "−" : "+"}</i>
                    </button>
                    {expanded && (
                      <div
                        aria-labelledby={buttonId}
                        className="truth-panel"
                        id={panelId}
                        role="region"
                      >
                        {item.detail}
                        <small>СИНТЕТИЧЕСКОЕ ДЕМО</small>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <section className="landing-scene workflow-scene" id="how-it-works" aria-labelledby="workflow-title">
          <div className="landing-grid workflow-layout">
            <div className="scene-copy">
              <SceneLabel>06 / От требования до ответа</SceneLabel>
              <h2 id="workflow-title">Один процесс.<br />Без ручной сверки десятков источников.</h2>
            </div>
            <ol className="landing-workflow-list">
              {workflow.map((step, index) => (
                <li key={step}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{step}</strong>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="landing-scene trust-scene" id="auditability" aria-labelledby="trust-title">
          <div className="landing-grid">
            <SceneLabel>07 / Проверяемость</SceneLabel>
            <div className="trust-heading-row">
              <h2 id="trust-title">
                Ответ должен быть<br />не только быстрым.
                <span>Он должен быть проверяемым.</span>
              </h2>
              <p>
                CTRL не скрывает неопределённость и не превращает отсутствие доказательства
                в уверенный ответ.
              </p>
            </div>
            <div className="trust-principles">
              {trustPrinciples.map((principle, index) => (
                <div key={principle}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{principle}</strong>
                  <i aria-hidden="true" />
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-scene audience-scene" id="audience" aria-labelledby="audience-title">
          <div className="landing-grid">
            <SceneLabel>08 / Для кого</SceneLabel>
            <h2 id="audience-title">Когда ответ клиенту<br />нельзя придумывать.</h2>
            <div className="audience-rows">
              {audiences.map(([number, role, description]) => (
                <div className="audience-row" key={number}>
                  <span>{number}</span><strong>{role}</strong><p>{description}</p>
                </div>
              ))}
            </div>
            <p className="audience-note"><span>Продукт · Безопасность · Юристы · Разработка</span><br />подключаются там, где требуется экспертное решение.</p>
          </div>
        </section>

        <section className="landing-scene engine-scene" id="technology" aria-labelledby="engine-title">
          <div className="landing-grid engine-layout">
            <div className="engine-heading">
              <SceneLabel>09 / CTRL Engine</SceneLabel>
              <h2 id="engine-title">ИИ находит.<br />CTRL проверяет.</h2>
              <div className="engine-state" aria-hidden="true">
                <span>CTRL / ENGINE</span><span>ТРАССИРОВКА / АКТИВНА</span><span>СОСТОЯНИЕ / ПРОВЕРКА</span>
              </div>
            </div>
            <div className="engine-trace">
              <span className="engine-terminal">Требование</span>
              <ol>
                {engineSteps.map(([number, operation, machineCode, description]) => (
                  <li key={number}>
                    <span>{number}</span>
                    <strong><span>{operation}</span><small>{machineCode}</small></strong>
                    <p>{description}</p>
                  </li>
                ))}
              </ol>
              <span className="engine-terminal engine-terminal-output">→ Проверенное решение</span>
            </div>
          </div>
        </section>

        <section className="landing-scene security-scene" id="security" aria-labelledby="security-title">
          <div className="landing-grid">
            <SceneLabel>10 / Безопасность</SceneLabel>
            <h2 id="security-title">Корпоративные документы<br />не должны становиться платой<br />за автоматизацию.</h2>
            <div className="security-grid">
              {securityClaims.map(([number, title, description]) => (
                <div key={number}>
                  <span>{number} / {title}</span>
                  <p>{description}</p>
                </div>
              ))}
            </div>
            <p className="security-note">Архитектура CTRL разделяет модельные вычисления,<br />корпоративные данные и авторитетное решение.</p>
          </div>
        </section>

        <section className="landing-scene company-scene" id="company" aria-labelledby="company-title">
          <div className="landing-grid company-layout">
            <div>
              <SceneLabel>11 / CTRL</SceneLabel>
              <span className="company-alpha">Пилот / 2026</span>
            </div>
            <div>
              <h2 id="company-title">Мы строим систему,<br />которая знает разницу<br />между правдоподобным ответом<br />и доказуемым обязательством.</h2>
              <p>CTRL превращает сложные требования<br />в решения, которые можно проверить,<br />обосновать и согласовать.</p>
            </div>
          </div>
        </section>

        <section className="landing-final" id="pilot" aria-labelledby="final-title">
          <div className="landing-grid final-grid">
            <div className="final-brand">
              <BrandLockup inverse />
              <span>Пилот / 2026</span>
            </div>
            <div className="final-keycap"><CtrlKeycap small /></div>
            <div className="pilot-layout">
              <div className="pilot-copy">
                <SceneLabel>12 / Пилот</SceneLabel>
                <h2 id="final-title">Каждое обязательство.<br />Под CTRL.</h2>
                <p>
                  Покажем CTRL на одном вашем реальном сценарии: RFP, RFI, ТЗ или анкете по ИБ.
                </p>
                <p className="pilot-boundary">
                  На этапе пилота работаем с публичными, тестовыми или предварительно
                  согласованными материалами. Не отправляйте документы через эту форму.
                </p>
                <p className="pilot-commercial">
                  Коммерческие условия — по масштабу и формату внедрения.
                </p>
                <a className="pilot-demo-link" href="/demo/guided">Сначала пройти безопасное демо →</a>
              </div>

              <form
                aria-busy={pilotFormState === "submitting"}
                className="pilot-form"
                onSubmit={submitPilotRequest}
              >
                <div className="pilot-form-heading">
                  <span>Заявка на пилот</span>
                  <small>Без загрузки документов</small>
                </div>
                <label>
                  <span>Имя</span>
                  <input autoComplete="name" maxLength={120} name="name" placeholder="Как к вам обращаться" required type="text" />
                </label>
                <label>
                  <span>Рабочий email</span>
                  <input autoComplete="email" maxLength={254} name="email" placeholder="name@company.ru" required type="email" />
                </label>
                <label>
                  <span>Компания</span>
                  <input autoComplete="organization" maxLength={160} name="company" placeholder="Название компании" required type="text" />
                </label>
                <label>
                  <span>Что хотите проверить?</span>
                  <select defaultValue="" name="scenario" required>
                    <option disabled value="">Выберите сценарий</option>
                    <option>RFP</option>
                    <option>RFI</option>
                    <option>ТЗ</option>
                    <option>Анкета по ИБ</option>
                    <option>Другое</option>
                  </select>
                </label>
                <label aria-hidden="true" className="pilot-honeypot">
                  <span>Сайт</span>
                  <input autoComplete="off" maxLength={200} name="website" tabIndex={-1} type="text" />
                </label>
                <button
                  className="landing-button landing-button-primary"
                  disabled={pilotFormState === "submitting"}
                  type="submit"
                >
                  {pilotFormState === "submitting" ? "Отправляем…" : "Отправить заявку"}
                  {pilotFormState !== "submitting" && <span aria-hidden="true"> →</span>}
                </button>
                <p className="pilot-form-note" id="pilot-form-note">
                  Контактные данные используются только для связи по поводу пилота. Не прикладывайте
                  конфиденциальные документы через эту форму.
                </p>
                <p className="pilot-contact">
                  Или напишите напрямую: <a href={`mailto:${pilotEmail}`}>{pilotEmail}</a>
                </p>
                {pilotStatus && (
                  <p
                    className={`pilot-status pilot-status-${pilotFormState}`}
                    role={pilotFormState.endsWith("error") ? "alert" : "status"}
                  >
                    {pilotStatus}
                  </p>
                )}
              </form>
            </div>
            <footer className="landing-footer">
              <span>CTRL DOC · Проверка обязательств</span>
              <span>Доказательства вместо предположений</span>
            </footer>
          </div>
        </section>
      </main>
    </div>
  );
}
