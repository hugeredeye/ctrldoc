from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .gold_dataset import GoldCase, GoldDataset


def _canonical_payload(model: GoldDataset) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)


def _replace(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def initialize_dataset(path: Path, dataset_id: str, version: str, description: str) -> str:
    dataset = GoldDataset(
        dataset_id=dataset_id,
        version=version,
        description=description,
        created_at=datetime.now(UTC),
        cases=(),
    )
    payload = _canonical_payload(dataset)
    _write_new(path, payload)
    return hashlib.sha256(payload).hexdigest()


def add_manual_case(dataset_path: Path, case_path: Path) -> str:
    dataset = GoldDataset.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    case = GoldCase.model_validate_json(case_path.read_text(encoding="utf-8"))
    if any(existing.case_id == case.case_id for existing in dataset.cases):
        raise ValueError(f"case_id already exists: {case.case_id}")
    updated = dataset.model_copy(update={"cases": (*dataset.cases, case)})
    payload = _canonical_payload(updated)
    _replace(dataset_path, payload)
    return hashlib.sha256(payload).hexdigest()


def validate_dataset(path: Path) -> tuple[int, str]:
    dataset = GoldDataset.model_validate_json(path.read_text(encoding="utf-8"))
    payload = _canonical_payload(dataset)
    return len(dataset.cases), hashlib.sha256(payload).hexdigest()


def export_schema(path: Path) -> None:
    payload = json.dumps(
        GoldDataset.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + b"\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual CTRL v2 gold-dataset authoring")
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init", help="Create an empty versioned dataset")
    initialize.add_argument("path", type=Path)
    initialize.add_argument("--dataset-id", required=True)
    initialize.add_argument("--version", required=True)
    initialize.add_argument("--description", required=True)

    add_case = subparsers.add_parser("add-case", help="Append a manually authored case JSON")
    add_case.add_argument("dataset", type=Path)
    add_case.add_argument("case", type=Path)

    validate = subparsers.add_parser("validate", help="Validate and hash a dataset")
    validate.add_argument("path", type=Path)

    schema = subparsers.add_parser("export-schema", help="Export the JSON Schema")
    schema.add_argument("path", type=Path)

    arguments = parser.parse_args()
    if arguments.command == "init":
        digest = initialize_dataset(
            arguments.path,
            arguments.dataset_id,
            arguments.version,
            arguments.description,
        )
        print(f"initialized cases=0 sha256={digest}")
    elif arguments.command == "add-case":
        digest = add_manual_case(arguments.dataset, arguments.case)
        print(f"case-added sha256={digest}")
    elif arguments.command == "validate":
        count, digest = validate_dataset(arguments.path)
        print(f"valid cases={count} sha256={digest}")
    else:
        export_schema(arguments.path)
        print(f"schema-written path={arguments.path}")


if __name__ == "__main__":
    main()
