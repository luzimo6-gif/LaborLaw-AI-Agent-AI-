"""Metrics and comparison utilities for legal hybrid retrieval."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence


class SupportsRetrieve(Protocol):
    def retrieve(self, query: str, **kwargs) -> Any: ...


@dataclass(frozen=True)
class GoldenRetrievalCase:
    case_id: str
    query: str
    expected_rule_ids: tuple[str, ...]
    expected_source_ids: tuple[str, ...]
    jurisdiction: Optional[str] = None


@dataclass(frozen=True)
class CaseEvaluation:
    case_id: str
    query: str
    retrieved_rule_ids: tuple[str, ...]
    retrieved_source_ids: tuple[str, ...]
    rule_recall: float
    hit: bool
    reciprocal_rank: float
    citation_precision: float
    citation_recall: float


@dataclass(frozen=True)
class RetrievalMetrics:
    case_count: int
    rule_recall_at_k: float
    hit_rate_at_k: float
    mrr_at_k: float
    citation_precision_at_k: float
    citation_recall_at_k: float


@dataclass(frozen=True)
class EvaluationReport:
    k: int
    graph_depth: int
    metrics: RetrievalMetrics
    cases: tuple[CaseEvaluation, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExpansionComparison:
    baseline: EvaluationReport
    expanded: EvaluationReport

    def gains(self) -> dict[str, float]:
        baseline = self.baseline.metrics
        expanded = self.expanded.metrics
        return {
            "rule_recall_gain": expanded.rule_recall_at_k - baseline.rule_recall_at_k,
            "hit_rate_gain": expanded.hit_rate_at_k - baseline.hit_rate_at_k,
            "mrr_gain": expanded.mrr_at_k - baseline.mrr_at_k,
            "citation_precision_gain": (
                expanded.citation_precision_at_k - baseline.citation_precision_at_k
            ),
            "citation_recall_gain": (
                expanded.citation_recall_at_k - baseline.citation_recall_at_k
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "expanded": self.expanded.to_dict(),
            "gains": self.gains(),
        }


def load_golden_cases(path: str) -> list[GoldenRetrievalCase]:
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = []
    seen_ids = set()
    for record in records:
        case = GoldenRetrievalCase(
            case_id=str(record["case_id"]),
            query=str(record["query"]),
            expected_rule_ids=tuple(str(item) for item in record["expected_rule_ids"]),
            expected_source_ids=tuple(str(item) for item in record["expected_source_ids"]),
            jurisdiction=(
                str(record["jurisdiction"]) if record.get("jurisdiction") else None
            ),
        )
        if case.case_id in seen_ids:
            raise ValueError(f"duplicate golden case_id: {case.case_id}")
        if not case.expected_rule_ids:
            raise ValueError(f"case {case.case_id!r} has no expected rules")
        seen_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("golden retrieval set is empty")
    return cases


def evaluate_retriever(
    retriever: SupportsRetrieve,
    cases: Sequence[GoldenRetrievalCase],
    k: int = 5,
    graph_depth: int = 1,
) -> EvaluationReport:
    if k <= 0:
        raise ValueError("k must be positive")
    evaluations = []
    for case in cases:
        result = retriever.retrieve(
            case.query,
            k_rules=k,
            graph_depth=graph_depth,
            jurisdiction=case.jurisdiction,
        )
        retrieved = list(result.rules[:k])
        rule_ids = tuple(item.rule.rule_id for item in retrieved)
        source_ids = tuple(
            dict.fromkeys(
                source.source_id
                for item in retrieved
                for source in item.rule.sources
            )
        )
        expected_rules = set(case.expected_rule_ids)
        expected_sources = set(case.expected_source_ids)
        matched_rules = expected_rules & set(rule_ids)
        matched_sources = expected_sources & set(source_ids)
        first_relevant_rank = next(
            (rank for rank, rule_id in enumerate(rule_ids, 1) if rule_id in expected_rules),
            None,
        )
        evaluations.append(
            CaseEvaluation(
                case_id=case.case_id,
                query=case.query,
                retrieved_rule_ids=rule_ids,
                retrieved_source_ids=source_ids,
                rule_recall=len(matched_rules) / len(expected_rules),
                hit=bool(matched_rules),
                reciprocal_rank=(1.0 / first_relevant_rank if first_relevant_rank else 0.0),
                citation_precision=(
                    len(matched_sources) / len(set(source_ids)) if source_ids else 0.0
                ),
                citation_recall=(
                    len(matched_sources) / len(expected_sources)
                    if expected_sources
                    else 1.0
                ),
            )
        )

    count = len(evaluations)
    metrics = RetrievalMetrics(
        case_count=count,
        rule_recall_at_k=_mean(item.rule_recall for item in evaluations),
        hit_rate_at_k=_mean(float(item.hit) for item in evaluations),
        mrr_at_k=_mean(item.reciprocal_rank for item in evaluations),
        citation_precision_at_k=_mean(item.citation_precision for item in evaluations),
        citation_recall_at_k=_mean(item.citation_recall for item in evaluations),
    )
    return EvaluationReport(
        k=k,
        graph_depth=graph_depth,
        metrics=metrics,
        cases=tuple(evaluations),
    )


def compare_graph_expansion(
    retriever: SupportsRetrieve,
    cases: Sequence[GoldenRetrievalCase],
    k: int = 5,
) -> ExpansionComparison:
    return ExpansionComparison(
        baseline=evaluate_retriever(retriever, cases, k=k, graph_depth=0),
        expanded=evaluate_retriever(retriever, cases, k=k, graph_depth=1),
    )


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0
