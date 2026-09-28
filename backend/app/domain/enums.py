"""Domain vocabulary. These enums are the single source of truth for the whole system:
the DB constrains to them, Pydantic validates against them, and the LLM's output is
rejected when it invents a value outside them (§2.5 structured-output guardrail).
"""

from enum import StrEnum


class Category(StrEnum):
    WATER = "water"
    ELECTRICITY = "electricity"
    SANITATION = "sanitation"
    ROADS = "roads"
    STREETLIGHTS = "streetlights"
    OTHER = "other"


class Priority(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Status(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class TriagedBy(StrEnum):
    LLM_GROQ = "llm:groq"
    LLM_OLLAMA = "llm:ollama"
    RULES = "rules"
    RULES_FALLBACK = "rules:fallback"
    SIMULATED = "simulated"
