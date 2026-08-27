# Stage 2.5 official DeepSeek V4 Pro research provider

This stage adds one inference adapter. It does not redesign product intelligence, change production
runtime, add model routing, or let a model decide `COMPLY`, `PARTIAL`, or `GAP` directly.

```text
AtomicRequirementExtractor
  ├─ Scripted/Fake
  ├─ OpenAI Responses
  └─ Official DeepSeek Chat Completions

EvidenceVerifier
  ├─ Scripted/Fake
  ├─ OpenAI Responses
  └─ Official DeepSeek Chat Completions
```

Everything after inference remains provider-independent: extraction validation, controlled
Capability mapping, per-requirement retrieval, reranking, provenance/version/authority/temporal
guardrails, conflict aggregation, guarded-compliance-v1, and mandatory human review.

Atomic extraction currently keeps provider-supplied character offsets in its `1.0` response schema
for compatibility, but treats them only as diagnostics. CTRL resolves each exact `source_quote`
inside the source unit identified by the authoritative locator and computes canonical Python string
offsets. A missing or repeated exact quote is rejected; there is no fuzzy or cross-unit recovery.
A future provider-contract version should omit offsets and request only the exact quote and locator,
leaving all character counting to deterministic CTRL code.

## Official API boundary

The adapter has a non-configurable official base URL, a constrained model ID, and no provider
fallback:

```text
base URL: https://api.deepseek.com
endpoint: https://api.deepseek.com/chat/completions
model: deepseek-v4-pro
API key environment variable: DEEPSEEK_API_KEY
```

The official quick start currently states that `deepseek-v4-pro` resolves to the current V4 Pro
snapshot while the calling alias remains stable. The request explicitly sends thinking mode instead
of accepting its default. Research defaults are thinking enabled with `high` effort, 4,096 maximum
output tokens, a 60-second timeout, zero SDK transport retries, and at most one output retry.
`low`, `high`, and `max` reasoning effort are configurable; disabled thinking omits
`reasoning_effort` from the request.

The provider defaults remain unchanged. The opt-in smoke has two explicit experiment profiles:

- `FAST`: thinking disabled, 4,096 maximum output tokens;
- `REASONING`: thinking enabled with `high` effort, 8,192 maximum output tokens.

The smoke requires `--mode`; it does not infer a profile or silently change the adapter default.
The effective thinking setting, effort, timeout, token budget, and retry bound are retained in each
successful `ModelCallRecord.provider_configuration`.

Official references:

- <https://api-docs.deepseek.com/>
- <https://api-docs.deepseek.com/api/create-chat-completion>
- <https://api-docs.deepseek.com/guides/json_mode>
- <https://api-docs.deepseek.com/guides/thinking_mode>
- <https://api-docs.deepseek.com/quick_start/error_codes>

OpenRouter, resellers, proxy gateways, legacy `deepseek-chat`, and legacy `deepseek-reasoner` cannot
be configured through this adapter.

## JSON output and typed failure

DeepSeek JSON Output is deliberately not represented as OpenAI strict Structured Outputs. Each
request:

1. enables `response_format={"type":"json_object"}`;
2. supplies a provider-specific immutable prompt containing an example and the exact Pydantic JSON
   Schema;
3. parses the final content as JSON;
4. validates it without repair against the existing strict CTRL contract.

Empty content and syntactically invalid JSON may be retried only up to the configured bound. Valid
JSON that violates the schema is not retried or repaired. Truncated output, unexpected tool calls,
API failures, missing credentials, and policy violations have distinct typed failures. There is no
fallback to OpenAI or another provider and no failure can become a compliance decision.

`TRUNCATED_OUTPUT` is emitted only when the SDK response reports
`choices[0].finish_reason == "length"`. Content from such a response is rejected before JSON parsing
or schema validation, even if the partial content happens to be syntactically valid JSON.

The response's `reasoning_content` is ignored and never stored in `ModelCallRecord`. A successful
record contains provider, actual and requested model IDs, prompt/schema versions, effective
thinking configuration, timeout, output limit, retry bounds/count, privacy-safe input/output hashes,
finish reason, latency, prompt/completion/reasoning/total token usage, and non-sensitive prior
failure reason codes. Typed provider failures retain the same available response metadata without
retaining content or hidden reasoning. Pricing is not encoded.

`SCHEMA_INVALID` also reports privacy-safe Pydantic diagnostics: schema model name, error count,
locations and JSON paths, error types, concise messages, returned top-level keys, and the SHA-256 of
the canonical JSON output. Raw output remains hidden by default. The smoke-only
`--show-synthetic-output` switch may expose parsed JSON only for the CLI's built-in
`SYNTHETIC_SAFE` fixtures; enabling it restricts the adapter to that classification exclusively.
The adapter additionally requires the canonical input hash to match one of those built-in cases.
It is not a general logging option and never includes `reasoning_content`.

## Data and logging policy

Allowed classifications are only:

- `PUBLIC`
- `DEMO`
- legacy `SYNTHETIC`
- `SYNTHETIC_SAFE`

The following are rejected before payload serialization and before calling the client:

- `CONFIDENTIAL`
- `RESTRICTED`
- `PERSONAL_DATA`
- `CUSTOMER_CONFIDENTIAL`

Classification is still caller-supplied research metadata, not automated DLP. Therefore this
adapter must not be exposed to tenant documents or production request paths. It never attempts
anonymization to bypass the boundary and does not log keys, authorization headers, payloads, source
documents, or hidden reasoning.

## One public-safe smoke

The smoke performs exactly three hard-coded public/synthetic-safe cases: Russian three-way atomic
extraction, registered-versus-concurrent users, and roadmap-versus-released capability. It reports
the actual model, API-call status, parse status, tokens, latency, retries, provider/effective labels,
guardrail changes, and guarded decision. It makes no model-quality claim.

Obtain a key from the official platform only:

1. Open <https://platform.deepseek.com/api_keys> and sign in to the official DeepSeek Platform.
2. Create a dedicated disposable/research API key; do not reuse a production credential.
3. Confirm account balance/usage controls in the official platform.
4. Install the checked research dependencies: `python -m pip install -e ".[research]"`.
5. In a fresh PowerShell session, inject the key without writing it into a command, file, or history:

```powershell
$deepseekSecret = Read-Host "DeepSeek research API key" -AsSecureString
$deepseekPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($deepseekSecret)
try {
  $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($deepseekPointer)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($deepseekPointer)
}
$env:CTRL_RUN_REAL_DEEPSEEK_SMOKE = "true"
```

6. Run the controlled profiles separately with zero output retries so the comparison cannot add an
   unplanned provider call:

```powershell
ctrl-deepseek-smoke --mode FAST --timeout-seconds 180 --retries 0
ctrl-deepseek-smoke --mode REASONING --timeout-seconds 180 --retries 0
```

For one explicitly authorized schema-debug rerun of the built-in synthetic FAST case:

```powershell
ctrl-deepseek-smoke --mode FAST --timeout-seconds 180 --retries 0 --show-synthetic-output
```

7. Confirm each report identifies `mode`, `max_output_tokens`, thinking configuration, actual model,
   finish reason, token details, latency, and retry count. A `TRUNCATED_OUTPUT` report must show
   `finish_reason="length"` and `structured_parse_success=false`. On success, confirm both safety
   cases are not effective `ENTAILS`/`COMPLY`, and inspect whether guardrails downgraded the provider.
8. Remove the process-local secrets immediately:

```powershell
Remove-Item Env:DEEPSEEK_API_KEY
Remove-Item Env:CTRL_RUN_REAL_DEEPSEEK_SMOKE
```

Never use a customer RFP, technical specification, internal product document, personal data, or
confidential text for this smoke.

## After a successful smoke

Keep DeepSeek research-only. The next evidence-based step is to run DeepSeek V4 Pro and GPT-5.6
Terra on identical manually reviewed Gold Benchmark cases, record provider/model/prompt/config
identity, and compare extraction recall, evidence correctness, false COMPLY, version errors,
conflict detection, corrections, latency, and observed token usage. Production integration should
remain blocked until benchmark results, legal/privacy review, and an explicit deployment decision.
