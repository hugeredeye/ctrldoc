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
