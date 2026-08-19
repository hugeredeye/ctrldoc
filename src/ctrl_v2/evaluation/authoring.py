from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from .gold_dataset import (
    DatasetScope,
    GoldCase,
    GoldDataset,
    assert_checked_in_fixture,
)


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


def dataset_sha256(dataset: GoldDataset) -> str:
    return hashlib.sha256(_canonical_payload(dataset)).hexdigest()


def load_dataset(path: Path, *, checked_in: bool = False) -> GoldDataset:
    source = path.read_text(encoding="utf-8")
    dataset = GoldDataset.model_validate_json(source)
    if checked_in:
        assert_checked_in_fixture(dataset)
    return dataset


def initialize_dataset(
    path: Path,
    dataset_id: str,
    version: str,
    description: str,
    *,
    scope: DatasetScope = DatasetScope.EXTERNAL_RESTRICTED,
    contains_customer_data: bool = False,
) -> str:
    dataset = GoldDataset(
        dataset_id=dataset_id,
        version=version,
        description=description,
        created_at=datetime.now(UTC),
        scope=scope,
        contains_customer_data=contains_customer_data,
        cases=(),
    )
    payload = _canonical_payload(dataset)
    _write_new(path, payload)
    return hashlib.sha256(payload).hexdigest()


def add_manual_case(dataset_path: Path, case_path: Path) -> str:
    dataset = load_dataset(dataset_path)
    case = GoldCase.model_validate_json(case_path.read_text(encoding="utf-8"))
    if any(existing.case_id == case.case_id for existing in dataset.cases):
        raise ValueError(f"case_id already exists: {case.case_id}")
    updated = GoldDataset.model_validate_json(
        dataset.model_copy(update={"cases": (*dataset.cases, case)}).model_dump_json()
    )
    payload = _canonical_payload(updated)
    _replace(dataset_path, payload)
    return hashlib.sha256(payload).hexdigest()


def validate_dataset(path: Path) -> tuple[int, str]:
    dataset = load_dataset(path)
    payload = _canonical_payload(dataset)
    return len(dataset.cases), hashlib.sha256(payload).hexdigest()


def validate_case(path: Path) -> tuple[str, str]:
    case = GoldCase.model_validate_json(path.read_text(encoding="utf-8"))
    payload = (
        json.dumps(case.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    return case.case_id, hashlib.sha256(payload).hexdigest()


def export_schema(path: Path) -> None:
    payload = json.dumps(
        GoldDataset.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + b"\n")


def _write_model_new(path: Path, model: BaseModel) -> str:
    from .benchmark import canonical_model_payload

    payload = canonical_model_payload(model)
    _write_new(path, payload)
    return hashlib.sha256(payload).hexdigest()


def _load_model(path: Path, model_type: type[BaseModel]) -> BaseModel:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual CTRL v2 gold-dataset authoring")
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init", help="Create an empty versioned dataset")
    initialize.add_argument("path", type=Path)
    initialize.add_argument("--dataset-id", required=True)
    initialize.add_argument("--version", required=True)
    initialize.add_argument("--description", required=True)
    initialize.add_argument(
        "--scope",
        choices=[scope.value for scope in DatasetScope],
        default=DatasetScope.EXTERNAL_RESTRICTED.value,
    )
    initialize.add_argument("--contains-customer-data", action="store_true")

    add_case = subparsers.add_parser("add-case", help="Append a manually authored case JSON")
    add_case.add_argument("dataset", type=Path)
    add_case.add_argument("case", type=Path)

    validate = subparsers.add_parser("validate", help="Validate and hash a dataset")
    validate.add_argument("path", type=Path)

    validate_single_case = subparsers.add_parser(
        "validate-case", help="Validate and hash one manually authored case"
    )
    validate_single_case.add_argument("path", type=Path)

    schema = subparsers.add_parser("export-schema", help="Export the JSON Schema")
    schema.add_argument("path", type=Path)

    benchmark_validate = subparsers.add_parser(
        "validate-benchmark",
        help="Validate an external benchmark and its uncommitted storage boundary",
    )
    benchmark_validate.add_argument("path", type=Path)
    benchmark_validate.add_argument("--repository", type=Path, default=Path.cwd())

    diagnostics = subparsers.add_parser(
        "diagnostics", help="Produce content-free benchmark diagnostics"
    )
    diagnostics.add_argument("dataset", type=Path)
    diagnostics.add_argument("--output", type=Path)

    split = subparsers.add_parser(
        "split", help="Create a deterministic grouped DEV/TEST split manifest"
    )
    split.add_argument("dataset", type=Path)
    split.add_argument("configuration", type=Path)
    split.add_argument("output", type=Path)
    split.add_argument("--repository", type=Path, default=Path.cwd())

    manifest = subparsers.add_parser(
        "manifest", help="Create a content-free CTRL Gold Benchmark manifest"
    )
    manifest.add_argument("dataset", type=Path)
    manifest.add_argument("split_manifest", type=Path)
    manifest.add_argument("output", type=Path)
    manifest.add_argument("--repository", type=Path, default=Path.cwd())

    freeze = subparsers.add_parser(
        "freeze-test-config", help="Freeze and hash a semantic TEST configuration"
    )
    freeze.add_argument("dataset", type=Path)
    freeze.add_argument("split_manifest", type=Path)
    freeze.add_argument("semantic_configuration", type=Path)
    freeze.add_argument("output", type=Path)
    freeze.add_argument("--frozen-by", required=True)
    freeze.add_argument("--repository", type=Path, default=Path.cwd())

    verify_freeze = subparsers.add_parser(
        "verify-frozen-test", help="Detect changes after TEST configuration freeze"
    )
    verify_freeze.add_argument("dataset", type=Path)
    verify_freeze.add_argument("split_manifest", type=Path)
    verify_freeze.add_argument("semantic_configuration", type=Path)
    verify_freeze.add_argument("frozen_record", type=Path)

    disagreements = subparsers.add_parser(
        "inspect-disagreements", help="List recorded review disagreements and adjudication"
    )
    disagreements.add_argument("dataset", type=Path)

    blind_test = subparsers.add_parser(
        "blind-test", help="Run a primary test experiment behind the frozen boundary"
    )
    blind_test.add_argument("dataset", type=Path)
    blind_test.add_argument("split_manifest", type=Path)
    blind_test.add_argument("semantic_configuration", type=Path)
    blind_test.add_argument("frozen_record", type=Path)
    blind_test.add_argument("output", type=Path)
    blind_test.add_argument("--repository", type=Path, default=Path.cwd())

    arguments = parser.parse_args()
    if arguments.command == "init":
        digest = initialize_dataset(
            arguments.path,
            arguments.dataset_id,
            arguments.version,
            arguments.description,
            scope=DatasetScope(arguments.scope),
            contains_customer_data=arguments.contains_customer_data,
        )
        print(f"initialized cases=0 sha256={digest}")
    elif arguments.command == "add-case":
        digest = add_manual_case(arguments.dataset, arguments.case)
        print(f"case-added sha256={digest}")
    elif arguments.command == "validate":
        count, digest = validate_dataset(arguments.path)
        print(f"valid cases={count} sha256={digest}")
    elif arguments.command == "validate-case":
        case_id, digest = validate_case(arguments.path)
        print(f"case-valid case_id={case_id} sha256={digest}")
    elif arguments.command == "export-schema":
        export_schema(arguments.path)
        print(f"schema-written path={arguments.path}")
    elif arguments.command == "validate-benchmark":
        from .benchmark import (
            assert_external_dataset_storage_boundary,
            validate_benchmark_dataset,
        )

        dataset = load_dataset(arguments.path)
        validate_benchmark_dataset(dataset)
        assert_external_dataset_storage_boundary(
            arguments.path,
            dataset,
            arguments.repository,
        )
        print(
            f"benchmark-valid cases={len(dataset.cases)} sha256={dataset_sha256(dataset)}"
        )
    elif arguments.command == "diagnostics":
        from .benchmark import build_diagnostics, canonical_model_payload

        report = build_diagnostics(load_dataset(arguments.dataset))
        payload = canonical_model_payload(report)
        if arguments.output is None:
            print(payload.decode("utf-8"), end="")
        else:
            _write_new(arguments.output, payload)
            print(f"diagnostics-written path={arguments.output}")
    elif arguments.command == "split":
        from .benchmark import BenchmarkSplitConfig, generate_split_manifest
        from .experiment import resolve_git_commit

        configuration = _load_model(arguments.configuration, BenchmarkSplitConfig)
        split_manifest = generate_split_manifest(
            load_dataset(arguments.dataset),
            configuration,
            code_git_commit=resolve_git_commit(arguments.repository),
        )
        digest = _write_model_new(arguments.output, split_manifest)
        print(f"split-written sha256={digest} path={arguments.output}")
    elif arguments.command == "manifest":
        from .benchmark import BenchmarkSplitManifest, build_benchmark_manifest
        from .experiment import resolve_git_commit

        dataset = load_dataset(arguments.dataset)
        split_manifest = _load_model(arguments.split_manifest, BenchmarkSplitManifest)
        benchmark_manifest = build_benchmark_manifest(
            dataset,
            split_manifest,
            code_git_commit=resolve_git_commit(arguments.repository),
        )
        digest = _write_model_new(arguments.output, benchmark_manifest)
        print(f"manifest-written sha256={digest} path={arguments.output}")
    elif arguments.command == "freeze-test-config":
        from .benchmark import BenchmarkSplitManifest
        from .blind_evaluation import freeze_test_configuration
        from .experiment import resolve_git_commit
        from .semantic_config import load_semantic_config

        frozen = freeze_test_configuration(
            load_dataset(arguments.dataset),
            _load_model(arguments.split_manifest, BenchmarkSplitManifest),
            load_semantic_config(arguments.semantic_configuration),
            frozen_at=datetime.now(UTC),
            frozen_by=arguments.frozen_by,
            code_git_commit=resolve_git_commit(arguments.repository),
        )
        digest = _write_model_new(arguments.output, frozen)
        print(f"test-configuration-frozen sha256={digest} path={arguments.output}")
    elif arguments.command == "verify-frozen-test":
        from .benchmark import BenchmarkSplitManifest
        from .blind_evaluation import FrozenTestConfiguration, verify_frozen_test_configuration
        from .semantic_config import load_semantic_config

        verify_frozen_test_configuration(
            load_dataset(arguments.dataset),
            _load_model(arguments.split_manifest, BenchmarkSplitManifest),
            load_semantic_config(arguments.semantic_configuration),
            _load_model(arguments.frozen_record, FrozenTestConfiguration),
        )
        print("frozen-test-configuration-valid")
    elif arguments.command == "inspect-disagreements":
        from .benchmark import inspect_disagreements

        items = inspect_disagreements(load_dataset(arguments.dataset))
        payload = [item.model_dump(mode="json") for item in items]
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        from .benchmark import BenchmarkSplitManifest
        from .blind_evaluation import (
            FrozenTestConfiguration,
            create_blind_test_artifact,
            write_blind_test_artifact,
        )
        from .experiment import resolve_git_commit
        from .semantic_config import load_semantic_config

        code_git_commit = resolve_git_commit(arguments.repository)
        artifact = create_blind_test_artifact(
            load_dataset(arguments.dataset),
            _load_model(arguments.split_manifest, BenchmarkSplitManifest),
            load_semantic_config(arguments.semantic_configuration),
            _load_model(arguments.frozen_record, FrozenTestConfiguration),
            created_at=datetime.now(UTC),
            code_git_commit=code_git_commit,
        )
        digest = write_blind_test_artifact(
            arguments.output,
            artifact,
            repository_root=arguments.repository,
        )
        print(f"blind-test-written sha256={digest} path={arguments.output}")


if __name__ == "__main__":
    main()
