import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scibowl.bank import _canonical_record
from scibowl.discord_app import BowlBot
from scibowl.engine import Session
from scibowl.judging import AnswerJudge
from scibowl.models import Question, default_settings
from scibowl.replacements import apply_replacements, correct_question, validate_replacements
from scibowl.storage import Store


def question(question_id: str, **overrides) -> Question:
    values = {
        "id": question_id,
        "text": f"Question {question_id}",
        "answer": "answer",
        "category": "Mathematics",
        "format": "short_answer",
        "source": "DOE synthetic",
        "page": 3,
        "revision": 1,
        "source_url": "https://example.test/packet",
        "checksum": "",
        "document_checksum": "document-checksum",
    }
    values.update(overrides)
    return Question.from_dict(_canonical_record(Question(**values).to_dict()))


def change(old: Question, new: Question) -> dict:
    return {"old": old.to_dict(), "new": new.to_dict()}


def replacement_payload(*changes: dict, history: list[dict] | None = None) -> dict:
    return {"reviewed": True, "changes": list(changes), "history": history or []}


def test_validation_rejects_unreviewed_invalid_identity_and_cycles():
    old = question("q-old")
    new = question("q-new", revision=2, text="Corrected question")
    assert validate_replacements(replacement_payload(change(old, new))) == {
        old.id: {"old": old.to_dict(), "new": new.to_dict()}
    }

    with pytest.raises(ValueError):
        validate_replacements({"reviewed": False, "changes": [change(old, new)]})
    tampered = new.to_dict() | {"checksum": "wrong"}
    with pytest.raises(ValueError):
        validate_replacements(replacement_payload({"old": old.to_dict(), "new": tampered}))
    bad_identity = question("q-new", revision=2, category="Physics")
    with pytest.raises(ValueError):
        validate_replacements(replacement_payload(change(old, bad_identity)))

    a, b = question("a", text="A"), question("b", text="B")
    a2, b2 = question(a.id, text="A", revision=2), question(b.id, text="B", revision=2)
    with pytest.raises(ValueError):
        validate_replacements(replacement_payload(change(a, b2), change(b, a2)))


def test_correct_question_follows_chain_and_keeps_incoming_provenance_and_aliases():
    origin = question("q1", text="Original wording", answer="original answer")
    first = question(origin.id, text="Corrected wording", answer="new answer", revision=2)
    final = question(first.id, text="Final wording", answer="final answer", revision=3)
    mapping = {
        origin.id: {"old": origin.to_dict(), "new": first.to_dict()},
        first.id: {"old": first.to_dict(), "new": final.to_dict()},
    }
    incoming = question(
        origin.id,
        text=origin.text,
        answer=origin.answer,
        source="Imported packet",
        page=17,
        source_url="https://import.test",
        document_checksum="incoming-document",
        aliases=["alternate answer"],
    )
    corrected = correct_question(incoming, mapping)
    assert corrected.id == final.id
    assert (corrected.text, corrected.answer, corrected.revision) == (
        "Final wording",
        "final answer",
        3,
    )
    assert (corrected.source, corrected.page, corrected.source_url) == (
        "Imported packet",
        17,
        "https://import.test",
    )
    assert corrected.checksum == final.checksum
    assert corrected.document_checksum == "incoming-document"
    assert corrected.aliases == ["alternate answer"]


@pytest.mark.asyncio
async def test_apply_dry_run_is_read_only(tmp_path: Path):
    database = tmp_path / "questions.sqlite3"
    store = await Store(database).open()
    old = question("q-old")
    await store.import_questions([old])
    await store.close()
    before = database.read_bytes()
    new = question(old.id, text="Corrected text", revision=2)

    result = apply_replacements(database, replacement_payload(change(old, new)))

    assert result == {"updated": 1, "applied": False, "backup": None, "audit": None}
    assert database.read_bytes() == before
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT id FROM questions").fetchall() == [(old.id,)]


@pytest.mark.asyncio
async def test_apply_is_atomic_idempotent_and_preserves_existing_history(tmp_path: Path):
    database = tmp_path / "questions.sqlite3"
    store = await Store(database).open()
    old = question("q-old", text="Reviewed intermediate", revision=2)
    await store.import_questions([old])
    await store.close()
    legacy = question("q-legacy", text="Legacy wording")
    history = [change(legacy, old)]
    payload = replacement_payload(
        change(old, question(old.id, text="Final wording", revision=3)), history=history
    )
    snapshot = json.dumps({"id": "finished", "attempts": [{"question": legacy.to_dict()}]})
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO sessions(id,payload,finished) VALUES (?,?,1)", ("finished", snapshot)
        )
        db.execute("INSERT INTO reviews VALUES (?,?)", ("finished", 123))

    first = apply_replacements(database, payload, apply=True)
    second = apply_replacements(database, payload, apply=True)

    assert first["updated"] == 1 and first["applied"] is True
    assert first["backup"] and Path(first["backup"]).exists()
    assert first["audit"] and Path(first["audit"]).exists()
    assert second["updated"] == 0
    final = Question.from_dict(payload["changes"][0]["new"])
    reverted = question("legacy", text=legacy.text, revision=4)
    with pytest.raises(ValueError, match="cycle"):
        apply_replacements(database, replacement_payload(change(final, reverted)), apply=True)
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT id,payload FROM questions").fetchall()
        assert [row[0] for row in rows] == [payload["changes"][0]["new"]["id"]]
        stored = json.loads(rows[0][1])
        assert stored["id"] == payload["changes"][0]["new"]["id"]
        assert db.execute("SELECT payload FROM sessions").fetchone() == (snapshot,)
        assert db.execute("SELECT * FROM reviews").fetchall() == [("finished", 123)]
    with sqlite3.connect(first["backup"]) as db:
        assert (
            json.loads(db.execute("SELECT payload FROM questions").fetchone()[0]) == old.to_dict()
        )


@pytest.mark.asyncio
async def test_apply_refuses_stale_old_question_and_destination_collision(tmp_path: Path):
    database = tmp_path / "questions.sqlite3"
    store = await Store(database).open()
    old = question("q-old")
    destination = question("destination")
    await store.import_questions([old, destination])
    await store.close()
    payload = replacement_payload(change(old, question(old.id, text="changed review", revision=2)))
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE questions SET payload=replace(payload, 'Question q-old', 'changed locally') WHERE id=?",
            (old.id,),
        )

    with pytest.raises(ValueError):
        apply_replacements(database, payload, apply=True)
    with sqlite3.connect(database) as db:
        assert {row[0] for row in db.execute("SELECT id FROM questions")} == {
            old.id,
            destination.id,
        }
        assert db.execute("SELECT COUNT(*) FROM question_replacements").fetchone() == (0,)

    collision_db = tmp_path / "collision.sqlite3"
    store = await Store(collision_db).open()
    await store.import_questions([old, Question.from_dict(payload["changes"][0]["new"])])
    await store.close()
    with pytest.raises(ValueError):
        apply_replacements(collision_db, payload, apply=True)


@pytest.mark.asyncio
async def test_corrected_math_flows_through_shared_and_solo_discord_delivery(tmp_path):
    database = tmp_path / "math-delivery.sqlite3"
    old = question(
        "math",
        text="Evaluate x^2 + 1/2.",
        answer="W) 1/2",
        format="multiple_choice",
        choices={"W": "1/2", "X": "3/2"},
    )
    new = question(
        "math",
        text="Consider x², √(x + 1), and θ. " * 130 + "Evaluate (x² + 1)/(x + 1).",
        answer="W) (1)/(2)",
        revision=2,
        format="multiple_choice",
        choices={"W": "(1)/(2)", "X": "(3)/(2)"},
        aliases=["W) 1/2", "1/2"],
    )
    store = await Store(database).open()
    try:
        await store.import_questions([old])
    finally:
        await store.close()
    apply_replacements(database, replacement_payload(change(old, new)), apply=True)
    bot = BowlBot(database)
    try:
        await bot.store.open()
        assert await bot.store.import_questions([old]) == 0
        selected = await bot.store.questions({"categories": ["Mathematics"], "count": 1})
        assert selected[0].to_dict() == new.to_dict()
        assert AnswerJudge._local(selected[0], "1/2").verdict == "correct"
        messages = []

        async def send(**kwargs):
            message = SimpleNamespace(id=len(messages) + 1, edit=AsyncMock(), delete=AsyncMock())
            messages.append(message)
            return message

        channel = SimpleNamespace(id=1, send=AsyncMock(side_effect=send))
        bot.channels[1] = channel
        for mode in ("shared", "solo"):
            session = Session(mode, 1, 10, mode, default_settings(mode), selected)
            bot.sessions[1] = session
            await session.next_question()
            channel.send.reset_mock()
            assert await bot.post_question(session)
            calls = channel.send.await_args_list
            expected = new.text + "\n\nW) (1)/(2)\nX) (3)/(2)"
            assert len(calls) > 1
            assert "".join(c.kwargs["embed"].description for c in calls) == expected
            assert all("file" not in c.kwargs and "files" not in c.kwargs for c in calls)
            channel.send.reset_mock()
            bot.hidden_questions.add(session.id)
            assert await bot.restore_question(session)
            assert (
                "".join(c.kwargs["embed"].description for c in channel.send.await_args_list)
                == expected
            )
            channel.send.reset_mock()
            await session.skip()
            await bot.reveal(session, "Skipped")
            assert any(
                "Official answer: W) (1)/(2)" in c.kwargs["embed"].description
                for c in channel.send.await_args_list
            )
            bot.cancel_timer(session)
            bot.stop_question_view(session)
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_ledger_failure_rolls_back_and_reimport_follows_replacement(tmp_path: Path):
    database = tmp_path / "questions.sqlite3"
    store = await Store(database).open()
    first = question("q-first", text="first")
    second = question("q-second", text="second")
    await store.import_questions([first, second])
    await store.close()
    corrected_first = question(first.id, text="first fixed", revision=2)
    corrected_second = question(second.id, text="second fixed", revision=2)
    payload = replacement_payload(change(first, corrected_first), change(second, corrected_second))
    apply_replacements(database, payload, apply=True)

    reopened = await Store(database).open()
    try:
        assert await reopened.import_questions([first, second]) == 0
        assert {item.id for item in await reopened.questions({"count": 10})} == {
            corrected_first.id,
            corrected_second.id,
        }
    finally:
        await reopened.close()

    rollback_db = tmp_path / "rollback.sqlite3"
    store = await Store(rollback_db).open()
    await store.import_questions([first, second])
    await store.close()
    with sqlite3.connect(rollback_db) as db:
        db.execute(
            f"CREATE TRIGGER reject_second_update BEFORE UPDATE ON questions WHEN OLD.id='{second.id}' BEGIN SELECT RAISE(ABORT, 'forced update failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        apply_replacements(rollback_db, payload, apply=True)
    with sqlite3.connect(rollback_db) as db:
        assert {row[0] for row in db.execute("SELECT id FROM questions")} == {first.id, second.id}
        assert db.execute("SELECT COUNT(*) FROM question_replacements").fetchone() == (0,)
