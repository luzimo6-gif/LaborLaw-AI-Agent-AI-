import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from legal_schema import LegalKnowledgeGraph


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "legal_graph_golden.json"
RETRIEVAL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "retrieval_golden.json"


class LegalSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_golden_graph_is_valid(self):
        graph = LegalKnowledgeGraph.model_validate(self.fixture)

        self.assertEqual("1.0.0", graph.schema_version)
        self.assertEqual(7, len(graph.entities))
        self.assertEqual(3, len(graph.rules))
        self.assertTrue(all(rule.sources for rule in graph.rules))

    def test_unknown_entity_reference_is_rejected(self):
        invalid = copy.deepcopy(self.fixture)
        invalid["rules"][0]["subjects"][0]["entity_id"] = "actor.unknown"

        with self.assertRaisesRegex(ValidationError, "unknown entities"):
            LegalKnowledgeGraph.model_validate(invalid)

    def test_rule_without_source_evidence_is_rejected(self):
        invalid = copy.deepcopy(self.fixture)
        invalid["rules"][0]["sources"] = []

        with self.assertRaises(ValidationError):
            LegalKnowledgeGraph.model_validate(invalid)

    def test_inverted_effective_dates_are_rejected(self):
        invalid = copy.deepcopy(self.fixture)
        invalid["rules"][0]["effective_to"] = "2010-01-01"

        with self.assertRaisesRegex(ValidationError, "effective_to"):
            LegalKnowledgeGraph.model_validate(invalid)

    def test_unknown_fields_are_rejected(self):
        invalid = copy.deepcopy(self.fixture)
        invalid["rules"][0]["hallucinated_article"] = "第一千条"

        with self.assertRaises(ValidationError):
            LegalKnowledgeGraph.model_validate(invalid)

    def test_retrieval_golden_cases_reference_known_records(self):
        graph = LegalKnowledgeGraph.model_validate(self.fixture)
        cases = json.loads(RETRIEVAL_FIXTURE_PATH.read_text(encoding="utf-8"))
        known_rules = {rule.rule_id for rule in graph.rules}
        known_sources = {
            source.source_id for rule in graph.rules for source in rule.sources
        }

        self.assertTrue(cases)
        for case in cases:
            self.assertTrue(set(case["expected_rule_ids"]) <= known_rules)
            self.assertTrue(set(case["expected_source_ids"]) <= known_sources)


if __name__ == "__main__":
    unittest.main()
