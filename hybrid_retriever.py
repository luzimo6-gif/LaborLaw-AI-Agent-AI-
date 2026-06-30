"""Hybrid vector + SQLite graph retrieval for labor-law evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, Protocol, Sequence

from graph_store import LegalGraphStore
from legal_schema import LegalRule


class SupportsVectorSearch(Protocol):
    def similarity_search_with_score(self, query: str, k: int = 4, **kwargs): ...


@dataclass
class RetrievedRule:
    rule: LegalRule
    score: float
    matched_by: list[str] = field(default_factory=list)
    graph_path: list[str] = field(default_factory=list)
    vector_documents: list[Any] = field(default_factory=list)


@dataclass
class HybridRetrievalResult:
    rules: list[RetrievedRule]
    fallback_documents: list[Any]
    matched_entity_ids: list[str]


@dataclass(frozen=True)
class HybridWeights:
    vector: float = 1.25
    entity: float = 1.0
    lexical: float = 0.75
    graph_expansion: float = 0.35


class HybridLegalRetriever:
    def __init__(
        self,
        vectorstore: SupportsVectorSearch,
        graph_store: LegalGraphStore,
        rrf_constant: int = 60,
        weights: Optional[HybridWeights] = None,
    ):
        self.vectorstore = vectorstore
        self.graph_store = graph_store
        self.rrf_constant = rrf_constant
        self.weights = weights or HybridWeights()

    def retrieve(
        self,
        query: str,
        k_vector: int = 12,
        k_rules: int = 8,
        graph_depth: int = 1,
        jurisdiction: Optional[str] = None,
        as_of: Optional[date] = None,
    ) -> HybridRetrievalResult:
        vector_documents, _vector_scores = self.vectorstore.similarity_search_with_score(
            query, k=k_vector
        )
        chunk_ids = [
            str(doc.metadata.get("chunk_id"))
            for doc in vector_documents
            if doc.metadata.get("chunk_id")
        ]
        citations = [_document_citation(doc) for doc in vector_documents]
        citations = [citation for citation in citations if citation]

        matched_entities = self.graph_store.match_entities(query)
        entity_rules = self.graph_store.rule_ids_for_entities(matched_entities)
        vector_rules = self.graph_store.rule_ids_for_chunks(chunk_ids)
        vector_rules.extend(self.graph_store.rule_ids_for_citations(citations))
        vector_rules = list(dict.fromkeys(vector_rules))
        lexical_scores = self.graph_store.lexical_rule_scores(query, limit=max(20, k_rules * 3))
        lexical_rules = [rule_id for rule_id, _score in lexical_scores]

        seed_rules = list(dict.fromkeys(vector_rules + entity_rules + lexical_rules[:k_rules]))
        expanded = self.graph_store.expand_rules(
            seed_rules, depth=graph_depth, limit=max(k_rules * 6, 30)
        )

        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        self._add_ranked(
            scores, reasons, vector_rules, "vector_chunk", self.weights.vector
        )
        self._add_ranked(scores, reasons, entity_rules, "entity", self.weights.entity)
        for rank, (rule_id, lexical_score) in enumerate(lexical_scores, 1):
            scores[rule_id] = scores.get(rule_id, 0.0) + (
                self.weights.lexical * lexical_score / (1.0 + rank / 10.0)
            )
            reasons.setdefault(rule_id, []).append("lexical")
        for rule_id, (depth, _via) in expanded.items():
            if depth > 0:
                scores[rule_id] = scores.get(rule_id, 0.0) + (
                    self.weights.graph_expansion / (self.rrf_constant + depth)
                )
                reasons.setdefault(rule_id, []).append("graph_expansion")

        ordered_ids = sorted(scores, key=lambda rule_id: (-scores[rule_id], rule_id))
        applicable_rules = self.graph_store.get_rules(
            ordered_ids, jurisdiction=jurisdiction, as_of=as_of
        )
        applicable_by_id = {rule.rule_id: rule for rule in applicable_rules}

        entity_ids_on_paths = {
            entity_id for _rule_id, (_depth, via) in expanded.items() for entity_id in via
        }
        entity_names = self.graph_store.entity_names(entity_ids_on_paths)
        doc_by_chunk: dict[str, list[Any]] = {}
        for document in vector_documents:
            chunk_id = document.metadata.get("chunk_id")
            if chunk_id:
                doc_by_chunk.setdefault(str(chunk_id), []).append(document)

        retrieved: list[RetrievedRule] = []
        for rule_id in ordered_ids:
            rule = applicable_by_id.get(rule_id)
            if not rule:
                continue
            depth, via = expanded.get(rule_id, (0, ()))
            path = [entity_names[item] for item in via if item in entity_names]
            attached_documents = []
            for source in rule.sources:
                attached_documents.extend(doc_by_chunk.get(source.chunk_id, []))
            retrieved.append(
                RetrievedRule(
                    rule=rule,
                    score=scores[rule_id],
                    matched_by=list(dict.fromkeys(reasons.get(rule_id, []))),
                    graph_path=path if depth else [],
                    vector_documents=attached_documents,
                )
            )
            if len(retrieved) >= k_rules:
                break

        matched_chunks = {
            source.chunk_id for item in retrieved for source in item.rule.sources
        }
        fallback = [
            document
            for document in vector_documents
            if str(document.metadata.get("chunk_id", "")) not in matched_chunks
        ]
        return HybridRetrievalResult(
            rules=retrieved,
            fallback_documents=fallback,
            matched_entity_ids=matched_entities,
        )

    def _add_ranked(
        self,
        scores: dict[str, float],
        reasons: dict[str, list[str]],
        rule_ids: Sequence[str],
        reason: str,
        weight: float,
    ) -> None:
        for rank, rule_id in enumerate(dict.fromkeys(rule_ids), 1):
            scores[rule_id] = scores.get(rule_id, 0.0) + weight / (
                self.rrf_constant + rank
            )
            reasons.setdefault(rule_id, []).append(reason)


def _document_citation(document: Any) -> Optional[tuple[str, str]]:
    metadata = document.metadata or {}
    law_name = metadata.get("law_name")
    article = metadata.get("article")
    text = getattr(document, "page_content", "")
    if not law_name:
        match = re.search(r"《([^》]+)》", text)
        law_name = match.group(1) if match else None
    if not article:
        match = re.search(r"第[一二三四五六七八九十百千万零〇两\d]+条", text)
        article = match.group(0) if match else None
    if law_name and article:
        return str(law_name), str(article)
    return None
