# Stage 2.4 product-intelligence vertical slice

This stage is a research/application boundary, not an autonomous production workflow. It adds one
end-to-end callable path:

```text
RawRequirement
  -> AtomicRequirementExtractor
  -> deterministic extraction validation
  -> controlled-catalog CapabilityMapper
  -> existing per-requirement EvidenceRetriever
  -> existing EvidenceReranker
  -> EvidenceVerifier per exact span
  -> deterministic provenance/evidence guardrails
  -> explicit conflict aggregation
  -> guarded-compliance-v1 proposal
  -> human-review-ready result (never approved)
```

No production database migration, API route, vector database, new embedding/reranking model, agent,
frontend, or deployment change is part of this stage.

## Safety boundary

The extractor output is not trusted. Exact source text, locator, quote offsets, numbers, units,
comparators, modality, polarity, duplicate atoms and suspicious remaining conjunctions are checked
deterministically. Invalid atoms stop before mapping. Ambiguity becomes `NEEDS_CLARIFICATION` and
human review.

Mapping accepts only IDs in a supplied `ControlledProductCatalog`. The included mapper is a small
deterministic token-overlap baseline; it is replaceable by a learned classifier or graph lookup via
the same contract. Unknown or inconsistent Product, ProductVersion, or Capability IDs become
`NO_MATCH`, never newly created entities.

Retrieval is performed once per accepted atomic requirement through the Stage 2.1/2.2 protocols.
The workflow therefore accepts the existing BM25 + multilingual E5 + weighted RRF retriever and BGE
reranker without rewriting them. Evidence retains the exact EvidenceSpan ID, immutable source hash,
document version, locator, authority, source type, ProductVersion scope and temporal validity.

The verifier returns only `ENTAILS`, `CONTRADICTS`, or `INSUFFICIENT`, reason tags, a concise public
explanation, and an explicit unsupported portion for partial support. The provider verdict remains
in the trace. A separate effective verdict is downgraded when deterministic checks find wrong
ProductVersion, stale dates, roadmap-only material, incomplete provenance, wrong quantitative
metric/limit, or known semantic-neighbor qualifiers such as registered versus concurrent users and
at-rest versus in-transit encryption.

Opposing provider verdicts are never discarded. Conflict output records every EvidenceSpan ID plus
authority, source type, document/product versions and validity dates, and blocks `COMPLY` pending
human review.

`guarded-compliance-v1` has five proposals:

- `COMPLY`: applicable complete-provenance `ENTAILS`, known ProductVersion, no conflict;
- `PARTIAL`: exact partial evidence and an explicit unsupported portion;
- `GAP`: explicit applicable `CONTRADICTS` evidence;
- `UNKNOWN`: unresolved mapping, unavailable/insufficient evidence, or conflict;
- `NEEDS_CLARIFICATION`: materially ambiguous customer language.

Every result has `requires_human_review=true` and `auto_approved=false`. Numeric model confidence is
not a policy gate.

## Research-only OpenAI adapter

`OpenAIResponsesResearchAdapter` is the only real provider adapter. It uses the Responses API with
strict JSON Schema Structured Outputs, `store=false`, `tool_choice="none"`, an empty tools list, and
explicit timeout/retry settings. The default model is `gpt-5.6-terra`; setting `model_id` to
`gpt-5.6-sol` is an explicit escalation configuration. There is no automatic fallback.

The API key is read only from `OPENAI_API_KEY` when a real client is constructed. The adapter refuses
`CONFIDENTIAL` and `RESTRICTED` classifications before any provider call and supports only public or
synthetic material in this stage. It emits typed configuration, data-policy, provider, refusal and
structured-output failures. It does not log keys, source text, prompts, or provider payloads.

Prompt resource files are immutable versions. Every call record contains provider, model, prompt
version, schema version, reasoning effort, SHA-256 of canonical input/output, latency and reported
token usage. Optional observed cost can be attached by research tooling; current pricing is not
hardcoded.

The implementation follows the official OpenAI model and Responses references:

- <https://developers.openai.com/api/docs/models/gpt-5.6-terra>
- <https://developers.openai.com/api/reference/java/resources/beta/subresources/responses>

## Reproducible demos

After installing the project, the no-network public/synthetic demo is:

```powershell
ctrl-intelligence-demo
```

It deliberately uses scripted extraction/verification, feature-hashing dense retrieval and the
identity reranker so it can run in mandatory CI. This proves contracts and safety flow, not model
quality. To exercise the existing pinned E5/BGE components with locally verified model artifacts:

```powershell
ctrl-intelligence-demo `
  --semantic-config evaluations/config/semantic-retrieval-v1.json
```

The opt-in real call uses only a public sentence and is separate from pytest:

```powershell
$env:CTRL_RUN_REAL_LLM_SMOKE = "1"
$env:OPENAI_API_KEY = "<injected secret>"
python -m ctrl_v2.evaluation.openai_llm_smoke
```

It prints executed/model/prompt/tokens/latency/safe-data metadata but never the key. Without both
explicit authorization and the environment secret, no call is made. Mandatory tests always use
deterministic fakes and do not access external APIs.

## Evaluation and limitations

The existing gold benchmark remains manually curated. `IntelligenceComparisonRecord` can later
compare manual, human plus general-purpose LLM, and CTRL runs on atomic recall, exact evidence,
false COMPLY, wrong-version errors, conflicts, corrections, latency and cost. `ResearchTrace` now
also carries mapping and verifier state plus optional token/provider/model metadata.
The sequence builder emits explicit extract, map, retrieve, rerank, verify,
select-or-abstain, and mandatory human-escalation events; an extraction call record can be attached
without copying source content into trace metadata.

No quality claim follows from the small synthetic fixtures. The deterministic language checks are a
conservative safety layer, not complete semantic validation. Before product use, real manually
reviewed gold cases must measure extraction recall, evidence correctness, false COMPLY, wrong-version
errors and conflict detection; prompt/model changes must be evaluated as versioned experiments.
