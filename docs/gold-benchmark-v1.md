# CTRL Gold Benchmark v1

CTRL Gold Benchmark v1 is an external, uncommitted, human-reviewed evaluation dataset. It is a
research boundary around GoldDataset `2.0`, not a production data store or an annotation platform.
Customer, tenant, workspace and organization identifiers are forbidden as benchmark identity.
Authorized confidential source material and all result artifacts stay outside Git or under an
explicitly ignored local research path.

## Evidence annotation guide

### Positive EvidenceSpan

A passage is positive only when its exact words directly support or directly contradict a concrete
atomic requirement and are usable for downstream compliance reasoning. Preserve its document hash,
document and product version, temporal validity, source type, authority and exact locator. Select the
smallest self-contained quote that retains the qualifying conditions and quantitative limits.

Semantic similarity, shared terminology, product marketing context, or mention of a related feature
is not entailment. Such passages are not positive evidence.

### Hard negative

A hard negative is plausible enough to challenge retrieval but does not prove the atomic
requirement. Record a human reason and every applicable error tag:

| Category | Tag |
|---|---|
| Same product, wrong version | `WRONG_PRODUCT_VERSION` |
| Obsolete documentation | `OBSOLETE_SOURCE` |
| Roadmap or unreleased capability | `ROADMAP_NOT_RELEASED` |
| Related feature, missing required capability | `RELATED_FEATURE_MISSING_CAPABILITY` |
| Same terminology, different semantics | `SAME_TERMINOLOGY_DIFFERENT_SEMANTICS` |
| Similar but non-entailing passage | `NON_ENTAILING` |
| Insufficient quantitative limit | `INSUFFICIENT_QUANTITATIVE_LIMIT` |
| Lower-authority source conflicts with stronger evidence | `LOWER_AUTHORITY_CONTRADICTION`, `SOURCE_AUTHORITY` |
| Evidence invalid for the assessment date | `TEMPORAL_VALIDITY` |
| Partial evidence for a compound requirement | `PARTIAL_COMPOUND_EVIDENCE` |
| Plausible previous response without current authoritative support | `PREVIOUS_RESPONSE_UNVERIFIED` |
| Explicitly conflicting evidence | `CONFLICTING_EVIDENCE` |

Hard negatives retain the same provenance standard as positives. A wrong-version or obsolete span
must identify the actual version and validity period; it must not be relabelled as if current.

### Ambiguity and abstention

Do not force a positive, hard-negative, mapping or compliance label when the source is genuinely
unclear. Record the uncertainty in review disagreement/notes and keep the case `DRAFT`, or omit the
optional compliance outcome. A requirement without a defensible positive and hard negative is not
eligible for the frozen retrieval benchmark. Split compound requirements before annotation whenever
possible; otherwise treat a passage proving only one clause as a hard negative for the compound.

## Required benchmark metadata

Every atomic requirement records `RU`, `EN`, `MIXED`, or `OTHER`. Every case records a safe source
category and grouping identifiers for document family and source-case family; product and
ProductVersion family identifiers are added when known. Group identifiers describe shared origins,
not customers. Evidence has a stable key and SHA-256 of the exact source bytes.

The checked-in JSON Schema is at `evaluations/schema/gold-dataset.schema.json`. GoldDataset parsing
remains backward-compatible for small `CHECKED_IN_TEST` fixtures, while benchmark readiness applies
the stricter external-dataset validator.

## Review lifecycle

1. `DRAFT`: primary annotator authors requirements, mapping, evidence and reasons.
2. `REVIEWED`: a different reviewer independently checks exact quotes, labels and provenance.
3. `ADJUDICATED`: a disagreement is recorded and resolved with adjudicator, timestamp and note.
4. `FROZEN`: reviewed case is closed for the dataset version. Disagreements require complete
   adjudication before freeze.

Cases with no disagreement may move from `REVIEWED` to `FROZEN`. Changes to a frozen case require a
new annotation and dataset version; do not silently rewrite the reported benchmark version.

## External layout and authoring

Recommended external layout:

```text
<restricted-root>/ctrl-gold-benchmark-v1/
  dataset.json
  cases/
  assets/
  manifests/
  results/
```

Initialize and append complete manually authored cases:

```text
python -m ctrl_v2.evaluation.authoring init <restricted-root>/dataset.json \
  --dataset-id ctrl-gold-benchmark-v1 --version 1.0.0 \
  --description "Human-reviewed CTRL evidence retrieval benchmark"
python -m ctrl_v2.evaluation.authoring validate-case <reviewed-case.json>
python -m ctrl_v2.evaluation.authoring add-case <dataset.json> <reviewed-case.json>
python -m ctrl_v2.evaluation.authoring validate <dataset.json>
python -m ctrl_v2.evaluation.authoring validate-benchmark <dataset.json> \
  --repository C:/dev/ctrl-v2
python -m ctrl_v2.evaluation.authoring diagnostics <dataset.json> \
  --output <restricted-root>/manifests/diagnostics.json
python -m ctrl_v2.evaluation.authoring inspect-disagreements <dataset.json>
```

`validate-benchmark` requires external scope, language, benchmark metadata, explicit evidence keys,
source SHA-256, positives, hard negatives with human tags, unique evidence identities and consistent
explicit ProductVersion references. An external file inside the repository must be Git-ignored and
untracked.

## Grouped deterministic split

Use `evaluations/config/gold-benchmark-split-v1.json` as the reviewed starting configuration:

```text
python -m ctrl_v2.evaluation.authoring split <dataset.json> \
  evaluations/config/gold-benchmark-split-v1.json <split-manifest.json>
python -m ctrl_v2.evaluation.authoring manifest <dataset.json> \
  <split-manifest.json> <benchmark-manifest.json>
```

The splitter forms connected components across all selected grouping fields. Cases sharing any
selected source family remain together even through transitive links. Components are assigned by a
seeded hash; row-level random splitting is not used. The manifest contains safe case IDs, hashed
group IDs, dataset/subset hashes, strategy, seed and commit, but no requirements or evidence text.
If fewer than two independent components exist, DEV/TEST generation fails.

Optional `TRAIN` membership is represented by a non-zero `train_fraction`, but no training consumer
exists in this stage. Keep it zero for Benchmark v1 unless a later approved stage requires training.

## Blind test protocol

After all TEST cases are `FROZEN`, freeze the TEST semantic configuration:

```text
python -m ctrl_v2.evaluation.authoring freeze-test-config <dataset.json> \
  <split-manifest.json> <semantic-test-config.json> <frozen-config.json> \
  --frozen-by <researcher-alias>
python -m ctrl_v2.evaluation.authoring verify-frozen-test <dataset.json> \
  <split-manifest.json> <semantic-test-config.json> <frozen-config.json>
python -m ctrl_v2.evaluation.authoring blind-test <dataset.json> \
  <split-manifest.json> <semantic-test-config.json> <frozen-config.json> \
  <ignored-results-path>/primary-result.json
```

The frozen record binds the DEV hash, TEST hash, split-manifest hash and complete semantic-config
hash. Any post-freeze configuration mutation fails verification, and the blind run must use the
recorded code commit. The runner selects only TEST cases and creates a new result file with
exclusive-create semantics; it will not overwrite an existing primary artifact. The returned file
SHA-256 must be retained with the report.

This prevents accidental contamination and makes changes auditable. It cannot prevent a researcher
from deliberately reading TEST data, deleting artifacts or choosing a new output filename.

## First real benchmark procedure

1. Obtain written authorization for every source collection and choose benchmark-safe aliases.
2. Copy source bytes to restricted storage and calculate SHA-256 before annotation.
3. Author cases and atomic requirements; assign language and source-family metadata.
4. Add exact positive spans and deliberately selected hard negatives with provenance and tags.
5. Add Product/ProductVersion/Capability mappings and optional compliance labels only when known.
6. Perform independent review and record disagreements.
7. Adjudicate disagreements; leave genuinely unresolved cases out of the frozen retrieval set.
8. Freeze cases and dataset version, then run strict validation and diagnostics.
9. Generate the deterministic grouped DEV/TEST split and content-free benchmark manifest.
10. Tune instructions, N, K and RRF weights only on DEV.
11. Create a TEST semantic config carrying the exact DEV hash, then freeze its configuration hash.
12. Run the primary TEST artifact once and retain its output SHA-256.
13. Produce the benchmark/experiment report, including diagnostics, limitations and all hashes.

Do not use the checked-in test fixture for model-quality claims. Do not use an LLM to assign gold
labels. Future embedding/reranker fine-tuning or hard-negative mining may consume the retained human
annotations only under a separate approved stage.
