"""Extract provenance-backed legal hyperedges from law article chunks.

The language model identifies rule semantics only. Source metadata and stable IDs
are supplied by the application, and every quoted span is checked against the
input chunk before a rule can enter the knowledge graph.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Iterable, List, Mapping, Optional, Protocol, Sequence

from pydantic import Field, ValidationError

from legal_schema import (
    AuthorityLevel,
    DocumentType,
    EntityRef,
    EntityType,
    LegalEntity,
    LegalKnowledgeGraph,
    LegalRule,
    LimitationPeriod,
    RuleElement,
    SourceEvidence,
    StrictModel,
)


class SupportsInvoke(Protocol):
    def invoke(self, messages: Sequence[Any]) -> Any: ...


class DocumentLike(Protocol):
    page_content: str
    metadata: Mapping[str, Any]


class ExtractionEntity(StrictModel):
    canonical_name: str = Field(min_length=1)
    entity_type: EntityType
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class ExtractionParticipant(StrictModel):
    canonical_name: str = Field(min_length=1)
    role: Optional[str] = None


class ExtractionElement(StrictModel):
    text: str = Field(min_length=1)
    entity_names: List[str] = Field(default_factory=list)


class ExtractionLimitationPeriod(StrictModel):
    iso_8601_duration: str = Field(min_length=2)
    starts_when: str = Field(min_length=1)
    interruption_rules: List[str] = Field(default_factory=list)
    suspension_rules: List[str] = Field(default_factory=list)


class ExtractionRule(StrictModel):
    name: str = Field(min_length=1)
    subjects: List[ExtractionParticipant] = Field(min_length=1)
    action: str = Field(min_length=1)
    objects: List[ExtractionParticipant] = Field(default_factory=list)
    conditions: List[ExtractionElement] = Field(default_factory=list)
    exceptions: List[ExtractionElement] = Field(default_factory=list)
    procedures: List[ExtractionElement] = Field(default_factory=list)
    consequences: List[ExtractionElement] = Field(min_length=1)
    limitation_period: Optional[ExtractionLimitationPeriod] = None
    evidence_quote: str = Field(min_length=8)
    tags: List[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ChunkExtraction(StrictModel):
    entities: List[ExtractionEntity]
    rules: List[ExtractionRule]


class GraphExtractionError(RuntimeError):
    """Raised when a chunk cannot be converted into a valid graph."""


SYSTEM_PROMPT = """你是中国劳动法知识工程师。请只提取输入原文明确表达的法律规则。

要求：
1. 不补充常识，不猜测未出现的条件、例外、程序或后果。
2. 每条规则必须有主体、行为、法律后果和 evidence_quote。
3. evidence_quote 必须是输入原文中连续出现的逐字引文，不得改写。
4. 规则使用到的每个实体都必须同时出现在 entities 中，名称完全一致。
5. 时效使用 ISO-8601 duration，例如一年为 P1Y、三十日为 P30D。
6. 没有明确规则时返回 {"entities": [], "rules": []}。
7. 仅输出一个 JSON 对象，不输出 Markdown 或解释。

JSON 结构：
{
  "entities": [{
    "canonical_name": "实体规范名称",
    "entity_type": "person_role|organization_role|legal_instrument|legal_concept|action|procedure|evidence|remedy|jurisdiction",
    "aliases": [],
    "description": null
  }],
  "rules": [{
    "name": "规则名称",
    "subjects": [{"canonical_name": "主体", "role": "角色或null"}],
    "action": "行为",
    "objects": [{"canonical_name": "对象", "role": "角色或null"}],
    "conditions": [{"text": "条件", "entity_names": []}],
    "exceptions": [{"text": "例外", "entity_names": []}],
    "procedures": [{"text": "程序", "entity_names": []}],
    "consequences": [{"text": "后果", "entity_names": []}],
    "limitation_period": null,
    "evidence_quote": "原文中的连续逐字引文",
    "tags": [],
    "confidence": 0.0
  }]
}"""


class GraphExtractor:
    def __init__(self, llm: SupportsInvoke, max_retries: int = 2):
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.llm = llm
        self.max_retries = max_retries

    def extract_document(self, document: DocumentLike) -> LegalKnowledgeGraph:
        """Extract and validate one `LegalRegexSplitter` output document."""

        context = _source_context(document)
        last_error: Optional[Exception] = None
        correction = ""

        for _attempt in range(self.max_retries + 1):
            prompt = _user_prompt(document, context, correction)
            try:
                response = self.llm.invoke(
                    [("system", SYSTEM_PROMPT), ("human", prompt)]
                )
                payload = _parse_json_object(_response_text(response))
                extraction = ChunkExtraction.model_validate(payload)
                return _materialize_graph(extraction, document, context)
            except (GraphExtractionError, ValidationError, ValueError, TypeError) as exc:
                last_error = exc
                correction = (
                    "\n上一次输出未通过校验，请修正后完整重试。"
                    f"校验错误：{str(exc)[:500]}"
                )

        raise GraphExtractionError(
            f"failed to extract chunk {context.chunk_id!r} after "
            f"{self.max_retries + 1} attempt(s): {last_error}"
        ) from last_error

    def extract_documents(self, documents: Sequence[DocumentLike]) -> LegalKnowledgeGraph:
        """Extract several chunks and merge their validated graphs."""

        return merge_graphs(self.extract_document(document) for document in documents)


def merge_graphs(graphs: Iterable[LegalKnowledgeGraph]) -> LegalKnowledgeGraph:
    """Merge validated per-chunk graphs and deduplicate stable entity IDs."""

    entities: dict[str, LegalEntity] = {}
    rules: dict[str, LegalRule] = {}
    for graph in graphs:
        for entity in graph.entities:
            existing = entities.get(entity.entity_id)
            if existing is None:
                entities[entity.entity_id] = entity
            elif existing.entity_type != entity.entity_type:
                raise GraphExtractionError(
                    f"entity type conflict for {entity.canonical_name!r}"
                )
            else:
                aliases = sorted(set(existing.aliases + entity.aliases))
                entities[entity.entity_id] = existing.model_copy(
                    update={"aliases": aliases}
                )
        for rule in graph.rules:
            if rule.rule_id in rules and rules[rule.rule_id] != rule:
                raise GraphExtractionError(f"rule ID collision: {rule.rule_id}")
            rules[rule.rule_id] = rule

    return LegalKnowledgeGraph(entities=list(entities.values()), rules=list(rules.values()))


class _SourceContext(StrictModel):
    chunk_id: str
    law_name: str
    article: str
    paragraph: Optional[str] = None
    source_path: Optional[str] = None
    jurisdiction: str = "全国"
    document_type: DocumentType
    authority_level: AuthorityLevel
    promulgated_on: Optional[date] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


def _source_context(document: DocumentLike) -> _SourceContext:
    text = document.page_content
    metadata = dict(document.metadata or {})
    law_match = re.search(r"《([^》]+)》", text)
    law_name = str(metadata.get("law_name") or (law_match.group(1) if law_match else ""))
    article_match = re.search(r"第[一二三四五六七八九十百千万零〇两\d]+条", text)
    article = str(metadata.get("article") or (article_match.group(0) if article_match else ""))
    if not law_name:
        raise GraphExtractionError("law_name is missing from metadata and chunk text")
    if not article:
        raise GraphExtractionError("article is missing from metadata and chunk text")

    source_path = metadata.get("source")
    chunk_id = str(metadata.get("chunk_id") or _stable_id("chunk", source_path or law_name, text))
    document_type, authority_level = _classify_source(law_name, metadata)
    return _SourceContext(
        chunk_id=chunk_id,
        law_name=law_name,
        article=article,
        paragraph=metadata.get("paragraph"),
        source_path=str(source_path) if source_path else None,
        jurisdiction=str(metadata.get("region") or "全国"),
        document_type=document_type,
        authority_level=authority_level,
        promulgated_on=metadata.get("promulgated_on"),
        effective_from=metadata.get("effective_from"),
        effective_to=metadata.get("effective_to"),
    )


def _classify_source(
    law_name: str, metadata: dict[str, Any]
) -> tuple[DocumentType, AuthorityLevel]:
    explicit_type = metadata.get("document_type")
    explicit_level = metadata.get("authority_level")
    if explicit_type and explicit_level:
        return DocumentType(explicit_type), AuthorityLevel(explicit_level)

    category = str(metadata.get("category") or "")
    if "司法解释" in law_name or "Judicial" in category:
        inferred = (DocumentType.JUDICIAL_INTERPRETATION, AuthorityLevel.JUDICIAL_INTERPRETATION)
    elif "Local" in category or metadata.get("region") not in (None, "", "全国"):
        inferred = (DocumentType.LOCAL_REGULATION, AuthorityLevel.LOCAL_REGULATION)
    elif "Administrative" in category or "条例" in law_name:
        inferred = (
            DocumentType.ADMINISTRATIVE_REGULATION,
            AuthorityLevel.ADMINISTRATIVE_REGULATION,
        )
    elif "Rules" in category or "办法" in law_name or "规定" in law_name:
        inferred = (DocumentType.DEPARTMENT_RULE, AuthorityLevel.DEPARTMENT_RULE)
    else:
        inferred = (DocumentType.LAW, AuthorityLevel.NATIONAL_LAW)

    return (
        DocumentType(explicit_type) if explicit_type else inferred[0],
        AuthorityLevel(explicit_level) if explicit_level else inferred[1],
    )


def _user_prompt(
    document: DocumentLike, context: _SourceContext, correction: str = ""
) -> str:
    return (
        f"法律名称：{context.law_name}\n"
        f"条款：{context.article}\n"
        f"地域：{context.jurisdiction}\n"
        "待抽取原文：\n"
        "<source>\n"
        f"{document.page_content}\n"
        "</source>"
        f"{correction}"
    )


def _materialize_graph(
    extraction: ChunkExtraction,
    document: DocumentLike,
    context: _SourceContext,
) -> LegalKnowledgeGraph:
    entities: list[LegalEntity] = []
    name_to_id: dict[str, str] = {}
    for extracted in extraction.entities:
        key = _normalize_name(extracted.canonical_name)
        if key in name_to_id:
            raise GraphExtractionError(
                f"duplicate canonical entity name: {extracted.canonical_name!r}"
            )
        entity_id = _stable_id("entity", extracted.entity_type.value, key)
        name_to_id[key] = entity_id
        entities.append(
            LegalEntity(
                entity_id=entity_id,
                canonical_name=extracted.canonical_name,
                entity_type=extracted.entity_type,
                aliases=extracted.aliases,
                description=extracted.description,
            )
        )

    rules: list[LegalRule] = []
    for index, extracted in enumerate(extraction.rules):
        if not _quote_exists(extracted.evidence_quote, document.page_content):
            raise GraphExtractionError(
                f"evidence_quote for rule {extracted.name!r} is not in source chunk"
            )

        source_id = _stable_id(
            "source", context.chunk_id, context.article, extracted.evidence_quote
        )
        evidence = SourceEvidence(
            source_id=source_id,
            law_name=context.law_name,
            document_type=context.document_type,
            authority_level=context.authority_level,
            article=context.article,
            paragraph=context.paragraph,
            quote=extracted.evidence_quote,
            chunk_id=context.chunk_id,
            source_path=context.source_path,
            jurisdiction=context.jurisdiction,
            promulgated_on=context.promulgated_on,
            effective_from=context.effective_from,
            effective_to=context.effective_to,
        )
        rule_id = _stable_id("rule", context.chunk_id, str(index), extracted.name)
        rules.append(
            LegalRule(
                rule_id=rule_id,
                name=extracted.name,
                subjects=[
                    EntityRef(entity_id=_entity_id(item.canonical_name, name_to_id), role=item.role)
                    for item in extracted.subjects
                ],
                action=extracted.action,
                objects=[
                    EntityRef(entity_id=_entity_id(item.canonical_name, name_to_id), role=item.role)
                    for item in extracted.objects
                ],
                conditions=_elements(extracted.conditions, name_to_id),
                exceptions=_elements(extracted.exceptions, name_to_id),
                procedures=_elements(extracted.procedures, name_to_id),
                consequences=_elements(extracted.consequences, name_to_id),
                limitation_period=(
                    LimitationPeriod.model_validate(extracted.limitation_period.model_dump())
                    if extracted.limitation_period
                    else None
                ),
                jurisdictions=[context.jurisdiction],
                effective_from=context.effective_from,
                effective_to=context.effective_to,
                sources=[evidence],
                tags=extracted.tags,
                extraction_confidence=extracted.confidence,
            )
        )

    return LegalKnowledgeGraph(entities=entities, rules=rules)


def _elements(
    elements: Sequence[ExtractionElement], name_to_id: dict[str, str]
) -> list[RuleElement]:
    return [
        RuleElement(
            text=element.text,
            entity_refs=[_entity_id(name, name_to_id) for name in element.entity_names],
        )
        for element in elements
    ]


def _entity_id(name: str, name_to_id: dict[str, str]) -> str:
    key = _normalize_name(name)
    try:
        return name_to_id[key]
    except KeyError as exc:
        raise GraphExtractionError(
            f"rule references entity not declared in entities: {name!r}"
        ) from exc


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _quote_exists(quote: str, source: str) -> bool:
    normalize = lambda value: re.sub(r"\s+", "", value)
    return normalize(quote) in normalize(source)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}.{digest}"


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(block["text"])
        if texts:
            return "\n".join(texts)
    raise TypeError("LLM response does not contain textual content")


def _parse_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise GraphExtractionError("LLM response does not contain a valid JSON object")
