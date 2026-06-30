import json
import tempfile
import unittest
from pathlib import Path

from hybrid_retriever import HybridRetrievalResult, RetrievedRule
from legal_schema import LegalKnowledgeGraph
from retrieval_evaluation import (
    GoldenRetrievalCase,
    compare_graph_expansion,
    evaluate_retriever,
    load_golden_cases,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "legal_graph_golden.json"


class StubRetriever:
    def __init__(self, primary, distractor):
        self.primary = primary
        self.distractor = distractor

    def retrieve(self, query, graph_depth=1, **kwargs):
        rules = (
            [RetrievedRule(self.primary, 1.0)]
            if graph_depth == 1
            else [
                RetrievedRule(self.distractor, 1.0),
                RetrievedRule(self.primary, 0.5),
            ]
        )
        return HybridRetrievalResult(
            rules=rules, fallback_documents=[], matched_entity_ids=[]
        )


class RetrievalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        graph = LegalKnowledgeGraph.model_validate_json(
            FIXTURE_PATH.read_text(encoding="utf-8")
        )
        cls.rules = {rule.rule_id: rule for rule in graph.rules}
        cls.case = GoldenRetrievalCase(
            case_id="test",
            query="不能胜任工作解除",
            expected_rule_ids=("lcl.article40.incompetence",),
            expected_source_ids=("lcl-40-2",),
        )
        cls.retriever = StubRetriever(
            cls.rules["lcl.article40.incompetence"],
            cls.rules["lcl.article47.compensation"],
        )

    def test_metrics_include_rule_and_citation_quality(self):
        report = evaluate_retriever(
            self.retriever, [self.case], k=2, graph_depth=0
        )

        self.assertEqual(1.0, report.metrics.rule_recall_at_k)
        self.assertEqual(1.0, report.metrics.hit_rate_at_k)
        self.assertEqual(0.5, report.metrics.mrr_at_k)
        self.assertEqual(0.5, report.metrics.citation_precision_at_k)
        self.assertEqual(1.0, report.metrics.citation_recall_at_k)

    def test_expansion_comparison_reports_metric_gain(self):
        comparison = compare_graph_expansion(self.retriever, [self.case], k=2)

        self.assertEqual(0.5, comparison.gains()["mrr_gain"])
        self.assertEqual(0.5, comparison.gains()["citation_precision_gain"])
        self.assertEqual(1.0, comparison.expanded.metrics.mrr_at_k)

    def test_golden_loader_rejects_duplicate_ids(self):
        duplicate = {
            "case_id": "same",
            "query": "问题",
            "expected_rule_ids": ["rule"],
            "expected_source_ids": ["source"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "golden.json"
            path.write_text(
                json.dumps([duplicate, duplicate], ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_golden_cases(str(path))

    def test_project_golden_file_loads(self):
        cases = load_golden_cases(
            str(Path(__file__).parent / "fixtures" / "retrieval_golden.json")
        )
        self.assertEqual(3, len(cases))


if __name__ == "__main__":
    unittest.main()
