# Stage 2.1 retrieval research boundary

Stage 2.1 is an offline, workspace-independent evaluation boundary for the single task:

```text
atomic Requirement -> ranked exact EvidenceSpan candidates
```

It is not a production global index and it does not query tenant data. A caller constructs an
explicit evaluation corpus from a versioned gold dataset and supplies that corpus to lexical, dense
and hybrid adapters. Gold relevance labels and hard-negative labels are kept outside candidates and
are visible only to metric calculation.

The dependency direction is:

```text
GoldDataset -> RetrievalProblem -> EvidenceRetriever adapter -> EvidenceReranker
            -> RetrievalExperimentRun -> Recall/MRR/nDCG + reproducibility metadata
```

`EvidenceSpanCandidate` preserves dataset-relative document identity, document version, locator,
source type, authority, temporal validity and optional source digest. Retrieval methods never become
domain entities and do not alter the production Requirement -> Evidence -> EvidenceSpan -> Decision
invariant.

The research trace contract stores only a lightweight state/action/outcome record for possible later
learning-from-feedback work. It does not implement rewards, policies, training, agents or an event
store.
