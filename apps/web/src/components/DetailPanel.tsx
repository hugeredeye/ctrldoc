import { useState } from "react";

import type {
  AtomicRequirement,
  ComplianceStatus,
  EvidenceSpan,
  ReviewState,
} from "../types";
import { EvidenceCard } from "./EvidenceCard";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";
import { statusLabels } from "./statusLabels";

interface DetailPanelProps {
  decision: ComplianceStatus;
  onDecisionChange: (decision: ComplianceStatus) => void;
  onReviewStateChange: (state: ReviewState) => void;
  requirement: AtomicRequirement;
  reviewState: ReviewState;
}

const decisionOptions: ComplianceStatus[] = [
  "COMPLY",
  "PARTIAL",
  "GAP",
  "UNKNOWN",
  "NEEDS_CLARIFICATION",
];

function MappingPath({ requirement }: { requirement: AtomicRequirement }) {
  const { mapping } = requirement;
  return (
    <div className="mapping-path" aria-label="Связь с моделью продукта">
      <div>
        <span>Продукт</span>
        <strong>{mapping.product.name}</strong>
      </div>
      <Icon name="arrow-right" size={16} />
      <div>
        <span>Версия продукта</span>
        <strong>{mapping.productVersion.label}</strong>
      </div>
      <Icon name="arrow-right" size={16} />
      <div>
        <span>Возможность</span>
        <strong>{mapping.capability.name}</strong>
      </div>
      <span className="mapping-confidence">{Math.round(mapping.confidence * 100)}% совпадение</span>
    </div>
  );
}

function SemanticMismatch({ evidence }: { evidence: EvidenceSpan }) {
  return (
    <section className="semantic-mismatch" aria-labelledby="semantic-mismatch-title">
      <div className="mismatch-intro">
        <span className="mismatch-kicker">Логика проверки CTRL</span>
        <h3 id="semantic-mismatch-title">Семантически близко — логически недостаточно</h3>
      </div>
      <div className="verdict-route">
        <div className="route-step route-model">
          <span>Найденный кандидат</span>
          <strong>Доказательство похоже по смыслу</strong>
          <StatusPill value={evidence.verifierCandidate} quiet />
        </div>
        <Icon name="arrow-right" size={18} />
        <div className="route-step route-guardrail">
          <span>Защитная проверка CTRL</span>
          <strong>Показатели не совпадают</strong>
          <em>Зарегистрированные ≠ одновременные</em>
        </div>
        <Icon name="arrow-right" size={18} />
        <div className="route-step route-effective">
          <span>Итог проверки</span>
          <strong>Кандидат отклонён</strong>
          <StatusPill showCode value={evidence.effectiveVerdict} />
        </div>
      </div>
      <div className="safe-outcome">
        <Icon name="shield" size={20} />
        <div>
          <strong>CTRL не делает неподтверждённое обещание</strong>
          <span>Недостаточно данных · UNKNOWN · требуется проверка человеком</span>
        </div>
      </div>
    </section>
  );
}

function ConflictView({ requirement }: { requirement: AtomicRequirement }) {
  if (!requirement.conflict) return null;
  const [leftId, rightId] = requirement.conflict.evidenceSpanIds;
  const left = requirement.evidence.find((item) => item.id === leftId);
  const right = requirement.evidence.find((item) => item.id === rightId);
  if (!left || !right) return null;

  return (
    <section className="conflict-section" aria-labelledby="conflict-title">
      <div className="section-heading conflict-heading">
        <div>
          <p className="eyebrow">Существенный конфликт</p>
          <h3 id="conflict-title">Источники противоречат друг другу</h3>
        </div>
        <StatusPill value="BLOCKING" />
      </div>
      <p className="conflict-explanation">{requirement.conflict.explanation}</p>
      <div className="conflict-grid">
        <div>
          <span className="comparison-label comparison-supports">Подтверждает</span>
          <EvidenceCard compact evidence={left} />
        </div>
        <div>
          <span className="comparison-label comparison-contradicts">Противоречит</span>
          <EvidenceCard compact evidence={right} />
        </div>
      </div>
      <div className="conflict-policy">
        <Icon name="warning" size={18} />
        CTRL не скрывает противоречащие доказательства и не выбирает удобный источник автоматически.
      </div>
    </section>
  );
}

export function DetailPanel({
  decision,
  onDecisionChange,
  onReviewStateChange,
  requirement,
  reviewState,
}: DetailPanelProps) {
  const [selectedEvidenceId, setSelectedEvidenceId] = useState(requirement.selectedEvidenceId);
  const [editing, setEditing] = useState(false);
  const [draftDecision, setDraftDecision] = useState(decision);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const selectedEvidence =
    requirement.evidence.find((item) => item.id === selectedEvidenceId) ?? requirement.evidence[0];
  const isSemanticMismatch = requirement.guardrails.some(
    (guardrail) => guardrail.code === "METRIC_MISMATCH",
  );

  const applyDecision = () => {
    onDecisionChange(draftDecision);
    setEditing(false);
    setActionMessage("Решение изменено только в браузере. Запись в рабочей системе не создана.");
  };

  const approve = () => {
    onReviewStateChange("APPROVED");
    setActionMessage("Решение подтверждено только в состоянии демо.");
  };

  return (
    <aside className="detail-panel" aria-label={`Детали ${requirement.shortId}`}>
      <div className="detail-topbar">
        <div className="detail-identifiers">
          <span className="requirement-id">{requirement.shortId}</span>
          <span>{requirement.category}</span>
          <StatusPill value={requirement.risk} quiet />
        </div>
      </div>

      <div className="detail-scroll">
        <section className="customer-requirement" aria-labelledby="customer-requirement-title">
          <p className="eyebrow">Требование заказчика</p>
          <h2 id="customer-requirement-title">{requirement.text}</h2>
          <div className="source-reference">
            <Icon name="document" size={15} />
            {requirement.sourceLocation}
          </div>
        </section>

        <MappingPath requirement={requirement} />

        <section className="decision-band" aria-label="Предлагаемое решение">
          <div>
            <span>Предлагаемое решение</span>
            <StatusPill showCode value={decision} />
          </div>
          <div>
            <span>Итог проверки</span>
            <StatusPill showCode value={selectedEvidence.effectiveVerdict} />
          </div>
          <div className="review-reason">
            <span>Почему CTRL принял такое решение</span>
            <strong>{requirement.reviewReason}</strong>
          </div>
        </section>

        {isSemanticMismatch && <SemanticMismatch evidence={selectedEvidence} />}

        <section className="evidence-section" aria-labelledby="evidence-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Доказательство из первоисточника</p>
              <h3 id="evidence-title">Подтверждающие фрагменты</h3>
            </div>
            <span className="section-count">Кандидатов: {requirement.evidence.length}</span>
          </div>
          {requirement.evidence.length > 1 && (
            <div className="evidence-tabs" role="tablist" aria-label="Кандидаты в доказательства">
              {requirement.evidence.map((item, index) => (
                <button
                  aria-selected={selectedEvidence.id === item.id}
                  key={item.id}
                  onClick={() => setSelectedEvidenceId(item.id)}
                  role="tab"
                  type="button"
                >
                  Доказательство {index + 1}
                  <StatusPill value={item.effectiveVerdict} quiet />
                </button>
              ))}
            </div>
          )}
          <EvidenceCard evidence={selectedEvidence} />
        </section>

        {requirement.guardrails.length > 0 && (
          <section className="guardrails-section" aria-labelledby="guardrails-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Детерминированная политика</p>
                <h3 id="guardrails-title">Активные защитные проверки</h3>
              </div>
              <span className="section-count">Активно: {requirement.guardrails.length}</span>
            </div>
            <div className="guardrail-list">
              {requirement.guardrails.map((guardrail) => (
                <div className={`guardrail guardrail-${guardrail.severity}`} key={guardrail.code}>
                  <Icon name={guardrail.severity === "critical" ? "warning" : "shield"} size={19} />
                  <div>
                    <strong>{guardrail.label}</strong>
                    <span>{guardrail.explanation}</span>
                  </div>
                  <code>{guardrail.code}</code>
                </div>
              ))}
            </div>
          </section>
        )}

        {requirement.unsupportedPortion && (
          <section className="unsupported-note" aria-label="Неподтверждённая часть">
            <span>Неподтверждённая часть</span>
            <strong>{requirement.unsupportedPortion}</strong>
          </section>
        )}

        {requirement.clarificationQuestion && (
          <section className="clarification-note" aria-label="Вопрос для уточнения">
            <Icon name="flag" size={20} />
            <div>
              <span>Предлагаемый вопрос</span>
              <strong>{requirement.clarificationQuestion}</strong>
            </div>
          </section>
        )}

        <ConflictView requirement={requirement} />

        <details className="technical-details">
          <summary>
            <Icon name="layers" size={16} />
            Техническая трассировка
            <Icon name="chevron-down" size={15} />
          </summary>
          <div>
            <span>ID требования</span><code>{requirement.id}</code>
            <span>Фрагмент доказательства</span><code>{selectedEvidence.id}</code>
            <span>Версия документа</span><code>{selectedEvidence.documentVersion}</code>
            <span>Политика</span><code>guarded-compliance-v1</code>
          </div>
        </details>
      </div>

      <section className="review-bar" aria-labelledby="human-review-title">
        <div className="review-state">
          <span className="review-icon"><Icon name="shield" size={20} /></span>
          <div>
            <p id="human-review-title">Проверка человеком</p>
            <strong>{reviewState === "APPROVED" ? "Подтверждено человеком в демо" : "Требуется финальное подтверждение"}</strong>
          </div>
          <StatusPill value={reviewState === "APPROVED" ? "APPROVED" : "PENDING"} />
        </div>

        {editing ? (
          <div className="edit-decision-row">
            <label>
              <span className="sr-only">Новое решение</span>
              <select
                aria-label="Новое решение"
                onChange={(event) => setDraftDecision(event.target.value as ComplianceStatus)}
                value={draftDecision}
              >
                {decisionOptions.map((option) => <option key={option} value={option}>{statusLabels[option]}</option>)}
              </select>
            </label>
            <button className="button button-primary" onClick={applyDecision} type="button">Сохранить</button>
            <button className="button button-ghost" onClick={() => setEditing(false)} type="button">Отмена</button>
          </div>
        ) : (
          <div className="review-actions">
            <button className="button button-primary" disabled={reviewState === "APPROVED"} onClick={approve} type="button">
              <Icon name="check" size={16} />
              {reviewState === "APPROVED" ? "Подтверждено" : "Подтвердить"}
            </button>
            <button className="button button-secondary" onClick={() => { setDraftDecision(decision); setEditing(true); }} type="button">
              Изменить решение
            </button>
            <button className="button button-ghost" onClick={() => setActionMessage("Поиск дополнительных доказательств отмечен только в состоянии демо.")} type="button">
              <Icon name="search" size={15} /> Найти ещё доказательства
            </button>
            <button className="button button-ghost" onClick={() => { onReviewStateChange("CLARIFICATION_REQUESTED"); setActionMessage("Запрос на уточнение отмечен локально."); }} type="button">
              Запросить уточнение
            </button>
            <button className="button button-danger" onClick={() => { onReviewStateChange("ESCALATED"); setActionMessage("Требование передано эксперту только в состоянии демо."); }} type="button">
              <Icon name="escalate" size={15} /> Передать эксперту
            </button>
          </div>
        )}
        {actionMessage && <p className="demo-action-message" role="status">{actionMessage}</p>}
      </section>
    </aside>
  );
}
