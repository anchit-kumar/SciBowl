"""Offline regressions for runtime lifecycle failures found during review."""

import asyncio
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from scibowl.discord_app import BowlBot, QuestionView
from scibowl.engine import Session
from scibowl.models import Question, default_settings


def request():
    return SimpleNamespace(
        user=SimpleNamespace(id=10),
        guild=object(),
        guild_id=100,
        channel_id=1,
        permissions=SimpleNamespace(manage_guild=False),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def game(mode="shared", session_id="audit", channel_id=1):
    return Session(
        session_id,
        channel_id,
        10,
        mode,
        default_settings(mode),
        [Question("q1", "First?", "A", "Physics"), Question("q2", "Second?", "B", "Physics")],
    )


def forbidden():
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden", headers={}), "denied")


@pytest.fixture
async def bot(tmp_path):
    client = BowlBot(tmp_path / "runtime.sqlite3")
    try:
        yield client
    finally:
        await client.close()


async def test_slow_delivery_gives_complete_question_full_buzz_window(bot):
    session = game()
    bot.sessions[1] = session
    bot.persist = AsyncMock()
    now = [100.0]

    async def slow_send(**kwargs):
        now[0] += 40
        return SimpleNamespace(edit=AsyncMock())

    bot.channels[1] = SimpleNamespace(send=slow_send)
    bot.schedule_deadline = MagicMock()
    with patch("scibowl.engine.time.monotonic", side_effect=lambda: now[0]):
        await bot.advance(session)
        assert session.remaining_seconds() == session.settings["buzz_seconds"]
        assert await session.buzz(10, session.round_id)


async def test_timer_accounts_for_elapsed_answer_delivery_time(bot):
    session = game()
    await session.next_question()
    await session.buzz(10, session.round_id)
    with patch.object(session, "remaining_seconds", return_value=2.0):
        bot.schedule_deadline(session)
    with patch("scibowl.discord_app.asyncio.sleep", new=AsyncMock()) as sleep:
        await bot.timers[session.id]
    sleep.assert_awaited_once_with(2.05)


async def test_practice_stop_works_from_shared_game_channel(bot):
    shared, solo = game(), game("solo", "private", 2)
    bot.sessions = {1: shared, 2: solo}
    bot.finalize = AsyncMock()
    await bot.control(request(), "stop", "solo")
    bot.finalize.assert_awaited_once_with(solo, early=True)


async def test_queued_control_rechecks_active_session_after_acquiring_lock(bot):
    session = game()
    bot.sessions[1] = session
    bot.persist = AsyncMock()
    interaction = request()
    async with bot.operation_lock(session):
        pending = asyncio.create_task(bot.control(interaction, "pause"))
        await asyncio.sleep(0)
        bot.sessions.pop(1)
        await session.finish()
    await pending
    bot.persist.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with(
        "No matching active session.", ephemeral=True
    )


async def test_queued_stop_cannot_end_a_new_round(bot):
    session = game("solo")
    bot.sessions[1] = session
    await session.next_question()
    old = QuestionView(bot, session)
    await session.skip()
    await session.next_question()
    bot.finalize = AsyncMock()
    await old.stop_game(request())
    bot.finalize.assert_not_awaited()


@pytest.mark.parametrize("action", ["buzz", "reveal", "next_question", "stop_game", "submit"])
async def test_replaced_sessions_cannot_be_mutated_by_queued_controls(bot, action):
    session = game("shared" if action == "buzz" else "solo")
    await session.next_question()
    view = QuestionView(bot, session)
    if action == "next_question":
        await session.skip()
    bot.sessions[1] = game(session_id="replacement")
    before = deepcopy(session.snapshot())
    bot.persist = AsyncMock()
    bot.advance = AsyncMock()
    bot.reveal = AsyncMock()
    bot.finalize = AsyncMock()
    if action == "submit":
        await bot.submit_answer(request(), session, session.round_id, "A")
    else:
        await getattr(view, action)(request())
    assert session.snapshot() == before
    bot.persist.assert_not_awaited()
    bot.advance.assert_not_awaited()
    bot.reveal.assert_not_awaited()
    bot.finalize.assert_not_awaited()


async def test_replaced_and_finished_question_views_stop_dispatching(bot):
    session = game("solo")
    await session.next_question()
    old = bot.question_view(session)
    bot._connection.store_view(old, 100)
    replacement = bot.question_view(session)
    assert old.is_finished()
    assert 100 not in bot._connection._view_store._views
    bot._connection.store_view(replacement, 101)
    await session.finish()
    await bot.update_controls(session)
    assert replacement.is_finished()
    assert 101 not in bot._connection._view_store._views
    assert session.id not in bot.question_views


async def test_failed_save_pauses_and_resume_retains_judgment(bot):
    await bot.store.open()
    session = game("solo")
    bot.sessions[1] = session
    bot.channels[1] = SimpleNamespace(send=AsyncMock())
    await session.next_question()
    await bot.persist(session)
    interaction = request()
    with patch.object(
        bot.store,
        "save_session",
        new=AsyncMock(side_effect=sqlite3.OperationalError("disk full")),
    ):
        await bot.submit_answer(interaction, session, session.round_id, "A")
    assert session.state == "paused"
    assert session.leaderboard()[0]["points"] == 4
    assert "held in memory" in interaction.followup.send.await_args.args[0]
    await session.resume()
    await bot.advance(session, already_open=True)
    saved = await bot.store.load_session(session.id)
    assert len(saved["attempts"]) == 1
    assert saved["attempts"][0]["verdict"] == "correct"


async def test_start_acknowledgment_failure_still_opens_first_question(bot):
    interaction = request()
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = 1
    interaction.channel.mention = "<#1>"
    interaction.followup.send.side_effect = forbidden()
    bot.store.allowed = AsyncMock(return_value=True)
    bot.store.questions = AsyncMock(return_value=[Question("q", "Q", "A", "Physics")])
    bot.persist = AsyncMock()
    bot.advance = AsyncMock()
    await bot.start_session(interaction, "shared", default_settings())
    bot.advance.assert_awaited_once_with(bot.sessions[1])


async def test_old_finalization_keeps_replacement_session_channel_cache(bot):
    session, replacement = game(), game(session_id="new")
    bot.sessions[1] = session
    bot.channels[1] = object()
    replacement_channel = object()
    bot.store.finish_session = AsyncMock()
    bot.resolve_channel = AsyncMock(return_value=object())
    bot.deliver_reviews = AsyncMock()

    async def post_and_start_new(channel, payload):
        bot.sessions[1] = replacement
        bot.channels[1] = replacement_channel

    bot.post_leaderboard = post_and_start_new
    bot.operation_lock(session)
    await bot.finalize(session)
    assert bot.sessions[1] is replacement
    assert bot.channels[1] is replacement_channel
    assert session.id not in bot.operations
