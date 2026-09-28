import sqlite3
from pathlib import Path

from scibowl.storage import Store


async def test_v1_database_retains_legacy_reports_and_gains_message_table(tmp_path: Path):
    database = tmp_path / "existing.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                session_id TEXT, question_id TEXT, reason TEXT NOT NULL);
            INSERT INTO reports(user_id,session_id,question_id,reason) VALUES (1, 'legacy-session', 'q1', 'typo');
            PRAGMA user_version=1;
            """
        )

    store = await Store(database).open()
    try:
        async with store.db.execute("SELECT reason FROM reports WHERE id=1") as cursor:
            assert (await cursor.fetchone())[0] == "typo"
        await store.track_message("legacy-session", 9, 10)
        assert await store.session_messages("legacy-session") == [
            {"channel_id": 9, "message_id": 10}
        ]
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
        await store.forget_message("finished", 100)
    finally:
        await store.close()

    reopened = await Store(database).open()
    try:
        assert await reopened.session_messages("finished") == [
            {"channel_id": 44, "message_id": 101}
        ]
        assert (await reopened.review(5, "finished"))["attempts"] == [{"user_id": 5, "answer": "x"}]
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
