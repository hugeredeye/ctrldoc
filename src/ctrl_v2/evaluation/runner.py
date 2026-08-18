from __future__ import annotations

import json
from pathlib import Path

from .contracts import EvaluationFixture
from .metrics import evaluate


def run_fixture(path: Path) -> dict[str, object]:
    fixture = EvaluationFixture.model_validate_json(path.read_text(encoding="utf-8"))
    return {
        "schema_version": fixture.schema_version,
        "versions": fixture.versions.model_dump(),
        "metrics": evaluate(fixture).as_dict(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run_fixture(arguments.fixture), indent=2, sort_keys=True))
