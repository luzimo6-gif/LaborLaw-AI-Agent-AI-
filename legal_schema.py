"""Canonical schema for the labor-law knowledge graph.

The graph keeps legal conclusions inseparable from their scope and evidence.
`LegalRule` is the n-ary hyperedge: it connects actors, actions, conditions,
exceptions, procedures, consequences, time, jurisdiction, and source text.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Shared strict settings for persisted graph records."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EntityType(str, Enum):
    PERSON_ROLE = "person_role"
    ORGANIZATION_ROLE = "organization_role"
    LEGAL_INSTRUMENT = "legal_instrument"
    LEGAL_CONCEPT = "legal_concept"
    ACTION = "action"
    PROCEDURE = "procedure"
    EVIDENCE = "evidence"
    REMEDY = "remedy"
    JURISDICTION = "jurisdiction"


class DocumentType(str, Enum):
    LAW = "law"
    ADMINISTRATIVE_REGULATION = "administrative_regulation"
    JUDICIAL_INTERPRETATION = "judicial_interpretation"
    LOCAL_REGULATION = "local_regulation"
    DEPARTMENT_RULE = "department_rule"
    GUIDING_CASE = "guiding_case"
    OTHER = "other"


class AuthorityLevel(str, Enum):
    NATIONAL_LAW = "national_law"
    ADMINISTRATIVE_REGULATION = "administrative_regulation"
    JUDICIAL_INTERPRETATION = "judicial_interpretation"
    LOCAL_REGULATION = "local_regulation"
    DEPARTMENT_RULE = "department_rule"
    CASE = "case"
    OTHER = "other"


class LegalEntity(StrictModel):
    entity_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    entity_type: EntityType
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class EntityRef(StrictModel):
    entity_id: str = Field(min_length=1)
    role: Optional[str] = None


class RuleElement(StrictModel):
    """One condition, exception, procedure, or legal consequence."""

    text: str = Field(min_length=1)
    entity_refs: List[str] = Field(default_factory=list)


class LimitationPeriod(StrictModel):
    iso_8601_duration: str = Field(
        min_length=2,
        description="ISO-8601 duration, for example P1Y or P30D.",
    )
    starts_when: str = Field(min_length=1)
    interruption_rules: List[str] = Field(default_factory=list)
    suspension_rules: List[str] = Field(default_factory=list)


class SourceEvidence(StrictModel):
    """Verbatim provenance supporting a rule; never optional."""

    source_id: str = Field(min_length=1)
    law_name: str = Field(min_length=1)
    document_type: DocumentType
    authority_level: AuthorityLevel
    article: str = Field(min_length=1)
    paragraph: Optional[str] = None
    quote: str = Field(min_length=8)
    chunk_id: str = Field(min_length=1)
    source_path: Optional[str] = None
    jurisdiction: str = Field(default="全国", min_length=1)
    promulgated_on: Optional[date] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "SourceEvidence":
        if self.effective_from and self.effective_to:
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to cannot be earlier than effective_from")
        return self


class LegalRule(StrictModel):
    """A provenance-backed legal rule represented as a graph hyperedge."""

    rule_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    subjects: List[EntityRef] = Field(min_length=1)
    action: str = Field(min_length=1)
    objects: List[EntityRef] = Field(default_factory=list)
    conditions: List[RuleElement] = Field(default_factory=list)
    exceptions: List[RuleElement] = Field(default_factory=list)
    procedures: List[RuleElement] = Field(default_factory=list)
    consequences: List[RuleElement] = Field(min_length=1)
    limitation_period: Optional[LimitationPeriod] = None
    jurisdictions: List[str] = Field(default_factory=lambda: ["全国"], min_length=1)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    sources: List[SourceEvidence] = Field(min_length=1)
    tags: List[str] = Field(default_factory=list)
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_date_range(self) -> "LegalRule":
        if self.effective_from and self.effective_to:
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to cannot be earlier than effective_from")
        return self

    def referenced_entity_ids(self) -> set[str]:
        references = {ref.entity_id for ref in self.subjects + self.objects}
        for element in (
            self.conditions + self.exceptions + self.procedures + self.consequences
        ):
            references.update(element.entity_refs)
        return references


class LegalKnowledgeGraph(StrictModel):
    schema_version: str = Field(default="1.0.0", min_length=1)
    entities: List[LegalEntity]
    rules: List[LegalRule]

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> "LegalKnowledgeGraph":
        entity_ids = [entity.entity_id for entity in self.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity_id values must be unique")

        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule_id values must be unique")

        known_entities = set(entity_ids)
        for rule in self.rules:
            missing = rule.referenced_entity_ids() - known_entities
            if missing:
                raise ValueError(
                    f"rule {rule.rule_id!r} references unknown entities: "
                    f"{sorted(missing)}"
                )
        return self
