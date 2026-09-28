import asyncio

from scibowl.engine import Session
from scibowl.models import Judgment, Question, default_settings


class Judge:
    async def judge(self, question, answer):
        return Judgment("correct" if answer == "yes" else "incorrect")


def q(number):
    return Question(str(number), f"q{number}", "yes", "Physics")


async def test_buzz_race_and_leaderboard():
    session = Session("s", 1, 99, "shared", default_settings(), [q(1)])
    await session.next_question()
    result = await asyncio.gather(session.buzz(1, 1), session.buzz(2, 1))
    assert sum(result) == 1
    winner = 1 if result[0] else 2
    assert (await session.submit(winner, 1, "yes", Judge())).verdict == "correct"
    assert session.leaderboard()[0]["points"] == 4


async def test_stale_and_restore_discard_current():
    session = Session("s", 1, 1, "solo", default_settings(), [q(1), q(2)])
    await session.next_question()
    assert not await session.buzz(1, 0)
    recovered = Session.restore(session.snapshot())
    assert recovered.state == "paused"
    assert (await recovered.resume()).id == "2"


async def test_timeout_and_pause_do_not_score():
    settings = default_settings()
    session = Session("s", 1, 1, "shared", settings, [q(1), q(2)])
    await session.next_question()
    assert await session.buzz(1, 1)
    session._deadline = 0
    assert await session.timeout(1)
    assert session.leaderboard()[0]["timeout"] == 1
    assert session.state == "open"
    await session.skip()
    await session.next_question()
    await session.pause()
    assert (await session.resume()) is None


async def test_solo_is_untimed_and_skip_is_idempotent():
    session = Session("s", 1, 1, "solo", default_settings(), [q(1)])
    await session.next_question()
    assert session._deadline is None
    await session.skip()
    await session.skip()
    assert len(session.attempts) == 1


async def test_judge_exception_becomes_ungraded_with_metadata():
    class BrokenJudge:
        model = "test-model"
        policy_version = "test-policy"

        async def judge(self, question, answer):
            raise RuntimeError("failure")

    session = Session("s", 1, 1, "solo", default_settings(), [q(1)])
    await session.next_question()
    assert (await session.submit(1, 1, "yes", BrokenJudge())).verdict == "ungraded"
    assert session.attempts[0]["judging"] == {
        "method": "judge",
        "model": "test-model",
        "policy_version": "test-policy",
    }


async def test_failed_player_locked_out_until_next_question():
    session = Session("s", 1, 1, "shared", default_settings(), [q(1), q(2)])
    await session.next_question()
    assert await session.buzz(1, 1)
    assert (await session.submit(1, 1, "no", Judge())).verdict == "incorrect"
    assert session.state == "open"
    assert session.winner_id is None
    assert (await session.next_question()).id == "1"
    assert not await session.buzz(1, 1)
    assert (await session.submit(1, 1, "yes", Judge())).verdict == "ungraded"
    claims = await asyncio.gather(session.buzz(2, 1), session.buzz(3, 1))
    assert sum(claims) == 1
    winner = 2 if claims[0] else 3
    await session.submit(winner, 1, "yes", Judge())
    assert session.state == "revealed"
    assert len(session.attempts) == 2
    assert (await session.next_question()).id == "2"
    assert session.locked_out == set()
    assert not await session.buzz(1, 1)
    assert await session.buzz(1, 2)
    await session.submit(1, 2, "yes", Judge())
    assert await session.next_question() is None
    row = next(row for row in session.leaderboard() if row["user_id"] == 1)
    assert (row["points"], row["incorrect"], row["accuracy"]) == (4, 1, 0.5)


async def test_configured_timeout_reopens_then_open_timeout_closes(monkeypatch):
    now = 100.0
    monkeypatch.setattr("scibowl.engine.time.monotonic", lambda: now)
    settings = {**default_settings(), "answer_seconds": 7, "buzz_seconds": 19}
    session = Session("s", 1, 1, "shared", settings, [q(1)])
    await session.next_question()
    assert await session.buzz(1, 1)
    assert session.remaining_seconds() == 7
    now = 106.9
    assert not await session.timeout(1)
    now = 107.0
    assert await session.timeout(1)
    assert session.state == "open"
    assert session.remaining_seconds() == 19
    assert not await session.buzz(1, 1)
    assert session.attempts[0]["verdict"] == "timeout"
    assert session.leaderboard()[0]["accuracy"] == 0
    assert not await session.timeout(1)
    now = 126.0
    assert await session.timeout(1)
    assert session.state == "revealed"
    assert len(session.attempts) == 1


async def test_expired_submit_records_timeout_once_and_allows_other_player():
    session = Session("s", 1, 1, "shared", default_settings(), [q(1)])
    await session.next_question()
    await session.buzz(1, 1)
    session._deadline = 0
    assert (await session.submit(1, 1, "yes", Judge())).verdict == "timeout"
    assert not await session.timeout(1)
    assert await session.buzz(2, 1)
    assert (await session.submit(1, 1, "yes", Judge())).verdict == "ungraded"
    assert len(session.attempts) == 1
    await session.submit(2, 1, "yes", Judge())
    assert [item["verdict"] for item in session.attempts] == ["timeout", "correct"]


async def test_restore_rebound_keeps_attempt_without_replaying_score():
    session = Session("s", 1, 1, "shared", default_settings(), [q(1), q(2)])
    await session.next_question()
    await session.buzz(1, 1)
    await session.submit(1, 1, "no", Judge())
    snapshot = session.snapshot()
    assert snapshot["locked_out"] == [1]
    recovered = Session.restore(snapshot)
    assert recovered.state == "paused"
    assert len(recovered.attempts) == 1
    assert (await recovered.resume()).id == "2"
    assert recovered.locked_out == set()
    assert await recovered.buzz(1, 2)
    await recovered.submit(1, 2, "yes", Judge())
    assert recovered.leaderboard()[0]["accuracy"] == 0.5


async def test_solo_incorrect_advances_and_shared_ungraded_closes():
    solo = Session("solo", 1, 1, "solo", default_settings(), [q(1), q(2)])
    await solo.next_question()
    await solo.submit(1, 1, "no", Judge())
    assert solo.state == "revealed"
    assert (await solo.next_question()).id == "2"

    class Unavailable:
        async def judge(self, question, answer):
            return Judgment("ungraded", "Sorry, unavailable.")

    shared = Session("shared", 1, 1, "shared", default_settings(), [q(1)])
    await shared.next_question()
    await shared.buzz(1, 1)
    await shared.submit(1, 1, "no", Unavailable())
    assert shared.state == "revealed"
    assert shared.leaderboard()[0]["accuracy"] is None
