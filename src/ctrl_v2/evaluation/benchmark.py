from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .authoring import dataset_sha256
from .gold_dataset import (
    AnnotationReviewStatus,
    DatasetScope,
    GoldCase,
    GoldDataset,
    HardNegativeErrorTag,
    evidence_span_content_identity,
)


class BenchmarkValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Benchmark validation failed:\n- " + "\n- ".join(errors))


class BenchmarkModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class LeakageGroupField(StrEnum):
    SOURCE_COLLECTION = "SOURCE_COLLECTION"
    DOCUMENT_FAMILY = "DOCUMENT_FAMILY"
    PRODUCT_FAMILY = "PRODUCT_FAMILY"
    PRODUCT_VERSION_FAMILY = "PRODUCT_VERSION_FAMILY"
    SOURCE_CASE_FAMILY = "SOURCE_CASE_FAMILY"


class BenchmarkSplitLabel(StrEnum):
    TRAIN = "TRAIN"
    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"


class BenchmarkSplitConfig(BenchmarkModel):
    schema_version: Literal["1.0"] = "1.0"
    seed: int
    development_fraction: float = Field(gt=0, lt=1)
    train_fraction: float = Field(default=0, ge=0, lt=1)
    group_fields: tuple[LeakageGroupField, ...] = Field(min_length=1)
    strategy: Literal["CONNECTED_SOURCE_GROUP_HASH_V1"] = "CONNECTED_SOURCE_GROUP_HASH_V1"

    @model_validator(mode="after")
    def validate_fractions_and_groups(self) -> BenchmarkSplitConfig:
        if self.development_fraction + self.train_fraction >= 1:
            raise ValueError("development_fraction + train_fraction must leave a test split")
        if len(self.group_fields) != len(set(self.group_fields)):
            raise ValueError("split group_fields must be unique")
        return self


class BenchmarkSplitAssignment(BenchmarkModel):
    case_id: str = Field(min_length=1)
    split: BenchmarkSplitLabel
    source_group_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BenchmarkSplitManifest(BenchmarkModel):
    schema_version: Literal["1.0"] = "1.0"
    benchmark_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    train_dataset_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    configuration: BenchmarkSplitConfig
    assignments: tuple[BenchmarkSplitAssignment, ...] = Field(min_length=2)
    created_at: datetime
    code_git_commit: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_assignments(self) -> BenchmarkSplitManifest:
        case_ids = [item.case_id for item in self.assignments]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("split manifest case IDs must be unique")
        splits = {item.split for item in self.assignments}
        if BenchmarkSplitLabel.DEVELOPMENT not in splits or BenchmarkSplitLabel.TEST not in splits:
            raise ValueError("split manifest must contain non-empty DEVELOPMENT and TEST splits")
        has_train = BenchmarkSplitLabel.TRAIN in splits
        if has_train != (self.configuration.train_fraction > 0):
            raise ValueError("TRAIN membership must match the configured train_fraction")
        if has_train != (self.train_dataset_sha256 is not None):
            raise ValueError("TRAIN membership must match train_dataset_sha256")
        group_splits: dict[str, set[BenchmarkSplitLabel]] = {}
        for item in self.assignments:
            group_splits.setdefault(item.source_group_sha256, set()).add(item.split)
        leaked = sorted(
            group for group, memberships in group_splits.items() if len(memberships) > 1
        )
        if leaked:
            raise ValueError(f"source groups cannot cross split boundaries: {leaked}")
        return self

    def case_ids(self, split: BenchmarkSplitLabel) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.assignments if item.split == split)


class NumericDistribution(BenchmarkModel):
    count: int = Field(ge=0)
    minimum: float = Field(ge=0)
    mean: float = Field(ge=0)
    p50: float = Field(ge=0)
    p95: float = Field(ge=0)
    maximum: float = Field(ge=0)


class CoverageMeasure(BenchmarkModel):
    covered_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    ratio: float = Field(ge=0, le=1)


class BenchmarkDiagnostics(BenchmarkModel):
    schema_version: Literal["1.0"] = "1.0"
    benchmark_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=0)
    atomic_requirement_count: int = Field(ge=0)
    positive_evidence_count: int = Field(ge=0)
    hard_negative_count: int = Field(ge=0)
    positives_per_query: NumericDistribution
    hard_negatives_per_query: NumericDistribution
    requirement_length_characters: NumericDistribution
    evidence_length_characters: NumericDistribution
    language_distribution: dict[str, int]
    source_category_distribution: dict[str, int]
    source_type_distribution: dict[str, int]
    source_authority_distribution: dict[str, int]
    review_status_distribution: dict[str, int]
    error_tag_coverage: dict[str, int]
    product_version_coverage: CoverageMeasure
    bounded_temporal_validity_coverage: CoverageMeasure
    temporal_error_tag_coverage: CoverageMeasure
    reviewed_percentage: float = Field(ge=0, le=100)
    adjudicated_percentage: float = Field(ge=0, le=100)
    frozen_percentage: float = Field(ge=0, le=100)


class BenchmarkManifest(BenchmarkModel):
    schema_version: Literal["1.0"] = "1.0"
    benchmark_id: str
    dataset_schema_version: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    train_dataset_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    split_configuration: BenchmarkSplitConfig
    case_counts: dict[str, int]
    atomic_requirement_count: int = Field(ge=0)
    positive_evidence_count: int = Field(ge=0)
    hard_negative_count: int = Field(ge=0)
    languages: dict[str, int]
    source_categories: dict[str, int]
    product_version_coverage: CoverageMeasure
    error_tag_coverage: dict[str, int]
    review_status_counts: dict[str, int]
    reviewed_percentage: float = Field(ge=0, le=100)
    adjudicated_percentage: float = Field(ge=0, le=100)
    created_at: datetime
    code_git_commit: str = Field(min_length=1)


class AnnotationDisagreement(BenchmarkModel):
    case_id: str
    status: AnnotationReviewStatus
    primary_annotator: str
    reviewer_alias: str | None
    disagreement: str
    adjudicator_alias: str | None
    adjudication_note: str | None


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _distribution(values: list[int]) -> NumericDistribution:
    if not values:
        return NumericDistribution(count=0, minimum=0, mean=0, p50=0, p95=0, maximum=0)
    return NumericDistribution(
        count=len(values),
        minimum=min(values),
        mean=sum(values) / len(values),
        p50=_percentile(values, 0.5),
        p95=_percentile(values, 0.95),
        maximum=max(values),
    )


def canonical_model_payload(model: BaseModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_model_sha256(model: BaseModel) -> str:
    return hashlib.sha256(canonical_model_payload(model)).hexdigest()


def select_dataset_cases(dataset: GoldDataset, case_ids: tuple[str, ...]) -> GoldDataset:
    requested = set(case_ids)
    available = {case.case_id: case for case in dataset.cases}
    missing = sorted(requested - set(available))
    if missing:
        raise BenchmarkValidationError([f"split references unknown cases: {missing}"])
    selected = tuple(available[case_id] for case_id in sorted(requested))
    return dataset.model_copy(update={"cases": selected})


def _explicit_product_versions(case: GoldCase, atomic_key: str) -> set[str]:
    return {
        mapping.product_version_key
        for mapping in case.gold_mappings
        if mapping.atomic_requirement_key == atomic_key and mapping.product_version_key is not None
    }


def validate_benchmark_dataset(dataset: GoldDataset) -> None:
    errors: list[str] = []
    if dataset.scope != DatasetScope.EXTERNAL_RESTRICTED:
        errors.append("real benchmark dataset must declare EXTERNAL_RESTRICTED scope")
    if not dataset.cases:
        errors.append("benchmark dataset must contain at least one case")
    seen_keys: dict[str, str] = {}
    seen_content: dict[str, str] = {}
    for case in dataset.cases:
        prefix = f"case {case.case_id}"
        if case.benchmark is None:
            errors.append(f"{prefix}: benchmark metadata is required")
            continue
        review = case.benchmark.review
        if review.reviewer_alias == case.annotation.annotator:
            errors.append(f"{prefix}: independent reviewer must differ from primary annotator")
        atomic_keys = {item.key for item in case.gold_atomic_requirements}
        for atomic in case.gold_atomic_requirements:
            atomic_prefix = f"{prefix}, atomic {atomic.key}"
            if not atomic.atomic_text.strip():
                errors.append(f"{atomic_prefix}: atomic requirement cannot be blank")
            if atomic.language is None:
                errors.append(f"{atomic_prefix}: language is required")
            positives = [
                item
                for item in case.gold_evidence_spans
                if item.atomic_requirement_key == atomic.key
            ]
            hard_negatives = [
                item
                for item in case.hard_negative_evidence
                if item.atomic_requirement_key == atomic.key
            ]
            if not positives:
                errors.append(
                    f"{atomic_prefix}: at least one exact positive EvidenceSpan is required"
                )
            if not hard_negatives:
                errors.append(f"{atomic_prefix}: at least one explicit hard negative is required")
            mapped_versions = _explicit_product_versions(case, atomic.key)
            for positive in positives:
                if mapped_versions and positive.product_version_key not in mapped_versions:
                    errors.append(
                        f"{atomic_prefix}: positive EvidenceSpan {positive.key!r} has "
                        "ProductVersion "
                        "inconsistent with the explicit mapping"
                    )
            for outcome in case.gold_compliance_outcomes:
                if (
                    outcome.atomic_requirement_key == atomic.key
                    and mapped_versions
                    and outcome.product_version_key not in mapped_versions
                ):
                    errors.append(
                        f"{atomic_prefix}: compliance ProductVersion is inconsistent with mapping"
                    )
            for negative in hard_negatives:
                if not negative.error_tags:
                    errors.append(
                        f"{atomic_prefix}: hard negative {negative.key!r} requires human error tags"
                    )
        for span in (*case.gold_evidence_spans, *case.hard_negative_evidence):
            span_label = span.key or "<missing-key>"
            if span.atomic_requirement_key not in atomic_keys:
                errors.append(f"{prefix}: EvidenceSpan {span_label} references unknown atomic key")
            if span.key is None:
                errors.append(f"{prefix}: benchmark EvidenceSpan requires an explicit key")
            elif span.key in seen_keys:
                errors.append(
                    f"{prefix}: duplicate EvidenceSpan key {span.key!r}; first seen in "
                    f"{seen_keys[span.key]}"
                )
            else:
                seen_keys[span.key] = prefix
            if span.source_sha256 is None:
                errors.append(f"{prefix}: EvidenceSpan {span_label} requires source_sha256")
            content_identity = evidence_span_content_identity(span)
            if content_identity in seen_content:
                errors.append(
                    f"{prefix}: duplicate EvidenceSpan provenance/content identity; first seen in "
                    f"{seen_content[content_identity]}"
                )
            else:
                seen_content[content_identity] = prefix
    if errors:
        raise BenchmarkValidationError(errors)


def assert_external_dataset_storage_boundary(
    dataset_path: Path,
    dataset: GoldDataset,
    repository_root: Path,
) -> None:
    if dataset.scope != DatasetScope.EXTERNAL_RESTRICTED:
        return
    assert_untracked_research_path(dataset_path, repository_root, "external benchmark file")


def assert_untracked_research_path(
    path: Path,
    repository_root: Path,
    label: str = "research artifact",
) -> None:
    resolved_path = path.resolve()
    resolved_repository = repository_root.resolve()
    try:
        relative = resolved_path.relative_to(resolved_repository)
    except ValueError:
        return
    git_path = relative.as_posix()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", git_path],
        cwd=resolved_repository,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if tracked.returncode == 0:
        raise BenchmarkValidationError([f"{label} is tracked by Git: {git_path}"])
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", git_path],
        cwd=resolved_repository,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if ignored.returncode != 0:
        raise BenchmarkValidationError(
            [f"{label} inside repository must be ignored by Git: {git_path}"]
        )


def _group_value(case: GoldCase, field: LeakageGroupField) -> str:
    if case.benchmark is None:
        raise BenchmarkValidationError([f"case {case.case_id}: benchmark metadata is required"])
    grouping = case.benchmark.grouping
    values = {
        LeakageGroupField.SOURCE_COLLECTION: case.provenance.source_collection,
        LeakageGroupField.DOCUMENT_FAMILY: grouping.document_family,
        LeakageGroupField.PRODUCT_FAMILY: grouping.product_family,
        LeakageGroupField.PRODUCT_VERSION_FAMILY: grouping.product_version_family,
        LeakageGroupField.SOURCE_CASE_FAMILY: grouping.source_case_family,
    }
    value = values[field]
    if value is None or not value.strip():
        raise BenchmarkValidationError(
            [f"case {case.case_id}: split grouping field {field.value} is missing"]
        )
    return value.strip().casefold()


def _connected_source_groups(
    dataset: GoldDataset,
    config: BenchmarkSplitConfig,
) -> list[tuple[tuple[str, ...], str]]:
    cases = tuple(sorted(dataset.cases, key=lambda item: item.case_id))
    parent = list(range(len(cases)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owners: dict[tuple[LeakageGroupField, str], int] = {}
    tokens_by_case: list[tuple[str, ...]] = []
    for index, case in enumerate(cases):
        tokens = tuple(
            f"{field.value}:{_group_value(case, field)}" for field in config.group_fields
        )
        tokens_by_case.append(tokens)
        for field, token in zip(config.group_fields, tokens, strict=True):
            value = token.split(":", 1)[1]
            existing = owners.setdefault((field, value), index)
            union(index, existing)

    component_indexes: dict[int, list[int]] = {}
    for index in range(len(cases)):
        component_indexes.setdefault(find(index), []).append(index)
    groups: list[tuple[tuple[str, ...], str]] = []
    for indexes in component_indexes.values():
        case_ids = tuple(sorted(cases[index].case_id for index in indexes))
        safe_payload = "\n".join(
            sorted({token for index in indexes for token in tokens_by_case[index]})
        ).encode("utf-8")
        groups.append((case_ids, hashlib.sha256(safe_payload).hexdigest()))
    return groups


def _split_group_counts(group_count: int, config: BenchmarkSplitConfig) -> tuple[int, int]:
    minimum = 3 if config.train_fraction > 0 else 2
    if group_count < minimum:
        raise BenchmarkValidationError(
            [
                f"grouped split requires at least {minimum} independent source groups; "
                f"found {group_count}"
            ]
        )
    train_count = 0
    if config.train_fraction > 0:
        train_count = max(1, round(group_count * config.train_fraction))
        train_count = min(train_count, group_count - 2)
    development_count = max(1, round(group_count * config.development_fraction))
    development_count = min(development_count, group_count - train_count - 1)
    return train_count, development_count


def generate_split_manifest(
    dataset: GoldDataset,
    configuration: BenchmarkSplitConfig,
    *,
    code_git_commit: str,
) -> BenchmarkSplitManifest:
    validate_benchmark_dataset(dataset)
    unreviewed = [
        case.case_id
        for case in dataset.cases
        if case.benchmark is not None
        and case.benchmark.review.status == AnnotationReviewStatus.DRAFT
    ]
    if unreviewed:
        raise BenchmarkValidationError(
            [f"cases cannot enter a split before independent review: {sorted(unreviewed)}"]
        )
    groups = _connected_source_groups(dataset, configuration)
    groups.sort(
        key=lambda item: hashlib.sha256(
            f"{configuration.seed}:{item[1]}".encode()
        ).hexdigest()
    )
    train_count, development_count = _split_group_counts(len(groups), configuration)
    assignments: list[BenchmarkSplitAssignment] = []
    for index, (case_ids, group_sha256) in enumerate(groups):
        if index < train_count:
            split = BenchmarkSplitLabel.TRAIN
        elif index < train_count + development_count:
            split = BenchmarkSplitLabel.DEVELOPMENT
        else:
            split = BenchmarkSplitLabel.TEST
        assignments.extend(
            BenchmarkSplitAssignment(
                case_id=case_id,
                split=split,
                source_group_sha256=group_sha256,
            )
            for case_id in case_ids
        )
    ordered = tuple(sorted(assignments, key=lambda item: item.case_id))
    by_split = {
        split: tuple(item.case_id for item in ordered if item.split == split)
        for split in BenchmarkSplitLabel
    }
    development_hash = dataset_sha256(
        select_dataset_cases(dataset, by_split[BenchmarkSplitLabel.DEVELOPMENT])
    )
    test_hash = dataset_sha256(select_dataset_cases(dataset, by_split[BenchmarkSplitLabel.TEST]))
    train_hash = None
    if by_split[BenchmarkSplitLabel.TRAIN]:
        train_hash = dataset_sha256(
            select_dataset_cases(dataset, by_split[BenchmarkSplitLabel.TRAIN])
        )
    return BenchmarkSplitManifest(
        benchmark_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_sha256=dataset_sha256(dataset),
        development_dataset_sha256=development_hash,
        test_dataset_sha256=test_hash,
        train_dataset_sha256=train_hash,
        configuration=configuration,
        assignments=ordered,
        created_at=dataset.created_at,
        code_git_commit=code_git_commit,
    )


def validate_split_manifest(dataset: GoldDataset, manifest: BenchmarkSplitManifest) -> None:
    expected = generate_split_manifest(
        dataset,
        manifest.configuration,
        code_git_commit=manifest.code_git_commit,
    )
    if manifest != expected:
        raise BenchmarkValidationError(
            ["split manifest does not match the deterministic grouped split for this dataset"]
        )


def build_diagnostics(dataset: GoldDataset) -> BenchmarkDiagnostics:
    atomic_requirements = [
        atomic for case in dataset.cases for atomic in case.gold_atomic_requirements
    ]
    evidence = [
        span
        for case in dataset.cases
        for span in (*case.gold_evidence_spans, *case.hard_negative_evidence)
    ]
    positives_by_query: list[int] = []
    negatives_by_query: list[int] = []
    product_version_covered = 0
    for case in dataset.cases:
        for atomic in case.gold_atomic_requirements:
            positives_by_query.append(
                sum(
                    span.atomic_requirement_key == atomic.key
                    for span in case.gold_evidence_spans
                )
            )
            negatives_by_query.append(
                sum(
                    span.atomic_requirement_key == atomic.key
                    for span in case.hard_negative_evidence
                )
            )
            if _explicit_product_versions(case, atomic.key):
                product_version_covered += 1
    languages = Counter(
        atomic.language.value if atomic.language is not None else "UNSPECIFIED"
        for atomic in atomic_requirements
    )
    source_categories = Counter(
        case.benchmark.source_category.value if case.benchmark is not None else "UNSPECIFIED"
        for case in dataset.cases
    )
    review_statuses = Counter(
        case.benchmark.review.status.value if case.benchmark is not None else "UNSPECIFIED"
        for case in dataset.cases
    )
    source_types = Counter(span.source_type.value for span in evidence)
    authorities = Counter(span.authority_level.value for span in evidence)
    error_tags = Counter(
        tag.value
        for case in dataset.cases
        for span in case.hard_negative_evidence
        for tag in span.error_tags
    )
    reviewed = sum(
        case.benchmark is not None
        and case.benchmark.review.status != AnnotationReviewStatus.DRAFT
        for case in dataset.cases
    )
    adjudicated = sum(
        case.benchmark is not None
        and case.benchmark.review.adjudicator_alias is not None
        for case in dataset.cases
    )
    frozen = sum(
        case.benchmark is not None
        and case.benchmark.review.status == AnnotationReviewStatus.FROZEN
        for case in dataset.cases
    )
    bounded = sum(span.valid_to is not None for span in evidence)
    hard_negative_count = sum(len(case.hard_negative_evidence) for case in dataset.cases)
    temporal_tagged = sum(
        HardNegativeErrorTag.TEMPORAL_VALIDITY in span.error_tags
        for case in dataset.cases
        for span in case.hard_negative_evidence
    )
    case_count = len(dataset.cases)
    atomic_count = len(atomic_requirements)
    return BenchmarkDiagnostics(
        benchmark_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_sha256=dataset_sha256(dataset),
        case_count=case_count,
        atomic_requirement_count=atomic_count,
        positive_evidence_count=sum(len(case.gold_evidence_spans) for case in dataset.cases),
        hard_negative_count=hard_negative_count,
        positives_per_query=_distribution(positives_by_query),
        hard_negatives_per_query=_distribution(negatives_by_query),
        requirement_length_characters=_distribution(
            [len(atomic.atomic_text) for atomic in atomic_requirements]
        ),
        evidence_length_characters=_distribution([len(span.exact_quote) for span in evidence]),
        language_distribution=dict(sorted(languages.items())),
        source_category_distribution=dict(sorted(source_categories.items())),
        source_type_distribution=dict(sorted(source_types.items())),
        source_authority_distribution=dict(sorted(authorities.items())),
        review_status_distribution=dict(sorted(review_statuses.items())),
        error_tag_coverage=dict(sorted(error_tags.items())),
        product_version_coverage=CoverageMeasure(
            covered_count=product_version_covered,
            total_count=atomic_count,
            ratio=_ratio(product_version_covered, atomic_count),
        ),
        bounded_temporal_validity_coverage=CoverageMeasure(
            covered_count=bounded,
            total_count=len(evidence),
            ratio=_ratio(bounded, len(evidence)),
        ),
        temporal_error_tag_coverage=CoverageMeasure(
            covered_count=temporal_tagged,
            total_count=hard_negative_count,
            ratio=_ratio(temporal_tagged, hard_negative_count),
        ),
        reviewed_percentage=100 * _ratio(reviewed, case_count),
        adjudicated_percentage=100 * _ratio(adjudicated, case_count),
        frozen_percentage=100 * _ratio(frozen, case_count),
    )


def build_benchmark_manifest(
    dataset: GoldDataset,
    split_manifest: BenchmarkSplitManifest,
    *,
    code_git_commit: str,
) -> BenchmarkManifest:
    validate_split_manifest(dataset, split_manifest)
    diagnostics = build_diagnostics(dataset)
    case_counts = Counter(item.split.value for item in split_manifest.assignments)
    return BenchmarkManifest(
        benchmark_id=dataset.dataset_id,
        dataset_schema_version=dataset.schema_version,
        dataset_version=dataset.version,
        dataset_sha256=dataset_sha256(dataset),
        development_dataset_sha256=split_manifest.development_dataset_sha256,
        test_dataset_sha256=split_manifest.test_dataset_sha256,
        train_dataset_sha256=split_manifest.train_dataset_sha256,
        split_configuration=split_manifest.configuration,
        case_counts=dict(sorted(case_counts.items())),
        atomic_requirement_count=diagnostics.atomic_requirement_count,
        positive_evidence_count=diagnostics.positive_evidence_count,
        hard_negative_count=diagnostics.hard_negative_count,
        languages=diagnostics.language_distribution,
        source_categories=diagnostics.source_category_distribution,
        product_version_coverage=diagnostics.product_version_coverage,
        error_tag_coverage=diagnostics.error_tag_coverage,
        review_status_counts=diagnostics.review_status_distribution,
        reviewed_percentage=diagnostics.reviewed_percentage,
        adjudicated_percentage=diagnostics.adjudicated_percentage,
        created_at=dataset.created_at,
        code_git_commit=code_git_commit,
    )


def inspect_disagreements(dataset: GoldDataset) -> tuple[AnnotationDisagreement, ...]:
    disagreements: list[AnnotationDisagreement] = []
    for case in dataset.cases:
        if case.benchmark is None or not case.benchmark.review.disagreement:
            continue
        review = case.benchmark.review
        disagreements.append(
            AnnotationDisagreement(
                case_id=case.case_id,
                status=review.status,
                primary_annotator=case.annotation.annotator,
                reviewer_alias=review.reviewer_alias,
                disagreement=review.disagreement,
                adjudicator_alias=review.adjudicator_alias,
                adjudication_note=review.adjudication_note,
            )
        )
    return tuple(sorted(disagreements, key=lambda item: item.case_id))
