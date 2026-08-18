# Manual gold evaluation datasets

No synthetic product dataset is generated or committed. Gold cases are authored and reviewed by
humans, with source assets stored beside the versioned dataset according to the repository's data
governance policy.

Each case contains:

- one source requirement and its exact locator;
- one or more gold atomic requirements;
- gold ProductVersion/Capability mappings;
- exact gold EvidenceSpans with authority, source type, temporal validity and locator;
- a gold compliance outcome for every atomic requirement.

Create an empty dataset:

```text
python -m ctrl_v2.evaluation.authoring init evaluations/datasets/<name>/<version>/dataset.json \
  --dataset-id <name> --version <version> --description "Human curated dataset"
```

Review and author a case JSON against `schema/gold-dataset.schema.json` definitions, then append it:

```text
python -m ctrl_v2.evaluation.authoring add-case <dataset.json> <reviewed-case.json>
python -m ctrl_v2.evaluation.authoring validate <dataset.json>
```

The CLI never invents source text, requirements, mappings, evidence, or outcomes. `init` only
creates an empty metadata envelope, and `add-case` accepts a complete manually authored case.
