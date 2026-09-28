"""Small asynchronous SQLite repository with explicit schema and JSON snapshots."""

import asyncio
import json
import random
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from .models import Question, default_settings, validate_settings


class Store:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.db: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()

    async def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        async with self.db.execute("PRAGMA user_version") as cursor:
            version = (await cursor.fetchone())[0]
        if version > self.SCHEMA_VERSION:
            await self.db.close()
            self.db = None
            raise ValueError(
                f"Database schema version {version} is newer than this application supports."
            )
        await self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY, category TEXT NOT NULL, pool TEXT NOT NULL,
                source TEXT NOT NULL, format TEXT NOT NULL, role TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS question_filters ON questions(category,pool,format,role);
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(user_id,mode));
            CREATE TABLE IF NOT EXISTS notifications (
                user_id INTEGER PRIMARY KEY, dm_enabled INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, finished INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')));
            CREATE TABLE IF NOT EXISTS reviews (
                session_id TEXT NOT NULL REFERENCES sessions(id), user_id INTEGER NOT NULL,
                PRIMARY KEY(session_id,user_id));
            CREATE TABLE IF NOT EXISTS deliveries (
                session_id TEXT NOT NULL, user_id INTEGER NOT NULL, status TEXT NOT NULL,
                PRIMARY KEY(session_id,user_id));
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY, channel_ids TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                session_id TEXT, question_id TEXT, reason TEXT NOT NULL);
            PRAGMA user_version=1;
        """)
        await self.db.commit()
        return self

    @asynccontextmanager
    async def _transaction(self):
        """Serialize a write and roll it back for every interruption, including cancellation."""
        async with self.lock:
            try:
                yield
                await self.db.commit()
            except BaseException:
                await self.db.rollback()
                raise

    async def close(self):
        if self.db:
            await self.db.close()

    async def import_questions(self, questions: list[Question]) -> int:
        async with self._transaction():
            before = self.db.total_changes
            await self.db.executemany(
                "INSERT OR IGNORE INTO questions VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        q.id,
                        q.category,
                        q.pool,
                        q.source,
                        q.format,
                        q.role,
                        json.dumps(q.to_dict()),
                    )
                    for q in questions
                ],
            )
            return self.db.total_changes - before

    async def questions(self, filters: dict) -> list[Question]:
        clauses, args = [], []
        categories = filters.get("categories", [])
        if categories:
            clauses.append("category IN (" + ",".join("?" for _ in categories) + ")")
            args.extend(categories)
        for key in ("pool", "source", "format", "role"):
            value = filters.get(key, "all")
            if value != "all":
                clauses.append(f"{key}=?")
                args.append(value)
        count = filters.get("count", 100)
        if not isinstance(count, int) or not 1 <= count <= 100:
            raise ValueError("Question count must be between 1 and 100.")
        sql = "SELECT payload FROM questions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        # Select the requested random subset in SQLite before decoding JSON snapshots.
        sql += " ORDER BY RANDOM() LIMIT ?"
        args.append(count)
        async with self.lock, self.db.execute(sql, args) as cursor:
            result = [Question.from_dict(json.loads(row[0])) for row in await cursor.fetchall()]
        random.shuffle(result)
        return result

    async def sources(self) -> list[dict]:
        async with (
            self.lock,
            self.db.execute(
                "SELECT source,pool,count(*) FROM questions GROUP BY source,pool ORDER BY source,pool"
            ) as cur,
        ):
            return [{"source": r[0], "pool": r[1], "count": r[2]} for r in await cur.fetchall()]

    async def get_settings(self, user_id: int, mode: str) -> dict:
        result = default_settings(mode)
        async with (
            self.lock,
            self.db.execute(
                "SELECT payload FROM settings WHERE user_id=? AND mode=?", (user_id, mode)
            ) as cur,
        ):
            row = await cur.fetchone()
        if row:
            result.update(json.loads(row[0]))
        return result

    async def save_settings(self, user_id, mode, settings):
        if mode not in ("shared", "solo"):
            raise ValueError("Unknown settings profile.")
        validate_settings(settings)
        async with self._transaction():
            await self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?,?)",
                (user_id, mode, json.dumps(settings)),
            )

    async def dm_enabled(self, user_id) -> bool:
        async with (
            self.lock,
            self.db.execute(
                "SELECT dm_enabled FROM notifications WHERE user_id=?", (user_id,)
            ) as cur,
        ):
            row = await cur.fetchone()
        return bool(row[0]) if row else True

    async def set_dm(self, user_id, enabled):
        async with self._transaction():
            await self.db.execute(
                "INSERT OR REPLACE INTO notifications VALUES (?,?)", (user_id, int(enabled))
            )

    async def save_preferences(self, user_id, profiles, dm_enabled):
        for mode, profile in profiles.items():
            if mode not in ("shared", "solo"):
                raise ValueError("Unknown settings profile.")
            validate_settings(profile)
        async with self._transaction():
            for mode, profile in profiles.items():
                await self.db.execute(
                    "INSERT OR REPLACE INTO settings VALUES (?,?,?)",
                    (user_id, mode, json.dumps(profile)),
                )
            await self.db.execute(
                "INSERT OR REPLACE INTO notifications VALUES (?,?)", (user_id, int(dm_enabled))
            )

    async def save_session(self, session_id, payload):
        async with self._transaction():
            await self.db.execute(
                """INSERT INTO sessions(id,payload) VALUES (?,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,
                updated_at=strftime('%Y-%m-%dT%H:%M:%f','now') WHERE sessions.finished=0""",
                (session_id, json.dumps(payload)),
            )

    async def load_session(self, session_id):
        async with (
            self.lock,
            self.db.execute("SELECT payload FROM sessions WHERE id=?", (session_id,)) as cur,
        ):
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def unfinished_sessions(self):
        async with (
            self.lock,
            self.db.execute("SELECT payload FROM sessions WHERE finished=0") as cur,
        ):
            return [json.loads(row[0]) for row in await cur.fetchall()]

    async def finish_session(self, session_id, payload, attempts):
        payload = dict(payload, attempts=attempts, finalized=True)
        async with self._transaction():
            cursor = await self.db.execute(
                """INSERT INTO sessions(id,payload,finished) VALUES (?,?,1)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,finished=1,
                updated_at=strftime('%Y-%m-%dT%H:%M:%f','now') WHERE sessions.finished=0""",
                (session_id, json.dumps(payload)),
            )
            if cursor.rowcount:
                for user_id in payload.get("participants", []):
                    await self.db.execute(
                        "INSERT OR IGNORE INTO reviews VALUES (?,?)", (session_id, user_id)
                    )

    async def review(self, user_id, session_id=None):
        query = """SELECT s.payload FROM sessions s JOIN reviews r ON s.id=r.session_id
                   WHERE r.user_id=? AND s.finished=1"""
        args = [user_id]
        if session_id:
            query += " AND s.id=?"
            args.append(session_id)
        query += " ORDER BY s.updated_at DESC LIMIT 1"
        async with self.lock, self.db.execute(query, args) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def mark_delivery(self, session_id, user_id, status):
        async with self._transaction():
            await self.db.execute(
                "INSERT OR REPLACE INTO deliveries VALUES (?,?,?)", (session_id, user_id, status)
            )

    async def delivery_status(self, session_id, user_id):
        async with (
            self.lock,
            self.db.execute(
                "SELECT status FROM deliveries WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            ) as cur,
        ):
            row = await cur.fetchone()
        return row[0] if row else None

    async def allowed(self, guild_id, channel_id):
        async with (
            self.lock,
            self.db.execute(
                "SELECT channel_ids FROM guild_settings WHERE guild_id=?", (guild_id,)
            ) as cur,
        ):
            row = await cur.fetchone()
        return not row or not json.loads(row[0]) or channel_id in json.loads(row[0])

    async def set_channels(self, guild_id, channels):
        async with self._transaction():
            await self.db.execute(
                "INSERT OR REPLACE INTO guild_settings VALUES (?,?)",
                (guild_id, json.dumps(channels)),
            )

    async def report(self, user_id, session_id, question_id, reason):
        async with self._transaction():
            await self.db.execute(
                "INSERT INTO reports(user_id,session_id,question_id,reason) VALUES (?,?,?,?)",
                (user_id, session_id, question_id, reason),
            )

    async def stats(self, user_id):
        async with (
            self.lock,
            self.db.execute(
                """SELECT s.payload FROM sessions s JOIN reviews r ON s.id=r.session_id
            WHERE r.user_id=? AND s.finished=1""",
                (user_id,),
            ) as cur,
        ):
            return [json.loads(row[0]) for row in await cur.fetchall()]

    async def backup(self, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        async with self.lock, aiosqlite.connect(target) as destination:
            await self.db.backup(destination)
