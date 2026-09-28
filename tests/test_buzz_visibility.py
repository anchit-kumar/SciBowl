import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from scibowl.discord_app import BowlBot, QuestionView
from scibowl.engine import Session
from scibowl.models import Judgment, Question, default_settings


def request(user=10):
    return SimpleNamespace(
        user=SimpleNamespace(id=user),
        response=SimpleNamespace(defer=AsyncMock(), send_modal=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


@pytest.fixture
async def game(tmp_path, monkeypatch):
    bot = BowlBot(tmp_path / "visibility.sqlite3")
    await bot.store.open()
    bot.schedule_deadline = MagicMock()
    session = Session(
        "game",
        1,
        10,
        "shared",
        dict(default_settings(), buzz_seconds=47),
        [
            Question(
                "q",
                "Public question " * 300,
                "helium",
                "Physics",
                format="multiple_choice",
                choices={"W": "helium", "X": "oxygen"},
            ),
            Question("next", "Next question", "next answer", "Physics"),
        ],
    )
    bot.sessions[1] = session
    messages = []

    async def send(**kwargs):
        message = SimpleNamespace(id=100 + len(messages), delete=AsyncMock(), edit=AsyncMock())
        messages.append(message)
        return message

    bot.channels[1] = SimpleNamespace(id=1, send=AsyncMock(side_effect=send))
    release = asyncio.Event()
    sleep_started = asyncio.Event()
    original_sleep = asyncio.sleep

    async def sleep(seconds):
        if seconds == session.settings.get("hide_seconds", 0.5):
            sleep_started.set()
            await release.wait()
        else:
            await original_sleep(seconds)

    monkeypatch.setattr("scibowl.discord_app.asyncio.sleep", sleep)
    await bot.advance(session)
    try:
        yield bot, session, release, sleep_started
    finally:
        await bot.close()


async def buzz_and_hide(game):
    bot, session, release, started = game
    original = list(bot.question_messages[session.id])
    interaction = request()
    await QuestionView(bot, session).buzz(interaction)
    await started.wait()
    assert all(message.delete.await_count == 0 for message in original)
    task = bot.hide_tasks[session.id]
    release.set()
    assert await task is True
    return original, interaction


async def test_deletes_all_chunks_after_default_half_second_and_keeps_private_answer(game):
    bot, session, _, _ = game
    original, interaction = await buzz_and_hide(game)
    assert len(original) > 1
    for message in original:
        message.delete.assert_awaited_once()
    assert session.id not in bot.messages
    ack = interaction.followup.send.await_args
    assert ack.kwargs["ephemeral"] is True
    assert "0.5 seconds" in ack.args[0]
    view = ack.kwargs["view"]
    assert [item.label for item in view.children] == ["Answer"]
    answer = request()
    await view.answer(answer)
    answer.response.send_modal.assert_awaited_once()


@pytest.mark.parametrize("delay", [0, 1.25])
async def test_custom_hide_delay_is_used_without_waiting_for_real_time(game, delay):
    _, session, _, _ = game
    session.settings["hide_seconds"] = delay
    original, interaction = await buzz_and_hide(game)
    assert all(message.delete.await_count == 1 for message in original)
    assert f"{delay:g} seconds" in interaction.followup.send.await_args.args[0]


@pytest.mark.parametrize("verdict", ["correct", "incorrect", "ungraded"])
async def test_restores_full_question_after_verdict_and_resets_rebound_clock(game, verdict):
    bot, session, _, _ = game
    original, _ = await buzz_and_hide(game)
    expected = session.current.text + "\n\nW) helium\nX) oxygen"
    bot.channels[1].send.reset_mock()
    bot.judge.judge = AsyncMock(return_value=Judgment(verdict, "Verdict", "local"))
    await bot.submit_answer(request(), session, session.round_id, "response")
    posted = bot.channels[1].send.await_args_list
    restored = [
        c.kwargs["embed"].description
        for c in posted
        if c.kwargs["embed"].title.startswith("Question")
    ]
    assert "".join(restored) == expected
    assert bot.question_messages[session.id] != original
    if verdict == "incorrect":
        assert session.state == "open"
        assert 46 < session.remaining_seconds() <= 47
        assert not await session.buzz(10, session.round_id)
        assert await session.buzz(20, session.round_id)
        assert all("Official answer:" not in c.kwargs["embed"].description for c in posted)
    else:
        assert session.state == "revealed"
        assert any("Official answer: helium" in c.kwargs["embed"].description for c in posted)


async def test_early_wrong_answer_cancels_pending_delete_and_resets_timer(game):
    bot, session, release, _ = game
    original = list(bot.question_messages[session.id])
    await QuestionView(bot, session).buzz(request())
    old_task = bot.hide_tasks[session.id]
    bot.judge.judge = AsyncMock(return_value=Judgment("incorrect", "Wrong", "local"))
    await bot.submit_answer(request(), session, session.round_id, "X")
    release.set()
    assert old_task.cancelled()
    assert all(message.delete.await_count == 0 for message in original)
    assert session.state == "open"
    assert 46 < session.remaining_seconds() <= 47


async def test_question_is_deleted_even_while_judging_holds_operation_lock(game):
    bot, session, release, _ = game
    await QuestionView(bot, session).buzz(request())
    judging = asyncio.Event()
    finish = asyncio.Event()

    async def judge(*args):
        judging.set()
        await finish.wait()
        return Judgment("correct", "Correct", "local")

    bot.judge.judge = judge
    submission = asyncio.create_task(bot.submit_answer(request(), session, session.round_id, "W"))
    try:
        await judging.wait()
        assert session.state == "judging"
        release.set()
        assert await bot.hide_tasks[session.id] is True
        assert session.id not in bot.messages
    finally:
        finish.set()
        await submission
    assert session.state == "revealed"
    assert session.id in bot.messages


async def test_answer_timeout_restores_question_and_reopens(game):
    bot, session, _, _ = game
    await buzz_and_hide(game)
    session._deadline = 0
    assert await session.timeout(session.round_id)
    await bot.reopen_question(session, "Answer time expired.")
    assert session.state == "open"
    assert session.attempts[0]["verdict"] == "timeout"
    assert session.id in bot.messages
    assert 46 < session.remaining_seconds() <= 47


async def test_inflight_deletion_finishes_before_question_is_restored(game):
    bot, session, release, _ = game
    deleting = asyncio.Event()
    finish_delete = asyncio.Event()
    first = bot.question_messages[session.id][0]

    async def slow_delete():
        deleting.set()
        await finish_delete.wait()

    first.delete.side_effect = slow_delete
    await QuestionView(bot, session).buzz(request())
    release.set()
    await deleting.wait()
    bot.judge.judge = AsyncMock(return_value=Judgment("incorrect", "Wrong", "local"))
    submission = asyncio.create_task(bot.submit_answer(request(), session, session.round_id, "X"))
    finish_delete.set()
    await submission
    assert session.state == "open"
    assert bot.question_messages[session.id][0] is not first


async def test_delete_failure_pauses_without_timeout_penalty(game):
    bot, session, release, _ = game
    bot.question_messages[session.id][0].delete.side_effect = discord.Forbidden(
        MagicMock(status=403, reason="Forbidden", headers={}), "denied"
    )
    await QuestionView(bot, session).buzz(request())
    release.set()
    assert await bot.hide_tasks[session.id] is False
    await asyncio.gather(*list(bot.background))
    assert session.state == "paused"
    assert session.attempts == []


async def test_stop_cancels_pending_deletion_and_cleans_message_tracking(game):
    bot, session, release, _ = game
    original = list(bot.question_messages[session.id])
    await QuestionView(bot, session).buzz(request())
    task = bot.hide_tasks[session.id]
    bot.deliver_reviews = AsyncMock()
    await bot.finalize(session, early=True)
    release.set()
    assert task.cancelled()
    assert all(message.delete.await_count == 0 for message in original)
    assert session.id not in bot.question_messages
    assert session.id not in bot.answer_views
