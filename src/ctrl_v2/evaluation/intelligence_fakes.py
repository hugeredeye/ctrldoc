from __future__ import annotations

from collections.abc import Mapping

from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicExtractionResult,
    AtomicRequirementExtractor,
    EvidenceVerificationOutput,
    EvidenceVerificationRequest,
    EvidenceVerifier,
    RawRequirement,
)


class ScriptedAtomicRequirementExtractor(AtomicRequirementExtractor):
    """Deterministic CI/research double keyed by raw requirement ID."""

    def __init__(self, outputs: Mapping[str, AtomicExtractionOutput]) -> None:
        self._outputs = dict(outputs)

    def extract(self, requirement: RawRequirement) -> AtomicExtractionResult:
        try:
            output = self._outputs[requirement.requirement_id]
        except KeyError as exc:
            raise ValueError(
                f"No deterministic extraction for {requirement.requirement_id}"
            ) from exc
        return AtomicExtractionResult(output=output)


class ScriptedEvidenceVerifier(EvidenceVerifier):
    """Deterministic CI/research double keyed by EvidenceSpan ID."""

    def __init__(self, outputs: Mapping[str, EvidenceVerificationOutput]) -> None:
        self._outputs = dict(outputs)

    def verify(
        self,
        request: EvidenceVerificationRequest,
    ) -> tuple[EvidenceVerificationOutput, None]:
        evidence_span_id = request.evidence.candidate.evidence_span_id
        try:
            return self._outputs[evidence_span_id], None
        except KeyError as exc:
            raise ValueError(
                f"No deterministic verification for {evidence_span_id}"
            ) from exc
