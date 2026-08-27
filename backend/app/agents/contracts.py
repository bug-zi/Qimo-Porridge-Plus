from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    source: str
    locator: str = ""
    claim: str


class CourseTopic(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    priority: Literal["high", "medium", "low"]
    exam_value: int = Field(ge=1, le=100)
    prerequisites: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CourseProfile(BaseModel):
    course_name: str
    assessment_summary: str
    question_types: list[str]
    topics: list[CourseTopic]
    uncertainties: list[str] = Field(default_factory=list)


class PlanBlock(BaseModel):
    minutes: int = Field(ge=5, le=720)
    topic_id: str
    topic: str
    source: str
    action: str
    output: str
    completion: str


class PlanDay(BaseModel):
    day: int = Field(ge=1, le=30)
    title: str
    goal: str
    rationale: str
    blocks: list[PlanBlock]
    must_know: list[str]
    test: str
    review_rule: str


class ReviewPlanSpec(BaseModel):
    goal_summary: str
    scope_summary: str
    priority_notes: list[str]
    days: list[PlanDay]
    final_success_criteria: list[str]
    adjustment_rules: list[str]


class CoursePromptSpec(BaseModel):
    role_goal: str
    evidence_rules: list[str]
    teaching_rules: list[str]
    question_rules: list[str]
    adjustment_rules: list[str]
    output_rules: list[str]
    user_extension: str = ""


class ReviewReport(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    source_coverage: float = Field(ge=0, le=1)
    summary: str


class AgentToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class GlossaryCandidate(BaseModel):
    """Glossary Scanner Agent 的输出：候选术语条目。"""

    term: str = Field(min_length=1, max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    importance: Literal["core", "extended"]
    knowledge_point_id: str = ""
    module_id: str = ""
    rationale: str = ""


class GlossaryTermSpec(BaseModel):
    """Glossary Curator Agent 的输出：完整词条。"""

    term: str = Field(min_length=1, max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    one_liner: str = Field(min_length=1, max_length=120)
    article: str = Field(min_length=20, max_length=1200)
    exam_tips: list[str] = Field(default_factory=list, max_length=6)
    pitfalls: list[str] = Field(default_factory=list, max_length=6)
    knowledge_point_id: str = ""
    related_knowledge_point_ids: list[str] = Field(default_factory=list, max_length=5)
    module_id: str = ""
    importance: Literal["core", "extended"] = "core"
