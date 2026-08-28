import type { EvidenceSpan } from "../types";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

function HighlightedQuote({ quote, highlight }: { quote: string; highlight: string }) {
  const start = quote.indexOf(highlight);
  if (start < 0) return <>{quote}</>;
  const end = start + highlight.length;
  return (
    <>
      {quote.slice(0, start)}
      <mark>{quote.slice(start, end)}</mark>
      {quote.slice(end)}
    </>
  );
}

const sourceTypeLabels: Record<EvidenceSpan["sourceType"], string> = {
  CERTIFICATION: "Сертификационный документ",
  OFFICIAL_SPECIFICATION: "Официальная спецификация",
  PREVIOUS_APPROVED_RESPONSE: "Ранее согласованный ответ",
  RELEASE_NOTES: "Примечания к выпуску",
  ROADMAP: "План развития",
  TEST_REPORT: "Отчёт об испытаниях",
};

const authorityLabels: Record<EvidenceSpan["authority"], string> = {
  AUTHORITATIVE: "Авторитетный источник",
  STRONG: "Надёжный источник",
  SUPPORTING: "Вспомогательный источник",
  WEAK: "Слабый источник",
};

const evidenceStatusLabels: Record<EvidenceSpan["status"], string> = {
  CANDIDATE: "Кандидат",
  REJECTED: "Отклонено",
  VERIFIED: "Проверено",
};

export function EvidenceCard({ evidence, compact = false }: { evidence: EvidenceSpan; compact?: boolean }) {
  const location = [evidence.section, evidence.page ? `стр. ${evidence.page}` : undefined]
    .filter(Boolean)
    .join(" · ");

  return (
    <article className={`evidence-card${compact ? " evidence-card-compact" : ""}`}>
      <div className="evidence-card-head">
        <div className="evidence-identity">
          <Icon name="document" size={17} />
          <div>
            <strong>{evidence.documentName}</strong>
            <span>{evidence.documentVersion}</span>
          </div>
        </div>
        <StatusPill showCode value={evidence.effectiveVerdict} />
      </div>

      <blockquote>
        <span className="quote-mark">“</span>
        <HighlightedQuote highlight={evidence.highlight} quote={evidence.quote} />
      </blockquote>

      {!compact && (
        <>
          <div className="source-grid">
            <div>
              <span>Место в источнике</span>
              <strong>{location}</strong>
            </div>
            <div>
              <span>Версия продукта</span>
              <strong>{evidence.productVersion}</strong>
            </div>
            <div>
              <span>Авторитетность</span>
              <strong>{authorityLabels[evidence.authority]}</strong>
            </div>
            <div>
              <span>Тип источника</span>
              <strong>{sourceTypeLabels[evidence.sourceType]}</strong>
            </div>
            <div>
              <span>Период применимости</span>
              <strong>
                {evidence.validFrom} → {evidence.validTo ?? "по настоящее время"}
              </strong>
            </div>
            <div>
              <span>Статус доказательства</span>
              <strong>{evidenceStatusLabels[evidence.status]}</strong>
            </div>
          </div>
          <p className="evidence-explanation">{evidence.explanation}</p>
        </>
      )}
    </article>
  );
}
