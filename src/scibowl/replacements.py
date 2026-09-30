"""Reviewed content replacements, atomic maintenance, and import replay."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .bank import _canonical_record
from .models import Question

LEDGER_SCHEMA = """CREATE TABLE IF NOT EXISTS question_replacements (
    old_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"""
_EDITABLE = {"text", "answer", "choices", "aliases", "id", "checksum", "revision"}


def validate_replacements(payload: dict) -> dict[str, dict]:
    if not isinstance(payload, dict) or payload.get("reviewed") is not True:
        raise ValueError("Replacements require reviewed: true.")
    if not isinstance(payload.get("changes"), list) or not isinstance(
        payload.get("history", []), list
    ):
        raise ValueError("Replacements require changes and optional history lists.")  # noqa: TRY004
    mapping = {}
    for change in [*payload.get("history", []), *payload["changes"]]:
        if not isinstance(change, dict):
            raise ValueError("Each replacement requires old and new question payloads.")  # noqa: TRY004
        old, new = change.get("old"), change.get("new")
        for value in (old, new):
            if not isinstance(value, dict):
                raise ValueError("Each replacement requires old and new question payloads.")  # noqa: TRY004
            try:
                question = Question.from_dict(value)
                canonical = _canonical_record(value)
            except (TypeError, KeyError, AttributeError) as error:
                raise ValueError("Invalid replacement question payload.") from error
            if value != question.to_dict() or any(
                value[key] != canonical[key] for key in ("id", "checksum")
            ):
                raise ValueError("Replacement identity must match canonical content.")
            if (
                not isinstance(question.text, str)
                or not question.text.strip()
                or not isinstance(question.answer, str)
                or not question.answer.strip()
                or not isinstance(question.choices, dict)
                or not all(isinstance(v, str) and v.strip() for v in question.choices.values())
                or not isinstance(question.aliases, list)
                or not all(isinstance(v, str) and v.strip() for v in question.aliases)
                or type(question.revision) is not int
                or question.revision < 1
            ):
                raise ValueError("Invalid replacement text, choices, aliases, or revision.")
        if any(old[key] != new[key] for key in old.keys() - _EDITABLE):
            raise ValueError("Replacements cannot change question provenance or filters.")
        if set(old["choices"]) != set(new["choices"]):
            raise ValueError("Replacements cannot change choice labels.")
        if new["revision"] != old["revision"] + 1 or old["id"] == new["id"]:
            raise ValueError("Replacement requires new content identity and next revision.")
        if old["id"] in mapping:
            raise ValueError("Duplicate replacement origin.")
        mapping[old["id"]] = {"old": old, "new": new}
    for origin in mapping:
        seen = set()
        current = origin
        while current in mapping:
            if current in seen:
                raise ValueError("Replacement cycle.")
            seen.add(current)
            current = mapping[current]["new"]["id"]
    return mapping


def correct_question(question: Question, mapping: dict[str, dict]) -> Question:
    """Replay content corrections while retaining the importing packet's provenance."""
    value = question.to_dict()
    seen = set()
    while value["id"] in mapping:
        if value["id"] in seen:
            raise ValueError("Replacement cycle.")
        seen.add(value["id"])
        change = mapping[value["id"]]
        if _canonical_record(value)["checksum"] != change["old"]["checksum"]:
            raise ValueError("Imported content does not match its replacement origin.")
        target = change["new"]
        value.update({key: target[key] for key in ("text", "answer", "choices")})
        value["aliases"] = list(dict.fromkeys([*value["aliases"], *target["aliases"]]))
        value["revision"] = max(value["revision"], target["revision"])
        value = _canonical_record(value)
    return Question.from_dict(value)


def _prepare(db, payload, mapping):
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='question_replacements'"
    ).fetchone()
    if exists:
        combined = {
            row[0]: json.loads(row[1])
            for row in db.execute("SELECT old_id,payload FROM question_replacements")
        }
        for origin, change in mapping.items():
            if origin in combined and combined[origin] != change:
                raise ValueError("Stored replacement conflicts with reviewed history.")
            combined[origin] = change
        # Reject cycles across earlier batches, and resolve replays through later repairs.
        mapping = validate_replacements({"reviewed": True, "changes": list(combined.values())})
    planned = []
    targets = set()
    for change in payload["changes"]:
        old = change["old"]
        new = correct_question(Question.from_dict(change["new"]), mapping).to_dict()
        if new["id"] in targets:
            raise ValueError("Replacements converge on a duplicate destination.")
        targets.add(new["id"])
        current = db.execute("SELECT payload FROM questions WHERE id=?", (old["id"],)).fetchone()
        destination = db.execute(
            "SELECT payload FROM questions WHERE id=?", (new["id"],)
        ).fetchone()
        if current is None:
            if destination and json.loads(destination[0]) == new:
                continue
            raise ValueError(f"Replacement origin missing: {old['id']}")
        if json.loads(current[0]) != old:
            raise ValueError(f"Question changed since review: {old['id']}")
        if destination:
            raise ValueError(f"Replacement destination already exists: {new['id']}")
        planned.append({"old": old, "new": new})
    future = {change["new"]["id"]: change["new"] for change in planned}
    for change in payload.get("history", []):
        if db.execute("SELECT 1 FROM questions WHERE id=?", (change["old"]["id"],)).fetchone():
            raise ValueError("Historical repair has not been applied; include it in changes.")
        final = correct_question(Question.from_dict(change["new"]), mapping).to_dict()
        current = db.execute("SELECT payload FROM questions WHERE id=?", (final["id"],)).fetchone()
        if future.get(final["id"]) != final and (not current or json.loads(current[0]) != final):
            raise ValueError("Historical replacement destination does not match the database.")
    return planned


def apply_replacements(db_path: Path, payload: dict, *, apply: bool = False) -> dict:
    mapping = validate_replacements(payload)
    db_path = Path(db_path)
    if not db_path.is_file():
        raise ValueError("Replacement database does not exist.")
    uri = db_path.resolve().as_uri() + ("?mode=rw" if apply else "?mode=ro")
    result = {"applied": apply, "updated": 0, "backup": None, "audit": None}
    with closing(sqlite3.connect(uri, uri=True)) as db, db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Unsupported replacement database schema.")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Replacement database integrity check failed.")
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        planned = _prepare(db, payload, mapping)
        result["updated"] = len(planned)
        if not apply:
            return result
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='question_replacements'"
        ).fetchone()
        if not planned and exists:
            origins = {row[0] for row in db.execute("SELECT old_id FROM question_replacements")}
            if mapping.keys() <= origins:
                return result
        # A separate reader can back up while this transaction blocks concurrent writers.
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        folder = db_path.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f"math-text-{stamp}.sqlite3"
        audit = folder / f"math-text-{stamp}.json"
        with (
            closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(backup)) as saved,
        ):
            source.backup(saved)
            if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Replacement backup integrity check failed.")
        # Write the recovery information before any content update can commit.
        with audit.open("x", encoding="utf-8") as file:
            json.dump(
                {"backup": str(backup), "changes": planned, "replacements": payload},
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")
        count = db.execute("SELECT count(*) FROM questions").fetchone()[0]
        db.execute(LEDGER_SCHEMA)
        for origin, change in mapping.items():
            db.execute(
                "INSERT OR IGNORE INTO question_replacements VALUES (?,?)",
                (origin, json.dumps(change, ensure_ascii=False)),
            )
        for change in planned:
            old, new = change["old"], change["new"]
            db.execute(
                "UPDATE questions SET id=?,payload=? WHERE id=?",
                (new["id"], json.dumps(new, ensure_ascii=False), old["id"]),
            )
        if db.execute("SELECT count(*) FROM questions").fetchone()[0] != count:
            raise ValueError("Replacement changed the question count.")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Replacement integrity check failed; transaction rolled back.")
        db.commit()
        result.update(backup=str(backup), audit=str(audit))
    return result
