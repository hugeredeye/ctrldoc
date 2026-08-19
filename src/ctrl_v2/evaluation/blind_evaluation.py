from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from .benchmark import (
    BenchmarkModel,
    BenchmarkSplitLabel,
    BenchmarkSplitManifest,
    BenchmarkValidationError,
    assert_untracked_research_path,
    canonical_model_payload,
    canonical_model_sha256,
    select_dataset_cases,
    validate_split_manifest,
)
from .gold_dataset import AnnotationReviewStatus, GoldDataset
from .semantic_config import (
    DatasetSplit,
    RRFWeightSource,
    SemanticExperimentConfig,
)
from .semantic_experiment import SemanticExperimentResult, run_semantic_matrix


class FrozenTestConfiguration(BenchmarkModel):
    schema_version: Literal["1.0"] = "1.0"
    benchmark_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    development_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at: datetime
    frozen_by: str = Field(min_length=1)
    code_git_commit: str = Field(min_length=1)


class BlindTestResultArtifact(BenchmarkModel):
    schema_version: Literal["1.0"] = "1.0"
    purpose: Literal["PRIMARY_BLIND_TEST"] = "PRIMARY_BLIND_TEST"
    benchmark_id: str
    dataset_version: str
    test_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_configuration_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    code_git_commit: str
    experiment: SemanticExperimentResult


def _assert_test_cases_frozen(
    dataset: GoldDataset,
    split_manifest: BenchmarkSplitManifest,
) -> None:
    by_id = {case.case_id: case for case in dataset.cases}
    not_frozen = [
        case_id
        for case_id in split_manifest.case_ids(BenchmarkSplitLabel.TEST)
        if by_id[case_id].benchmark is None
        or by_id[case_id].benchmark.review.status != AnnotationReviewStatus.FROZEN
    ]
    if not_frozen:
        raise BenchmarkValidationError(
            [f"blind TEST cases must be FROZEN after review: {sorted(not_frozen)}"]
        )


def _assert_semantic_test_configuration(
    configuration: SemanticExperimentConfig,
    split_manifest: BenchmarkSplitManifest,
) -> None:
    leakage = configuration.leakage
    errors: list[str] = []
    if leakage.dataset_split != DatasetSplit.TEST:
        errors.append("blind test requires semantic configuration dataset_split=TEST")
    if not leakage.configuration_frozen_before_test:
        errors.append("blind test requires configuration_frozen_before_test=true")
    development_hash = leakage.development_dataset_sha256
    if leakage.rrf_weight_source == RRFWeightSource.DEVELOPMENT_TUNED:
        if development_hash != split_manifest.development_dataset_sha256:
            errors.append("development-tuned configuration must reference this benchmark dev hash")
    elif (
        development_hash is not None
        and development_hash != split_manifest.development_dataset_sha256
    ):
        errors.append("recorded development dataset hash does not match the split manifest")
    if errors:
        raise BenchmarkValidationError(errors)


def freeze_test_configuration(
    dataset: GoldDataset,
    split_manifest: BenchmarkSplitManifest,
    semantic_configuration: SemanticExperimentConfig,
    *,
    frozen_at: datetime,
    frozen_by: str,
    code_git_commit: str,
) -> FrozenTestConfiguration:
    validate_split_manifest(dataset, split_manifest)
    _assert_test_cases_frozen(dataset, split_manifest)
    _assert_semantic_test_configuration(semantic_configuration, split_manifest)
    if not frozen_by.strip():
        raise BenchmarkValidationError(["frozen_by cannot be blank"])
    return FrozenTestConfiguration(
        benchmark_id=dataset.dataset_id,
        dataset_version=dataset.version,
        development_dataset_sha256=split_manifest.development_dataset_sha256,
        test_dataset_sha256=split_manifest.test_dataset_sha256,
        split_manifest_sha256=canonical_model_sha256(split_manifest),
        semantic_configuration_sha256=canonical_model_sha256(semantic_configuration),
        frozen_at=frozen_at,
        frozen_by=frozen_by,
        code_git_commit=code_git_commit,
    )


def verify_frozen_test_configuration(
    dataset: GoldDataset,
    split_manifest: BenchmarkSplitManifest,
    semantic_configuration: SemanticExperimentConfig,
    frozen: FrozenTestConfiguration,
) -> None:
    validate_split_manifest(dataset, split_manifest)
    _assert_test_cases_frozen(dataset, split_manifest)
    _assert_semantic_test_configuration(semantic_configuration, split_manifest)
    expected = {
        "benchmark_id": dataset.dataset_id,
        "dataset_version": dataset.version,
        "development_dataset_sha256": split_manifest.development_dataset_sha256,
        "test_dataset_sha256": split_manifest.test_dataset_sha256,
        "split_manifest_sha256": canonical_model_sha256(split_manifest),
        "semantic_configuration_sha256": canonical_model_sha256(semantic_configuration),
    }
    actual = frozen.model_dump(mode="python")
    changed = [key for key, value in expected.items() if actual[key] != value]
    if changed:
        raise BenchmarkValidationError(
            [f"frozen test boundary mismatch or post-freeze mutation: {sorted(changed)}"]
        )


def create_blind_test_artifact(
    dataset: GoldDataset,
    split_manifest: BenchmarkSplitManifest,
    semantic_configuration: SemanticExperimentConfig,
    frozen: FrozenTestConfiguration,
    *,
    created_at: datetime,
    code_git_commit: str,
    evaluator: Callable[[GoldDataset, SemanticExperimentConfig, str], SemanticExperimentResult]
    | None = None,
) -> BlindTestResultArtifact:
    verify_frozen_test_configuration(
        dataset,
        split_manifest,
        semantic_configuration,
        frozen,
    )
    if code_git_commit != frozen.code_git_commit:
        raise BenchmarkValidationError(
            ["blind test code commit differs from the frozen configuration record"]
        )
    test_dataset = select_dataset_cases(
        dataset,
        split_manifest.case_ids(BenchmarkSplitLabel.TEST),
    )
    if evaluator is None:
        experiment = run_semantic_matrix(
            test_dataset,
            semantic_configuration,
            code_version=code_git_commit,
        )
    else:
        experiment = evaluator(test_dataset, semantic_configuration, code_git_commit)
    if experiment.suite.dataset_sha256 != split_manifest.test_dataset_sha256:
        raise BenchmarkValidationError(
            ["blind experiment result does not match the frozen test dataset hash"]
        )
    return BlindTestResultArtifact(
        benchmark_id=dataset.dataset_id,
        dataset_version=dataset.version,
        test_dataset_sha256=split_manifest.test_dataset_sha256,
        split_manifest_sha256=canonical_model_sha256(split_manifest),
        frozen_configuration_record_sha256=canonical_model_sha256(frozen),
        semantic_configuration_sha256=canonical_model_sha256(semantic_configuration),
        created_at=created_at,
        code_git_commit=code_git_commit,
        experiment=experiment,
    )


def write_blind_test_artifact(
    path: Path,
    artifact: BlindTestResultArtifact,
    *,
    repository_root: Path,
) -> str:
    assert_untracked_research_path(path, repository_root, "blind test result")
    payload = canonical_model_payload(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
    return hashlib.sha256(payload).hexdigest()
