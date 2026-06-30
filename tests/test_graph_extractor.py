import json
import unittest
from types import SimpleNamespace

from graph_extractor import GraphExtractionError, GraphExtractor


ARTICLE_TEXT = (
    "《中华人民共和国劳动合同法》\n"
    "第四十条 有下列情形之一的，用人单位提前三十日以书面形式通知劳动者本人"
    "或者额外支付劳动者一个月工资后，可以解除劳动合同：（二）劳动者不能胜任工作，"
    "经过培训或者调整工作岗位，仍不能胜任工作的；"
)


def valid_payload():
    quote = (
        "劳动者不能胜任工作，经过培训或者调整工作岗位，仍不能胜任工作的；"
    )
    return {
        "entities": [
            {
                "canonical_name": "用人单位",
                "entity_type": "organization_role",
                "aliases": ["单位"],
                "description": None,
            },
            {
                "canonical_name": "劳动者",
                "entity_type": "person_role",
                "aliases": ["员工"],
                "description": None,
            },
            {
                "canonical_name": "劳动合同",
                "entity_type": "legal_instrument",
                "aliases": [],
                "description": None,
            },
        ],
        "rules": [
            {
                "name": "不能胜任工作时解除劳动合同",
                "subjects": [{"canonical_name": "用人单位", "role": "解除方"}],
                "action": "解除劳动合同",
                "objects": [{"canonical_name": "劳动合同", "role": "解除对象"}],
                "conditions": [
                    {
                        "text": "劳动者经过培训或者调整工作岗位后仍不能胜任工作",
                        "entity_names": ["劳动者"],
                    }
                ],
                "exceptions": [],
                "procedures": [],
                "consequences": [
                    {
                        "text": "用人单位可以解除劳动合同",
                        "entity_names": ["用人单位", "劳动合同"],
                    }
                ],
                "limitation_period": None,
                "evidence_quote": quote,
                "tags": ["劳动合同解除"],
                "confidence": 0.98,
            }
        ],
    }


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        return SimpleNamespace(content=response)


def source_document(chunk_id="chunk:lcl:40"):
    return SimpleNamespace(
        page_content=ARTICLE_TEXT,
        metadata={
            "chunk_id": chunk_id,
            "law_name": "中华人民共和国劳动合同法",
            "source": "/data/中华人民共和国劳动合同法.docx",
            "category": "National Laws",
            "region": "全国",
            "promulgated_on": "2012-12-28",
            "effective_from": "2013-07-01",
        },
    )


class GraphExtractorTests(unittest.TestCase):
    def test_valid_extraction_uses_trusted_source_metadata(self):
        llm = FakeLLM([json.dumps(valid_payload(), ensure_ascii=False)])
        graph = GraphExtractor(llm, max_retries=0).extract_document(source_document())

        self.assertEqual(3, len(graph.entities))
        self.assertEqual(1, len(graph.rules))
        rule = graph.rules[0]
        self.assertEqual("全国", rule.jurisdictions[0])
        self.assertEqual("第四十条", rule.sources[0].article)
        self.assertEqual("chunk:lcl:40", rule.sources[0].chunk_id)
        self.assertEqual("national_law", rule.sources[0].authority_level.value)

    def test_non_verbatim_evidence_is_rejected(self):
        payload = valid_payload()
        payload["rules"][0]["evidence_quote"] = "原文中根本不存在的虚构法条内容"
        llm = FakeLLM([json.dumps(payload, ensure_ascii=False)])

        with self.assertRaisesRegex(GraphExtractionError, "not in source chunk"):
            GraphExtractor(llm, max_retries=0).extract_document(source_document())

    def test_undeclared_entity_reference_is_rejected(self):
        payload = valid_payload()
        payload["rules"][0]["conditions"][0]["entity_names"] = ["未知主体"]
        llm = FakeLLM([json.dumps(payload, ensure_ascii=False)])

        with self.assertRaisesRegex(GraphExtractionError, "not declared"):
            GraphExtractor(llm, max_retries=0).extract_document(source_document())

    def test_invalid_json_is_retried(self):
        llm = FakeLLM(
            ["这不是 JSON", json.dumps(valid_payload(), ensure_ascii=False)]
        )
        graph = GraphExtractor(llm, max_retries=1).extract_document(source_document())

        self.assertEqual(1, len(graph.rules))
        self.assertEqual(2, len(llm.calls))
        self.assertIn("上一次输出未通过校验", llm.calls[1][1][1])

    def test_multiple_chunks_merge_shared_entities(self):
        llm = FakeLLM(
            [
                json.dumps(valid_payload(), ensure_ascii=False),
                json.dumps(valid_payload(), ensure_ascii=False),
            ]
        )
        documents = [source_document("chunk:a"), source_document("chunk:b")]
        graph = GraphExtractor(llm, max_retries=0).extract_documents(documents)

        self.assertEqual(3, len(graph.entities))
        self.assertEqual(2, len(graph.rules))


if __name__ == "__main__":
    unittest.main()
