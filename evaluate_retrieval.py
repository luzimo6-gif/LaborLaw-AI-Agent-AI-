#!/usr/bin/env python3
"""CLI for repeatable GraphRAG retrieval evaluation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from graph_store import LegalGraphStore
from hybrid_retriever import HybridLegalRetriever, HybridWeights
from retrieval_evaluation import compare_graph_expansion, load_golden_cases


class EmptyVectorStore:
    def similarity_search_with_score(self, query, k=4, **kwargs):
        return [], []


def main() -> int:
    parser = argparse.ArgumentParser(description="评测劳动法 GraphRAG 检索质量")
    parser.add_argument("--graph-db", default="legal_graph.db")
    parser.add_argument("--vectorstore", default="vectorstore.pkl")
    parser.add_argument(
        "--golden", default="tests/fixtures/retrieval_golden.json"
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--graph-only", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--rrf-constant", type=int, default=60)
    parser.add_argument("--weight-vector", type=float, default=1.25)
    parser.add_argument("--weight-entity", type=float, default=1.0)
    parser.add_argument("--weight-lexical", type=float, default=0.75)
    parser.add_argument("--weight-graph", type=float, default=0.35)
    args = parser.parse_args()

    if args.k <= 0 or args.rrf_constant <= 0:
        parser.error("--k 和 --rrf-constant 必须为正数")
    if not Path(args.graph_db).exists():
        parser.error(f"图数据库不存在: {args.graph_db}")

    vectorstore = _load_vectorstore(args) if not args.graph_only else EmptyVectorStore()
    weights = HybridWeights(
        vector=args.weight_vector,
        entity=args.weight_entity,
        lexical=args.weight_lexical,
        graph_expansion=args.weight_graph,
    )
    cases = load_golden_cases(args.golden)
    with LegalGraphStore(args.graph_db, read_only=True) as graph_store:
        retriever = HybridLegalRetriever(
            vectorstore,
            graph_store,
            rrf_constant=args.rrf_constant,
            weights=weights,
        )
        comparison = compare_graph_expansion(retriever, cases, k=args.k)

    _print_report(comparison)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\n详细结果: {target}")
    return 0


def _load_vectorstore(args):
    path = Path(args.vectorstore)
    if not path.exists():
        raise SystemExit(
            f"向量库不存在: {path}；可使用 --graph-only 仅评测图检索"
        )
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise SystemExit("混合评测需要 DASHSCOPE_API_KEY；或使用 --graph-only")

    from langchain_openai import OpenAIEmbeddings
    from simple_vectorstore import SimpleVectorStore

    embeddings = OpenAIEmbeddings(
        model=os.getenv("EMBED_MODEL", "text-embedding-v2"),
        api_key=api_key,
        base_url=os.getenv(
            "OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    )
    vectorstore = SimpleVectorStore(str(path), embedding_function=embeddings)
    vectorstore.load()
    return vectorstore


def _print_report(comparison) -> None:
    baseline = comparison.baseline.metrics
    expanded = comparison.expanded.metrics
    gains = comparison.gains()
    print(f"评测问题数: {baseline.case_count}  |  K={comparison.baseline.k}")
    print("指标                     depth=0    depth=1      增益")
    rows = [
        ("Rule Recall@K", baseline.rule_recall_at_k, expanded.rule_recall_at_k, gains["rule_recall_gain"]),
        ("Hit Rate@K", baseline.hit_rate_at_k, expanded.hit_rate_at_k, gains["hit_rate_gain"]),
        ("MRR@K", baseline.mrr_at_k, expanded.mrr_at_k, gains["mrr_gain"]),
        ("Citation Precision@K", baseline.citation_precision_at_k, expanded.citation_precision_at_k, gains["citation_precision_gain"]),
        ("Citation Recall@K", baseline.citation_recall_at_k, expanded.citation_recall_at_k, gains["citation_recall_gain"]),
    ]
    for name, before, after, gain in rows:
        print(f"{name:<24} {before:>7.3f}    {after:>7.3f}   {gain:>+7.3f}")


if __name__ == "__main__":
    raise SystemExit(main())
