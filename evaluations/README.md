# Manual gold evaluation datasets

No synthetic product dataset is generated or committed. Gold cases are authored and reviewed by
humans, with source assets stored beside the versioned dataset according to the repository's data
governance policy.

Schema `2.0` makes every case workspace-independent and contains:

- one source requirement, optional context and its exact locator;
- one or more gold atomic requirements;
- optional expected Product/ProductVersion/Capability mappings;
- exact positive EvidenceSpans with authority, source type, document version, temporal validity and
  locator;
- explicit hard-negative EvidenceSpans and their annotation reason;
- optional explicit hard-negative error tags for version, temporal, roadmap, authority, conflict
  and non-entailment slices;
- a gold compliance outcome for every atomic requirement (`COMPLY`, `PARTIAL`, `GAP`, `UNKNOWN`, or
  `NEEDS_CLARIFICATION`);
- annotator, annotation version and provenance metadata.

`CHECKED_IN_TEST` datasets must declare `contains_customer_data=false`. The checked-in loader rejects
other scopes, customer-data declarations and tenant/workspace identifier fields. Real evaluation
datasets use `EXTERNAL_RESTRICTED` and remain outside Git.

Create an empty dataset:

```text
python -m ctrl_v2.evaluation.authoring init evaluations/datasets/<name>/<version>/dataset.json \
  --dataset-id <name> --version <version> --description "Human curated dataset" \
  --scope EXTERNAL_RESTRICTED
```

Review and author a case JSON against `schema/gold-dataset.schema.json` definitions, then append it:

```text
python -m ctrl_v2.evaluation.authoring add-case <dataset.json> <reviewed-case.json>
python -m ctrl_v2.evaluation.authoring validate <dataset.json>
```

The CLI never invents source text, requirements, mappings, evidence, or outcomes. `init` only
creates an empty metadata envelope, and `add-case` accepts a complete manually authored case.

## Retrieval baselines

Run the small automated-test fixture through directly comparable lexical, dense and hybrid
baselines:

```text
python -m ctrl_v2.evaluation.retrieval_runner \
  evaluations/fixtures/stage2-retrieval-v1.json \
  --checked-in-fixture --output runtime/evaluations/stage2-result.json
```

The strategies are:

- standard Okapi BM25 with explicit `k1`, `b` and deterministic tie-breaking;
- cosine dense retrieval through a vendor-neutral embedding interface;
- weighted Reciprocal Rank Fusion over lexical and dense rankings;
- an identity reranker implementing the vendor-neutral reranking contract.

The built-in dependency-free dense adapter is a deterministic feature-hashing document embedding.
It is a reproducible engineering baseline, not a semantic neural embedding model. A future model can
replace it through the `EmbeddingModel` interface without changing gold data, metrics or domain code.

Each serialized run records dataset version/hash, run ID, implementation and model identifiers,
parameters, seed, Git commit when available, candidate counts, per-query latency, ranked provenance,
Recall@1/3/5, MRR and nDCG@1/3/5.

## External semantic-retrieval datasets

Real Stage 2.2 datasets are never checked in. Keep separately reviewed dataset files for development
and test, both using GoldDataset `2.0`:

```text
<restricted-root>/semantic-retrieval/dev/dataset.json
<restricted-root>/semantic-retrieval/test/dataset.json
```

The development dataset may be used to choose RRF weights or candidate N. Record its SHA-256 in the
experiment configuration. Freeze the configuration before opening the test dataset. Test positives,
hard negatives and test metrics must never be used for tuning. Stage 2.2 performs no model fitting,
and there is currently no training split consumer.

The external dataset should contain manually reviewed Russian, English and mixed-terminology cases,
including wrong ProductVersion, obsolete sources, roadmap-only claims, non-entailing semantic
matches, conflicts, authority differences and temporal-validity errors. Annotators should set
explicit `error_tags` for applicable slices. Missing tags remain unavailable; the evaluator does not
infer gold labels.

No manually reviewed external dataset is present in this repository. Therefore real BM25-versus-
neural retrieval quality is not yet established.

## CTRL Gold Benchmark v1 authoring boundary

Stage 2.3 adds strict external-benchmark validation, human review lifecycle, grouped deterministic
DEV/TEST splitting, content-free manifests and diagnostics, and a hash-bound blind TEST protocol.
It does not add benchmark content. The complete evidence annotation guide and first real benchmark
procedure are in `docs/gold-benchmark-v1.md`.

The checked split configuration groups connected document/source-case families instead of randomly
splitting rows:

```text
python -m ctrl_v2.evaluation.authoring validate-benchmark <external-dataset.json>
python -m ctrl_v2.evaluation.authoring diagnostics <external-dataset.json>
python -m ctrl_v2.evaluation.authoring split <external-dataset.json> \
  evaluations/config/gold-benchmark-split-v1.json <external-split-manifest.json>
python -m ctrl_v2.evaluation.authoring manifest <external-dataset.json> \
  <external-split-manifest.json> <external-benchmark-manifest.json>
```

External dataset and blind-result paths inside the repository must remain ignored and untracked.
The tooling refuses to treat `CHECKED_IN_TEST` fixtures as the real benchmark.

## Stage 2.2 pinned neural experiment

Install the isolated CPU research stack without changing production dependencies:

```text
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.1.2+cpu
python -m pip install -e ".[research]"
```

Pinned configuration: `config/semantic-retrieval-v1.json`.

- embedding: `intfloat/multilingual-e5-large-instruct` at
  `84344a23ee1820ac951bc365f1e91d094a911763`;
- reranker: `BAAI/bge-reranker-v2-m3` at
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`;
- both weight and model-config SHA-256 values are verified before load;
- configuration defaults to offline loading and never falls back to feature hashing.

Acquire artifacts explicitly while network access is permitted, using the exact revisions, then run
with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. Execute an external experiment:

```text
python -m ctrl_v2.evaluation.semantic_runner \
  <external-test-dataset.json> evaluations/config/semantic-retrieval-v1.json \
  --output runtime/evaluations/semantic-result.json
```

The four reported methods are BM25, neural dense, hybrid RRF, and hybrid top-N plus cross-encoder
reranking. Reports include mean/p50/p95 total latency, retrieval/reranking phase latency, corpus and
candidate sizes, exact model identities and error slices.
