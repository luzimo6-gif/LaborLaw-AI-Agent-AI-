import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from graph_build import assign_chunk_ids, build_graph_checkpointed
from legal_schema import LegalKnowledgeGraph


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "legal_graph_golden.json"


class StubExtractor:
    def __init__(self, graph, error=None):
        self.graph = graph
        self.error = error
        self.calls = 0

    def extract_document(self, document):
        self.calls += 1
        if self.error:
            raise self.error
        return self.graph


def document():
    return SimpleNamespace(
        page_content="《测试劳动法》\n第一条 测试规则正文。",
        metadata={"source": "/data/测试劳动法.docx", "region": "全国"},
    )


class GraphBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = LegalKnowledgeGraph.model_validate_json(
            FIXTURE_PATH.read_text(encoding="utf-8")
        )

    def test_assign_chunk_ids_is_stable(self):
        first = document()
        second = document()
        assign_chunk_ids([first, second])

        self.assertEqual(first.metadata["chunk_id"], second.metadata["chunk_id"])
        original = first.metadata["chunk_id"]
        assign_chunk_ids([first])
        self.assertEqual(original, first.metadata["chunk_id"])

    def test_success_is_checkpointed_and_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = str(Path(directory) / "graph_chunks.jsonl")
            output = str(Path(directory) / "legal_graph.json")
            failures = str(Path(directory) / "graph_failures.jsonl")
            extractor = StubExtractor(self.graph)

            first = build_graph_checkpointed(
                [document()], extractor, checkpoint, output, failures
            )
            second = build_graph_checkpointed(
                [document()], extractor, checkpoint, output, failures
            )

            self.assertEqual(1, first.extracted)
            self.assertEqual(1, second.resumed)
            self.assertEqual(1, extractor.calls)
            persisted = LegalKnowledgeGraph.model_validate_json(
                Path(output).read_text(encoding="utf-8")
            )
            self.assertEqual(3, len(persisted.rules))
            self.assertEqual(1, len(Path(checkpoint).read_text().splitlines()))

    def test_failure_is_recorded_without_corrupting_output(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [str(Path(directory) / name) for name in (
                "checkpoint.jsonl", "graph.json", "failures.jsonl"
            )]
            report = build_graph_checkpointed(
                [document()], StubExtractor(self.graph, RuntimeError("API failed")), *paths
            )

            self.assertEqual(1, report.failed)
            self.assertEqual(0, report.rule_count)
            failure = json.loads(Path(paths[2]).read_text(encoding="utf-8"))
            self.assertEqual("RuntimeError", failure["error_type"])
            persisted = LegalKnowledgeGraph.model_validate_json(
                Path(paths[1]).read_text(encoding="utf-8")
            )
            self.assertEqual([], persisted.rules)

    def test_changed_chunk_is_extracted_again(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = str(Path(directory) / "graph_chunks.jsonl")
            output = str(Path(directory) / "legal_graph.json")
            failures = str(Path(directory) / "graph_failures.jsonl")
            extractor = StubExtractor(self.graph)
            original = document()
            assign_chunk_ids([original])

            build_graph_checkpointed(
                [original], extractor, checkpoint, output, failures
            )
            changed = document()
            changed.metadata["chunk_id"] = original.metadata["chunk_id"]
            changed.page_content += "修订内容"
            report = build_graph_checkpointed(
                [changed], extractor, checkpoint, output, failures
            )

            self.assertEqual(2, extractor.calls)
            self.assertEqual(1, report.extracted)
            self.assertEqual(2, len(Path(checkpoint).read_text().splitlines()))


if __name__ == "__main__":
    unittest.main()
