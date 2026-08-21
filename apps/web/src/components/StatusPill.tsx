import type { ComplianceStatus, RiskLevel, VerifierVerdict } from "../types";

type PillValue = ComplianceStatus | RiskLevel | VerifierVerdict | "APPROVED" | "PENDING";

const display: Record<PillValue, string> = {
  APPROVED: "APPROVED",
  BLOCKING: "BLOCKING",
  COMPLY: "COMPLY",
  CONTRADICTS: "CONTRADICTS",
  ENTAILS: "ENTAILS",
  GAP: "GAP",
  HIGH: "HIGH",
  INSUFFICIENT: "INSUFFICIENT",
  LOW: "LOW",
  MEDIUM: "MEDIUM",
  NEEDS_CLARIFICATION: "CLARIFY",
  PARTIAL: "PARTIAL",
  PENDING: "PENDING",
  UNKNOWN: "UNKNOWN",
};

export function StatusPill({ value, quiet = false }: { value: PillValue; quiet?: boolean }) {
  return (
    <span className={`status-pill status-${value.toLowerCase()}${quiet ? " status-quiet" : ""}`}>
      <span className="status-dot" />
      {display[value]}
    </span>
  );
}
