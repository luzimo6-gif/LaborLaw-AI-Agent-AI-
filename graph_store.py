"""SQLite persistence and traversal for the local labor-law graph."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import deque
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Sequence

from legal_schema import LegalKnowledgeGraph, LegalRule


class LegalGraphStore:
    def __init__(self, path: str, read_only: bool = False):
        self.path = path
        if not read_only:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        target = f"file:{Path(path).resolve()}?mode=ro" if read_only else path
        self._connection = sqlite3.connect(
            target, check_same_thread=False, uri=read_only
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if not read_only:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "LegalGraphStore":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    aliases_json TEXT NOT NULL,
                    description TEXT
                );
                CREATE TABLE IF NOT EXISTS entity_terms (
                    entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                    term TEXT NOT NULL,
                    PRIMARY KEY (entity_id, term)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_terms_term ON entity_terms(term);

                CREATE TABLE IF NOT EXISTS rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    jurisdictions_json TEXT NOT NULL,
                    effective_from TEXT,
                    effective_to TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rule_entities (
                    rule_id TEXT NOT NULL REFERENCES rules(rule_id) ON DELETE CASCADE,
                    entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                    PRIMARY KEY (rule_id, entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_rule_entities_entity ON rule_entities(entity_id);

                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL REFERENCES rules(rule_id) ON DELETE CASCADE,
                    law_name TEXT NOT NULL,
                    article TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    source_path TEXT,
                    jurisdiction TEXT NOT NULL,
                    PRIMARY KEY (source_id, rule_id)
                );
                CREATE INDEX IF NOT EXISTS idx_sources_chunk ON sources(chunk_id);
                CREATE INDEX IF NOT EXISTS idx_sources_citation ON sources(law_name, article);
                """
            )

    def replace_graph(self, graph: LegalKnowledgeGraph) -> None:
        """Atomically replace all graph rows with one validated snapshot."""

        with self._lock, self._connection:
            self._connection.execute("DELETE FROM sources")
            self._connection.execute("DELETE FROM rule_entities")
            self._connection.execute("DELETE FROM rules")
            self._connection.execute("DELETE FROM entity_terms")
            self._connection.execute("DELETE FROM entities")

            for entity in graph.entities:
                self._connection.execute(
                    "INSERT INTO entities VALUES (?, ?, ?, ?, ?)",
                    (
                        entity.entity_id,
                        entity.canonical_name,
                        entity.entity_type.value,
                        json.dumps(entity.aliases, ensure_ascii=False),
                        entity.description,
                    ),
                )
                terms = {_normalize(entity.canonical_name)}
                terms.update(_normalize(alias) for alias in entity.aliases)
                self._connection.executemany(
                    "INSERT INTO entity_terms(entity_id, term) VALUES (?, ?)",
                    [(entity.entity_id, term) for term in terms if term],
                )

            for rule in graph.rules:
                self._connection.execute(
                    "INSERT INTO rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rule.rule_id,
                        rule.name,
                        rule.action,
                        _rule_search_text(rule),
                        json.dumps(rule.jurisdictions, ensure_ascii=False),
                        rule.effective_from.isoformat() if rule.effective_from else None,
                        rule.effective_to.isoformat() if rule.effective_to else None,
                        rule.model_dump_json(),
                    ),
                )
                self._connection.executemany(
                    "INSERT INTO rule_entities(rule_id, entity_id) VALUES (?, ?)",
                    [(rule.rule_id, entity_id) for entity_id in rule.referenced_entity_ids()],
                )
                self._connection.executemany(
                    """INSERT INTO sources(
                        source_id, rule_id, law_name, article, quote,
                        chunk_id, source_path, jurisdiction
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            source.source_id,
                            rule.rule_id,
                            source.law_name,
                            source.article,
                            source.quote,
                            source.chunk_id,
                            source.source_path,
                            source.jurisdiction,
                        )
                        for source in rule.sources
                    ],
                )

    def counts(self) -> tuple[int, int, int]:
        with self._lock:
            entities = self._connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            rules = self._connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
            sources = self._connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        return int(entities), int(rules), int(sources)

    def match_entities(self, query: str, limit: int = 20) -> list[str]:
        normalized = _normalize(query)
        if not normalized:
            return []
        with self._lock:
            rows = self._connection.execute(
                """SELECT entity_id, MAX(LENGTH(term)) AS term_length
                   FROM entity_terms
                   WHERE INSTR(?, term) > 0
                   GROUP BY entity_id
                   ORDER BY term_length DESC
                   LIMIT ?""",
                (normalized, limit),
            ).fetchall()
        return [str(row["entity_id"]) for row in rows]

    def rule_ids_for_entities(self, entity_ids: Sequence[str]) -> list[str]:
        return self._select_ids("rule_entities", "entity_id", entity_ids)

    def rule_ids_for_chunks(self, chunk_ids: Sequence[str]) -> list[str]:
        return self._select_ids("sources", "chunk_id", chunk_ids)

    def rule_ids_for_citations(
        self, citations: Sequence[tuple[str, str]]
    ) -> list[str]:
        if not citations:
            return []
        found: list[str] = []
        with self._lock:
            for law_name, article in citations:
                rows = self._connection.execute(
                    "SELECT DISTINCT rule_id FROM sources WHERE law_name = ? AND article = ?",
                    (law_name, article),
                ).fetchall()
                found.extend(str(row["rule_id"]) for row in rows)
        return list(dict.fromkeys(found))

    def lexical_rule_scores(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        query_terms = _character_ngrams(_normalize(query))
        if not query_terms:
            return []
        with self._lock:
            rows = self._connection.execute(
                "SELECT rule_id, search_text FROM rules"
            ).fetchall()
        scored = []
        for row in rows:
            candidate_terms = _character_ngrams(str(row["search_text"]))
            overlap = len(query_terms & candidate_terms)
            if overlap:
                score = overlap / max(1, len(query_terms))
                scored.append((str(row["rule_id"]), score))
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]

    def expand_rules(
        self, seed_rule_ids: Sequence[str], depth: int = 1, limit: int = 50
    ) -> dict[str, tuple[int, tuple[str, ...]]]:
        """Return neighboring rules connected through shared entities."""

        if depth < 0:
            raise ValueError("depth must be non-negative")
        discovered: dict[str, tuple[int, tuple[str, ...]]] = {
            rule_id: (0, ()) for rule_id in dict.fromkeys(seed_rule_ids)
        }
        queue = deque((rule_id, 0) for rule_id in discovered)
        with self._lock:
            while queue and len(discovered) < limit:
                current, current_depth = queue.popleft()
                if current_depth >= depth:
                    continue
                rows = self._connection.execute(
                    """SELECT DISTINCT neighbor.rule_id, current.entity_id
                       FROM rule_entities AS current
                       JOIN rule_entities AS neighbor
                         ON neighbor.entity_id = current.entity_id
                       WHERE current.rule_id = ? AND neighbor.rule_id != ?""",
                    (current, current),
                ).fetchall()
                for row in rows:
                    rule_id = str(row["rule_id"])
                    entity_id = str(row["entity_id"])
                    if rule_id not in discovered:
                        discovered[rule_id] = (current_depth + 1, (entity_id,))
                        queue.append((rule_id, current_depth + 1))
                    elif discovered[rule_id][0] == current_depth + 1:
                        old = discovered[rule_id][1]
                        discovered[rule_id] = (
                            current_depth + 1,
                            tuple(dict.fromkeys(old + (entity_id,))),
                        )
                    if len(discovered) >= limit:
                        break
        return discovered

    def get_rules(
        self,
        rule_ids: Sequence[str],
        jurisdiction: Optional[str] = None,
        as_of: Optional[date] = None,
    ) -> list[LegalRule]:
        if not rule_ids:
            return []
        placeholders = ",".join("?" for _ in rule_ids)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT rule_id, payload_json FROM rules WHERE rule_id IN ({placeholders})",
                tuple(rule_ids),
            ).fetchall()
        by_id = {
            str(row["rule_id"]): LegalRule.model_validate_json(row["payload_json"])
            for row in rows
        }
        result = []
        for rule_id in rule_ids:
            rule = by_id.get(rule_id)
            if rule and _rule_is_applicable(rule, jurisdiction, as_of):
                result.append(rule)
        return result

    def entity_names(self, entity_ids: Iterable[str]) -> dict[str, str]:
        ids = list(dict.fromkeys(entity_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT entity_id, canonical_name FROM entities WHERE entity_id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        return {str(row["entity_id"]): str(row["canonical_name"]) for row in rows}

    def _select_ids(self, table: str, column: str, values: Sequence[str]) -> list[str]:
        if not values:
            return []
        if (table, column) not in {("rule_entities", "entity_id"), ("sources", "chunk_id")}:
            raise ValueError("unsupported lookup")
        placeholders = ",".join("?" for _ in values)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT DISTINCT rule_id FROM {table} WHERE {column} IN ({placeholders})",
                tuple(values),
            ).fetchall()
        return [str(row["rule_id"]) for row in rows]


def _normalize(value: str) -> str:
    return "".join(value.casefold().split())


def _character_ngrams(value: str) -> set[str]:
    if not value:
        return set()
    if len(value) == 1:
        return {value}
    return {value[index : index + 2] for index in range(len(value) - 1)}


def _rule_search_text(rule: LegalRule) -> str:
    values = [rule.name, rule.action, *rule.tags]
    for element in rule.conditions + rule.exceptions + rule.procedures + rule.consequences:
        values.append(element.text)
    for source in rule.sources:
        values.extend((source.law_name, source.article, source.quote))
    return _normalize(" ".join(values))


def _rule_is_applicable(
    rule: LegalRule, jurisdiction: Optional[str], as_of: Optional[date]
) -> bool:
    if jurisdiction and "全国" not in rule.jurisdictions and jurisdiction not in rule.jurisdictions:
        return False
    if as_of:
        if rule.effective_from and as_of < rule.effective_from:
            return False
        if rule.effective_to and as_of > rule.effective_to:
            return False
    return True
