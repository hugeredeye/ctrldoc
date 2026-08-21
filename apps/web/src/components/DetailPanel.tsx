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
    <div className="mapping-path" aria-label="Цепочка mapping">
      <div>
        <span>Product</span>
        <strong>{mapping.product.name}</strong>
      </div>
      <Icon name="arrow-right" size={16} />
      <div>
        <span>Product version</span>
        <strong>{mapping.productVersion.label}</strong>
      </div>
      <Icon name="arrow-right" size={16} />
      <div>
        <span>Capability</span>
        <strong>{mapping.capability.name}</strong>
      </div>
      <span className="mapping-confidence">{Math.round(mapping.confidence * 100)}% mapping</span>
    </div>
  );
}

function SemanticMismatch({ evidence }: { evidence: EvidenceSpan }) {
  return (
    <section className="semantic-mismatch" aria-labelledby="semantic-mismatch-title">
      <div className="mismatch-intro">
        <span className="mismatch-kicker">CTRL verification path</span>
        <h3 id="semantic-mismatch-title">Семантически близко — логически недостаточно</h3>
      </div>
      <div className="verdict-route">
        <div className="route-step route-model">
          <span>Model candidate</span>
          <strong>Semantic evidence found</strong>
          <StatusPill value={evidence.verifierCandidate} quiet />
        </div>
        <Icon name="arrow-right" size={18} />
        <div className="route-step route-guardrail">
          <span>CTRL guardrail</span>
          <strong>Metric mismatch</strong>
          <em>registered ≠ concurrent</em>
        </div>
        <Icon name="arrow-right" size={18} />
        <div className="route-step route-effective">
          <span>Effective verdict</span>
          <strong>Evidence rejected</strong>
          <StatusPill value={evidence.effectiveVerdict} />
        </div>
      </div>
      <div className="safe-outcome">
        <Icon name="shield" size={20} />
        <div>
          <strong>Safe abstention</strong>
          <span>Decision UNKNOWN · human review required</span>
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
          <p className="eyebrow">Material conflict</p>
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
        CTRL не скрывает opposing evidence и не выбирает удобный источник автоматически.
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
    setActionMessage("Решение изменено локально. Production record не создан.");
  };

  const approve = () => {
    onReviewStateChange("APPROVED");
    setActionMessage("Решение подтверждено только в demo-state.");
  };

  return (
    <aside className="detail-panel" aria-label={`Детали ${requirement.shortId}`}>
      <div className="detail-topbar">
        <div className="detail-identifiers">
          <span className="requirement-id">{requirement.shortId}</span>
          <span>{requirement.category}</span>
          <StatusPill value={requirement.risk} quiet />
        </div>
        <button className="icon-button" aria-label="Дополнительные действия" type="button">
          <span />
          <span />
          <span />
        </button>
      </div>

      <div className="detail-scroll">
        <section className="customer-requirement" aria-labelledby="customer-requirement-title">
          <p className="eyebrow">Customer requirement</p>
          <h2 id="customer-requirement-title">{requirement.text}</h2>
          <div className="source-reference">
            <Icon name="document" size={15} />
            {requirement.sourceLocation}
          </div>
        </section>

        <MappingPath requirement={requirement} />

        <section className="decision-band" aria-label="Предлагаемое решение">
          <div>
            <span>Proposed compliance</span>
            <StatusPill value={decision} />
          </div>
          <div>
            <span>Effective verdict</span>
            <StatusPill value={selectedEvidence.effectiveVerdict} />
          </div>
          <div className="review-reason">
            <span>Review rationale</span>
            <strong>{requirement.reviewReason}</strong>
          </div>
        </section>

        {isSemanticMismatch && <SemanticMismatch evidence={selectedEvidence} />}

        <section className="evidence-section" aria-labelledby="evidence-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Source-grounded evidence</p>
              <h3 id="evidence-title">Evidence spans</h3>
            </div>
            <span className="section-count">{requirement.evidence.length} candidate(s)</span>
          </div>
          {requirement.evidence.length > 1 && (
            <div className="evidence-tabs" role="tablist" aria-label="Evidence candidates">
              {requirement.evidence.map((item, index) => (
                <button
                  aria-selected={selectedEvidence.id === item.id}
                  key={item.id}
                  onClick={() => setSelectedEvidenceId(item.id)}
                  role="tab"
                  type="button"
                >
                  Evidence {index + 1}
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
                <p className="eyebrow">Deterministic policy</p>
                <h3 id="guardrails-title">Active guardrails</h3>
              </div>
              <span className="section-count">{requirement.guardrails.length} active</span>
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
            <span>Unsupported portion</span>
            <strong>{requirement.unsupportedPortion}</strong>
          </section>
        )}

        {requirement.clarificationQuestion && (
          <section className="clarification-note" aria-label="Вопрос для уточнения">
            <Icon name="flag" size={20} />
            <div>
              <span>Suggested clarification</span>
              <strong>{requirement.clarificationQuestion}</strong>
            </div>
          </section>
        )}

        <ConflictView requirement={requirement} />

        <details className="technical-details">
          <summary>
            <Icon name="layers" size={16} />
            Technical trace
            <Icon name="chevron-down" size={15} />
          </summary>
          <div>
            <span>Requirement ID</span><code>{requirement.id}</code>
            <span>EvidenceSpan</span><code>{selectedEvidence.id}</code>
            <span>DocumentVersion</span><code>{selectedEvidence.documentVersion}</code>
            <span>Policy</span><code>guarded-compliance-v1</code>
          </div>
        </details>
      </div>

      <section className="review-bar" aria-labelledby="human-review-title">
        <div className="review-state">
          <span className="review-icon"><Icon name="shield" size={20} /></span>
          <div>
            <p id="human-review-title">Human approval</p>
            <strong>{reviewState === "APPROVED" ? "Approved in demo" : "Final approval required"}</strong>
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
                {decisionOptions.map((option) => <option key={option}>{option}</option>)}
              </select>
            </label>
            <button className="button button-primary" onClick={applyDecision} type="button">Сохранить</button>
            <button className="button button-ghost" onClick={() => setEditing(false)} type="button">Отмена</button>
          </div>
        ) : (
          <div className="review-actions">
            <button className="button button-primary" disabled={reviewState === "APPROVED"} onClick={approve} type="button">
              <Icon name="check" size={16} />
              {reviewState === "APPROVED" ? "Подтверждено" : "Approve"}
            </button>
            <button className="button button-secondary" onClick={() => { setDraftDecision(decision); setEditing(true); }} type="button">
              Edit decision
            </button>
            <button className="button button-ghost" onClick={() => setActionMessage("Поиск evidence отмечен в demo-state.")} type="button">
              <Icon name="search" size={15} /> Find more evidence
            </button>
            <button className="button button-ghost" onClick={() => { onReviewStateChange("CLARIFICATION_REQUESTED"); setActionMessage("Запрос на уточнение отмечен локально."); }} type="button">
              Request clarification
            </button>
            <button className="button button-danger" onClick={() => { onReviewStateChange("ESCALATED"); setActionMessage("Требование эскалировано в demo-state."); }} type="button">
              <Icon name="escalate" size={15} /> Escalate
            </button>
          </div>
        )}
        {actionMessage && <p className="demo-action-message" role="status">{actionMessage}</p>}
      </section>
    </aside>
  );
}
