from __future__ import annotations

import json
import os

from ctrl_v2.application.structured_contracts import XlsxLocator
from ctrl_v2.evaluation.intelligence_contracts import DataClassification, RawRequirement
from ctrl_v2.evaluation.openai_responses import (
    DEFAULT_MODEL,
    OpenAIResearchConfig,
    OpenAIResponsesResearchAdapter,
)


def main() -> None:
    if os.environ.get("CTRL_RUN_REAL_LLM_SMOKE") != "1":
        raise SystemExit("Set CTRL_RUN_REAL_LLM_SMOKE=1 to authorize the opt-in external call")
    model_id = os.environ.get("CTRL_OPENAI_RESEARCH_MODEL", DEFAULT_MODEL)
    adapter = OpenAIResponsesResearchAdapter(OpenAIResearchConfig(model_id=model_id))
    result = adapter.extract(
        RawRequirement(
            requirement_id="openai-public-smoke",
            original_text="The public demo service must support SAML 2.0.",
            source_locator=XlsxLocator(sheet="PublicDemo", cell_range="A1"),
            data_classification=DataClassification.PUBLIC,
        )
    )
    call = result.model_call
    assert call is not None
    print(
        json.dumps(
            {
                "executed": True,
                "safe_data": "PUBLIC",
                "provider": call.provider,
                "model": call.model_id,
                "prompt_version": call.prompt_version,
                "latency_ms": call.latency_ms,
                "tokens": call.token_usage.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
