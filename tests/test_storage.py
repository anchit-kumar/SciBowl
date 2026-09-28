import asyncio
import sqlite3
from pathlib import Path

import pytest

from scibowl.models import CATEGORIES, Question, default_settings
from scibowl.storage import Store


def question(question_id: str, **overrides) -> Question:
    values = {
        "id": question_id,
        "text": f"Question {question_id}",
        "answer": "answer",
        "category": "Biology",
        "source": "DOE",
    }
    values.update(overrides)
    return Question(**values)


@pytest.fixture
async def store(tmp_path: Path):
    result = await Store(tmp_path / "scibowl.sqlite3").open()
    yield result
    await result.close()


async def test_questions_filter_and_deduplicate(store: Store):
    biology = question("b1")
    chemistry = question("c1", category="Chemistry", pool="invitational", format="multiple_choice")

    assert await store.import_questions([biology, chemistry, biology]) == 2
    assert await store.import_questions([biology]) == 0

    found = await store.questions(
        {"categories": ["Chemistry"], "pool": "invitational", "count": 10}
    )
    assert [item.id for item in found] == ["c1"]
    assert await store.questions({"categories": ["Physics"], "count": 10}) == []
    assert await store.sources() == [
        {"source": "DOE", "pool": "invitational", "count": 1},
        {"source": "DOE", "pool": "regional", "count": 1},
    ]


async def test_settings_defaults_validation_and_user_isolation(store: Store):
    defaults = await store.get_settings(100, "shared")
    assert defaults == default_settings("shared")

    chosen = default_settings("shared")
    chosen.update({"count": 12, "categories": ["Physics"], "pool": "all"})
    await store.save_settings(100, "shared", chosen)

    assert await store.get_settings(100, "shared") == chosen
    assert await store.get_settings(101, "shared") == default_settings("shared")
    assert await store.get_settings(100, "solo") == default_settings("solo")

    invalid = dict(chosen, categories=["Astronomy"])
    with pytest.raises(ValueError, match="valid category"):
        await store.save_settings(100, "shared", invalid)
    with pytest.raises(ValueError, match="Unknown settings"):
        await store.save_settings(100, "invalid", chosen)


async def test_settings_and_dm_preference_persist_after_reopen(tmp_path: Path):
    database = tmp_path / "scibowl.sqlite3"
    store = await Store(database).open()
    solo = default_settings("solo")
    solo["categories"] = [CATEGORIES[0], CATEGORIES[1]]
    await store.save_preferences(400, {"solo": solo}, dm_enabled=False)
    await store.close()

    reopened = await Store(database).open()
    try:
        assert await reopened.get_settings(400, "solo") == solo
        assert await reopened.dm_enabled(400) is False
        assert await reopened.dm_enabled(401) is True
    finally:
        await reopened.close()


async def test_finished_review_is_private_and_delivery_state_isolated(store: Store):
    payload = {"id": "finished-1", "participants": [11, 22], "state": "finished"}
    attempts = [{"user_id": 11, "verdict": "incorrect", "question": {"id": "q1"}}]
    await store.finish_session("finished-1", payload, attempts)

    assert (await store.review(11))["attempts"] == attempts
    assert (await store.review(22))["id"] == "finished-1"
    assert await store.review(33) is None
    assert await store.review(11, "missing") is None

    await store.mark_delivery("finished-1", 11, "sent")
    assert await store.delivery_status("finished-1", 11) == "sent"
    assert await store.delivery_status("finished-1", 22) is None


async def test_unfinished_session_and_backup(store: Store, tmp_path: Path):
    await store.save_session("live-1", {"id": "live-1", "participants": [7]})
    assert await store.load_session("live-1") == {"id": "live-1", "participants": [7]}
    assert await store.unfinished_sessions() == [{"id": "live-1", "participants": [7]}]

    target = tmp_path / "backups" / "snapshot.sqlite3"
    await store.backup(target)
    assert target.exists()

    restored = await Store(target).open()
    try:
        assert await restored.load_session("live-1") == {"id": "live-1", "participants": [7]}
    finally:
        await restored.close()


async def test_open_rejects_a_newer_schema_without_changing_it(tmp_path: Path):
    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=2")

    with pytest.raises(ValueError, match="newer"):
        await Store(database).open()

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


async def test_finalized_session_is_immutable_and_review_access_does_not_expand(store: Store):
    first = {"id": "finished-immutable", "participants": [11], "state": "finished"}
    second = {"id": "finished-immutable", "participants": [22], "state": "finished"}
    await store.finish_session("finished-immutable", first, [{"answer": "first"}])
    await store.finish_session("finished-immutable", second, [{"answer": "second"}])

    assert (await store.review(11, "finished-immutable"))["attempts"] == [{"answer": "first"}]
    assert await store.review(22, "finished-immutable") is None


async def test_cancelled_preferences_write_is_rolled_back(store: Store, monkeypatch):
    profile = default_settings("solo")
    started = asyncio.Event()
    original_commit = store.db.commit

    async def interrupted_commit():
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(store.db, "commit", interrupted_commit)
    task = asyncio.create_task(store.save_preferences(99, {"solo": profile}, dm_enabled=False))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    monkeypatch.setattr(store.db, "commit", original_commit)
    assert await store.get_settings(99, "solo") == default_settings("solo")
    assert await store.dm_enabled(99) is True
