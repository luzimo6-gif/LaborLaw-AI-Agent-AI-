"""Checkpointed graph-building orchestration for `build_db.py`."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

from graph_extractor import DocumentLike, merge_graphs
from legal_schema import LegalKnowledgeGraph


class SupportsExtractDocument(Protocol):
    def extract_document(self, document: DocumentLike) -> LegalKnowledgeGraph: ...


ProgressCallback = Callable[[int, int, str], None]
StopCallback = Callable[[], bool]


@dataclass(frozen=True)
class GraphBuildReport:
    total: int
    extracted: int
    resumed: int
    failed: int
    interrupted: bool
    entity_count: int
    rule_count: int


def assign_chunk_ids(documents: Sequence[DocumentLike]) -> None:
    """Add deterministic IDs to splitter output without replacing existing IDs."""

    for document in documents:
        metadata = document.metadata
        if metadata.get("chunk_id"):
            continue
        source = str(metadata.get("source") or metadata.get("law_name") or "unknown")
        metadata["chunk_id"] = _digest("chunk", source, document.page_content)


def build_graph_checkpointed(
    documents: Sequence[DocumentLike],
    extractor: SupportsExtractDocument,
    checkpoint_path: str,
    output_path: str,
    failure_path: str,
    progress_callback: Optional[ProgressCallback] = None,
    should_stop: Optional[StopCallback] = None,
) -> GraphBuildReport:
    """Extract chunks with an append-only success journal and resumable output."""

    assign_chunk_ids(documents)
    checkpoint = _load_success_checkpoint(checkpoint_path)
    current_graphs: list[LegalKnowledgeGraph] = []
    extracted = resumed = failed = 0
    interrupted = False
    total = len(documents)

    for position, document in enumerate(documents, 1):
        if should_stop and should_stop():
            interrupted = True
            break

        chunk_id = str(document.metadata["chunk_id"])
        fingerprint = _chunk_fingerprint(document)
        cached = checkpoint.get(chunk_id)
        if cached and cached.get("fingerprint") == fingerprint:
            try:
                graph = LegalKnowledgeGraph.model_validate(cached["graph"])
                current_graphs.append(graph)
                resumed += 1
                _notify(progress_callback, position, total, "resumed")
                continue
            except (KeyError, TypeError, ValueError):
                pass

        try:
            graph = extractor.extract_document(document)
            record = {
                "status": "success",
                "chunk_id": chunk_id,
                "fingerprint": fingerprint,
                "written_at": _utc_now(),
                "graph": graph.model_dump(mode="json"),
            }
            _append_jsonl(checkpoint_path, record)
            checkpoint[chunk_id] = record
            current_graphs.append(graph)
            extracted += 1
            _notify(progress_callback, position, total, "extracted")
        except Exception as exc:  # isolate a bad chunk without losing prior work
            failed += 1
            _append_jsonl(
                failure_path,
                {
                    "status": "failed",
                    "chunk_id": chunk_id,
                    "fingerprint": fingerprint,
                    "written_at": _utc_now(),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:2000],
                    "source": document.metadata.get("source"),
                },
            )
            _notify(progress_callback, position, total, "failed")

    merged = merge_graphs(current_graphs)
    _atomic_write_json(output_path, merged.model_dump(mode="json"))
    return GraphBuildReport(
        total=total,
        extracted=extracted,
        resumed=resumed,
        failed=failed,
        interrupted=interrupted,
        entity_count=len(merged.entities),
        rule_count=len(merged.rules),
    )


def _load_success_checkpoint(path: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    checkpoint = Path(path)
    if not checkpoint.exists():
        return records
    with checkpoint.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                if record.get("status") == "success" and record.get("chunk_id"):
                    records[str(record["chunk_id"])] = record
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue
    return records


def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write_json(path: str, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _chunk_fingerprint(document: DocumentLike) -> str:
    metadata = document.metadata
    relevant_metadata = {
        key: metadata.get(key)
        for key in (
            "law_name",
            "article",
            "paragraph",
            "region",
            "category",
            "promulgated_on",
            "effective_from",
            "effective_to",
        )
    }
    return _digest(
        "fingerprint",
        document.page_content,
        json.dumps(relevant_metadata, ensure_ascii=False, sort_keys=True, default=str),
    )


def _digest(prefix: str, *parts: str) -> str:
    value = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}.{hashlib.sha256(value).hexdigest()[:20]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _notify(
    callback: Optional[ProgressCallback], current: int, total: int, status: str
) -> None:
    if callback:
        callback(current, total, status)
