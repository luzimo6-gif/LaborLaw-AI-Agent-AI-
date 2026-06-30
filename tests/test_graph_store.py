import tempfile
import unittest
from datetime import date
from pathlib import Path

from graph_store import LegalGraphStore
from legal_schema import LegalKnowledgeGraph


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "legal_graph_golden.json"


class GraphStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.graph = LegalKnowledgeGraph.model_validate_json(
            FIXTURE_PATH.read_text(encoding="utf-8")
        )
        self.store = LegalGraphStore(str(Path(self.temporary.name) / "graph.db"))
        self.store.replace_graph(self.graph)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_snapshot_is_normalized_into_sqlite(self):
        self.assertEqual((7, 3, 3), self.store.counts())
        self.assertIn("actor.worker", self.store.match_entities("员工被拖欠工资"))
        self.assertIn("actor.employer", self.store.match_entities("公司违法解除"))

    def test_chunk_and_citation_find_rules(self):
        self.assertEqual(
            ["lcl.article40.incompetence"],
            self.store.rule_ids_for_chunks(["golden:lcl:40"]),
        )
        self.assertEqual(
            ["lcl.article47.compensation"],
            self.store.rule_ids_for_citations(
                [("中华人民共和国劳动合同法", "第四十七条")]
            ),
        )

    def test_graph_expansion_uses_shared_entities(self):
        expanded = self.store.expand_rules(
            ["lcl.article40.incompetence"], depth=1
        )

        self.assertEqual(0, expanded["lcl.article40.incompetence"][0])
        self.assertEqual(1, expanded["lcl.article47.compensation"][0])
        self.assertIn("actor.employer", expanded["lcl.article47.compensation"][1])

    def test_effective_date_filter(self):
        rules = self.store.get_rules(
            ["lcl.article40.incompetence"], as_of=date(2010, 1, 1)
        )
        self.assertEqual([], rules)

    def test_lexical_search_finds_arbitration_limit(self):
        scored = self.store.lexical_rule_scores("拖欠工资申请仲裁超过一年")
        ids = [rule_id for rule_id, _score in scored[:2]]
        self.assertIn("ldm.article27.limit", ids)

    def test_read_only_store_can_query_bundled_database(self):
        path = self.store.path
        self.store.close()
        read_only = LegalGraphStore(path, read_only=True)
        try:
            self.assertEqual((7, 3, 3), read_only.counts())
            self.assertIn("actor.worker", read_only.match_entities("劳动者"))
        finally:
            read_only.close()
        # Avoid closing the same SQLite connection again in tearDown.
        self.store = LegalGraphStore(path, read_only=True)


if __name__ == "__main__":
    unittest.main()
