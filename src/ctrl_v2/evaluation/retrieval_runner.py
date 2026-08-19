from __future__ import annotations

import argparse
from pathlib import Path

from .authoring import load_dataset
from .experiment import build_retrieval_problem, resolve_git_commit, run_retrieval_comparison
from .retrieval import (
    BM25Retriever,
    DenseRetriever,
    HashingEmbeddingConfig,
    HashingEmbeddingModel,
    HybridRetriever,
    IdentityReranker,
)


def run_baselines(
    dataset_path: Path,
    *,
    repository: Path,
    checked_in_fixture: bool = False,
    retrieval_limit: int = 5,
    random_seed: int = 0,
    embedding_dimensions: int = 256,
) -> str:
    dataset = load_dataset(dataset_path, checked_in=checked_in_fixture)
    problem = build_retrieval_problem(dataset)
    lexical = BM25Retriever(problem.corpus)
    embedding_model = HashingEmbeddingModel(HashingEmbeddingConfig(dimensions=embedding_dimensions))
    dense = DenseRetriever(problem.corpus, embedding_model)
    hybrid = HybridRetriever(lexical, dense)
    suite = run_retrieval_comparison(
        dataset,
        (lexical, dense, hybrid),
        IdentityReranker(),
        retrieval_limit=retrieval_limit,
        random_seed=random_seed,
        code_version=resolve_git_commit(repository),
    )
    return suite.model_dump_json(indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run comparable CTRL evidence-retrieval baselines")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--checked-in-fixture", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--embedding-dimensions", type=int, default=256)
    arguments = parser.parse_args()
    payload = run_baselines(
        arguments.dataset,
        repository=arguments.repository,
        checked_in_fixture=arguments.checked_in_fixture,
        retrieval_limit=arguments.limit,
        random_seed=arguments.seed,
        embedding_dimensions=arguments.embedding_dimensions,
    )
    if arguments.output is None:
        print(payload)
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload + "\n", encoding="utf-8")
        print(f"results-written path={arguments.output}")


if __name__ == "__main__":
    main()
