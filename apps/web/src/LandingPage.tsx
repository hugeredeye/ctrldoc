import { useState } from "react";
import type { ReactNode } from "react";

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
        <div><span>Возможность</span><strong>Horizontal user scaling</strong></div>
        <div><span>Подтверждено для</span><strong>Cloud + On-prem</strong></div>
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
        <div><strong>Admin Guide 7.4</strong><span>§ 8.12 · стр. 143</span></div>
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
        <div><span>Роль</span><strong>Solution Architect</strong></div>
        <div><span>Статус</span><strong>Проверено человеком</strong></div>
        <div><span>Decision</span><strong className="truth-decision">COMPLY</strong></div>
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
  "Security questionnaire",
  "Документация продукта",
  "Release notes",
  "Технические спецификации",
];

const decisionOutputs = [
  "Атомарные требования",
  "COMPLY / PARTIAL / GAP / UNKNOWN",
  "Точный первоисточник",
  "Версия продукта",
  "Конфликты и пробелы",
  "Пункты для проверки человеком",
  "Матрица соответствия",
];

const audiences = [
  ["01", "PRESALES", "Проверить, что продукт действительно закрывает требования заказчика."],
  ["02", "SOLUTION ARCHITECT", "Увидеть технические ограничения, версии и условия применимости."],
  ["03", "BID / TENDER TEAM", "Собрать проверенную матрицу без ручной сверки десятков документов."],
];

const engineSteps = [
  ["01", "DECOMPOSE", "Разделить сложное требование на проверяемые части."],
  ["02", "RETRIEVE", "Найти кандидатов в корпоративных источниках."],
  ["03", "RERANK", "Отделить действительно релевантные фрагменты."],
  ["04", "VERIFY", "Определить: доказывает / противоречит / недостаточно."],
  ["05", "GUARD", "Проверить: версию · показатель · срок · источник · конфликт."],
  ["06", "APPROVE", "Передать человеку то, что требует решения."],
];

const securityClaims = [
  ["01", "ИЗОЛЯЦИЯ", "Изоляция рабочих пространств и данных организаций."],
  ["02", "ДОСТУП", "Ролевой доступ к рабочим пространствам и действиям."],
  ["03", "ПРОИСХОЖДЕНИЕ", "Неизменяемая цепочка источников и доказательств."],
  ["04", "КЛАССИФИКАЦИЯ", "Политика обработки данных зависит от их класса."],
  ["05", "ВНЕШНИЙ INFERENCE", "Закрытые классы данных не должны автоматически уходить во внешний модельный API."],
  ["06", "HUMAN AUTHORITY", "Модель не получает право самостоятельно принять обязательство от имени компании."],
];

function SceneLabel({ children }: { children: ReactNode }) {
  return <p className="landing-eyebrow">{children}</p>;
}

export function LandingPage() {
  const [accessNotice, setAccessNotice] = useState(false);
  const [expandedTruth, setExpandedTruth] = useState<string | null>("03");

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
          <a className="landing-demo-link" href="/demo">Посмотреть демо</a>
          <a className="landing-access-link" href="#access">Запросить доступ</a>
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
                CTRL проверяет требования по документации продукта, версиям и первоисточникам —
                и показывает, где ответ доказан, где есть конфликт, а где данных недостаточно.
              </p>
              <div className="hero-actions">
                <a className="landing-button landing-button-primary" href="/demo">
                  Посмотреть, как работает
                  <span aria-hidden="true">↗</span>
                </a>
                <a className="landing-button landing-button-secondary" href="#access">
                  Запросить доступ
                </a>
              </div>
            </div>

            <div className="hero-object">
              <CtrlKeycap />
              <div className="hero-object-caption">
                <span>Verified commitments</span>
                <span>CTRL / 01</span>
              </div>
            </div>

            <div className="hero-sequence" aria-label="Процесс CTRL">
              <span>RFP / RFI / ТЗ</span><i>→</i>
              <span>Требование</span><i>→</i>
              <span>Доказательство</span><i>→</i>
              <span>Решение</span>
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
                <span>Семантически близко</span><i>→</i>
                <span>Разные показатели</span><i>→</i>
                <span>Доказательство отклонено</span><i>→</i>
                <strong>Недостаточно данных</strong>
              </div>
            </div>
            <div className="mismatch-product-frame">
              <div className="product-frame-label">
                <span>Intelligence Workbench</span>
                <span>Synthetic-safe demo</span>
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
          </div>
        </section>

        <section className="landing-scene exchange-scene" id="input-decision" aria-labelledby="exchange-title">
          <div className="landing-grid">
            <SceneLabel>04 / От документов к решению</SceneLabel>
            <h2 id="exchange-title">Сначала — требования.<br />Потом — доказательства.</h2>
            <div className="exchange-layout">
              <div className="exchange-territory">
                <span>На входе</span>
                <ul>{inputSources.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
              <div className="exchange-trace" aria-hidden="true">
                <span>CTRL</span><i /><b>→</b>
              </div>
              <div className="exchange-territory exchange-output">
                <span>На выходе</span>
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
                        <small>SYNTHETIC DEMO</small>
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
            <p className="audience-note"><span>Product · Security · Legal · Engineering</span><br />подключаются там, где требуется экспертное решение.</p>
          </div>
        </section>

        <section className="landing-scene engine-scene" id="technology" aria-labelledby="engine-title">
          <div className="landing-grid engine-layout">
            <div className="engine-heading">
              <SceneLabel>09 / CTRL Engine</SceneLabel>
              <h2 id="engine-title">ИИ находит.<br />CTRL проверяет.</h2>
              <div className="engine-state" aria-hidden="true">
                <span>CTRL / ENGINE</span><span>TRACE / ACTIVE</span><span>STATE / VERIFY</span>
              </div>
            </div>
            <div className="engine-trace">
              <span className="engine-terminal">Requirement</span>
              <ol>
                {engineSteps.map(([number, operation, description]) => (
                  <li key={number}>
                    <span>{number}</span>
                    <strong>{operation}</strong>
                    <p>{description}</p>
                  </li>
                ))}
              </ol>
              <span className="engine-terminal engine-terminal-output">→ Verified decision</span>
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
            <p className="security-note">Архитектура CTRL разделяет модельный inference,<br />корпоративные данные и авторитетное решение.</p>
          </div>
        </section>

        <section className="landing-scene company-scene" id="company" aria-labelledby="company-title">
          <div className="landing-grid company-layout">
            <div>
              <SceneLabel>11 / CTRL</SceneLabel>
              <span className="company-alpha">Private alpha / 2026</span>
            </div>
            <div>
              <h2 id="company-title">Мы строим систему,<br />которая знает разницу<br />между правдоподобным ответом<br />и доказуемым обязательством.</h2>
              <p>CTRL превращает сложные требования<br />в решения, которые можно проверить,<br />обосновать и согласовать.</p>
            </div>
          </div>
        </section>

        <section className="landing-final" id="access" aria-labelledby="final-title">
          <div className="landing-grid final-grid">
            <div className="final-brand">
              <BrandLockup inverse />
              <span>Private alpha / 2026</span>
            </div>
            <div className="final-keycap"><CtrlKeycap small /></div>
            <h2 id="final-title">Каждое обязательство.<br />Под CTRL.</h2>
            <div className="final-actions">
              <button
                className="landing-button landing-button-primary"
                onClick={() => setAccessNotice(true)}
                type="button"
              >
                Запросить доступ <span aria-hidden="true">↗</span>
              </button>
              <a href="/demo">Посмотреть демо</a>
            </div>
            {accessNotice && (
              <p className="access-notice" role="status">
                Private alpha: запрос передаётся через представителя CTRL. Публичная форма не
                собирает данные до подключения защищённого канала.
              </p>
            )}
            <footer className="landing-footer">
              <span>CTRL DOC · Response Intelligence</span>
              <span>Доказательства вместо предположений</span>
            </footer>
          </div>
        </section>
      </main>
    </div>
  );
}
