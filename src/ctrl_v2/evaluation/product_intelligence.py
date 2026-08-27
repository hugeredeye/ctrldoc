from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from functools import partial

from ctrl_v2.domain.enums import EvidenceAuthorityLevel
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicIntelligenceResult,
    AtomicRequirement,
    AtomicRequirementExtractor,
    CapabilityCandidate,
    CapabilityMapper,
    ConflictEvidenceContext,
    ControlledProductCatalog,
    EvidenceConflict,
    EvidenceVerificationOutput,
    EvidenceVerificationRequest,
    EvidenceVerificationResult,
    EvidenceVerifier,
    ExtractionValidationResult,
    GuardedComplianceDecision,
    GuardedComplianceStatus,
    MappingDisposition,
    MappingResult,
    ModelCallRecord,
    ProductIntelligenceResult,
    ProductVersionCandidate,
    RawRequirement,
    RequirementMappingCandidate,
    RequirementModality,
    RetrievalMetadata,
    SourceAnchorResolution,
    ValidationIssue,
    ValidationIssueCode,
    VerificationLabel,
    VerificationReasonTag,
)
from ctrl_v2.evaluation.retrieval import tokenize
from ctrl_v2.evaluation.retrieval_contracts import (
    EvidenceReranker,
    EvidenceRetriever,
    RetrievalQuery,
    RetrievedEvidenceSpan,
)

_NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:[ ,.]+\d+)*(?:[.,]\d+)?(?!\w)")
_ACRONYM_PATTERN = re.compile(r"\b[A-ZА-Я]{2,}(?:[- ]?\d+(?:\.\d+)*)?\b")
_CONJUNCTION_PATTERN = re.compile(r"\b(?:and|и)\b", re.IGNORECASE)
_BETWEEN_PATTERN = re.compile(r"\b(?:between|между)\b.{0,40}\b(?:and|и)\b", re.IGNORECASE)

_MODALITY_MARKERS: tuple[tuple[RequirementModality, tuple[str, ...]], ...] = (
    (
        RequirementModality.PROHIBITED,
        ("must not", "shall not", "не должен", "не должна", "не должно", "запрещ"),
    ),
    (RequirementModality.MUST, ("must", "shall", "должен", "должна", "должно", "должны")),
    (RequirementModality.SHOULD, ("should", "следует")),
    (RequirementModality.MAY, ("may", "может", "могут")),
)
_COMPARATOR_MARKERS = {
    ">=": (">=", "at least", "not less than", "не менее"),
    "<=": ("<=", "at most", "not more than", "не более"),
    ">": (">", "more than", "greater than", "более"),
    "<": ("<", "less than", "fewer than", "менее"),
    "=": ("=", "exactly", "ровно"),
}
_NEGATION_MARKERS = (" not ", " no ", "without", " не ", "нет ", "запрещ")
_CONTRASTING_QUALIFIERS = (
    ("concurrent", "registered", VerificationReasonTag.WRONG_METRIC),
    ("одноврем", "зарегистрирован", VerificationReasonTag.WRONG_METRIC),
    ("at rest", "in transit", VerificationReasonTag.SEMANTIC_NEIGHBOR_ONLY),
    ("in transit", "at rest", VerificationReasonTag.SEMANTIC_NEIGHBOR_ONLY),
    ("при хранении", "при передаче", VerificationReasonTag.SEMANTIC_NEIGHBOR_ONLY),
    ("при передаче", "при хранении", VerificationReasonTag.SEMANTIC_NEIGHBOR_ONLY),
)
_INAPPLICABLE_TAGS = {
    VerificationReasonTag.WRONG_VERSION,
    VerificationReasonTag.WRONG_METRIC,
    VerificationReasonTag.INSUFFICIENT_LIMIT,
    VerificationReasonTag.ROADMAP_ONLY,
    VerificationReasonTag.OBSOLETE_SOURCE,
    VerificationReasonTag.TEMPORALLY_INVALID,
    VerificationReasonTag.SEMANTIC_NEIGHBOR_ONLY,
    VerificationReasonTag.AMBIGUOUS_SOURCE,
    VerificationReasonTag.INCOMPLETE_PROVENANCE,
    VerificationReasonTag.LOWER_AUTHORITY,
}


def _add_validation_issue(
    issues: list[ValidationIssue],
    atomic_id: str,
    code: ValidationIssueCode,
    message: str,
    *,
    blocking: bool = True,
) -> None:
    issues.append(
        ValidationIssue(
            code=code,
            atomic_id=atomic_id,
            message=message,
            blocking=blocking,
        )
    )


def _normalized_numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", match.group()) for match in _NUMBER_PATTERN.finditer(text)}


def _expected_modality(text: str) -> RequirementModality:
    lowered = f" {text.casefold()} "
    for modality, markers in _MODALITY_MARKERS:
        if any(marker in lowered for marker in markers):
            return modality
    return RequirementModality.UNKNOWN


def _has_negation(text: str) -> bool:
    lowered = f" {text.casefold()} "
    for comparative in ("not less than", "not more than", "не менее", "не более"):
        lowered = lowered.replace(comparative, " ")
    return any(marker in lowered for marker in _NEGATION_MARKERS)


def _source_comparator(text: str) -> str | None:
    lowered = text.casefold()
    ordered = (
        (">=", _COMPARATOR_MARKERS[">="]),
        ("<=", _COMPARATOR_MARKERS["<="]),
        (">", _COMPARATOR_MARKERS[">"]),
        ("<", _COMPARATOR_MARKERS["<"]),
        ("=", _COMPARATOR_MARKERS["="]),
    )
    for comparator, markers in ordered:
        for marker in markers:
            if marker in lowered:
                if comparator == ">" and any(
                    compound in lowered for compound in ("not more than", "не более")
                ):
                    continue
                if comparator == "<" and any(
                    compound in lowered for compound in ("not less than", "не менее")
                ):
                    continue
                return comparator
    return None


def _has_unresolved_conjunction(text: str) -> bool:
    return bool(_CONJUNCTION_PATTERN.search(text)) and not bool(_BETWEEN_PATTERN.search(text))


def _exact_quote_starts(source_text: str, source_quote: str) -> tuple[int, ...]:
    starts: list[int] = []
    search_from = 0
    while True:
        start = source_text.find(source_quote, search_from)
        if start < 0:
            return tuple(starts)
        starts.append(start)
        search_from = start + 1


def _canonicalize_source_anchor(
    source_text: str,
    proposal: AtomicRequirement,
) -> tuple[AtomicRequirement, SourceAnchorResolution, ValidationIssueCode | None]:
    matches = _exact_quote_starts(source_text, proposal.source_quote)
    if len(matches) != 1:
        resolution = SourceAnchorResolution(
            atomic_id=proposal.atomic_id,
            provider_start_offset=proposal.source_start_offset,
            provider_end_offset=proposal.source_end_offset,
            exact_match_count=len(matches),
            offsets_corrected=False,
        )
        issue = (
            ValidationIssueCode.SOURCE_RELATION_UNRECOVERABLE
            if not matches
            else ValidationIssueCode.AMBIGUOUS_SOURCE_ANCHOR
        )
        return proposal, resolution, issue

    canonical_start = matches[0]
    canonical_end = canonical_start + len(proposal.source_quote)
    offsets_corrected = (
        proposal.source_start_offset != canonical_start
        or proposal.source_end_offset != canonical_end
    )
    canonical = proposal.model_copy(
        update={
            "source_start_offset": canonical_start,
            "source_end_offset": canonical_end,
        }
    )
    resolution = SourceAnchorResolution(
        atomic_id=proposal.atomic_id,
        provider_start_offset=proposal.source_start_offset,
        provider_end_offset=proposal.source_end_offset,
        canonical_start_offset=canonical_start,
        canonical_end_offset=canonical_end,
        exact_match_count=1,
        offsets_corrected=offsets_corrected,
    )
    return canonical, resolution, None


def validate_extraction(
    source: RawRequirement,
    proposals: Sequence[AtomicRequirement],
) -> ExtractionValidationResult:
    accepted: list[AtomicRequirement] = []
    rejected: list[AtomicRequirement] = []
    issues: list[ValidationIssue] = []
    source_anchor_resolutions: list[SourceAnchorResolution] = []
    seen: set[str] = set()
    source_numbers = _normalized_numbers(source.original_text)

    for provider_proposal in proposals:
        proposal, anchor_resolution, anchor_issue = _canonicalize_source_anchor(
            source.original_text,
            provider_proposal,
        )
        source_anchor_resolutions.append(anchor_resolution)
        local: list[ValidationIssue] = []
        add = partial(_add_validation_issue, local, proposal.atomic_id)

        normalized = " ".join(proposal.normalized_text.split()).casefold()
        if not normalized:
            add(ValidationIssueCode.EMPTY_ATOMIC, "Atomic requirement is blank")
        elif normalized in seen:
            add(ValidationIssueCode.DUPLICATE_ATOMIC, "Duplicate normalized atomic requirement")
        else:
            seen.add(normalized)
        if proposal.original_source_text != source.original_text:
            add(ValidationIssueCode.ORIGINAL_SOURCE_CHANGED, "Original source text changed")
        if proposal.source_locator.model_dump(mode="json") != source.source_locator.model_dump(
            mode="json"
        ):
            add(ValidationIssueCode.SOURCE_LOCATOR_LOST, "Source locator changed or was lost")
        if anchor_issue is ValidationIssueCode.SOURCE_RELATION_UNRECOVERABLE:
            add(
                ValidationIssueCode.SOURCE_RELATION_UNRECOVERABLE,
                "Source quote does not occur exactly in the declared source unit",
            )
        elif anchor_issue is ValidationIssueCode.AMBIGUOUS_SOURCE_ANCHOR:
            add(
                ValidationIssueCode.AMBIGUOUS_SOURCE_ANCHOR,
                "Source quote occurs more than once in the declared source unit",
            )
        invented_numbers = _normalized_numbers(proposal.normalized_text) - source_numbers
        if invented_numbers:
            add(
                ValidationIssueCode.INVENTED_NUMERIC_CONSTRAINT,
                f"Atomic text introduced numeric values: {sorted(invented_numbers)}",
            )
        constraint = proposal.quantitative_constraint
        if constraint is not None:
            constraint_number = re.sub(r"\D", "", constraint.value)
            if constraint_number not in source_numbers:
                add(
                    ValidationIssueCode.INVENTED_NUMERIC_CONSTRAINT,
                    "Quantitative constraint is absent from source",
                )
            if constraint.unit.casefold() not in source.original_text.casefold():
                add(ValidationIssueCode.UNIT_CHANGED, "Quantitative unit is absent from source")
            comparator = constraint.comparator.value
            if _source_comparator(source.original_text) != comparator:
                add(
                    ValidationIssueCode.COMPARATOR_CHANGED,
                    "Quantitative comparator is not recoverable from source",
                )
        expected_modality = _expected_modality(proposal.source_quote)
        if (
            expected_modality != RequirementModality.UNKNOWN
            and proposal.modality != expected_modality
        ):
            add(
                ValidationIssueCode.MODALITY_CHANGED,
                f"Expected {expected_modality.value}, received {proposal.modality.value}",
            )
        source_negated = _has_negation(proposal.source_quote)
        if proposal.negated != source_negated:
            add(ValidationIssueCode.POLARITY_REVERSED, "Requirement polarity changed")
        if _has_unresolved_conjunction(proposal.normalized_text):
            add(
                ValidationIssueCode.NON_ATOMIC_CONJUNCTION,
                "Atomic text still contains a potentially separable conjunction",
            )
        if proposal.ambiguous or proposal.clarification_needed:
            add(
                ValidationIssueCode.AMBIGUOUS_REQUIREMENT,
                "Requirement needs human clarification",
                blocking=False,
            )
        issues.extend(local)
        if any(item.blocking for item in local):
            rejected.append(proposal)
        else:
            accepted.append(proposal)

    return ExtractionValidationResult(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        issues=tuple(issues),
        source_anchor_resolutions=tuple(source_anchor_resolutions),
        requires_human_review=bool(issues),
    )


class KeywordCapabilityMapper:
    """Deterministic controlled-catalog baseline; it never creates catalog entities."""

    def map_requirement(
        self,
        requirement: AtomicRequirement,
        catalog: ControlledProductCatalog,
        *,
        assessment_as_of: date,
    ) -> tuple[RequirementMappingCandidate, ...]:
        requirement_terms = set(tokenize(requirement.normalized_text))
        products = {item.product_id: item for item in catalog.products}
        applicable_versions: dict[str, list[ProductVersionCandidate]] = {}
        for version in catalog.product_versions:
            if version.valid_from <= assessment_as_of and (
                version.valid_to is None or version.valid_to >= assessment_as_of
            ):
                applicable_versions.setdefault(version.product_id, []).append(version)
        scored: list[
            tuple[float, tuple[str, ...], CapabilityCandidate, ProductVersionCandidate]
        ] = []
        for capability in catalog.capabilities:
            versions = applicable_versions.get(capability.product_id, [])
            if not versions:
                continue
            candidate_terms = set(
                tokenize(
                    " ".join(
                        (
                            capability.canonical_name,
                            capability.description,
                            *capability.aliases,
                            products[capability.product_id].canonical_name,
                            *products[capability.product_id].aliases,
                        )
                    )
                )
            )
            matching = tuple(sorted(requirement_terms & candidate_terms))
            if not matching:
                continue
            score = len(matching) / max(len(requirement_terms), 1)
            scored.extend(
                (score, matching, capability, version)
                for version in sorted(versions, key=lambda item: item.product_version_id)
            )
        if not scored:
            return (
                RequirementMappingCandidate(
                    requirement_id=requirement.atomic_id,
                    disposition=MappingDisposition.NO_MATCH,
                    explanation="No controlled ProductVersion/Capability candidate matched",
                ),
            )
        scored.sort(key=lambda item: (-item[0], item[2].capability_id))
        top_score = scored[0][0]
        ambiguous = sum(item[0] == top_score for item in scored) > 1
        return tuple(
            RequirementMappingCandidate(
                requirement_id=requirement.atomic_id,
                disposition=(
                    MappingDisposition.AMBIGUOUS
                    if ambiguous and score == top_score
                    else MappingDisposition.MATCH
                ),
                product_id=capability.product_id,
                product_version_id=version.product_version_id,
                capability_id=capability.capability_id,
                score=score,
                matching_terms=matching,
                explanation="Controlled-catalog token overlap baseline",
            )
            for score, matching, capability, version in scored
        )


def validate_mapping(
    requirement: AtomicRequirement,
    candidates: Sequence[RequirementMappingCandidate],
    catalog: ControlledProductCatalog,
) -> MappingResult:
    products = {item.product_id for item in catalog.products}
    versions = {item.product_version_id: item for item in catalog.product_versions}
    capabilities = {item.capability_id: item for item in catalog.capabilities}
    accepted: list[RequirementMappingCandidate] = []
    issues: list[ValidationIssue] = []
    for candidate in candidates:
        invalid = False
        if candidate.requirement_id != requirement.atomic_id:
            invalid = True
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.SOURCE_RELATION_UNRECOVERABLE,
                    atomic_id=requirement.atomic_id,
                    message="Mapping references a different atomic requirement",
                    blocking=True,
                )
            )
        if candidate.disposition != MappingDisposition.NO_MATCH:
            if candidate.product_id not in products:
                invalid = True
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNKNOWN_PRODUCT,
                        atomic_id=requirement.atomic_id,
                        message="Mapper invented or referenced an unknown Product",
                        blocking=True,
                    )
                )
            if candidate.product_version_id not in versions:
                invalid = True
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNKNOWN_PRODUCT_VERSION,
                        atomic_id=requirement.atomic_id,
                        message="Mapper invented or referenced an unknown ProductVersion",
                        blocking=True,
                    )
                )
            if candidate.capability_id not in capabilities:
                invalid = True
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNKNOWN_CAPABILITY,
                        atomic_id=requirement.atomic_id,
                        message="Mapper invented or referenced an unknown Capability",
                        blocking=True,
                    )
                )
            if not invalid:
                version = versions[candidate.product_version_id]
                capability = capabilities[candidate.capability_id]
                if (
                    version.product_id != candidate.product_id
                    or capability.product_id != candidate.product_id
                ):
                    invalid = True
                    issues.append(
                        ValidationIssue(
                            code=ValidationIssueCode.UNKNOWN_PRODUCT_VERSION,
                            atomic_id=requirement.atomic_id,
                            message="Mapping combines entities from different controlled products",
                            blocking=True,
                        )
                    )
        if not invalid:
            accepted.append(candidate)
    viable = [item for item in accepted if item.disposition == MappingDisposition.MATCH]
    ambiguous = any(item.disposition == MappingDisposition.AMBIGUOUS for item in accepted)
    contradictory_no_match = any(
        item.disposition == MappingDisposition.NO_MATCH for item in accepted
    ) and bool(viable)
    selected = (
        max(viable, key=lambda item: (item.score or 0.0, item.capability_id or ""))
        if viable and not ambiguous and not contradictory_no_match
        else None
    )
    if not accepted:
        accepted.append(
            RequirementMappingCandidate(
                requirement_id=requirement.atomic_id,
                disposition=MappingDisposition.NO_MATCH,
                explanation="All mapper candidates failed controlled-catalog validation",
            )
        )
    return MappingResult(
        candidates=tuple(accepted),
        issues=tuple(issues),
        selected=selected,
        requires_human_review=selected is None or bool(issues),
    )


def _append_tag(
    tags: list[VerificationReasonTag], tag: VerificationReasonTag
) -> None:
    if tag not in tags:
        tags.append(tag)


def apply_evidence_guardrails(
    request: EvidenceVerificationRequest,
    provider_output: EvidenceVerificationOutput,
    model_call: ModelCallRecord | None = None,
) -> EvidenceVerificationResult:
    candidate = request.evidence.candidate
    provenance = candidate.provenance
    adjustments: list[VerificationReasonTag] = []
    tags = list(provider_output.reason_tags)
    if provenance.product_version_key != request.mapping.product_version_id:
        _append_tag(adjustments, VerificationReasonTag.WRONG_VERSION)
    if provenance.valid_from > request.assessment_as_of or (
        provenance.valid_to is not None and provenance.valid_to < request.assessment_as_of
    ):
        _append_tag(adjustments, VerificationReasonTag.TEMPORALLY_INVALID)
        _append_tag(adjustments, VerificationReasonTag.OBSOLETE_SOURCE)
    if provenance.source_type.value == "ROADMAP":
        _append_tag(adjustments, VerificationReasonTag.ROADMAP_ONLY)
    if provenance.authority_level in {
        EvidenceAuthorityLevel.WEAK,
        EvidenceAuthorityLevel.UNVERIFIED,
    }:
        _append_tag(adjustments, VerificationReasonTag.LOWER_AUTHORITY)
    if provenance.source_sha256 is None:
        _append_tag(adjustments, VerificationReasonTag.INCOMPLETE_PROVENANCE)
    if request.product_version.valid_from > request.assessment_as_of or (
        request.product_version.valid_to is not None
        and request.product_version.valid_to < request.assessment_as_of
    ):
        _append_tag(adjustments, VerificationReasonTag.TEMPORALLY_INVALID)

    evidence_text = candidate.canonical_text.casefold()
    requirement_text = request.requirement.normalized_text.casefold()
    constraint = request.requirement.quantitative_constraint
    if constraint is not None and constraint.unit.casefold() not in evidence_text:
        _append_tag(adjustments, VerificationReasonTag.WRONG_METRIC)
    if provider_output.label == VerificationLabel.ENTAILS:
        if constraint is not None:
            value = re.sub(r"\D", "", constraint.value)
            if value not in _normalized_numbers(evidence_text):
                _append_tag(adjustments, VerificationReasonTag.INSUFFICIENT_LIMIT)
        for required, conflicting, tag in _CONTRASTING_QUALIFIERS:
            if required in requirement_text and required not in evidence_text:
                _append_tag(adjustments, tag)
                if conflicting in evidence_text:
                    _append_tag(adjustments, tag)
        for critical_term in _ACRONYM_PATTERN.findall(request.requirement.normalized_text):
            if critical_term.casefold() not in evidence_text:
                _append_tag(adjustments, VerificationReasonTag.SEMANTIC_NEIGHBOR_ONLY)
    for tag in adjustments:
        _append_tag(tags, tag)
    effective_label = provider_output.label
    if any(tag in _INAPPLICABLE_TAGS for tag in adjustments):
        effective_label = VerificationLabel.INSUFFICIENT
    effective = provider_output.model_copy(
        update={
            "label": effective_label,
            "reason_tags": tuple(tags),
            "explanation": (
                provider_output.explanation
                if not adjustments
                else "Provider verdict downgraded by deterministic provenance/evidence guardrails."
            ),
        }
    )
    return EvidenceVerificationResult(
        evidence_span_id=candidate.evidence_span_id,
        provider_output=provider_output,
        effective_output=effective,
        guardrail_adjustments=tuple(adjustments),
        model_call=model_call,
    )


def aggregate_evidence_conflicts(
    evidence: Sequence[RetrievedEvidenceSpan],
    verifications: Sequence[EvidenceVerificationResult],
) -> EvidenceConflict:
    by_id = {item.candidate.evidence_span_id: item for item in evidence}
    entails = [
        item for item in verifications if item.provider_output.label == VerificationLabel.ENTAILS
    ]
    contradicts = [
        item
        for item in verifications
        if item.provider_output.label == VerificationLabel.CONTRADICTS
    ]
    conflicting = (*entails, *contradicts) if entails and contradicts else ()
    contexts = tuple(
        ConflictEvidenceContext(
            evidence_span_id=item.evidence_span_id,
            provider_label=item.provider_output.label,
            effective_label=item.effective_output.label,
            authority_level=by_id[item.evidence_span_id].candidate.provenance.authority_level,
            source_type=by_id[item.evidence_span_id].candidate.provenance.source_type,
            document_version=by_id[
                item.evidence_span_id
            ].candidate.provenance.document_version,
            product_version_id=by_id[
                item.evidence_span_id
            ].candidate.provenance.product_version_key,
            valid_from=by_id[item.evidence_span_id].candidate.provenance.valid_from,
            valid_to=by_id[item.evidence_span_id].candidate.provenance.valid_to,
        )
        for item in conflicting
    )
    present = bool(conflicting)
    return EvidenceConflict(
        present=present,
        material=present,
        evidence_span_ids=tuple(item.evidence_span_id for item in conflicting),
        contexts=contexts,
        explanation=(
            "Opposing evidence verdicts require authority, version, and temporal adjudication."
            if present
            else None
        ),
        requires_human_review=present,
    )


def guarded_compliance_policy(
    requirement: AtomicRequirement,
    mapping: MappingResult,
    verifications: Sequence[EvidenceVerificationResult],
    conflict: EvidenceConflict,
) -> GuardedComplianceDecision:
    selected = mapping.selected
    common = {
        "product_version_id": selected.product_version_id if selected else None,
        "capability_id": selected.capability_id if selected else None,
    }
    if requirement.ambiguous or requirement.clarification_needed:
        return GuardedComplianceDecision(
            status=GuardedComplianceStatus.NEEDS_CLARIFICATION,
            uncertainty_reasons=("SOURCE_REQUIREMENT_AMBIGUOUS",),
            **common,
        )
    if selected is None:
        return GuardedComplianceDecision(
            status=GuardedComplianceStatus.UNKNOWN,
            uncertainty_reasons=("MAPPING_UNRESOLVED",),
            **common,
        )
    if conflict.present:
        return GuardedComplianceDecision(
            status=GuardedComplianceStatus.UNKNOWN,
            uncertainty_reasons=("UNRESOLVED_EVIDENCE_CONFLICT",),
            **common,
        )
    entails = [
        item
        for item in verifications
        if item.effective_output.label == VerificationLabel.ENTAILS
    ]
    contradicts = [
        item
        for item in verifications
        if item.effective_output.label == VerificationLabel.CONTRADICTS
    ]
    partial = [
        item
        for item in verifications
        if VerificationReasonTag.PARTIAL_SUPPORT in item.effective_output.reason_tags
        and item.effective_output.unsupported_portion
        and VerificationReasonTag.INCOMPLETE_PROVENANCE not in item.effective_output.reason_tags
    ]
    if contradicts:
        return GuardedComplianceDecision(
            status=GuardedComplianceStatus.GAP,
            contradicting_evidence_span_ids=tuple(item.evidence_span_id for item in contradicts),
            **common,
        )
    if entails:
        return GuardedComplianceDecision(
            status=GuardedComplianceStatus.COMPLY,
            supporting_evidence_span_ids=tuple(item.evidence_span_id for item in entails),
            **common,
        )
    if partial:
        return GuardedComplianceDecision(
            status=GuardedComplianceStatus.PARTIAL,
            supporting_evidence_span_ids=tuple(item.evidence_span_id for item in partial),
            unsupported_portions=tuple(
                item.effective_output.unsupported_portion for item in partial
            ),
            **common,
        )
    return GuardedComplianceDecision(
        status=GuardedComplianceStatus.UNKNOWN,
        uncertainty_reasons=("NO_APPLICABLE_VERIFIED_EVIDENCE",),
        **common,
    )


class ProductIntelligenceWorkflow:
    def __init__(
        self,
        *,
        extractor: AtomicRequirementExtractor,
        mapper: CapabilityMapper,
        retriever: EvidenceRetriever,
        reranker: EvidenceReranker,
        verifier: EvidenceVerifier,
    ) -> None:
        self._extractor = extractor
        self._mapper = mapper
        self._retriever = retriever
        self._reranker = reranker
        self._verifier = verifier

    def run(
        self,
        requirement: RawRequirement,
        catalog: ControlledProductCatalog,
        *,
        assessment_as_of: date,
        candidate_limit: int = 20,
        final_limit: int = 5,
    ) -> ProductIntelligenceResult:
        if final_limit > candidate_limit:
            raise ValueError("final_limit cannot exceed candidate_limit")
        extraction_result = self._extractor.extract(requirement)
        extraction = validate_extraction(requirement, extraction_result.output.requirements)
        model_calls: list[ModelCallRecord] = []
        if extraction_result.model_call is not None:
            model_calls.append(extraction_result.model_call)
        atomic_results: list[AtomicIntelligenceResult] = []
        versions = {item.product_version_id: item for item in catalog.product_versions}
        for atomic in extraction.accepted:
            if atomic.ambiguous or atomic.clarification_needed:
                mapping = MappingResult(
                    candidates=(
                        RequirementMappingCandidate(
                            requirement_id=atomic.atomic_id,
                            disposition=MappingDisposition.NO_MATCH,
                            explanation="Clarification is required before controlled mapping",
                        ),
                    ),
                    selected=None,
                    requires_human_review=True,
                )
            else:
                proposed_mappings = self._mapper.map_requirement(
                    atomic,
                    catalog,
                    assessment_as_of=assessment_as_of,
                )
                mapping = validate_mapping(atomic, proposed_mappings, catalog)
            retrieved = ()
            reranked = ()
            verifications: list[EvidenceVerificationResult] = []
            retrieval_metadata = None
            selected = mapping.selected
            if selected is not None:
                query = RetrievalQuery(
                    query_id=f"{requirement.requirement_id}:{atomic.atomic_id}",
                    case_id=requirement.requirement_id,
                    atomic_requirement_key=atomic.atomic_id,
                    requirement_text=atomic.normalized_text,
                    source_context=requirement.source_context,
                )
                retrieved = self._retriever.retrieve(query, limit=candidate_limit)
                reranked = self._reranker.rerank(query, retrieved, limit=final_limit)
                retrieval_metadata = RetrievalMetadata(
                    retriever_implementation_id=self._retriever.implementation_id,
                    retriever_method=self._retriever.method,
                    embedding_model_id=self._retriever.embedding_model_id,
                    reranker_implementation_id=self._reranker.implementation_id,
                    reranker_model_id=self._reranker.model_id,
                    candidate_limit=candidate_limit,
                    final_limit=final_limit,
                )
                product_version = versions[selected.product_version_id]
                for evidence in reranked:
                    request = EvidenceVerificationRequest(
                        requirement=atomic,
                        mapping=selected,
                        evidence=evidence,
                        product_version=product_version,
                        assessment_as_of=assessment_as_of,
                        data_classification=requirement.data_classification,
                    )
                    output, call = self._verifier.verify(request)
                    verification = apply_evidence_guardrails(request, output, call)
                    verifications.append(verification)
                    if call is not None:
                        model_calls.append(call)
            conflict = aggregate_evidence_conflicts(reranked, verifications)
            decision = guarded_compliance_policy(atomic, mapping, verifications, conflict)
            calls = tuple(
                item.model_call for item in verifications if item.model_call is not None
            )
            atomic_results.append(
                AtomicIntelligenceResult(
                    original_requirement=requirement,
                    atomic_requirement=atomic,
                    mapping=mapping,
                    candidate_evidence=tuple(reranked),
                    verifications=tuple(verifications),
                    conflict=conflict,
                    proposed_decision=decision,
                    retrieval_metadata=retrieval_metadata,
                    model_calls=calls,
                )
            )
        return ProductIntelligenceResult(
            original_requirement=requirement,
            extraction=extraction,
            atomic_results=tuple(atomic_results),
            model_calls=tuple(model_calls),
        )
