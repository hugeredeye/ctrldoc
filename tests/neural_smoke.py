from __future__ import annotations

import argparse
import gc
import json
import platform
import time
from pathlib import Path

import psutil

from ctrl_v2.evaluation.authoring import load_dataset
from ctrl_v2.evaluation.experiment import build_retrieval_problem
from ctrl_v2.evaluation.neural_models import CrossEncoderReranker, E5EmbeddingModel
from ctrl_v2.evaluation.retrieval import BM25Retriever, DenseRetriever
from ctrl_v2.evaluation.semantic_config import load_semantic_config


def _rss_gib() -> float:
    return psutil.Process().memory_info().rss / (1024**3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Opt-in real neural model smoke test")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("configuration", type=Path)
    arguments = parser.parse_args()

    dataset = load_dataset(arguments.dataset, checked_in=True)
    configuration = load_semantic_config(arguments.configuration)
    problem = build_retrieval_problem(dataset)
    query = problem.judgments[0].query
    started_rss = _rss_gib()

    embedding = E5EmbeddingModel(configuration.embedding)
    embedding_started = time.perf_counter()
    dense = DenseRetriever(problem.corpus, embedding)
    dense_results = dense.retrieve(query, limit=2)
    embedding_seconds = time.perf_counter() - embedding_started
    embedding_rss = _rss_gib()
    embedding.close()
    del dense
    gc.collect()

    lexical = BM25Retriever(problem.corpus)
    candidates = lexical.retrieve(query, limit=2)
    reranker = CrossEncoderReranker(configuration.reranker)
    reranker_started = time.perf_counter()
    reranked = reranker.rerank(query, candidates, limit=2)
    reranker_seconds = time.perf_counter() - reranker_started
    reranker_rss = _rss_gib()
    reranker.close()

    result = {
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": psutil.cpu_count(logical=True),
            "gpu_used": False,
        },
        "rss_gib": {
            "start": started_rss,
            "embedding_loaded": embedding_rss,
            "reranker_loaded": reranker_rss,
        },
        "embedding": {
            "model_id": embedding.model_id,
            "weights_loaded": True,
            "latency_seconds": embedding_seconds,
            "dimension": configuration.embedding.embedding_dimension,
            "top_ids": [item.candidate.evidence_span_id for item in dense_results],
        },
        "reranker": {
            "model_id": reranker.model_id,
            "weights_loaded": True,
            "latency_seconds": reranker_seconds,
            "top_ids": [item.candidate.evidence_span_id for item in reranked],
            "scores": [item.reranker_score for item in reranked],
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
