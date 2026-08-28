import { useState } from "react";

import { BrandLockup } from "./components/BrandLockup";
import "./landing.css";
import "./guided.css";

const scenarios = [
  { label: "CTRL находит", detail: "SAML 2.0 → Соответствует" },
  { label: "CTRL проверяет", detail: "Похожие данные → отказ" },
  { label: "Человек решает", detail: "Финальное подтверждение" },
];

const nextLabels = ["Показать защитную проверку", "Показать роль человека"];

export function GuidedDemo() {
  const [stage, setStage] = useState(0);
  const [approved, setApproved] = useState(false);

  const selectStage = (nextStage: number) => {
    setStage(nextStage);
    if (nextStage !== 2) setApproved(false);
  };

  return (
    <div className="landing guided-demo">
      <a className="landing-skip-link" href="#guided-main">Перейти к демо</a>

      <header className="guided-header">
        <a aria-label="CTRL DOC — на главную" href="/">
          <BrandLockup compact inverse />
        </a>
        <div className="guided-header-actions">
          <span><i aria-hidden="true" /> ДЕМО · СИНТЕТИЧЕСКИЕ ДАННЫЕ</span>
          <a href="/">← На главную</a>
        </div>
      </header>

      <main className="guided-main" id="guided-main">
        <section className="guided-intro" aria-labelledby="guided-title">
          <div>
            <p className="landing-eyebrow">Безопасное демо · три шага · без регистрации</p>
            <h1 id="guided-title">ИИ находит.<br />CTRL проверяет.</h1>
          </div>
          <div className="guided-intro-copy">
            <p>
              Три коротких сценария показывают полный принцип CTRL DOC: найти доказательство,
              проверить его применимость и передать финальное обязательство человеку.
            </p>
            <div className="guided-safety-note">
              <strong>Только предустановленные примеры</strong>
              <span>Реальные документы не принимаются и никуда не загружаются.</span>
            </div>
          </div>
        </section>

        <section className="guided-workspace" aria-label="Три сценария CTRL DOC">
          <ol className="guided-flow" aria-label={`Сценарий ${stage + 1} из ${scenarios.length}`}>
            {scenarios.map((item, index) => (
              <li
                className={`${index < stage ? "is-complete" : ""}${index === stage ? " is-current" : ""}`}
                key={item.label}
              >
                <button
                  aria-current={index === stage ? "step" : undefined}
                  onClick={() => selectStage(index)}
                  type="button"
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </button>
              </li>
            ))}
          </ol>

          <div className="guided-analysis">
            <article className="guided-requirement">
              {stage === 0 && (
                <>
                  <div className="guided-panel-meta">
                    <span>Требование заказчика</span>
                    <strong>REQ-024 · НИЗКИЙ РИСК</strong>
                  </div>
                  <blockquote>
                    Решение должно поддерживать аутентификацию через <mark>SAML 2.0</mark>.
                  </blockquote>
                  <dl>
                    <div><dt>Источник</dt><dd>Синтетическое ТЗ · раздел 3.4.2</dd></div>
                    <div><dt>Продукт</dt><dd>Aegis 7.4 LTS</dd></div>
                    <div><dt>Что нужно доказать</dt><dd>Поддержку протокола SAML 2.0</dd></div>
                  </dl>
                </>
              )}

              {stage === 1 && (
                <>
                  <div className="guided-panel-meta">
                    <span>Требование заказчика</span>
                    <strong>REQ-041 · ВЫСОКИЙ РИСК</strong>
                  </div>
                  <blockquote>
                    Система должна поддерживать не менее <mark>10 000 одновременных пользователей</mark>.
                  </blockquote>
                  <dl>
                    <div><dt>Источник</dt><dd>Синтетический RFP · строка 41</dd></div>
                    <div><dt>Проверяемый показатель</dt><dd>Одновременные сессии</dd></div>
                    <div><dt>Порог</dt><dd>≥ 10 000</dd></div>
                  </dl>
                </>
              )}

              {stage === 2 && (
                <>
                  <div className="guided-panel-meta">
                    <span>Решение CTRL</span>
                    <strong>REQ-041 · ОБЯЗАТЕЛЬСТВО ОСТАНОВЛЕНО</strong>
                  </div>
                  <blockquote>
                    Для обещания <mark>10 000 одновременных пользователей</mark> недостаточно данных.
                  </blockquote>
                  <dl>
                    <div><dt>Автоматический ответ</dt><dd>Заблокирован</dd></div>
                    <div><dt>Следующий шаг</dt><dd>Запросить корректное доказательство</dd></div>
                    <div><dt>Кто принимает решение</dt><dd>Ответственный архитектор</dd></div>
                  </dl>
                </>
              )}
            </article>

            <div className="guided-result" aria-live="polite">
              {stage === 0 && (
                <>
                  <article className="guided-evidence">
                    <div className="guided-panel-meta">
                      <span>Доказательство найдено</span>
                      <strong>Руководство администратора · стр. 72</strong>
                    </div>
                    <blockquote>
                      Aegis 7.4 <mark>поддерживает федеративную аутентификацию по протоколу SAML 2.0</mark>.
                    </blockquote>
                  </article>
                  <div className="guided-checks" aria-label="Проверки применимости">
                    <div><span>01</span><strong>Точная формулировка</strong><small>SAML 2.0 совпадает</small></div>
                    <div><span>02</span><strong>Версия продукта</strong><small>Aegis 7.4 LTS</small></div>
                    <div><span>03</span><strong>Источник</strong><small>Официальное руководство</small></div>
                  </div>
                  <div className="guided-decision guided-decision-positive">
                    <span>Решение CTRL</span>
                    <h2>Соответствует</h2>
                    <strong>COMPLY · доказательство применимо</strong>
                    <p>CTRL нашёл точный первоисточник и проверил версию, показатель и применимость.</p>
                  </div>
                </>
              )}

              {stage === 1 && (
                <>
                  <article className="guided-evidence">
                    <div className="guided-panel-meta">
                      <span>Кандидат в доказательства найден</span>
                      <strong>Техническая спецификация · стр. 39</strong>
                    </div>
                    <blockquote>
                      Система поддерживает до <mark>10 000 зарегистрированных пользователей</mark> в
                      одной инсталляции.
                    </blockquote>
                  </article>
                  <div className="guided-similarity">
                    <span>Семантическая близость</span>
                    <strong>0,91 · фрагменты похожи по смыслу</strong>
                    <p>Одинаковые число и тема делают фрагменты похожими. Но показатели различаются.</p>
                  </div>
                  <div className="guided-guardrail">
                    <div>
                      <span>Несовпадение показателей</span>
                      <strong>Зарегистрированные ≠ одновременные</strong>
                      <p>Найденный фрагмент подтверждает число учётных записей, а не активных сессий.</p>
                    </div>
                    <div>
                      <span>Итог проверки доказательства</span>
                      <strong>Недостаточно доказательств</strong>
                      <p>Фрагмент нельзя использовать как основание для обязательства.</p>
                    </div>
                  </div>
                  <div className="guided-decision">
                    <span>Безопасный отказ CTRL</span>
                    <h2>Недостаточно данных</h2>
                    <strong>UNKNOWN · требуется проверка человеком</strong>
                    <p>CTRL отказывается превращать похожий фрагмент в неподтверждённое обещание.</p>
                  </div>
                </>
              )}

              {stage === 2 && (
                <div className="guided-human-outcome">
                  <span>Контроль обязательства</span>
                  <h2>{approved ? "Безопасный ответ подтверждён" : "Требуется финальное подтверждение"}</h2>
                  <p>
                    CTRL предлагает решение и показывает основание, но не получает право принять
                    обязательство от имени компании.
                  </p>
                  <div className="guided-approval-trace">
                    <div><span>Решение CTRL</span><strong>Недостаточно данных</strong><code>UNKNOWN</code></div>
                    <div><span>Ответ заказчику</span><strong>Запросить подтверждение для одновременных сессий</strong></div>
                    <div><span>Финальный авторитет</span><strong>Ответственный архитектор</strong></div>
                  </div>
                  {approved ? (
                    <div className="guided-approval-confirmed" role="status">
                      <span aria-hidden="true">✓</span>
                      <div>
                        <strong>Подтверждено человеком в демо</strong>
                        <p>В ответ попадёт безопасная формулировка: «Недостаточно данных для подтверждения».</p>
                      </div>
                    </div>
                  ) : (
                    <p className="guided-approval-pending">Автоматическая отправка ответа заблокирована.</p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="guided-controls">
            <p>
              {approved ? "Три принципа CTRL показаны" : `Сценарий ${stage + 1} из ${scenarios.length}`}
            </p>
            <div>
              {stage > 0 && (
                <button className="guided-secondary" onClick={() => selectStage(stage - 1)} type="button">
                  Назад
                </button>
              )}
              {stage < 2 && (
                <button
                  className="landing-button landing-button-primary"
                  onClick={() => selectStage(stage + 1)}
                  type="button"
                >
                  {nextLabels[stage]} <span aria-hidden="true">→</span>
                </button>
              )}
              {stage === 2 && !approved && (
                <button
                  className="landing-button landing-button-primary"
                  onClick={() => setApproved(true)}
                  type="button"
                >
                  Подтвердить безопасный ответ <span aria-hidden="true">→</span>
                </button>
              )}
              {stage === 2 && approved && (
                <a className="landing-button landing-button-primary" href="/demo">
                  Открыть рабочую область <span aria-hidden="true">→</span>
                </a>
              )}
            </div>
          </div>
        </section>

        <footer className="guided-footer">
          <span>Требование → Доказательство → Проверка → Решение → Подтверждение человеком</span>
          <a href="/#pilot">Обсудить пилот на вашем сценарии</a>
        </footer>
      </main>
    </div>
  );
}
