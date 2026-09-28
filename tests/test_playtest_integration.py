import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from scibowl.discord_app import BowlBot
from scibowl.engine import Session
from scibowl.models import Judgment, Question, default_settings
from scibowl.session_messages import PrivateMessages


def interaction(user=10):
    return SimpleNamespace(
        user=SimpleNamespace(id=user),
        guild=object(),
        guild_id=99,
        channel_id=1,
        permissions=SimpleNamespace(manage_guild=False),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


@pytest.fixture
async def bot(tmp_path):
    client = BowlBot(tmp_path / "bank.sqlite3")
    await client.store.open()
    try:
        yield client
    finally:
        await client.close()


async def test_rebound_does_not_publish_answer_or_judge_explanation(bot):
    question = Question("q", "Name this gas", "HELIUM", "Physics")
    session = Session("game", 1, 10, "shared", default_settings(), [question])
    bot.sessions[1] = session
    channel = SimpleNamespace(
        id=1, send=AsyncMock(return_value=SimpleNamespace(id=123, edit=AsyncMock()))
    )
    bot.channels[1] = channel
    await bot.advance(session)
    assert await session.buzz(10, session.round_id)
    channel.send.reset_mock()
    bot.judge.judge = AsyncMock(return_value=Judgment("incorrect", "The answer is HELIUM", "groq"))
    await bot.submit_answer(interaction(), session, session.round_id, "wrong")
    assert session.state == "open"
    assert not await session.buzz(10, session.round_id)
    posted = [call.kwargs["embed"].description for call in channel.send.await_args_list]
    assert all("HELIUM" not in text and "Official answer" not in text for text in posted)
    assert (await bot.store.load_session(session.id))["attempts"][0]["verdict"] == "incorrect"
    assert await session.buzz(20, session.round_id)
    bot.judge.judge.return_value = Judgment("correct", "Matched", "local")
    await bot.submit_answer(interaction(20), session, session.round_id, "HELIUM")
    assert session.state == "revealed"
    assert any(
        "HELIUM" in call.kwargs["embed"].description for call in channel.send.await_args_list
    )


async def test_answer_deadline_reopens_through_adapter_timer(bot):
    settings = dict(default_settings(), answer_seconds=7)
    session = Session(
        "timer", 1, 10, "shared", settings, [Question("q", "Question", "SECRET", "Physics")]
    )
    bot.sessions[1] = session
    bot.channels[1] = SimpleNamespace(id=1, send=AsyncMock())
    await session.next_question()
    await session.buzz(10, session.round_id)
    session._deadline = time.monotonic() - 1
    bot.schedule_deadline(session)
    timer = bot.timers[session.id]
    await timer
    assert session.state == "open"
    assert session.attempts[0]["verdict"] == "timeout"
    assert session.leaderboard()[0]["accuracy"] == 0
    assert not await session.buzz(10, session.round_id)
    assert all(
        "SECRET" not in call.kwargs["embed"].description
        for call in bot.channels[1].send.await_args_list
    )


async def test_clear_scopes_messages_and_keeps_saved_results(bot):
    payload = {"id": "finished", "channel_id": 1, "starter_id": 10, "participants": [10]}
    await bot.store.finish_session("finished", payload, [])
    await bot.store.track_message("finished", 1, 101)
    await bot.store.track_message("other", 1, 202)
    delete = AsyncMock()
    request = interaction()
    request.channel = SimpleNamespace(
        get_partial_message=MagicMock(return_value=SimpleNamespace(delete=delete))
    )
    private, another_private = (
        SimpleNamespace(delete=AsyncMock()),
        SimpleNamespace(delete=AsyncMock()),
    )
    bot.private_messages.remember("finished", 10, private)
    bot.private_messages.remember("finished", 20, another_private)
    await bot.clear_session_messages(request)
    request.channel.get_partial_message.assert_called_once_with(101)
    delete.assert_awaited_once()
    private.delete.assert_awaited_once()
    another_private.delete.assert_not_awaited()
    assert await bot.store.session_messages("finished") == []
    assert len(await bot.store.session_messages("other")) == 1
    assert await bot.store.review(10, "finished") is not None


async def test_clear_rejects_other_players_and_active_games(bot):
    payload = {"id": "finished", "channel_id": 1, "starter_id": 10, "participants": [10]}
    await bot.store.finish_session("finished", payload, [])
    await bot.store.track_message("finished", 1, 101)
    other = interaction(20)
    await bot.clear_session_messages(other)
    assert "Only the session starter" in other.followup.send.await_args.args[0]
    bot.sessions[1] = object()
    owner = interaction()
    await bot.clear_session_messages(owner)
    assert "Stop the active game" in owner.followup.send.await_args.args[0]
    assert len(await bot.store.session_messages("finished")) == 1


async def test_private_cleanup_expires_without_persisting_tokens(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("scibowl.session_messages.time.monotonic", lambda: now[0])
    messages = PrivateMessages()
    expired = SimpleNamespace(delete=AsyncMock())
    messages.remember("s", 10, expired)
    now[0] = 841
    assert await messages.clear("s", 10) == (0, 0)
    expired.delete.assert_not_awaited()
    assert not messages.entries
