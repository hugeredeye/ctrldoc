from __future__ import annotations

import argparse
from pathlib import Path

from .authoring import load_dataset
from .experiment import resolve_git_commit
from .semantic_config import load_semantic_config
from .semantic_experiment import run_semantic_matrix


def run_semantic_baselines(
    dataset_path: Path,
    configuration_path: Path,
    *,
    repository: Path,
    checked_in_fixture: bool = False,
) -> str:
    dataset = load_dataset(dataset_path, checked_in=checked_in_fixture)
    configuration = load_semantic_config(configuration_path)
    result = run_semantic_matrix(
        dataset,
        configuration,
        code_version=resolve_git_commit(repository),
    )
    return result.model_dump_json(indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run pinned offline neural retrieval and reranking experiments"
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--checked-in-fixture", action="store_true")
    arguments = parser.parse_args()
    payload = run_semantic_baselines(
        arguments.dataset,
        arguments.configuration,
        repository=arguments.repository,
        checked_in_fixture=arguments.checked_in_fixture,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(payload + "\n", encoding="utf-8")
    print(f"results-written path={arguments.output}")


if __name__ == "__main__":
    main()
