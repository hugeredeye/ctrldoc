from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

import pytest
from pydantic import ValidationError

from ctrl_v2.evaluation.authoring import load_dataset
from ctrl_v2.evaluation.authoring import main as authoring_main
from ctrl_v2.evaluation.benchmark import (
    BenchmarkSplitConfig,
    BenchmarkSplitLabel,
    BenchmarkSplitManifest,
    BenchmarkValidationError,
    LeakageGroupField,
    assert_external_dataset_storage_boundary,
    build_benchmark_manifest,
    build_diagnostics,
    generate_split_manifest,
    inspect_disagreements,
    validate_benchmark_dataset,
    validate_split_manifest,
)
from ctrl_v2.evaluation.blind_evaluation import (
    create_blind_test_artifact,
    freeze_test_configuration,
    verify_frozen_test_configuration,
    write_blind_test_artifact,
)
from ctrl_v2.evaluation.gold_dataset import (
    AnnotationReviewStatus,
    BenchmarkSourceCategory,
    DatasetScope,
    GoldBenchmarkCaseMetadata,
    GoldBenchmarkGrouping,
    GoldCase,
    GoldDataset,
    GoldIndependentReview,
    RequirementLanguage,
)
from ctrl_v2.evaluation.semantic_config import RRFWeightSource, load_semantic_config
from ctrl_v2.evaluation.semantic_experiment import run_semantic_matrix

FIXTURE = Path("evaluations/fixtures/stage2-retrieval-v1.json")
SEMANTIC_CONFIG = Path("evaluations/config/semantic-retrieval-v1.json")
NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _benchmark_case(source: GoldCase, index: int) -> GoldCase:
    atomic_source = source.gold_atomic_requirements[0]
    atomic_key = f"REQ-{index}"
    product_version = f"product-{index}"
    atomic = atomic_source.model_copy(
        update={
            "key": atomic_key,
            "language": RequirementLanguage.EN,
        }
    )
    mappings = tuple(
        mapping.model_copy(
            update={
                "atomic_requirement_key": atomic_key,
                "product_version_key": product_version,
            }
        )
        for mapping in source.gold_mappings
    )
    positives = tuple(
        span.model_copy(
            update={
                "key": f"POS-{index}-{span_index}",
                "atomic_requirement_key": atomic_key,
                "product_version_key": product_version,
                "asset_path": f"assets/case-{index}/positive-{span_index}.pdf",
                "document_key": f"positive-document-{index}-{span_index}",
                "document_version": str(index),
                "source_sha256": _sha(f"positive-source-{index}-{span_index}"),
            }
        )
        for span_index, span in enumerate(source.gold_evidence_spans, start=1)
    )
    negatives = tuple(
        span.model_copy(
            update={
                "key": f"NEG-{index}-{span_index}",
                "atomic_requirement_key": atomic_key,
                "asset_path": f"assets/case-{index}/negative-{span_index}.pdf",
                "document_key": f"negative-document-{index}-{span_index}",
                "source_sha256": _sha(f"negative-source-{index}-{span_index}"),
            }
        )
        for span_index, span in enumerate(source.hard_negative_evidence, start=1)
    )
    outcomes = tuple(
        outcome.model_copy(
            update={
                "atomic_requirement_key": atomic_key,
                "product_version_key": product_version,
            }
        )
        for outcome in source.gold_compliance_outcomes
    )
    benchmark = GoldBenchmarkCaseMetadata(
        source_category=BenchmarkSourceCategory.PRODUCT_DOCUMENTATION,
        grouping=GoldBenchmarkGrouping(
            document_family=f"document-family-{index}",
            source_case_family=f"source-case-family-{index}",
            product_family="test-product",
            product_version_family=product_version,
        ),
        review=GoldIndependentReview(
            status=AnnotationReviewStatus.FROZEN,
            reviewer_alias=f"reviewer-{index}",
            reviewed_at=NOW,
            frozen_at=NOW,
        ),
    )
    case = source.model_copy(
        update={
            "case_id": f"benchmark-case-{index}",
            "description": f"Synthetic checked-test derivative {index}",
            "annotation": source.annotation.model_copy(
                update={"annotator": f"primary-{index}"}
            ),
            "provenance": source.provenance.model_copy(
                update={
                    "source_collection": f"source-collection-{index}",
                    "source_revision": str(index),
                }
            ),
            "benchmark": benchmark,
            "gold_atomic_requirements": (atomic,),
            "gold_mappings": mappings,
            "gold_evidence_spans": positives,
            "hard_negative_evidence": negatives,
            "gold_compliance_outcomes": outcomes,
        }
    )
    return GoldCase.model_validate_json(case.model_dump_json())


def _benchmark_dataset(case_count: int = 4) -> GoldDataset:
    fixture = load_dataset(FIXTURE, checked_in=True)
    cases = tuple(
        _benchmark_case(fixture.cases[index % len(fixture.cases)], index + 1)
        for index in range(case_count)
    )
    dataset = fixture.model_copy(
        update={
            "dataset_id": "ctrl-gold-benchmark-test-only",
            "version": "1.0.0-test",
            "description": "Programmatically derived test-only benchmark contract fixture",
            "scope": DatasetScope.EXTERNAL_RESTRICTED,
            "cases": cases,
        }
    )
    return GoldDataset.model_validate_json(dataset.model_dump_json())


def _split_config(*fields: LeakageGroupField) -> BenchmarkSplitConfig:
    return BenchmarkSplitConfig(
        seed=2301,
        development_fraction=0.5,
        group_fields=fields
        or (
            LeakageGroupField.DOCUMENT_FAMILY,
            LeakageGroupField.SOURCE_CASE_FAMILY,
        ),
    )


def _split(dataset: GoldDataset) -> BenchmarkSplitManifest:
    return generate_split_manifest(dataset, _split_config(), code_git_commit="test-commit")


def test_valid_external_benchmark_passes_and_checked_fixture_cannot_be_mistaken_for_it():
    dataset = _benchmark_dataset()
    validate_benchmark_dataset(dataset)

    with pytest.raises(BenchmarkValidationError, match="EXTERNAL_RESTRICTED"):
        validate_benchmark_dataset(load_dataset(FIXTURE, checked_in=True))


def test_review_lifecycle_requires_independent_review_and_complete_adjudication():
    assert GoldIndependentReview().status == AnnotationReviewStatus.DRAFT
    reviewed = GoldIndependentReview(
        status=AnnotationReviewStatus.REVIEWED,
        reviewer_alias="reviewer",
        reviewed_at=NOW,
        disagreement="Reviewer cannot verify the quantitative threshold.",
    )
    assert reviewed.status == AnnotationReviewStatus.REVIEWED
    adjudicated = GoldIndependentReview(
        status=AnnotationReviewStatus.ADJUDICATED,
        reviewer_alias="reviewer",
        reviewed_at=NOW,
        disagreement=reviewed.disagreement,
        adjudicator_alias="adjudicator",
        adjudicated_at=NOW,
        adjudication_note="Threshold is unsupported; abstain.",
    )
    assert adjudicated.adjudicator_alias == "adjudicator"
    with pytest.raises(ValidationError, match="requires reviewer_alias"):
        GoldIndependentReview(status=AnnotationReviewStatus.REVIEWED)
    with pytest.raises(ValidationError, match="complete adjudication"):
        GoldIndependentReview(
            status=AnnotationReviewStatus.FROZEN,
            reviewer_alias="reviewer",
            reviewed_at=NOW,
            disagreement="Unresolved",
            frozen_at=NOW,
        )


def test_positive_hard_negative_collision_and_duplicate_identity_are_rejected():
    payload = _benchmark_dataset().model_dump(mode="json")
    positive = dict(payload["cases"][0]["gold_evidence_spans"][0])
    positive.update(
        {
            "key": "COLLIDING-HARD-NEGATIVE",
            "reason": "Test-only collision",
            "error_tags": ["NON_ENTAILING"],
        }
    )
    payload["cases"][0]["hard_negative_evidence"][0] = positive
    with pytest.raises(ValidationError, match="same evidence content"):
        GoldDataset.model_validate_json(json.dumps(payload))

    payload = _benchmark_dataset().model_dump(mode="json")
    payload["cases"][1]["gold_evidence_spans"][0]["key"] = payload["cases"][0][
        "gold_evidence_spans"
    ][0]["key"]
    with pytest.raises(ValidationError, match="EvidenceSpan keys must be unique"):
        GoldDataset.model_validate_json(json.dumps(payload))


def test_forbidden_identifier_and_invalid_temporal_range_are_rejected(tmp_path: Path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["workspace_id"] = "forbidden"
    path = tmp_path / "forbidden.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="workspace_id"):
        load_dataset(path)

    payload = _benchmark_dataset().model_dump(mode="json")
    payload["cases"][0]["gold_evidence_spans"][0]["valid_from"] = "2026-08-20"
    payload["cases"][0]["gold_evidence_spans"][0]["valid_to"] = "2026-08-19"
    with pytest.raises(ValidationError, match="valid_from must not be after valid_to"):
        GoldDataset.model_validate_json(json.dumps(payload))


def test_malformed_error_tag_and_product_version_inconsistency_are_rejected():
    payload = _benchmark_dataset().model_dump(mode="json")
    payload["cases"][0]["hard_negative_evidence"][0]["error_tags"] = ["MADE_UP_TAG"]
    with pytest.raises(ValidationError, match="MADE_UP_TAG"):
        GoldDataset.model_validate_json(json.dumps(payload))

    dataset = _benchmark_dataset()
    case = dataset.cases[0]
    positive = case.gold_evidence_spans[0].model_copy(
        update={"product_version_key": "wrong-version"}
    )
    changed_case = case.model_copy(update={"gold_evidence_spans": (positive,)})
    changed = dataset.model_copy(update={"cases": (changed_case, *dataset.cases[1:])})
    with pytest.raises(BenchmarkValidationError, match="inconsistent with the explicit mapping"):
        validate_benchmark_dataset(changed)


def test_benchmark_readiness_requires_source_hash_language_and_human_negative_tags():
    dataset = _benchmark_dataset()
    case = dataset.cases[0]
    atomic = case.gold_atomic_requirements[0].model_copy(update={"language": None})
    positive = case.gold_evidence_spans[0].model_copy(update={"source_sha256": None})
    negative = case.hard_negative_evidence[0].model_copy(update={"error_tags": ()})
    changed_case = case.model_copy(
        update={
            "gold_atomic_requirements": (atomic,),
            "gold_evidence_spans": (positive,),
            "hard_negative_evidence": (negative,),
        }
    )
    changed = dataset.model_copy(update={"cases": (changed_case, *dataset.cases[1:])})

    with pytest.raises(BenchmarkValidationError) as failure:
        validate_benchmark_dataset(changed)
    assert "language is required" in str(failure.value)
    assert "requires source_sha256" in str(failure.value)
    assert "requires human error tags" in str(failure.value)


def test_external_benchmark_file_cannot_be_a_tracked_fixture():
    with pytest.raises(BenchmarkValidationError, match="tracked by Git"):
        assert_external_dataset_storage_boundary(
            FIXTURE,
            _benchmark_dataset(),
            Path.cwd(),
        )


def test_deterministic_grouped_split_is_reproducible_and_manifest_is_deterministic():
    dataset = _benchmark_dataset()
    first = _split(dataset)
    second = _split(dataset)

    assert first == second
    assert first.development_dataset_sha256 == second.development_dataset_sha256
    assert first.test_dataset_sha256 == second.test_dataset_sha256
    benchmark_first = build_benchmark_manifest(dataset, first, code_git_commit="test-commit")
    benchmark_second = build_benchmark_manifest(dataset, second, code_git_commit="test-commit")
    assert benchmark_first == benchmark_second
    assert sum(benchmark_first.case_counts.values()) == 4
    assert benchmark_first.atomic_requirement_count == 4


def test_connected_source_family_cannot_silently_leak_between_dev_and_test():
    dataset = _benchmark_dataset()
    first_case, second_case, *remaining = dataset.cases
    shared_grouping = second_case.benchmark.grouping.model_copy(
        update={"document_family": first_case.benchmark.grouping.document_family}
    )
    second_metadata = second_case.benchmark.model_copy(update={"grouping": shared_grouping})
    second_case = second_case.model_copy(update={"benchmark": second_metadata})
    grouped = dataset.model_copy(update={"cases": (first_case, second_case, *remaining)})
    manifest = generate_split_manifest(
        grouped,
        _split_config(LeakageGroupField.DOCUMENT_FAMILY),
        code_git_commit="test-commit",
    )
    assignments = {item.case_id: item for item in manifest.assignments}
    assert assignments[first_case.case_id].split == assignments[second_case.case_id].split
    assert (
        assignments[first_case.case_id].source_group_sha256
        == assignments[second_case.case_id].source_group_sha256
    )

    changed = []
    for item in manifest.assignments:
        if item.case_id == second_case.case_id:
            other = (
                BenchmarkSplitLabel.TEST
                if item.split == BenchmarkSplitLabel.DEVELOPMENT
                else BenchmarkSplitLabel.DEVELOPMENT
            )
            item = item.model_copy(update={"split": other})
        changed.append(item)
    tampered = manifest.model_copy(update={"assignments": tuple(changed)})
    with pytest.raises(ValidationError, match="source groups cannot cross split boundaries"):
        BenchmarkSplitManifest.model_validate_json(tampered.model_dump_json())


def test_unreviewed_case_cannot_enter_split_or_blind_test():
    dataset = _benchmark_dataset()
    manifest = _split(dataset)
    test_case_id = manifest.case_ids(BenchmarkSplitLabel.TEST)[0]
    cases = []
    for case in dataset.cases:
        if case.case_id == test_case_id:
            metadata = case.benchmark.model_copy(
                update={"review": GoldIndependentReview(status=AnnotationReviewStatus.DRAFT)}
            )
            case = case.model_copy(update={"benchmark": metadata})
        cases.append(case)
    unreviewed = dataset.model_copy(update={"cases": tuple(cases)})
    with pytest.raises(BenchmarkValidationError, match="before independent review"):
        validate_split_manifest(unreviewed, manifest)


def test_dataset_diagnostics_report_exact_counts_and_distributions():
    diagnostics = build_diagnostics(_benchmark_dataset())

    assert diagnostics.case_count == 4
    assert diagnostics.atomic_requirement_count == 4
    assert diagnostics.positive_evidence_count == 4
    assert diagnostics.hard_negative_count == 4
    assert diagnostics.positives_per_query.mean == 1
    assert diagnostics.hard_negatives_per_query.p95 == 1
    assert diagnostics.language_distribution == {"EN": 4}
    assert diagnostics.source_type_distribution == {"OFFICIAL_SPECIFICATION": 8}
    assert diagnostics.product_version_coverage.ratio == 1
    assert diagnostics.reviewed_percentage == 100
    assert diagnostics.frozen_percentage == 100


def test_disagreement_inspection_preserves_human_adjudication_record():
    dataset = _benchmark_dataset()
    case = dataset.cases[0]
    review = GoldIndependentReview(
        status=AnnotationReviewStatus.FROZEN,
        reviewer_alias="reviewer-1",
        reviewed_at=NOW,
        disagreement="Positive span is related but may not entail the quantitative threshold.",
        adjudicator_alias="adjudicator-1",
        adjudicated_at=NOW,
        adjudication_note=(
            "Abstain from the disputed span and retain the independently verified one."
        ),
        frozen_at=NOW,
    )
    metadata = case.benchmark.model_copy(update={"review": review})
    changed = dataset.model_copy(
        update={"cases": (case.model_copy(update={"benchmark": metadata}), *dataset.cases[1:])}
    )

    disagreements = inspect_disagreements(changed)
    assert len(disagreements) == 1
    assert disagreements[0].adjudicator_alias == "adjudicator-1"
    assert build_diagnostics(changed).adjudicated_percentage == 25


def test_frozen_test_configuration_detects_any_semantic_config_mutation():
    dataset = _benchmark_dataset()
    manifest = _split(dataset)
    semantic = load_semantic_config(SEMANTIC_CONFIG)
    leakage = semantic.leakage.model_copy(
        update={
            "rrf_weight_source": RRFWeightSource.DEVELOPMENT_TUNED,
            "development_dataset_sha256": manifest.development_dataset_sha256,
        }
    )
    semantic = semantic.model_copy(update={"leakage": leakage})
    frozen = freeze_test_configuration(
        dataset,
        manifest,
        semantic,
        frozen_at=NOW,
        frozen_by="benchmark-owner",
        code_git_commit="test-commit",
    )
    verify_frozen_test_configuration(dataset, manifest, semantic, frozen)

    changed = semantic.model_copy(update={"random_seed": semantic.random_seed + 1})
    with pytest.raises(BenchmarkValidationError, match="post-freeze mutation"):
        verify_frozen_test_configuration(dataset, manifest, changed, frozen)
    wrong_leakage = semantic.leakage.model_copy(
        update={"development_dataset_sha256": "0" * 64}
    )
    with pytest.raises(BenchmarkValidationError, match="benchmark dev hash"):
        freeze_test_configuration(
            dataset,
            manifest,
            semantic.model_copy(update={"leakage": wrong_leakage}),
            frozen_at=NOW,
            frozen_by="benchmark-owner",
            code_git_commit="test-commit",
        )


class _EmbeddingBackend:
    dimension = 1024

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
        normalize: bool,
    ) -> Sequence[Sequence[float]]:
        del batch_size, normalize
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimension
            vector[hashlib.sha256(text.encode()).digest()[0] % 8] = 1.0
            vectors.append(vector)
        return vectors

    def close(self) -> None:
        return None


class _RerankerBackend:
    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]:
        del batch_size, max_length
        return tuple(float(index) for index, _ in enumerate(pairs))

    def close(self) -> None:
        return None


def _timer() -> Callable[[], int]:
    values = count(0, 1_000_000)
    return lambda: next(values)


def test_blind_result_is_hash_bound_and_exclusive_write_is_immutable(tmp_path: Path):
    dataset = _benchmark_dataset()
    manifest = _split(dataset)
    semantic = load_semantic_config(SEMANTIC_CONFIG)
    frozen = freeze_test_configuration(
        dataset,
        manifest,
        semantic,
        frozen_at=NOW,
        frozen_by="benchmark-owner",
        code_git_commit="test-commit",
    )

    def evaluator(test_dataset, configuration, code_version):
        return run_semantic_matrix(
            test_dataset,
            configuration,
            code_version=code_version,
            embedding_backend=_EmbeddingBackend(),
            reranker_backend=_RerankerBackend(),
            timer_ns=_timer(),
        )

    with pytest.raises(BenchmarkValidationError, match="code commit differs"):
        create_blind_test_artifact(
            dataset,
            manifest,
            semantic,
            frozen,
            created_at=NOW,
            code_git_commit="changed-after-freeze",
            evaluator=evaluator,
        )
    artifact = create_blind_test_artifact(
        dataset,
        manifest,
        semantic,
        frozen,
        created_at=NOW,
        code_git_commit="test-commit",
        evaluator=evaluator,
    )
    output = tmp_path / "primary-blind-result.json"
    digest = write_blind_test_artifact(output, artifact, repository_root=Path.cwd())

    assert len(digest) == 64
    assert artifact.test_dataset_sha256 == manifest.test_dataset_sha256
    with pytest.raises(FileExistsError):
        write_blind_test_artifact(output, artifact, repository_root=Path.cwd())


def test_authoring_cli_runs_content_free_benchmark_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    dataset_path = tmp_path / "dataset.json"
    diagnostics_path = tmp_path / "diagnostics.json"
    split_path = tmp_path / "split.json"
    manifest_path = tmp_path / "manifest.json"
    frozen_path = tmp_path / "frozen.json"
    dataset_path.write_text(_benchmark_dataset().model_dump_json(indent=2), encoding="utf-8")

    commands = (
        ["authoring", "validate-benchmark", str(dataset_path)],
        [
            "authoring",
            "diagnostics",
            str(dataset_path),
            "--output",
            str(diagnostics_path),
        ],
        [
            "authoring",
            "split",
            str(dataset_path),
            "evaluations/config/gold-benchmark-split-v1.json",
            str(split_path),
        ],
        [
            "authoring",
            "manifest",
            str(dataset_path),
            str(split_path),
            str(manifest_path),
        ],
        [
            "authoring",
            "freeze-test-config",
            str(dataset_path),
            str(split_path),
            str(SEMANTIC_CONFIG),
            str(frozen_path),
            "--frozen-by",
            "benchmark-owner",
        ],
        [
            "authoring",
            "verify-frozen-test",
            str(dataset_path),
            str(split_path),
            str(SEMANTIC_CONFIG),
            str(frozen_path),
        ],
        ["authoring", "inspect-disagreements", str(dataset_path)],
    )
    for command in commands:
        monkeypatch.setattr(sys, "argv", command)
        authoring_main()

    assert diagnostics_path.is_file()
    assert split_path.is_file()
    assert manifest_path.is_file()
    assert frozen_path.is_file()
