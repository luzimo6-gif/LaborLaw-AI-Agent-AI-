import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from graph_store import LegalGraphStore
from hybrid_retriever import HybridLegalRetriever
from legal_schema import LegalKnowledgeGraph


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "legal_graph_golden.json"


class FakeVectorStore:
    def __init__(self, documents):
        self.documents = documents

    def similarity_search_with_score(self, query, k=4, **kwargs):
        documents = self.documents[:k]
        return documents, [0.95 - index * 0.05 for index in range(len(documents))]


def vector_document(with_chunk=True):
    metadata = {
        "law_name": "中华人民共和国劳动合同法",
        "article": "第四十条",
        "region": "全国",
    }
    if with_chunk:
        metadata["chunk_id"] = "golden:lcl:40"
    return SimpleNamespace(
        page_content=(
            "《中华人民共和国劳动合同法》\n第四十条 "
            "劳动者不能胜任工作，经过培训或者调整工作岗位，仍不能胜任工作的。"
        ),
        metadata=metadata,
    )


class HybridRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        graph = LegalKnowledgeGraph.model_validate_json(
            FIXTURE_PATH.read_text(encoding="utf-8")
        )
        self.store = LegalGraphStore(str(Path(self.temporary.name) / "graph.db"))
        self.store.replace_graph(graph)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_vector_seed_and_graph_evidence_are_fused(self):
        document = vector_document()
        retriever = HybridLegalRetriever(FakeVectorStore([document]), self.store)
        result = retriever.retrieve("员工不能胜任工作，公司能否直接解除？", k_rules=3)

        self.assertTrue(result.rules)
        self.assertEqual("lcl.article40.incompetence", result.rules[0].rule.rule_id)
        self.assertIn("vector_chunk", result.rules[0].matched_by)
        self.assertEqual([document], result.rules[0].vector_documents)
        self.assertIn("actor.worker", result.matched_entity_ids)

    def test_citation_fallback_works_without_chunk_id(self):
        retriever = HybridLegalRetriever(
            FakeVectorStore([vector_document(with_chunk=False)]), self.store
        )
        result = retriever.retrieve("不能胜任工作解除", k_rules=1)

        self.assertEqual("lcl.article40.incompetence", result.rules[0].rule.rule_id)
        self.assertIn("vector_chunk", result.rules[0].matched_by)

    def test_unmapped_vector_document_is_preserved_as_fallback(self):
        unmapped = SimpleNamespace(
            page_content="普通参考材料，没有图谱对应规则。",
            metadata={"chunk_id": "unknown:chunk"},
        )
        retriever = HybridLegalRetriever(FakeVectorStore([unmapped]), self.store)
        result = retriever.retrieve("完全无关的问题", k_rules=2)

        self.assertIn(unmapped, result.fallback_documents)


if __name__ == "__main__":
    unittest.main()
