"""Discord-independent game state machine."""

import asyncio
import time
from collections import deque
from typing import Any

from .models import Judgment, Question


class Session:
    def __init__(
        self,
        id: str,
        channel_id: int,
        starter_id: int,
        mode: str,
        settings: dict,
        questions: list[Question],
    ) -> None:
        if mode not in {"shared", "solo"}:
            raise ValueError("mode must be shared or solo")
        self.id, self.channel_id, self.starter_id, self.mode = id, channel_id, starter_id, mode
        self.settings = dict(settings)
        self.state = "ready"
        self.current: Question | None = None
        self.participants: set[int] = {starter_id}
        self.attempts: list[dict[str, Any]] = []
        self.round_id = 0
        self.winner_id: int | None = None
        self.lock = asyncio.Lock()
        self._queue: deque[Question] = deque(
            questions[: int(self.settings.get("count", len(questions)))]
        )
        self._deadline: float | None = None

    def _expired(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    async def next_question(self) -> Question | None:
        async with self.lock:
            if self.state in {"finished", "paused", "answering", "judging"}:
                return None
            if self.current is not None and self.state == "open":
                return self.current
            self.current = self._queue.popleft() if self._queue else None
            self.winner_id = None
            self._deadline = None
            if self.current is None:
                self.state = "finished"
                return None
            self.round_id += 1
            if self.mode == "solo":
                self.participants.add(self.starter_id)
                self.winner_id = self.starter_id
                self.state = "answering"
                self._deadline = None  # Solo practice is intentionally untimed.
            else:
                self.state = "open"
                self._deadline = time.monotonic() + float(self.settings.get("buzz_seconds", 30))
            return self.current

    async def buzz(self, user_id: int, round_id: int) -> bool:
        async with self.lock:
            if (
                self.state != "open"
                or self.current is None
                or round_id != self.round_id
                or self._expired()
            ):
                return False
            self.winner_id = user_id
            self.participants.add(user_id)
            self.state = "answering"
            self._deadline = time.monotonic() + float(self.settings.get("answer_seconds", 15))
            return True

    def _record(
        self,
        user_id: int,
        answer: str | None,
        verdict: str,
        explanation: str = "",
        method: str = "state",
        judge: Any | None = None,
    ) -> None:
        assert self.current is not None
        self.attempts.append(
            {
                "user_id": user_id,
                "question": self.current.to_dict(),
                "answer": answer,
                "verdict": verdict,
                "explanation": explanation,
                "round_id": self.round_id,
                "judging": {
                    "method": method,
                    "model": getattr(judge, "model", None),
                    "policy_version": getattr(judge, "policy_version", None),
                },
            }
        )

    async def submit(self, user_id: int, round_id: int, text: str, judge: Any) -> Judgment:
        async with self.lock:
            if (
                self.state != "answering"
                or self.current is None
                or self.winner_id != user_id
                or round_id != self.round_id
            ):
                return Judgment("ungraded", "This answer control is no longer active.", "state")
            if self._expired():
                self._record(user_id, None, "timeout", "Answer time expired.")
                self.state, self._deadline = "revealed", None
                return Judgment("ungraded", "Answer time expired.", "state")
            self.state = "judging"
            # Holding the lock makes pause/skip/timeout wait for the active verdict.
            try:
                verdict = await judge.judge(self.current, text)
            except Exception:  # noqa: BLE001 - adapter failures must never break a game.
                verdict = Judgment(
                    "ungraded",
                    "Sorry, I couldn't check that answer. This question won't count.",
                    "judge",
                )
            if verdict.verdict not in {"correct", "incorrect"}:
                verdict = Judgment("ungraded", verdict.explanation, verdict.method)
            self._record(user_id, text, verdict.verdict, verdict.explanation, verdict.method, judge)
            self.state, self._deadline = "revealed", None
            return verdict

    async def timeout(self, round_id: int) -> bool:
        async with self.lock:
            if (
                self.current is None
                or round_id != self.round_id
                or self.state not in {"open", "answering"}
            ):
                return False
            if not self._expired():
                return False
            if self.state == "answering" and self.winner_id is not None:
                self._record(self.winner_id, None, "timeout", "Answer time expired.")
            self.state, self._deadline = "revealed", None
            return True

    async def skip(self) -> None:
        async with self.lock:
            if self.current is not None and self.state in {"open", "answering"}:
                if self.mode == "solo":
                    self._record(
                        self.starter_id, None, "skipped", "Question revealed without an answer."
                    )
                self.state, self._deadline = "revealed", None

    async def pause(self) -> None:
        async with self.lock:
            if self.state not in {"finished", "paused"}:
                # An unfinished question is deliberately discarded; it remains absent from attempts.
                self.current, self.winner_id, self._deadline = None, None, None
                self.state = "paused"

    async def resume(self) -> Question | None:
        async with self.lock:
            if self.state != "paused":
                return None
            self.state = "ready"
        return await self.next_question()

    async def finish(self) -> None:
        async with self.lock:
            self.current, self.winner_id, self._deadline = None, None, None
            self.state = "finished"

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "starter_id": self.starter_id,
            "mode": self.mode,
            "settings": self.settings,
            "state": self.state,
            "current": self.current.to_dict() if self.current else None,
            "queue": [question.to_dict() for question in self._queue],
            "participants": sorted(self.participants),
            "attempts": self.attempts,
            "round_id": self.round_id,
            "winner_id": self.winner_id,
        }

    @classmethod
    def restore(cls, payload: dict[str, Any]) -> "Session":
        queue = [Question.from_dict(item) for item in payload.get("queue", [])]
        # Current is unfinished during recovery and intentionally never replayed.
        session = cls(
            payload["id"],
            payload["channel_id"],
            payload["starter_id"],
            payload["mode"],
            payload["settings"],
            queue,
        )
        session.participants = set(payload.get("participants", []))
        session.attempts = list(payload.get("attempts", []))
        session.round_id = int(payload.get("round_id", 0))
        session.state = "paused"
        return session

    def leaderboard(self) -> list[dict[str, Any]]:
        totals: dict[int, dict[str, Any]] = {}
        for user_id in self.participants:
            totals[user_id] = {
                "user_id": user_id,
                "points": 0,
                "correct": 0,
                "incorrect": 0,
                "timeout": 0,
            }
        for attempt in self.attempts:
            user_id = attempt["user_id"]
            if user_id not in totals:
                totals[user_id] = {
                    "user_id": user_id,
                    "points": 0,
                    "correct": 0,
                    "incorrect": 0,
                    "timeout": 0,
                }
            bucket = totals[user_id]
            if attempt["verdict"] == "correct":
                bucket["correct"] += 1
                bucket["points"] += 4
            elif attempt["verdict"] == "incorrect":
                bucket["incorrect"] += 1
            elif attempt["verdict"] == "timeout":
                bucket["timeout"] += 1
        rows = list(totals.values())
        for row in rows:
            graded = row["correct"] + row["incorrect"] + row["timeout"]
            row["accuracy"] = row["correct"] / graded if graded else None
        rows.sort(key=lambda row: (-row["points"], -row["correct"], row["user_id"]))
        previous: int | None = None
        rank = 0
        for index, row in enumerate(rows, start=1):
            if row["points"] != previous:
                rank = index
                previous = row["points"]
            row["rank"] = rank
        return rows
