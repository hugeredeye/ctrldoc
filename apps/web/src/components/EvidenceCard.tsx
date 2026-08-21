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

function formatSourceType(sourceType: EvidenceSpan["sourceType"]) {
  return sourceType.replaceAll("_", " ");
}

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
        <StatusPill value={evidence.effectiveVerdict} />
      </div>

      <blockquote>
        <span className="quote-mark">“</span>
        <HighlightedQuote highlight={evidence.highlight} quote={evidence.quote} />
      </blockquote>

      {!compact && (
        <>
          <div className="source-grid">
            <div>
              <span>Location</span>
              <strong>{location}</strong>
            </div>
            <div>
              <span>Product version</span>
              <strong>{evidence.productVersion}</strong>
            </div>
            <div>
              <span>Authority</span>
              <strong>{evidence.authority}</strong>
            </div>
            <div>
              <span>Source type</span>
              <strong>{formatSourceType(evidence.sourceType)}</strong>
            </div>
            <div>
              <span>Applicable</span>
              <strong>
                {evidence.validFrom} → {evidence.validTo ?? "present"}
              </strong>
            </div>
            <div>
              <span>Evidence status</span>
              <strong>{evidence.status}</strong>
            </div>
          </div>
          <p className="evidence-explanation">{evidence.explanation}</p>
        </>
      )}
    </article>
  );
}
