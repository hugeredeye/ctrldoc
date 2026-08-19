from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

import pytest
from pydantic import ValidationError

from ctrl_v2.evaluation.authoring import load_dataset
from ctrl_v2.evaluation.experiment import (
    build_retrieval_problem,
    run_retrieval_comparison,
    run_retrieval_experiment,
)
from ctrl_v2.evaluation.gold_dataset import GoldComplianceLabel
from ctrl_v2.evaluation.metrics import RetrievalMetricCase, evaluate_retrieval
from ctrl_v2.evaluation.research_trace import (
    ResearchAction,
    ResearchActionType,
    ResearchOutcome,
    ResearchState,
    ResearchTrace,
)
from ctrl_v2.evaluation.retrieval import (
    BM25Retriever,
    DenseRetriever,
    HashingEmbeddingConfig,
    HashingEmbeddingModel,
    HybridRetriever,
    IdentityReranker,
)
from ctrl_v2.evaluation.retrieval_contracts import RetrievalQuery
from ctrl_v2.evaluation.retrieval_runner import run_baselines

FIXTURE = Path("evaluations/fixtures/stage2-retrieval-v1.json")


@pytest.fixture()
def retrieval_setup():
    dataset = load_dataset(FIXTURE, checked_in=True)
    problem = build_retrieval_problem(dataset)
    lexical = BM25Retriever(problem.corpus)
    dense = DenseRetriever(
        problem.corpus,
        HashingEmbeddingModel(HashingEmbeddingConfig(dimensions=128)),
    )
    hybrid = HybridRetriever(lexical, dense)
    return dataset, problem, lexical, dense, hybrid


def test_checked_in_dataset_is_explicitly_non_customer_and_workspace_independent(tmp_path):
    dataset = load_dataset(FIXTURE, checked_in=True)

    assert dataset.scope == "CHECKED_IN_TEST"
    assert dataset.contains_customer_data is False
    assert "workspace_id" not in dataset.model_dump_json()

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["workspace_id"] = "forbidden-workspace"
    invalid_path = tmp_path / "invalid-workspace-fixture.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="workspace_id"):
        load_dataset(invalid_path, checked_in=True)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["contains_customer_data"] = True
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="cannot contain customer data"):
        load_dataset(invalid_path, checked_in=True)


def test_retrieval_queries_are_requirement_specific(retrieval_setup):
    _, problem, lexical, _, _ = retrieval_setup
    tops = {
        judgment.query.query_id: lexical.retrieve(judgment.query, limit=1)[
            0
        ].candidate.evidence_span_id
        for judgment in problem.judgments
    }

    assert tops == {
        "encryption-at-rest-001:REQ-AES-REST": "SPAN-AES-REST-V7",
        "saml-sso-001:REQ-SAML": "SPAN-SAML-V7",
    }
    with pytest.raises(ValidationError):
        RetrievalQuery(
            query_id="empty",
            case_id="case",
            atomic_requirement_key="REQ",
            requirement_text="",
        )


def test_lexical_retrieval_returns_gold_evidence(retrieval_setup):
    _, problem, lexical, _, _ = retrieval_setup
    for judgment in problem.judgments:
        result = lexical.retrieve(judgment.query, limit=3)
        assert result[0].candidate.evidence_span_id in judgment.positive_evidence_span_ids
        assert result[0].lexical_score == result[0].score
        assert result[0].method == "lexical"


def test_dense_retrieval_returns_ranked_candidates_with_configurable_model(retrieval_setup):
    _, problem, _, dense, _ = retrieval_setup

    assert dense.embedding_model_id == "ctrl-feature-hashing-document-embedding-v1"
    assert dense.parameters["embedding.dimensions"] == 128
    for judgment in problem.judgments:
        result = dense.retrieve(judgment.query, limit=4)
        assert [item.rank for item in result] == [1, 2, 3, 4]
        assert result[0].candidate.evidence_span_id in judgment.positive_evidence_span_ids
        assert all(item.dense_score == item.score for item in result)


def test_hybrid_weighted_rrf_is_deterministic(retrieval_setup):
    _, problem, _, _, hybrid = retrieval_setup
    for judgment in problem.judgments:
        first = hybrid.retrieve(judgment.query, limit=4)
        second = hybrid.retrieve(judgment.query, limit=4)
        assert first == second
        assert first[0].candidate.evidence_span_id in judgment.positive_evidence_span_ids
        assert all(item.lexical_score is not None for item in first)
        assert all(item.dense_score is not None for item in first)


def test_evidence_span_provenance_survives_retrieval(retrieval_setup):
    _, problem, lexical, _, _ = retrieval_setup
    saml = next(item for item in problem.judgments if item.query.case_id == "saml-sso-001")
    retrieved = lexical.retrieve(saml.query, limit=1)[0]

    assert retrieved.candidate.evidence_span_id == "SPAN-SAML-V7"
    assert retrieved.candidate.provenance.document_key == "product-security-guide"
    assert retrieved.candidate.provenance.document_version == "7.0"
    assert retrieved.candidate.provenance.locator.page == 12
    assert retrieved.candidate.provenance.product_version_key == "product-7"


def test_gold_positive_can_use_canonical_text_without_an_explicit_span_id(retrieval_setup):
    dataset, _, _, _, _ = retrieval_setup
    first_case = dataset.cases[0]
    evidence_without_id = first_case.gold_evidence_spans[0].model_copy(update={"key": None})
    case_without_id = first_case.model_copy(update={"gold_evidence_spans": (evidence_without_id,)})
    dataset_without_id = dataset.model_copy(update={"cases": (case_without_id, *dataset.cases[1:])})

    problem = build_retrieval_problem(dataset_without_id)
    judgment = next(
        item for item in problem.judgments if item.query.case_id == case_without_id.case_id
    )

    assert len(judgment.positive_evidence_span_ids) == 1
    assert next(iter(judgment.positive_evidence_span_ids)).startswith("canonical-text:")


def test_hard_negative_is_not_silently_counted_as_positive():
    metrics = evaluate_retrieval(
        [
            RetrievalMetricCase(
                query_id="REQ-1",
                positive_evidence_span_ids=frozenset({"positive"}),
                hard_negative_evidence_span_ids=frozenset({"hard-negative"}),
                ranked_evidence_span_ids=("hard-negative", "positive"),
            )
        ]
    )

    assert metrics.evidence_recall_at_1 == 0.0
    assert metrics.evidence_recall_at_3 == 1.0
    assert metrics.mrr == 0.5
    assert metrics.ndcg_at_1 == 0.0
    assert 0 < metrics.ndcg_at_3 < 1


def test_retrieval_metric_calculations_for_multiple_positives():
    metrics = evaluate_retrieval(
        [
            RetrievalMetricCase(
                query_id="REQ-1",
                positive_evidence_span_ids=frozenset({"p1", "p2"}),
                ranked_evidence_span_ids=("p1", "negative", "p2"),
            )
        ]
    )

    assert metrics.query_count == 1
    assert metrics.evidence_recall_at_1 == 0.5
    assert metrics.evidence_recall_at_3 == 1.0
    assert metrics.evidence_recall_at_5 == 1.0
    assert metrics.mrr == 1.0
    assert metrics.ndcg_at_1 == 1.0
    assert 0 < metrics.ndcg_at_3 < 1
    assert metrics.ndcg_at_5 == metrics.ndcg_at_3


def _timer() -> Callable[[], int]:
    readings = count(0, 1_000_000)
    return lambda: next(readings)


def test_experiment_metadata_and_results_are_reproducible(retrieval_setup):
    dataset, problem, lexical, _, _ = retrieval_setup
    reranker = IdentityReranker()
    first = run_retrieval_experiment(
        dataset,
        problem,
        lexical,
        reranker,
        retrieval_limit=4,
        random_seed=17,
        code_version="test-commit",
        timer_ns=_timer(),
    )
    second = run_retrieval_experiment(
        dataset,
        problem,
        lexical,
        reranker,
        retrieval_limit=4,
        random_seed=17,
        code_version="test-commit",
        timer_ns=_timer(),
    )

    assert first == second
    assert first.metadata.run_id == second.metadata.run_id
    assert len(first.metadata.dataset_sha256) == 64
    assert first.metadata.retrieval_method == "lexical"
    assert first.metadata.random_seed == 17
    assert first.mean_latency_ms == 2.0
    assert all(case.candidate_count == 4 for case in first.cases)
    assert json.loads(first.model_dump_json())["metrics"]["evidence_recall_at_1"] == 1.0


def test_comparison_reports_lexical_dense_and_hybrid_runs(retrieval_setup):
    dataset, _, lexical, dense, hybrid = retrieval_setup
    suite = run_retrieval_comparison(
        dataset,
        (lexical, dense, hybrid),
        IdentityReranker(),
        retrieval_limit=4,
        code_version="test-commit",
        timer_ns=_timer(),
    )

    assert [run.metadata.retrieval_method for run in suite.runs] == [
        "lexical",
        "dense",
        "hybrid",
    ]
    assert all(run.metrics["evidence_recall_at_1"] == 1.0 for run in suite.runs)
    assert len({run.metadata.run_id for run in suite.runs}) == 3


def test_baseline_runner_serializes_comparable_results():
    payload = json.loads(
        run_baselines(
            FIXTURE,
            repository=Path.cwd(),
            checked_in_fixture=True,
            retrieval_limit=4,
            random_seed=23,
            embedding_dimensions=128,
        )
    )

    assert [run["metadata"]["retrieval_method"] for run in payload["runs"]] == [
        "lexical",
        "dense",
        "hybrid",
    ]
    assert all(run["metadata"]["random_seed"] == 23 for run in payload["runs"])
    assert all(run["cases"][0]["candidate_count"] == 4 for run in payload["runs"])


def test_research_trace_contract_serializes_future_feedback(retrieval_setup):
    _, problem, lexical, _, _ = retrieval_setup
    judgment = problem.judgments[0]
    retrieved = lexical.retrieve(judgment.query, limit=2)
    trace = ResearchTrace(
        trace_id="trace-1",
        case_id=judgment.query.case_id,
        occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
        state=ResearchState(
            requirement=judgment.query,
            retrieved_candidates=retrieved,
            conflicts=("hard-negative outranks weak evidence",),
            uncertainty=0.2,
        ),
        action=ResearchAction(
            action=ResearchActionType.SELECT_DECISION,
            selected_evidence_span_ids=(retrieved[0].candidate.evidence_span_id,),
            selected_decision=GoldComplianceLabel.COMPLY,
        ),
        outcome=ResearchOutcome(
            model_decision=GoldComplianceLabel.COMPLY,
            human_correction=GoldComplianceLabel.PARTIAL,
            accepted=False,
            latency_ms=12.5,
            inference_cost=0.01,
            tool_cost=0.0,
            cost_currency="USD",
        ),
    )

    payload = json.loads(trace.model_dump_json())
    assert payload["state"]["retrieved_candidates"][0]["candidate"]["provenance"]
    assert payload["outcome"]["human_correction"] == "PARTIAL"
