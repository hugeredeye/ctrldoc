# ADR 0001: Stage 0/1 baseline

Status: accepted for implementation by the user, with the amendments below.

## Runtime shape

CTRL v2 is an independent modular monolith. FastAPI and the future worker share application and
domain modules. CTRL v1 is not imported. PostgreSQL is the system of record; object storage is
private and accessed only through a port.

## Straight-through and risk-based review

Future automation proceeds extraction -> mapping -> retrieval -> assessment -> conflict
detection without mandatory review gates. Intermediate human intervention is created only for
low confidence, ambiguity, a conflict, or a configured policy. Every final compliance decision
still requires human approval. LOW-risk, high-confidence decisions with strong, consistent
evidence can be approved in a batch; mappings do not require individual confirmation.

Review risk is LOW, MEDIUM, HIGH, or BLOCKING. Risk is stored with the decision/review so a model,
prompt, parser, or retrieval change cannot silently reinterpret an old review.

## Authority and time

Evidence has an explicit source type and authority level. Evidence, ProductVersion, and
ComplianceDecision carry temporal scope. COMPLY/PARTIAL approval requires at least one evidence
span whose evidence is applicable on the decision assessment date. Product capability statements
are never treated as timeless.

## Evaluation boundary

Extraction, retrieval, decision, and conflict implementations must run against a versioned
dataset before promotion. Runs record dataset, parser, prompt, model, retrieval and contract
versions. Required product metrics are Atomic Requirement Recall, Evidence Recall@K, Compliance
Accuracy, Critical False Comply Rate, and Unedited Human Approval Rate.

## Product knowledge bootstrap

Capability extraction is a provider-neutral port and structured proposal contract. A proposal is
never a Capability until approved by a human. Stage 1 contains no implementation.

## Stage 1 limitation

All AI and retrieval artifacts are entered manually. This is intentional; no placeholder
heuristics masquerade as production automation.
