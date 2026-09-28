"""Shared contracts. External text is data, never executable instructions."""

from dataclasses import asdict, dataclass, field
from typing import Any

CATEGORIES = (
    "Biology",
    "Chemistry",
    "Earth and Space Science",
    "Energy",
    "Mathematics",
    "Physics",
    "General Science",
)


@dataclass
class Question:
    id: str
    text: str
    answer: str
    category: str
    format: str = "short_answer"
    choices: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    pool: str = "regional"
    source: str = "Unknown"
    page: int = 1
    role: str = "tossup"
    pair_id: str | None = None
    revision: int = 1
    source_url: str = ""
    checksum: str = ""
    document_checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Question":
        return cls(**value)


@dataclass
class Judgment:
    verdict: str  # correct, incorrect, ungraded
    explanation: str = ""
    method: str = "local"


def default_settings(mode: str = "shared") -> dict[str, Any]:
    return {
        "count": 20,
        "categories": list(CATEGORIES),
        "pool": "all",
        "source": "all",
        "format": "all",
        "role": "tossup",
        "buzz_seconds": 30,
        "answer_seconds": 15,
    }


def validate_settings(value: dict[str, Any]) -> None:
    if not isinstance(value.get("count"), int) or not 1 <= value["count"] <= 100:
        raise ValueError("Question count must be between 1 and 100.")
    categories = value.get("categories", [])
    if not categories or any(item not in CATEGORIES for item in categories):
        raise ValueError("Select at least one valid category.")
    if value.get("pool") not in ("regional", "invitational", "all"):
        raise ValueError("Pool must be regional, invitational, or all.")
    if value.get("format") not in ("short_answer", "multiple_choice", "all"):
        raise ValueError("Invalid answer format.")
    if value.get("role") not in ("tossup", "bonus", "all"):
        raise ValueError("Invalid question role.")
    for key in ("buzz_seconds", "answer_seconds"):
        if not isinstance(value.get(key), int) or not 5 <= value[key] <= 120:
            raise ValueError("Timers must be between 5 and 120 seconds.")
