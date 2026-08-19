# Stage 2.2 semantic retrieval experiment

This is an offline experiment boundary, not production RAG. It does not access CTRL tenant tables,
create a vector index, generate compliance decisions or change the production provenance chain.

## Models and preprocessing

The E5 adapter verifies the configured revision, `model.safetensors` SHA-256 and `config.json`
SHA-256 before loading. Requirements are encoded as:

```text
Instruct: Given an RFI, RFP, or technical requirement, retrieve exact product evidence passages that prove or disprove the requirement
Query: {atomic requirement}
```

EvidenceSpan text is stripped but receives no instruction or prefix. Embeddings are 1024-dimensional,
L2-normalized by SentenceTransformers and compared with cosine similarity.

The BGE cross-encoder receives `(atomic requirement, EvidenceSpan text)` pairs from hybrid top-N.
Raw single-label logits are converted with sigmoid and deterministically sorted by score and
EvidenceSpan ID. Exact candidate provenance is carried through unchanged.

Models are lazy-loaded and fail with a typed research error when packages, artifacts, hashes,
dimensions or finite scores are invalid. There is no feature-hashing fallback.

## Memory lifecycle

On constrained CPU hosts, hybrid top-N rankings are materialized first. The E5 model is then closed
before the cross-encoder is loaded. Retrieval latency from materialization is retained in the
cross-encoder run. This avoids requiring both large transformer models in memory simultaneously.

No embedding cache or vector store is implemented. Candidate embeddings exist only in the offline
process and are scoped to the explicitly supplied dataset.

## Reproducibility and leakage

The repository pins research package versions. The checked configuration records model identities,
artifact hashes, query/document preprocessing, dimensions, normalization, candidate N, final K,
RRF weights, seed and split policy.
When RRF parameters are development-tuned, the development dataset hash is mandatory and must differ
from the test dataset hash. Test labels and hard negatives are evaluation-only.

Error slices based on version, obsolete, roadmap, temporal, authority, conflict and non-entailment
are emitted only when a human annotator supplies the corresponding hard-negative tag. Lexical-miss
and semantic-miss slices are derived only from observed method rankings.

## Observed local CPU smoke

Measured on Windows 11, Intel Core i5-12500H, 16 logical CPUs, 15.7 GiB RAM, no discrete GPU:

- E5 standalone: 4.18 s load, 1.03 s for one query plus two documents, 2.61 GiB process RSS;
- BGE reranker standalone: 2.42 s load, 0.79 s for two query/document pairs, 2.55 GiB process RSS.

These are smoke measurements, not throughput benchmarks or retrieval-quality results. GPU
performance was not measured.
