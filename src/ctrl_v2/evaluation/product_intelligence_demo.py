from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from ctrl_v2.application.structured_contracts import PdfLocator, XlsxLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicRequirement,
    CapabilityCandidate,
    ControlledProductCatalog,
    DataClassification,
    EvidenceVerificationOutput,
    ProductCandidate,
    ProductVersionCandidate,
    QuantitativeComparator,
    QuantitativeConstraint,
    RawRequirement,
    RequirementModality,
    VerificationLabel,
)
from ctrl_v2.evaluation.intelligence_fakes import (
    ScriptedAtomicRequirementExtractor,
    ScriptedEvidenceVerifier,
)
from ctrl_v2.evaluation.neural_models import (
    CrossEncoderBackend,
    CrossEncoderReranker,
    E5EmbeddingModel,
    SentenceEmbeddingBackend,
)
from ctrl_v2.evaluation.product_intelligence import (
    KeywordCapabilityMapper,
    ProductIntelligenceWorkflow,
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
)
from ctrl_v2.evaluation.semantic_config import load_semantic_config

SOURCE_TEXT = (
    "Система должна поддерживать LDAP и SAML 2.0 и не менее 10 000 одновременных пользователей."
)
SOURCE_SHA = "2e6fbf460d2ce62fb3f1676f5f0fe5349a25d9f9e02d13de2ab0d6b045af201d"


def _requirement() -> RawRequirement:
    return RawRequirement(
        requirement_id="public-demo-001",
        original_text=SOURCE_TEXT,
        source_context="Public synthetic identity and scale requirement",
        source_locator=XlsxLocator(sheet="Requirements", cell_range="A2"),
        document_version_id="synthetic-rfp-v1",
        data_classification=DataClassification.SYNTHETIC,
    )


def _atomic(atomic_id: str, text: str, **updates: object) -> AtomicRequirement:
    values = {
        "atomic_id": atomic_id,
        "normalized_text": text,
        "original_source_text": SOURCE_TEXT,
        "source_quote": SOURCE_TEXT,
        "source_start_offset": 0,
        "source_end_offset": len(SOURCE_TEXT),
        "source_locator": XlsxLocator(sheet="Requirements", cell_range="A2"),
        "modality": RequirementModality.MUST,
        "category": "PRODUCT_CAPABILITY",
    }
    values.update(updates)
    return AtomicRequirement.model_validate(values)


def _catalog() -> ControlledProductCatalog:
    return ControlledProductCatalog(
        products=(
            ProductCandidate(product_id="ctrl", canonical_name="CTRL Public Demo Product"),
        ),
        product_versions=(
            ProductVersionCandidate(
                product_version_id="ctrl-7",
                product_id="ctrl",
                version_label="7.0",
                valid_from=date(2026, 1, 1),
            ),
        ),
        capabilities=(
            CapabilityCandidate(
                capability_id="identity.ldap",
                product_id="ctrl",
                canonical_name="LDAP support",
                description="LDAP directory authentication support",
            ),
            CapabilityCandidate(
                capability_id="identity.saml",
                product_id="ctrl",
                canonical_name="SAML 2.0 support",
                description="SAML 2.0 single sign-on support",
            ),
            CapabilityCandidate(
                capability_id="scale.concurrent-users",
                product_id="ctrl",
                canonical_name="Concurrent users",
                description="Scale tested for simultaneous and concurrent users",
                aliases=("одновременных пользователей",),
            ),
        ),
    )


def _span(span_id: str, text: str, page: int) -> EvidenceSpanCandidate:
    return EvidenceSpanCandidate(
        evidence_span_id=span_id,
        canonical_text=text,
        provenance=EvidenceSpanProvenance(
            asset_path=f"public-demo/{span_id}.pdf",
            document_key="public-demo-product-spec",
            document_version="spec-2026.1",
            source_sha256=SOURCE_SHA,
            locator=PdfLocator(page=page),
            source_type=EvidenceSourceType.OFFICIAL_SPECIFICATION,
            authority_level=EvidenceAuthorityLevel.AUTHORITATIVE,
            valid_from=date(2026, 1, 1),
            product_version_key="ctrl-7",
        ),
    )


def _workflow(
    semantic_configuration: Path | None,
    *,
    embedding_backend: SentenceEmbeddingBackend | None = None,
    reranker_backend: CrossEncoderBackend | None = None,
) -> tuple[ProductIntelligenceWorkflow, E5EmbeddingModel | None, CrossEncoderReranker | None]:
    raw = _requirement()
    extraction = AtomicExtractionOutput(
        requirements=(
            _atomic("REQ-LDAP", "Система должна поддерживать LDAP."),
            _atomic("REQ-SAML", "Система должна поддерживать SAML 2.0."),
            _atomic(
                "REQ-CONCURRENT",
                "Система должна поддерживать не менее 10 000 одновременных пользователей.",
                category="SCALABILITY",
                quantitative_constraint=QuantitativeConstraint(
                    comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
                    value="10 000",
                    unit="одновременных пользователей",
                ),
            ),
        )
    )
    corpus = (
        _span("SPAN-LDAP", "CTRL 7.0 supports LDAP directory authentication.", 3),
        _span("SPAN-SAML", "CTRL 7.0 supports SAML 2.0 single sign-on.", 4),
        _span(
            "SPAN-CONCURRENT",
            "CTRL 7.0 was tested with 10 000 одновременных пользователей.",
            8,
        ),
    )
    lexical = BM25Retriever(corpus)
    embedding: E5EmbeddingModel | None = None
    neural_reranker: CrossEncoderReranker | None = None
    if semantic_configuration is None:
        dense = DenseRetriever(corpus, HashingEmbeddingModel())
        reranker = IdentityReranker()
    else:
        configuration = load_semantic_config(semantic_configuration)
        embedding = E5EmbeddingModel(configuration.embedding, backend=embedding_backend)
        dense = DenseRetriever(corpus, embedding)
        neural_reranker = CrossEncoderReranker(
            configuration.reranker, backend=reranker_backend
        )
        reranker = neural_reranker
    retriever = HybridRetriever(lexical, dense)
    verifier = ScriptedEvidenceVerifier(
        {
            "SPAN-LDAP": EvidenceVerificationOutput(
                label=VerificationLabel.ENTAILS,
                explanation="The exact released LDAP capability is stated.",
            ),
            "SPAN-SAML": EvidenceVerificationOutput(
                label=VerificationLabel.ENTAILS,
                explanation="The exact released SAML 2.0 capability is stated.",
            ),
            "SPAN-CONCURRENT": EvidenceVerificationOutput(
                label=VerificationLabel.ENTAILS,
                explanation="The exact concurrent-user threshold is stated.",
            ),
        }
    )
    return (
        ProductIntelligenceWorkflow(
            extractor=ScriptedAtomicRequirementExtractor({raw.requirement_id: extraction}),
            mapper=KeywordCapabilityMapper(),
            retriever=retriever,
            reranker=reranker,
            verifier=verifier,
        ),
        embedding,
        neural_reranker,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Public/synthetic-safe CTRL product-intelligence research demo"
    )
    parser.add_argument(
        "--semantic-config",
        type=Path,
        help="Optional pinned E5/BGE config; default is deterministic dependency-free CI mode",
    )
    arguments = parser.parse_args()
    workflow, embedding, reranker = _workflow(arguments.semantic_config)
    try:
        result = workflow.run(
            _requirement(),
            _catalog(),
            assessment_as_of=date(2026, 8, 20),
            candidate_limit=3,
            final_limit=3,
        )
    finally:
        if embedding is not None:
            embedding.close()
        if reranker is not None:
            reranker.close()
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
