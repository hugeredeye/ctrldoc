export type ComplianceStatus =
  | "COMPLY"
  | "PARTIAL"
  | "GAP"
  | "UNKNOWN"
  | "NEEDS_CLARIFICATION";

export type VerifierVerdict = "ENTAILS" | "CONTRADICTS" | "INSUFFICIENT";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "BLOCKING";
export type ReviewState = "PENDING" | "APPROVED" | "ESCALATED" | "CLARIFICATION_REQUESTED";
export type EvidenceStatus = "VERIFIED" | "CANDIDATE" | "REJECTED";
export type EvidenceAuthority = "AUTHORITATIVE" | "STRONG" | "SUPPORTING" | "WEAK";
export type EvidenceSourceType =
  | "OFFICIAL_SPECIFICATION"
  | "CERTIFICATION"
  | "TEST_REPORT"
  | "RELEASE_NOTES"
  | "ROADMAP"
  | "PREVIOUS_APPROVED_RESPONSE";

export interface Product {
  id: string;
  name: string;
}

export interface ProductVersion {
  id: string;
  label: string;
  validFrom: string;
  validTo?: string;
}

export interface Capability {
  id: string;
  name: string;
}

export interface RequirementMapping {
  product: Product;
  productVersion: ProductVersion;
  capability: Capability;
  confidence: number;
}

export interface EvidenceSpan {
  id: string;
  quote: string;
  highlight: string;
  documentName: string;
  documentVersion: string;
  section: string;
  page?: number;
  productVersion: string;
  authority: EvidenceAuthority;
  sourceType: EvidenceSourceType;
  validFrom: string;
  validTo?: string;
  status: EvidenceStatus;
  verifierCandidate: VerifierVerdict;
  effectiveVerdict: VerifierVerdict;
  explanation: string;
}

export interface Guardrail {
  code:
    | "METRIC_MISMATCH"
    | "WRONG_VERSION"
    | "ROADMAP_ONLY"
    | "WEAK_AUTHORITY"
    | "TEMPORAL_INVALIDITY"
    | "PROVENANCE_INCOMPLETE"
    | "UNRESOLVED_CONFLICT"
    | "PARTIAL_SUPPORT";
  label: string;
  explanation: string;
  severity: "warning" | "critical";
}

export interface Conflict {
  id: string;
  material: boolean;
  evidenceSpanIds: [string, string];
  explanation: string;
}

export interface AtomicRequirement {
  id: string;
  shortId: string;
  text: string;
  sourceText: string;
  category: string;
  sourceLocation: string;
  decision: ComplianceStatus;
  risk: RiskLevel;
  needsReview: boolean;
  reviewReason: string;
  reviewState: ReviewState;
  mapping: RequirementMapping;
  evidence: EvidenceSpan[];
  selectedEvidenceId: string;
  guardrails: Guardrail[];
  conflict?: Conflict;
  unsupportedPortion?: string;
  clarificationQuestion?: string;
}

export interface ReviewUpdate {
  state: ReviewState;
  decision: ComplianceStatus;
}
