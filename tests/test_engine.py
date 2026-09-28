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
