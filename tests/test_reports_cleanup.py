import json
import sqlite3
from pathlib import Path

from scibowl.storage import Store


async def test_v1_database_gains_report_and_message_tables(tmp_path: Path):
    database = tmp_path / "existing.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                session_id TEXT, question_id TEXT, reason TEXT NOT NULL);
            PRAGMA user_version=1;
            """
        )

    store = await Store(database).open()
    try:
        report_id = await store.report(1, "legacy-session", "q1", "typo")
        assert report_id == 1
        await store.track_message("legacy-session", 9, 10)
        assert await store.session_messages("legacy-session") == [
            {"channel_id": 9, "message_id": 10}
        ]
    finally:
        await store.close()


async def test_reports_export_full_snapshots_per_session_and_rebuild_atomically(tmp_path: Path):
    store = await Store(tmp_path / "data" / "scibowl.sqlite3").open()
    try:
        details = {
            "channel_id": 22,
            "question": {"id": "q1", "text": "full question", "source": "DOE"},
            "attempt": {"user_id": 7, "answer": "wrong", "verdict": "incorrect"},
        }
        first = await store.report(7, "a" * 32, "q1", "bad answer key", details=details)
        second = await store.report(
            8, "b" * 32, "q2", "formatting", details={"question": {"id": "q2"}}
        )
        assert (first, second) == (1, 2)

        paths = await store.export_reports()
        assert {path.name for path in paths} == {"a" * 32 + ".json", "b" * 32 + ".json"}
        first_export = json.loads(
            (tmp_path / "data" / "reports" / ("a" * 32 + ".json")).read_text()
        )
        assert first_export["reports"][0]["details"]["question"] == details["question"]
        assert first_export["reports"][0]["details"]["attempt"] == details["attempt"]
        assert "received_at" in first_export["reports"][0]["details"]

        await store.report(7, "a" * 32, "q3", "duplicate", details={"question": {"id": "q3"}})
        rebuilt = await store.export_reports("a" * 32)
        assert rebuilt == [tmp_path / "data" / "reports" / ("a" * 32 + ".json")]
        assert [row["id"] for row in json.loads(rebuilt[0].read_text())["reports"]] == [1, 3]
    finally:
        await store.close()


async def test_message_tracking_survives_reopen_and_cleanup_does_not_change_reviews(tmp_path: Path):
    database = tmp_path / "scibowl.sqlite3"
    store = await Store(database).open()
    try:
        await store.finish_session(
            "finished", {"id": "finished", "participants": [5]}, [{"user_id": 5, "answer": "x"}]
        )
        await store.track_message("finished", 44, 100)
        await store.track_message("finished", 44, 100)  # idempotent
        await store.track_message("finished", 44, 101)
        await store.record_question("finished", 1, {"id": "q-timeout", "text": "unanswered"})
        await store.forget_message("finished", 100)
    finally:
        await store.close()

    reopened = await Store(database).open()
    try:
        assert await reopened.session_messages("finished") == [
            {"channel_id": 44, "message_id": 101}
        ]
        assert (await reopened.review(5, "finished"))["attempts"] == [{"user_id": 5, "answer": "x"}]
        assert await reopened.session_question("finished") == {
            "round_id": 1,
            "question": {"id": "q-timeout", "text": "unanswered"},
        }
    finally:
        await reopened.close()


async def test_latest_channel_session_accepts_active_and_finished_snapshots(tmp_path: Path):
    store = await Store(tmp_path / "scibowl.sqlite3").open()
    try:
        await store.save_session("active", {"id": "active", "channel_id": 3, "state": "open"})
        assert (await store.latest_channel_session(3))["id"] == "active"
        await store.finish_session("finished", {"id": "finished", "channel_id": 3}, [])
        assert (await store.latest_channel_session(3))["id"] == "finished"
        assert await store.latest_channel_session(99) is None
    finally:
        await store.close()


async def test_question_history_is_immutable_and_finds_no_attempt_rounds(tmp_path: Path):
    store = await Store(tmp_path / "scibowl.sqlite3").open()
    try:
        await store.record_question("solo", 2, {"id": "q2", "text": "first copy"})
        await store.record_question("solo", 3, {"id": "q3", "text": "timed out without attempt"})
        await store.record_question("solo", 2, {"id": "q2", "text": "changed copy"})

        assert await store.session_question("solo", 2) == {
            "round_id": 2,
            "question": {"id": "q2", "text": "first copy"},
        }
        assert await store.session_question("solo") == {
            "round_id": 3,
            "question": {"id": "q3", "text": "timed out without attempt"},
        }
        assert await store.session_question("missing") is None
    finally:
        await store.close()
