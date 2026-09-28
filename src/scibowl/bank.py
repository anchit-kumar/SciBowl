"""Offline, review-first question-bank parsing helpers.

The parser intentionally produces staging data rather than writing to SQLite.  PDF
layouts vary enough that a reviewer must mark each extracted question as reviewed
before it can enter the playable bank.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSEOF

from .models import CATEGORIES, Question

_ROLES = re.compile(r"(?im)^\s*(TOSS[\s-]*UP|BONUS)\s*:?[ \t]*$")
_ANSWER = re.compile(r"(?im)^\s*(?:ANSWER|ANS\.?)(?:\s*[:\-])\s*(.+?)\s*$")
_CHOICE = re.compile(r"(?im)^\s*\(?([A-EWXYZ])\)?[\.)\:]\s+(.+?)\s*$")
_HEADER = re.compile(
    r"(?im)^[ \t]*(?P<number>\d+)\)[ \t]*(?P<category>biology|chemistry|earth(?:[ \t]*(?:and|&)[ \t]*space)?(?:[ \t]+science)?|energy|math(?:ematics)?|physics|general[ \t]+science)[ \t]*(?:[-–—�][ \t]*)?(?P<format>multiple[ \t]*(?:choice|cho)|short[ \t]*(?:answer|ans))\b(?P<prompt>.*)$"
)
_CATEGORIES = {category.casefold(): category for category in CATEGORIES}
_CATEGORY_ALIASES = {
    "math": "Mathematics",
    "mathematics": "Mathematics",
    "earth": "Earth and Space Science",
    "earth science": "Earth and Space Science",
    "earth and space": "Earth and Space Science",
    "earth & space": "Earth and Space Science",
    "earth and space science": "Earth and Space Science",
}
_FORMAT = {
    "multiple choice": "multiple_choice",
    "multiple-choice": "multiple_choice",
    "short answer": "short_answer",
    "short-answer": "short_answer",
}
_QUESTION_FIELDS = {field.name for field in fields(Question)}


def _normal(value: str) -> str:
    # Case can change scientific meaning (Co versus CO).
    return " ".join(value.split())


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _content_checksum(role: str, text: str, answer: str, choices: dict[str, str]) -> str:
    """Return the identity checksum for the question content used in play."""
    material = "|".join(
        (
            role,
            _normal(text),
            _normal(answer),
            *(f"{key}:{_normal(value)}" for key, value in sorted(choices.items())),
        )
    )
    return _sha(material)


def _canonical_record(record: dict[str, Any]) -> dict[str, Any]:
    """Refresh derived identity fields after a reviewer has corrected a record."""
    value = dict(record)
    checksum = _content_checksum(value["role"], value["text"], value["answer"], value["choices"])
    value["checksum"] = checksum
    value["id"] = f"q_{checksum[:24]}"
    return value


def _source_kind(source: str) -> str:
    """Classify the known packet families while retaining the submitted name."""
    folded = source.casefold()
    if "doe" in folded or "department of energy" in folded:
        return "doe"
    if "mit" in folded:
        return "mit"
    if "stanford" in folded:
        return "stanford"
    return "generic"


def _clean_lines(value: str) -> list[str]:
    return [" ".join(line.split()) for line in value.splitlines() if line.strip()]


def _category(value: str) -> str | None:
    normalized = " ".join(value.casefold().replace("–", "-").split())
    return _CATEGORIES.get(normalized) or _CATEGORY_ALIASES.get(normalized)


def _format(value: str) -> str | None:
    normalized = " ".join(value.casefold().replace("–", "-").split())
    if normalized.startswith("multiple"):
        return "multiple_choice"
    if normalized.startswith("short"):
        return "short_answer"
    return _FORMAT.get(normalized)


def _choices(block: str) -> dict[str, str]:
    """Read option continuations until another option or the answer line."""
    choices: dict[str, str] = {}
    current: str | None = None
    for line in _clean_lines(block):
        if _ANSWER.match(line):
            break
        match = _CHOICE.match(line)
        if match:
            current = match.group(1).upper()
            choices[current] = match.group(2).strip()
        elif current:
            choices[current] = f"{choices[current]} {line}".strip()
    return choices


def _strip_packet_noise(lines: list[str]) -> list[str]:
    return [
        line
        for line in lines
        if not re.match(
            r"(?i)^(?:national science bowl|\d{4}\s+(?:national|regional)|page\s+\d+(?:\s+of\s+\d+)?|round\s+\d+[a-z]?)\b",
            line,
        )
    ]


def _answer_issues(block: str, answer_match: re.Match[str] | None, fmt: str) -> list[str]:
    """Flag extraction loss that is unsafe to silently approve."""
    if not answer_match:
        return []
    issues: list[str] = []
    answer = answer_match.group(1).strip()
    if fmt == "multiple_choice" and re.match(r"^[A-Z]\)\S", answer):
        issues.append("multiple-choice answer is missing whitespace after its option letter")
    trailing = _strip_packet_noise(_clean_lines(block[answer_match.end() :]))
    trailing = [
        line
        for line in trailing
        if not re.fullmatch(r"~+", line)
        and not _ROLES.match(line)
        and not re.match(r"(?i)^stanford science bowl page\s+\d+(?:toss[\s-]*up)?$", line)
    ]
    if trailing:
        issues.append("unexpected non-footer content after ANSWER line (possibly wrapped answer)")
    return issues


def _glyph_issues(text: str, answer: str, choices: dict[str, str]) -> list[str]:
    """Flag common PDF text-extraction losses; do not attempt mathematical repair."""
    combined = "\n".join((text, answer, *choices.values()))
    issues: list[str] = []
    if "�" in combined:
        issues.append("replacement character in extracted text")
    if re.search(r"\b(?:10|x|e)\s*[–—-]\s*\d", combined) or re.search(r"\bx2\b", combined):
        issues.append("possible lost superscript or mathematical formatting")
    if re.search(r"\b10\d{1,2}\s+(?:NANOMETERS|METERS|SECONDS)\b", combined, re.IGNORECASE):
        issues.append("possible lost exponent in scientific notation")
    return issues


def _block_question(
    block: str,
    *,
    role: str,
    source: str,
    pool: str,
    source_url: str,
    page: int,
    document_checksum: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse the common DOE/MIT/Stanford text layout into one staging record."""
    issues: list[str] = []
    lines = _clean_lines(block)
    header = _HEADER.search(block)
    category = (
        _category(header.group("category"))
        if header
        else next((_category(line) for line in lines if _category(line)), None)
    )
    answer_match = _ANSWER.search(block)
    answer = answer_match.group(1).strip() if answer_match else ""
    fmt = (
        _format(header.group("format"))
        if header
        else next((_format(line) for line in lines if _format(line)), None)
    )
    choices = _choices(block)
    if fmt is None:
        fmt = "multiple_choice" if choices else "short_answer"

    # Everything after the first option belongs to the options/answer, including
    # wrapped option text. Do not duplicate continuations in the prompt.
    body = block[: answer_match.start()] if answer_match else block
    first_choice = _CHOICE.search(body)
    if first_choice:
        body = body[: first_choice.start()]
    # DOE PDFs often put the first sentence immediately after the header. Keep
    # that captured prompt while dropping the number/category/format prefix.
    body = _HEADER.sub(lambda match: match.group("prompt"), body)
    body = _CHOICE.sub("", body)
    body_lines = [line for line in _clean_lines(body) if not _category(line) and not _format(line)]
    # Packet labels (e.g. "TOSS-UP") are split out before this function, but
    # tolerate them in source-specific PDFs that place a label on the same page.
    body_lines = _strip_packet_noise(
        [line for line in body_lines if line.casefold() not in {"toss-up", "tossup", "bonus"}]
    )
    text = "\n".join(body_lines).strip()
    if not category:
        issues.append(f"page {page}: missing category")
    if not text:
        issues.append(f"page {page}: missing question text")
    if not answer:
        issues.append(f"page {page}: missing answer")
    if fmt == "multiple_choice" and len(choices) < 2:
        issues.append(f"page {page}: malformed multiple-choice options")
    issues.extend(f"page {page}: {issue}" for issue in _answer_issues(block, answer_match, fmt))
    issues.extend(f"page {page}: {issue}" for issue in _glyph_issues(text, answer, choices))
    if not text or not answer or not category:
        return None, issues

    question_checksum = _content_checksum(role, text, answer, choices)
    return (
        {
            "id": f"q_{question_checksum[:24]}",
            "text": text,
            "answer": answer,
            "category": category,
            "format": fmt,
            "choices": choices,
            "aliases": [],
            "pool": pool,
            "source": source,
            "page": page,
            "role": role,
            "pair_id": None,
            "revision": 1,
            "source_url": source_url,
            "checksum": question_checksum,
            "document_checksum": document_checksum,
            "reviewed": False,
        },
        issues,
    )


def _parse_page(text: str, **context: Any) -> tuple[list[dict[str, Any]], list[str]]:
    matches = list(_ROLES.finditer(text))
    if not matches:
        record, issues = _block_question(text, role="tossup", **context)
        return ([record] if record else []), issues + [
            f"page {context['page']}: no tossup/bonus label; parsed as tossup"
        ]
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = match.group(1).casefold().replace("-", "").replace(" ", "")
        role = "tossup" if label == "tossup" else "bonus"
        section = text[match.end() : end]
        headers = list(_HEADER.finditer(section))
        if not headers:
            record, block_issues = _block_question(section, role=role, **context)
            if record:
                records.append(record)
            issues.extend(block_issues)
            continue
        for header_index, header in enumerate(headers):
            question_end = (
                headers[header_index + 1].start()
                if header_index + 1 < len(headers)
                else len(section)
            )
            record, block_issues = _block_question(
                section[header.start() : question_end], role=role, **context
            )
            if record:
                record["pair_id"] = (
                    f"pair_{context['document_checksum'][:16]}_{header.group('number')}"
                )
                records.append(record)
            issues.extend(block_issues)
    return records, issues


def parse_pdfs(path: Path, source: str, pool: str, source_url: str = "") -> dict:
    """Extract PDFs below *path* into unreviewed, editable staging records.

    Broken, scanned, or unrecognised material is represented in ``issues`` so it
    cannot silently become gameplay data.
    """
    if pool not in {"regional", "invitational", "all"}:
        raise ValueError("pool must be regional, invitational, or all")
    files = [path] if path.is_file() else sorted(path.rglob("*.pdf"))
    payload: dict[str, Any] = {
        "metadata": {
            "source": source,
            "source_kind": _source_kind(source),
            "pool": pool,
            "source_url": source_url,
        },
        "questions": [],
        "issues": [],
        "issues_acknowledged": False,
    }
    if not files:
        payload["issues"].append(f"no PDF files found at {path}")
        return payload
    for pdf_path in files:
        try:
            document_checksum = _sha(pdf_path.read_bytes())
            with pdfplumber.open(pdf_path) as pdf:
                for number, pdf_page in enumerate(pdf.pages, start=1):
                    page_text = pdf_page.extract_text() or ""
                    if not page_text.strip():
                        payload["issues"].append(
                            f"{pdf_path.name} page {number}: no extractable text (possibly scanned)"
                        )
                        continue
                    records, issues = _parse_page(
                        page_text,
                        source=source,
                        pool=pool,
                        source_url=source_url,
                        page=number,
                        document_checksum=document_checksum,
                    )
                    payload["questions"].extend(records)
                    payload["issues"].extend(f"{pdf_path.name} {issue}" for issue in issues)
        except (OSError, PDFSyntaxError, PSEOF, UnicodeError, ValueError) as exc:
            payload["issues"].append(f"{pdf_path.name}: could not parse PDF ({type(exc).__name__})")
    return payload


def validate_staging(payload: dict) -> list[str]:
    """Return validation errors; callers must not import a nonempty result."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["staging must be a JSON object"]
    metadata = payload.get("metadata")
    questions = payload.get("questions")
    if not isinstance(metadata, dict):
        return ["staging metadata is missing"]
    if not isinstance(questions, list):
        return ["staging questions must be a list"]
    if not questions:
        errors.append("staging contains no questions")
    if payload.get("issues") and payload.get("issues_acknowledged") is not True:
        errors.append("staging issues have not been explicitly acknowledged")
    if not isinstance(metadata.get("pool"), str) or metadata["pool"] not in {
        "regional",
        "invitational",
        "all",
    }:
        errors.append("staging metadata has an invalid pool")
    if not isinstance(metadata.get("source"), str) or not metadata["source"].strip():
        errors.append("staging metadata needs a source")
    seen: set[str] = set()
    required = {
        "id",
        "text",
        "answer",
        "category",
        "format",
        "pool",
        "source",
        "page",
        "role",
        "checksum",
        "document_checksum",
    }
    for index, record in enumerate(questions):
        prefix = f"question {index + 1}"
        if not isinstance(record, dict):
            errors.append(f"{prefix} is not an object")
            continue
        missing = required - record.keys()
        if missing:
            errors.append(f"{prefix} is missing {', '.join(sorted(missing))}")
            continue
        if record.get("reviewed") is not True:
            errors.append(f"{prefix} has not been reviewed")
        if not isinstance(record["text"], str) or not record["text"].strip():
            errors.append(f"{prefix} has no text")
        if not isinstance(record["answer"], str) or not record["answer"].strip():
            errors.append(f"{prefix} has no answer")
        if not isinstance(record["category"], str) or record["category"] not in CATEGORIES:
            errors.append(f"{prefix} has an invalid category")
        if not isinstance(record["format"], str) or record["format"] not in {
            "short_answer",
            "multiple_choice",
        }:
            errors.append(f"{prefix} has an invalid format")
        if not isinstance(record["pool"], str) or record["pool"] not in {
            "regional",
            "invitational",
            "all",
        }:
            errors.append(f"{prefix} has an invalid pool")
        if not isinstance(record["source"], str) or not record["source"].strip():
            errors.append(f"{prefix} has an invalid source")
        if not isinstance(record["role"], str) or record["role"] not in {"tossup", "bonus"}:
            errors.append(f"{prefix} has an invalid role")
        if not isinstance(record["page"], int) or record["page"] < 1:
            errors.append(f"{prefix} has an invalid page")
        choices = record.get("choices", {})
        if not isinstance(choices, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not v.strip()
            for k, v in choices.items()
        ):
            errors.append(f"{prefix} has invalid choices")
        elif record["format"] == "multiple_choice" and len(choices) < 2:
            errors.append(f"{prefix} has malformed multiple-choice options")
        if not isinstance(record["id"], str):
            errors.append(f"{prefix} has an invalid id")
        if not isinstance(record["checksum"], str):
            errors.append(f"{prefix} has an invalid checksum")
        if not isinstance(record["document_checksum"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", record["document_checksum"]
        ):
            errors.append(f"{prefix} has an invalid document checksum")
        if not isinstance(record.get("aliases", []), list) or any(
            not isinstance(alias, str) for alias in record.get("aliases", [])
        ):
            errors.append(f"{prefix} has invalid aliases")
        if (
            isinstance(record["text"], str)
            and isinstance(record["answer"], str)
            and isinstance(record["role"], str)
            and isinstance(choices, dict)
            and all(
                isinstance(key, str) and isinstance(value, str) for key, value in choices.items()
            )
        ):
            canonical_id = f"q_{_content_checksum(record['role'], record['text'], record['answer'], choices)[:24]}"
            if canonical_id in seen:
                errors.append(f"{prefix} duplicates stable content id {canonical_id}")
            seen.add(canonical_id)
    return errors


def load_approved(payload: dict) -> list[Question]:
    """Convert an entirely valid reviewed staging payload into storage records."""
    errors = validate_staging(payload)
    if errors:
        raise ValueError("staging cannot be imported: " + "; ".join(errors))
    return [
        Question.from_dict(
            {
                key: value
                for key, value in _canonical_record(record).items()
                if key in _QUESTION_FIELDS
            }
        )
        for record in payload["questions"]
    ]
