from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ctrl_v2.application.structured_contracts import PdfLocator, XlsxLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType
from ctrl_v2.evaluation.gold_dataset import GoldComplianceLabel
from ctrl_v2.evaluation.intelligence_comparison import (
    IntelligenceComparisonRecord,
    IntelligenceSystemVariant,
)
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicRequirement,
    CapabilityCandidate,
    ControlledProductCatalog,
    DataClassification,
    EvidenceVerificationOutput,
    EvidenceVerificationRequest,
    GuardedComplianceStatus,
    MappingDisposition,
    ProductCandidate,
    ProductVersionCandidate,
    QuantitativeComparator,
    QuantitativeConstraint,
    RawRequirement,
    RequirementMappingCandidate,
    RequirementModality,
    ValidationIssueCode,
    VerificationLabel,
    VerificationReasonTag,
)
from ctrl_v2.evaluation.intelligence_fakes import (
    ScriptedAtomicRequirementExtractor,
    ScriptedEvidenceVerifier,
)
from ctrl_v2.evaluation.intelligence_trace import (
    build_product_intelligence_trace,
    build_product_intelligence_traces,
)
from ctrl_v2.evaluation.product_intelligence import (
    KeywordCapabilityMapper,
    ProductIntelligenceWorkflow,
    aggregate_evidence_conflicts,
    apply_evidence_guardrails,
    guarded_compliance_policy,
    validate_extraction,
    validate_mapping,
)
from ctrl_v2.evaluation.product_intelligence_demo import (
    _catalog as demo_catalog,
)
from ctrl_v2.evaluation.product_intelligence_demo import (
    _requirement as demo_requirement,
)
from ctrl_v2.evaluation.product_intelligence_demo import (
    _workflow as demo_workflow,
)
from ctrl_v2.evaluation.retrieval import (
    BM25Retriever,
    DenseRetriever,
    HashingEmbeddingModel,
    HybridRetriever,
    IdentityReranker,
)
from ctrl_v2.evaluation.retrieval_contracts import (
    EvidenceSpanCandidate,
    EvidenceSpanProvenance,
    RetrievedEvidenceSpan,
)

SOURCE = (
    "Система должна поддерживать LDAP и SAML 2.0 и не менее 10 000 одновременных пользователей."
)
AS_OF = date(2026, 8, 20)
SEMANTIC_CONFIG = Path("evaluations/config/semantic-retrieval-v1.json")


class DemoEmbeddingBackend:
    dimension = 1024

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
        normalize: bool,
    ) -> Sequence[Sequence[float]]:
        del batch_size, normalize
        return tuple((1.0, *([0.0] * 1023)) for _ in texts)

    def close(self) -> None:
        pass


class DemoRerankerBackend:
    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]:
        del batch_size, max_length
        return tuple(float("saml" in evidence.casefold()) for _, evidence in pairs)

    def close(self) -> None:
        pass


def _raw() -> RawRequirement:
    return RawRequirement(
        requirement_id="case-1",
        original_text=SOURCE,
        source_context="Synthetic public test context",
        source_locator=XlsxLocator(sheet="Requirements", cell_range="A1"),
        document_version_id="rfp-v1",
        data_classification=DataClassification.SYNTHETIC,
    )


def _atomic(atomic_id: str, text: str, **updates: object) -> AtomicRequirement:
    data = {
        "atomic_id": atomic_id,
        "normalized_text": text,
        "original_source_text": SOURCE,
        "source_quote": SOURCE,
        "source_start_offset": 0,
        "source_end_offset": len(SOURCE),
        "source_locator": XlsxLocator(sheet="Requirements", cell_range="A1"),
        "modality": RequirementModality.MUST,
        "category": "CAPABILITY",
    }
    data.update(updates)
    return AtomicRequirement.model_validate(data)


def _catalog() -> ControlledProductCatalog:
    return ControlledProductCatalog(
        products=(ProductCandidate(product_id="product", canonical_name="Product"),),
        product_versions=(
            ProductVersionCandidate(
                product_version_id="product-7",
                product_id="product",
                version_label="7.0",
                valid_from=date(2026, 1, 1),
            ),
        ),
        capabilities=(
            CapabilityCandidate(
                capability_id="identity.ldap",
                product_id="product",
                canonical_name="LDAP support",
                description="LDAP directory support",
            ),
            CapabilityCandidate(
                capability_id="identity.saml",
                product_id="product",
                canonical_name="SAML 2.0 support",
                description="SAML 2.0 identity federation",
            ),
            CapabilityCandidate(
                capability_id="scale.concurrent",
                product_id="product",
                canonical_name="Concurrent users",
                description="Concurrent-user scalability",
                aliases=("одновременных пользователей",),
            ),
        ),
    )


def _mapping(atomic_id: str = "REQ-SAML") -> RequirementMappingCandidate:
    return RequirementMappingCandidate(
        requirement_id=atomic_id,
        disposition=MappingDisposition.MATCH,
        product_id="product",
        product_version_id="product-7",
        capability_id="identity.saml",
        score=1.0,
        matching_terms=("saml",),
        explanation="controlled candidate",
    )


def _evidence(
    span_id: str,
    text: str,
    *,
    product_version: str | None = "product-7",
    source_type: EvidenceSourceType = EvidenceSourceType.OFFICIAL_SPECIFICATION,
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = None,
    sha256: str | None = "a" * 64,
    authority: EvidenceAuthorityLevel = EvidenceAuthorityLevel.AUTHORITATIVE,
) -> RetrievedEvidenceSpan:
    return RetrievedEvidenceSpan(
        candidate=EvidenceSpanCandidate(
            evidence_span_id=span_id,
            canonical_text=text,
            provenance=EvidenceSpanProvenance(
                asset_path=f"fixtures/{span_id}.pdf",
                document_key="product-spec",
                document_version="spec-v3",
                source_sha256=sha256,
                locator=PdfLocator(page=1),
                source_type=source_type,
                authority_level=authority,
                valid_from=valid_from,
                valid_to=valid_to,
                product_version_key=product_version,
            ),
        ),
        rank=1,
        score=1.0,
        method="test",
    )


def _verification_request(
    atomic: AtomicRequirement,
    evidence: RetrievedEvidenceSpan,
    mapping: RequirementMappingCandidate | None = None,
) -> EvidenceVerificationRequest:
    return EvidenceVerificationRequest(
        requirement=atomic,
        mapping=mapping or _mapping(atomic.atomic_id),
        evidence=evidence,
        product_version=_catalog().product_versions[0],
        assessment_as_of=AS_OF,
        data_classification=DataClassification.SYNTHETIC,
    )


def test_valid_three_way_atomic_decomposition_preserves_source_traceability():
    atoms = (
        _atomic("REQ-LDAP", "Система должна поддерживать LDAP."),
        _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0."),
        _atomic(
            "REQ-USERS",
            "Система должна поддерживать не менее 10 000 одновременных пользователей.",
            quantitative_constraint=QuantitativeConstraint(
                comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
                value="10 000",
                unit="одновременных пользователей",
            ),
        ),
    )

    result = validate_extraction(_raw(), atoms)

    assert result.accepted == atoms
    assert result.rejected == ()
    assert result.issues == ()


def test_unique_exact_quote_recovers_incorrect_provider_offsets():
    source_quote = "SAML 2.0"
    provider = _atomic(
        "REQ-SAML",
        "Система должна поддерживать SAML 2.0.",
        source_quote=source_quote,
        source_start_offset=0,
        source_end_offset=len(source_quote),
    )

    result = validate_extraction(_raw(), (provider,))

    expected_start = SOURCE.index(source_quote)
    canonical = result.accepted[0]
    resolution = result.source_anchor_resolutions[0]
    assert result.rejected == ()
    assert canonical.source_start_offset == expected_start
    assert canonical.source_end_offset == expected_start + len(source_quote)
    assert resolution.provider_start_offset == 0
    assert resolution.provider_end_offset == len(source_quote)
    assert resolution.canonical_start_offset == expected_start
    assert resolution.canonical_end_offset == expected_start + len(source_quote)
    assert resolution.exact_match_count == 1
    assert resolution.offsets_corrected is True


def test_unique_exact_quote_preserves_correct_provider_offsets():
    source_quote = "SAML 2.0"
    start = SOURCE.index(source_quote)
    provider = _atomic(
        "REQ-SAML",
        "Система должна поддерживать SAML 2.0.",
        source_quote=source_quote,
        source_start_offset=start,
        source_end_offset=start + len(source_quote),
    )

    result = validate_extraction(_raw(), (provider,))

    assert result.accepted == (provider,)
    assert result.rejected == ()
    assert result.source_anchor_resolutions[0].offsets_corrected is False


def test_nonexistent_exact_quote_remains_unrecoverable():
    provider = _atomic(
        "REQ-KERBEROS",
        "Система должна поддерживать Kerberos.",
        source_quote="Kerberos",
        source_start_offset=0,
        source_end_offset=len("Kerberos"),
    )

    result = validate_extraction(_raw(), (provider,))

    assert result.accepted == ()
    assert result.rejected == (provider,)
    assert result.source_anchor_resolutions[0].exact_match_count == 0
    assert result.source_anchor_resolutions[0].canonical_start_offset is None
    assert {issue.code for issue in result.issues} == {
        ValidationIssueCode.SOURCE_RELATION_UNRECOVERABLE
    }


def test_duplicate_exact_quote_is_ambiguous_and_never_selects_first_match():
    source_text = "Система должна поддерживать LDAP; резервный профиль также использует LDAP."
    raw = _raw().model_copy(update={"original_text": source_text})
    provider = _atomic(
        "REQ-LDAP",
        "Система должна поддерживать LDAP.",
        original_source_text=source_text,
        source_quote="LDAP",
        source_start_offset=source_text.index("LDAP"),
        source_end_offset=source_text.index("LDAP") + len("LDAP"),
    )

    result = validate_extraction(raw, (provider,))

    assert result.accepted == ()
    assert result.rejected == (provider,)
    assert result.source_anchor_resolutions[0].exact_match_count == 2
    assert result.source_anchor_resolutions[0].canonical_start_offset is None
    assert {issue.code for issue in result.issues} == {
        ValidationIssueCode.AMBIGUOUS_SOURCE_ANCHOR
    }


def test_wrong_locator_still_blocks_after_unique_quote_offset_recovery():
    source_quote = "SAML 2.0"
    provider = _atomic(
        "REQ-SAML",
        "Система должна поддерживать SAML 2.0.",
        source_quote=source_quote,
        source_start_offset=0,
        source_end_offset=len(source_quote),
        source_locator=XlsxLocator(sheet="Other", cell_range="Z9"),
    )

    result = validate_extraction(_raw(), (provider,))

    expected_start = SOURCE.index(source_quote)
    assert result.accepted == ()
    assert result.rejected[0].source_start_offset == expected_start
    assert result.source_anchor_resolutions[0].offsets_corrected is True
    assert ValidationIssueCode.SOURCE_LOCATOR_LOST in {
        issue.code for issue in result.issues
    }


def test_short_exact_quote_cannot_bypass_structured_semantic_safety_validators():
    provider = _atomic(
        "REQ-INVENTED",
        "Система должна поддерживать 20 000 пользователей.",
        source_quote="Система",
        source_start_offset=1,
        source_end_offset=2,
    )

    result = validate_extraction(_raw(), (provider,))

    assert result.accepted == ()
    assert result.source_anchor_resolutions[0].offsets_corrected is True
    assert ValidationIssueCode.INVENTED_NUMERIC_CONSTRAINT in {
        issue.code for issue in result.issues
    }


@pytest.mark.parametrize(
    ("proposal", "expected"),
    [
        (
            _atomic("MERGED", "Система должна поддерживать LDAP и SAML 2.0."),
            ValidationIssueCode.NON_ATOMIC_CONJUNCTION,
        ),
        (
            _atomic("NUMBER", "Система должна поддерживать 20 000 пользователей."),
            ValidationIssueCode.INVENTED_NUMERIC_CONSTRAINT,
        ),
        (
            _atomic(
                "UNIT",
                "Система должна поддерживать не менее 10 000 registered users.",
                quantitative_constraint=QuantitativeConstraint(
                    comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
                    value="10 000",
                    unit="registered users",
                ),
            ),
            ValidationIssueCode.UNIT_CHANGED,
        ),
        (
            _atomic(
                "COMPARATOR",
                "Система должна поддерживать не более 10 000 одновременных пользователей.",
                quantitative_constraint=QuantitativeConstraint(
                    comparator=QuantitativeComparator.LESS_THAN_OR_EQUAL,
                    value="10 000",
                    unit="одновременных пользователей",
                ),
            ),
            ValidationIssueCode.COMPARATOR_CHANGED,
        ),
        (
            _atomic(
                "MODALITY",
                "Система может поддерживать LDAP.",
                modality=RequirementModality.MAY,
            ),
            ValidationIssueCode.MODALITY_CHANGED,
        ),
        (
            _atomic("POLARITY", "Система не должна поддерживать LDAP.", negated=True),
            ValidationIssueCode.POLARITY_REVERSED,
        ),
        (
            _atomic(
                "LOCATOR",
                "Система должна поддерживать LDAP.",
                source_locator=XlsxLocator(sheet="Other", cell_range="Z9"),
            ),
            ValidationIssueCode.SOURCE_LOCATOR_LOST,
        ),
    ],
)
def test_adversarial_extraction_is_rejected(proposal, expected):
    result = validate_extraction(_raw(), (proposal,))

    assert result.accepted == ()
    assert result.rejected == (proposal,)
    assert expected in {issue.code for issue in result.issues}


def test_empty_duplicate_and_ambiguous_extraction_fail_or_escalate():
    first = _atomic("A", "Система должна поддерживать LDAP.")
    duplicate = first.model_copy(update={"atomic_id": "B"})
    empty = first.model_copy(update={"atomic_id": "C", "normalized_text": " "})
    ambiguous = first.model_copy(
        update={
            "atomic_id": "D",
            "normalized_text": "Система должна поддерживать подходящий каталог.",
            "ambiguous": True,
            "clarification_needed": True,
            "clarification_question": "Какой протокол каталога требуется?",
        }
    )

    result = validate_extraction(_raw(), (first, duplicate, empty, ambiguous))

    assert {item.atomic_id for item in result.rejected} == {"B", "C"}
    assert ambiguous in result.accepted
    assert result.requires_human_review is True


def test_mapper_uses_only_controlled_entities_and_unknown_version_is_removed():
    atomic = _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0.")
    legitimate = KeywordCapabilityMapper().map_requirement(
        atomic, _catalog(), assessment_as_of=AS_OF
    )
    validated = validate_mapping(atomic, legitimate, _catalog())
    invented = legitimate[0].model_copy(update={"product_version_id": "product-99"})
    rejected = validate_mapping(atomic, (invented,), _catalog())

    assert validated.selected is not None
    assert validated.selected.product_version_id == "product-7"
    assert rejected.selected is None
    assert rejected.candidates[0].disposition == MappingDisposition.NO_MATCH
    assert ValidationIssueCode.UNKNOWN_PRODUCT_VERSION in {
        issue.code for issue in rejected.issues
    }


@pytest.mark.parametrize(
    ("evidence", "expected_tag"),
    [
        (
            _evidence("NEIGHBOR", "Product 7 encrypts data in transit."),
            VerificationReasonTag.SEMANTIC_NEIGHBOR_ONLY,
        ),
        (
            _evidence(
                "ROADMAP",
                "SAML 2.0 is planned.",
                source_type=EvidenceSourceType.ROADMAP,
            ),
            VerificationReasonTag.ROADMAP_ONLY,
        ),
        (
            _evidence(
                "OLD",
                "Product 6 supports SAML 2.0.",
                product_version="product-6",
                valid_from=date(2024, 1, 1),
                valid_to=date(2025, 1, 1),
            ),
            VerificationReasonTag.WRONG_VERSION,
        ),
        (
            _evidence(
                "UNVERIFIED",
                "Product 7 supports SAML 2.0.",
                authority=EvidenceAuthorityLevel.UNVERIFIED,
            ),
            VerificationReasonTag.LOWER_AUTHORITY,
        ),
    ],
)
def test_provider_entails_is_safely_downgraded_for_inapplicable_evidence(evidence, expected_tag):
    if evidence.candidate.evidence_span_id == "NEIGHBOR":
        atomic = _atomic("REQ-REST", "Customer data at rest must use AES-256.")
        source = _raw().model_copy(
            update={"original_text": "Customer data at rest must use AES-256."}
        )
        atomic = atomic.model_copy(
            update={
                "original_source_text": source.original_text,
                "source_quote": source.original_text,
                "source_end_offset": len(source.original_text),
            }
        )
    else:
        atomic = _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0.")
    result = apply_evidence_guardrails(
        _verification_request(atomic, evidence),
        EvidenceVerificationOutput(
            label=VerificationLabel.ENTAILS,
            explanation="Malicious or mistaken provider verdict",
        ),
    )

    assert result.provider_output.label == VerificationLabel.ENTAILS
    assert result.effective_output.label == VerificationLabel.INSUFFICIENT
    assert expected_tag in result.effective_output.reason_tags


@pytest.mark.parametrize(
    "provider_label",
    (
        VerificationLabel.ENTAILS,
        VerificationLabel.CONTRADICTS,
        VerificationLabel.INSUFFICIENT,
    ),
)
def test_material_metric_mismatch_is_always_insufficient_and_unknown(
    provider_label: VerificationLabel,
):
    atomic = _atomic(
        "REQ-USERS",
        "Система должна поддерживать не менее 10 000 одновременных пользователей.",
        quantitative_constraint=QuantitativeConstraint(
            comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
            value="10 000",
            unit="одновременных пользователей",
        ),
    )
    evidence = _evidence("REGISTERED", "Product 7 supports 10 000 registered users.")

    result = apply_evidence_guardrails(
        _verification_request(atomic, evidence),
        EvidenceVerificationOutput(
            label=provider_label,
            explanation="Provider verdict about evidence for a different metric",
        ),
    )
    mapping = validate_mapping(atomic, (_mapping(atomic.atomic_id),), _catalog())
    decision = guarded_compliance_policy(
        atomic,
        mapping,
        (result,),
        aggregate_evidence_conflicts((evidence,), (result,)),
    )

    assert result.effective_output.label == VerificationLabel.INSUFFICIENT
    assert VerificationReasonTag.WRONG_METRIC in result.effective_output.reason_tags
    assert decision.status == GuardedComplianceStatus.UNKNOWN


def test_same_metric_explicit_negative_limit_can_remain_gap():
    atomic = _atomic(
        "REQ-USERS",
        "Система должна поддерживать не менее 10 000 одновременных пользователей.",
        quantitative_constraint=QuantitativeConstraint(
            comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
            value="10 000",
            unit="одновременных пользователей",
        ),
    )
    evidence = _evidence(
        "LOWER-LIMIT",
        "Максимум одновременных пользователей: 5 000.",
    )
    result = apply_evidence_guardrails(
        _verification_request(atomic, evidence),
        EvidenceVerificationOutput(
            label=VerificationLabel.CONTRADICTS,
            explanation="Explicit applicable limit is below the required threshold",
        ),
    )
    mapping = validate_mapping(atomic, (_mapping(atomic.atomic_id),), _catalog())
    decision = guarded_compliance_policy(
        atomic,
        mapping,
        (result,),
        aggregate_evidence_conflicts((evidence,), (result,)),
    )

    assert result.effective_output.label == VerificationLabel.CONTRADICTS
    assert VerificationReasonTag.WRONG_METRIC not in result.effective_output.reason_tags
    assert decision.status == GuardedComplianceStatus.GAP


def test_guarded_policy_never_complies_without_exact_complete_evidence():
    atomic = _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0.")
    mapping = validate_mapping(atomic, (_mapping(),), _catalog())
    no_conflict = aggregate_evidence_conflicts((), ())

    no_evidence = guarded_compliance_policy(atomic, mapping, (), no_conflict)
    incomplete_span = _evidence("NO-SHA", "Product 7 supports SAML 2.0.", sha256=None)
    incomplete = apply_evidence_guardrails(
        _verification_request(atomic, incomplete_span),
        EvidenceVerificationOutput(
            label=VerificationLabel.ENTAILS,
            explanation="Exact text but incomplete immutable provenance",
        ),
    )
    incomplete_decision = guarded_compliance_policy(
        atomic,
        mapping,
        (incomplete,),
        aggregate_evidence_conflicts((incomplete_span,), (incomplete,)),
    )

    assert no_evidence.status == GuardedComplianceStatus.UNKNOWN
    assert incomplete_decision.status == GuardedComplianceStatus.UNKNOWN
    assert no_evidence.auto_approved is False


def test_explicit_contradiction_is_gap_and_partial_requires_unsupported_portion():
    atomic = _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0.")
    mapping = validate_mapping(atomic, (_mapping(),), _catalog())
    span = _evidence("SPAN", "Product 7 does not support SAML 2.0.")
    contradiction = apply_evidence_guardrails(
        _verification_request(atomic, span),
        EvidenceVerificationOutput(
            label=VerificationLabel.CONTRADICTS,
            explanation="Explicit non-support",
        ),
    )
    gap = guarded_compliance_policy(
        atomic,
        mapping,
        (contradiction,),
        aggregate_evidence_conflicts((span,), (contradiction,)),
    )
    partial = apply_evidence_guardrails(
        _verification_request(atomic, span),
        EvidenceVerificationOutput(
            label=VerificationLabel.INSUFFICIENT,
            reason_tags=(VerificationReasonTag.PARTIAL_SUPPORT,),
            explanation="Only enterprise IdPs are supported",
            unsupported_portion="Non-enterprise identity providers",
        ),
    )
    partial_decision = guarded_compliance_policy(
        atomic,
        mapping,
        (partial,),
        aggregate_evidence_conflicts((span,), (partial,)),
    )

    assert gap.status == GuardedComplianceStatus.GAP
    assert gap.contradicting_evidence_span_ids == ("SPAN",)
    assert partial_decision.status == GuardedComplianceStatus.PARTIAL
    assert partial_decision.unsupported_portions == ("Non-enterprise identity providers",)


def test_conflicting_current_and_obsolete_evidence_is_explicit_and_blocks_comply():
    atomic = _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0.")
    mapping = validate_mapping(atomic, (_mapping(),), _catalog())
    old = _evidence(
        "OLD-ENTAILS",
        "Product 6 supports SAML 2.0.",
        product_version="product-6",
        valid_from=date(2024, 1, 1),
        valid_to=date(2025, 12, 31),
    )
    current = _evidence("CURRENT-CONTRADICTS", "Product 7 does not support SAML 2.0.")
    entails = apply_evidence_guardrails(
        _verification_request(atomic, old),
        EvidenceVerificationOutput(
            label=VerificationLabel.ENTAILS,
            explanation="Obsolete version support",
        ),
    )
    contradicts = apply_evidence_guardrails(
        _verification_request(atomic, current),
        EvidenceVerificationOutput(
            label=VerificationLabel.CONTRADICTS,
            explanation="Current explicit non-support",
        ),
    )
    conflict = aggregate_evidence_conflicts((old, current), (entails, contradicts))
    decision = guarded_compliance_policy(atomic, mapping, (entails, contradicts), conflict)

    assert conflict.present is True
    assert set(conflict.evidence_span_ids) == {"OLD-ENTAILS", "CURRENT-CONTRADICTS"}
    assert conflict.contexts[0].document_version == "spec-v3"
    assert decision.status == GuardedComplianceStatus.UNKNOWN
    assert decision.uncertainty_reasons == ("UNRESOLVED_EVIDENCE_CONFLICT",)


def test_complete_vertical_slice_is_human_review_ready_and_traceable():
    atomic = _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0.")
    corpus = (
        EvidenceSpanCandidate(
            evidence_span_id="SAML",
            canonical_text="Product 7 supports SAML 2.0 identity federation.",
            provenance=_evidence("SAML", "unused").candidate.provenance,
        ),
        EvidenceSpanCandidate(
            evidence_span_id="LDAP",
            canonical_text="Product 7 supports LDAP directories.",
            provenance=_evidence("LDAP", "unused").candidate.provenance,
        ),
    )
    lexical = BM25Retriever(corpus)
    dense = DenseRetriever(corpus, HashingEmbeddingModel())
    workflow = ProductIntelligenceWorkflow(
        extractor=ScriptedAtomicRequirementExtractor(
            {"case-1": AtomicExtractionOutput(requirements=(atomic,))}
        ),
        mapper=KeywordCapabilityMapper(),
        retriever=HybridRetriever(lexical, dense),
        reranker=IdentityReranker(),
        verifier=ScriptedEvidenceVerifier(
            {
                "SAML": EvidenceVerificationOutput(
                    label=VerificationLabel.ENTAILS,
                    explanation="Exact current SAML support",
                ),
                "LDAP": EvidenceVerificationOutput(
                    label=VerificationLabel.ENTAILS,
                    explanation="Adversarial semantic-neighbor verdict",
                ),
            }
        ),
    )

    result = workflow.run(
        _raw(), _catalog(), assessment_as_of=AS_OF, candidate_limit=2, final_limit=2
    )
    item = result.atomic_results[0]
    trace = build_product_intelligence_trace(
        item,
        trace_id="trace-1",
        occurred_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    traces = build_product_intelligence_traces(
        item,
        trace_id_prefix="trace-sequence-1",
        occurred_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert item.mapping.selected is not None
    assert item.proposed_decision.status == GuardedComplianceStatus.COMPLY
    assert item.proposed_decision.supporting_evidence_span_ids == ("SAML",)
    assert item.requires_human_review is True
    assert result.auto_approved is False
    assert trace.state.mapping_candidates[0].product_version_id == "product-7"
    assert {entry.evidence_span_id for entry in trace.state.verifier_outputs} == {
        "SAML",
        "LDAP",
    }
    assert trace.action.selected_decision == GoldComplianceLabel.COMPLY
    assert [event.action.action.value for event in traces] == [
        "EXTRACT",
        "MAP",
        "RETRIEVE",
        "RERANK",
        "VERIFY",
        "SELECT_DECISION",
        "ESCALATE_HUMAN",
    ]


def test_general_ai_comparison_contract_uses_the_same_case_level_fields():
    record = IntelligenceComparisonRecord(
        case_id="case-1",
        system_variant=IntelligenceSystemVariant.HUMAN_GENERAL_LLM,
        predicted_atomic_requirement_keys=("REQ-SAML",),
        predicted_evidence_span_ids=("SAML",),
        predicted_decision=GoldComplianceLabel.COMPLY,
        wrong_version_error=False,
        conflict_detected=False,
        latency_ms=250.0,
        cost=0.01,
        cost_currency="USD",
        provider="general-baseline-provider",
        model_id="baseline-model",
    )

    assert record.system_variant == IntelligenceSystemVariant.HUMAN_GENERAL_LLM
    assert record.human_correction is None


def test_public_demo_runs_three_atomic_requirements_without_external_calls():
    workflow, embedding, reranker = demo_workflow(None)

    result = workflow.run(
        demo_requirement(),
        demo_catalog(),
        assessment_as_of=AS_OF,
        candidate_limit=3,
        final_limit=3,
    )

    assert embedding is None
    assert reranker is None
    assert [item.atomic_requirement.atomic_id for item in result.atomic_results] == [
        "REQ-LDAP",
        "REQ-SAML",
        "REQ-CONCURRENT",
    ]
    assert all(
        item.proposed_decision.status == GuardedComplianceStatus.COMPLY
        for item in result.atomic_results
    )


def test_vertical_slice_accepts_existing_e5_rrf_and_bge_research_stack():
    workflow, embedding, reranker = demo_workflow(
        SEMANTIC_CONFIG,
        embedding_backend=DemoEmbeddingBackend(),
        reranker_backend=DemoRerankerBackend(),
    )
    assert embedding is not None
    assert reranker is not None
    try:
        result = workflow.run(
            demo_requirement(),
            demo_catalog(),
            assessment_as_of=AS_OF,
            candidate_limit=3,
            final_limit=3,
        )
    finally:
        embedding.close()
        reranker.close()

    metadata = result.atomic_results[0].retrieval_metadata
    assert metadata is not None
    assert metadata.retriever_implementation_id == "weighted-rrf-v1"
    assert metadata.embedding_model_id.startswith("intfloat/multilingual-e5-large-instruct@")
    assert metadata.reranker_implementation_id == "transformers-cross-encoder-v1"
    assert metadata.reranker_model_id.startswith("BAAI/bge-reranker-v2-m3@")
