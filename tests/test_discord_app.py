import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from scibowl.discord_app import BowlBot, QuestionView
from scibowl.engine import Session
from scibowl.models import Question, default_settings


def payload(session_id="game-1", participants=(10,)):
    return {
        "id": session_id,
        "participants": list(participants),
        "attempts": [
            {
                "user_id": 10,
                "verdict": "incorrect",
                "answer": "wrong",
                "explanation": "expected answer",
                "question": {
                    "category": "Physics",
                    "source": "DOE",
                    "page": 1,
                    "text": "What is this?",
                    "choices": {},
                    "answer": "right",
                },
            }
        ],
    }


def interaction(user_id=10, custom_id=None):
    response = SimpleNamespace(
        send_message=AsyncMock(),
        edit_message=AsyncMock(),
        is_done=MagicMock(return_value=False),
        defer=AsyncMock(),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=response,
        followup=SimpleNamespace(send=AsyncMock()),
        data={"custom_id": custom_id} if custom_id else {},
        channel_id=1,
    )


async def test_command_tree_constructs_offline(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        commands = {command.name: command for command in bot.tree.get_commands()}
        assert {
            "game",
            "practice",
            "admin",
            "settings",
            "answer",
            "review",
            "score",
            "sources",
            "clear",
            "stats",
            "status",
            "help",
        } <= set(commands)
        assert "report" not in commands
        assert {command.name for command in commands["game"].commands} == {
            "start",
            "pause",
            "resume",
            "skip",
            "stop",
        }
        assert {command.name for command in commands["practice"].commands} == {"start", "stop"}
    finally:
        await bot.close()


async def test_game_start_uses_explicit_values_over_personal_defaults(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        saved = default_settings("shared")
        saved.update(
            {
                "count": 7,
                "categories": ["Physics"],
                "pool": "all",
                "buzz_seconds": 20,
                "hide_seconds": 1.5,
            }
        )
        bot.store.get_settings = AsyncMock(return_value=saved)
        bot.store.sources = AsyncMock(return_value=[])
        bot.start_session = AsyncMock()
        command = next(item for item in bot.tree.get_commands() if item.name == "game").get_command(
            "start"
        )
        request = interaction()

        await command.callback(
            request,
            count=11,
            category="Chemistry",
            pool=None,
            source=None,
            format=None,
            buzz_seconds=None,
            answer_seconds=40,
            hide_seconds=0.75,
        )

        bot.start_session.assert_not_awaited()
        panel = request.followup.send.await_args.kwargs["view"]
        resolved = panel.settings
        assert panel.mode == "shared"
        assert resolved["count"] == 11
        assert resolved["categories"] == ["Chemistry"]
        assert resolved["pool"] == "all"
        assert resolved["buzz_seconds"] == 20
        assert resolved["answer_seconds"] == 40
        assert resolved["hide_seconds"] == 0.75
        assert resolved["role"] == "tossup"
    finally:
        await bot.close()


async def test_review_owner_rejection_and_missing_review_are_ephemeral(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        other = interaction(user_id=99, custom_id="review:game-1:10:0:missed")
        await bot.on_interaction(other)
        other.response.send_message.assert_awaited_once_with(
            "This review belongs to another player.", ephemeral=True
        )

        bot.store.review = AsyncMock(return_value=None)
        owner = interaction(user_id=10)
        await bot.show_review(owner, "game-1")
        owner.response.send_message.assert_awaited_once_with(
            "No saved review found for you.", ephemeral=True
        )
    finally:
        await bot.close()


async def test_review_dm_opt_out_skips_delivery_and_enabled_sends(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        stored = []

        async def dm_enabled(user_id):
            return user_id == 11

        async def mark_delivery(session_id, user_id, status):
            stored.append((session_id, user_id, status))

        bot.store.dm_enabled = dm_enabled
        bot.store.delivery_status = AsyncMock(return_value=None)
        bot.store.mark_delivery = mark_delivery
        user = SimpleNamespace(send=AsyncMock())
        with patch.object(bot, "get_user", return_value=user):
            await bot.deliver_reviews(payload(participants=(10, 11)))

        assert ("game-1", 10, "opted_out") in stored
        assert ("game-1", 11, "sent") in stored
        user.send.assert_awaited_once()
        assert user.send.await_args.kwargs["content"].startswith("Your Science Bowl review")
    finally:
        await bot.close()


async def test_manual_finish_with_no_attempts_persists_and_posts_leaderboard(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        session = Session("empty-game", 1, 10, "solo", default_settings("solo"), [])
        channel = SimpleNamespace(send=AsyncMock())
        bot.sessions[session.channel_id] = session
        bot.resolve_channel = AsyncMock(return_value=channel)
        bot.store.finish_session = AsyncMock()

        def consume(coroutine):
            coroutine.close()

        bot.spawn = consume
        await bot.finalize(session, early=True)

        bot.store.finish_session.assert_awaited_once()
        saved = bot.store.finish_session.await_args.args[1]
        assert saved["ended_early"] is True
        assert saved["leaderboard"] == [
            {
                "user_id": 10,
                "points": 0,
                "correct": 0,
                "incorrect": 0,
                "timeout": 0,
                "accuracy": None,
                "rank": 1,
            }
        ]
        channel.send.assert_awaited_once()
        assert "<@10>" in channel.send.await_args.kwargs["embed"].description
        assert "0 pts" in channel.send.await_args.kwargs["embed"].description
        assert session.channel_id not in bot.sessions
    finally:
        await bot.close()


async def test_solo_question_is_selected_for_the_starter_without_a_deadline():
    session = Session(
        "solo-1",
        5,
        10,
        "solo",
        default_settings("solo"),
        [Question("q1", "question", "answer", "Physics")],
    )

    selected = await session.next_question()

    assert selected.id == "q1"
    assert session.state == "answering"
    assert session.winner_id == 10
    assert session._deadline is None


async def test_unavailable_recovered_channel_keeps_session_paused(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        session = Session("recovered", 1, 10, "shared", default_settings("shared"), [])
        await session.pause()
        bot.sessions[session.channel_id] = session
        response = MagicMock(status=404, reason="Not Found", headers={})
        bot.resolve_channel = AsyncMock(side_effect=discord.NotFound(response, "missing"))
        request = interaction(user_id=10)
        request.guild = object()
        request.permissions = SimpleNamespace(manage_guild=False)

        await bot.control(request, "resume")

        assert session.state == "paused"
        request.followup.send.assert_awaited_once_with(
            "The session channel is unavailable. Restore permissions before resuming.",
            ephemeral=True,
        )
    finally:
        await bot.close()


def forbidden():
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden", headers={}), "denied")


async def test_finish_survives_message_edit_and_leaderboard_delivery_failures(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        await bot.store.open()
        session = Session("delivery-failure", 1, 10, "solo", default_settings("solo"), [])
        bot.sessions[1] = session
        bot.messages[session.id] = SimpleNamespace(edit=AsyncMock(side_effect=forbidden()))
        channel = SimpleNamespace(send=AsyncMock(side_effect=forbidden()))
        bot.resolve_channel = AsyncMock(return_value=channel)
        bot.deliver_reviews = AsyncMock()

        await bot.finalize(session, early=True)
        await asyncio.gather(*list(bot.background))

        channel.send.assert_awaited_once()
        bot.deliver_reviews.assert_awaited_once()
        saved = await bot.store.review(10, session.id)
        assert saved["leaderboard"][0]["user_id"] == 10
        assert saved["state"] == "finished"
        assert 1 not in bot.sessions
        assert session.id not in bot.messages
    finally:
        await bot.close()


async def test_failed_question_delivery_pauses_without_starting_timer(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        await bot.store.open()
        session = Session(
            "question-failure",
            1,
            10,
            "shared",
            default_settings("shared"),
            [Question("q1", "Question", "answer", "Physics")],
        )
        bot.sessions[1] = session
        bot.channels[1] = SimpleNamespace(send=AsyncMock(side_effect=forbidden()))

        await bot.advance(session)

        assert session.state == "paused"
        assert session.id not in bot.timers
        assert (await bot.store.load_session(session.id))["state"] == "paused"
        assert session.attempts == []
    finally:
        await bot.close()


async def test_failed_result_delivery_keeps_judgment_and_pauses(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        await bot.store.open()
        session = Session(
            "result-failure",
            1,
            10,
            "solo",
            default_settings("solo"),
            [Question("q1", "Question", "answer", "Physics")],
        )
        await session.next_question()
        await session.submit(10, session.round_id, "answer", bot.judge)
        bot.sessions[1] = session
        bot.channels[1] = SimpleNamespace(send=AsyncMock(side_effect=forbidden()))

        await bot.reveal(session, "Correct")

        saved = await bot.store.load_session(session.id)
        assert saved["state"] == "paused"
        assert saved["attempts"][0]["verdict"] == "correct"
        assert session.leaderboard()[0]["points"] == 4
    finally:
        await bot.close()


async def test_maintenance_continues_after_backup_and_session_failures(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        sessions = [
            Session(f"idle-{i}", i, 10, "shared", default_settings("shared"), []) for i in (1, 2)
        ]
        bot.sessions = {s.channel_id: s for s in sessions}
        bot.store.backup = AsyncMock(side_effect=OSError("disk unavailable"))
        bot.finalize = AsyncMock(side_effect=[RuntimeError("transient failure"), None])
        with (
            patch.object(bot, "wait_until_ready", new=AsyncMock()),
            patch("scibowl.discord_app.time.monotonic", return_value=4000),
            patch(
                "scibowl.discord_app.asyncio.sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await bot.maintenance()

        assert bot.finalize.await_count == 2
        assert bot.finalize.await_args.args[0] is sessions[1]
    finally:
        await bot.close()


async def test_queued_reveal_cannot_skip_a_new_solo_round(tmp_path):
    bot = BowlBot(tmp_path / "bot.sqlite3")
    try:
        session = Session(
            "solo-race",
            1,
            10,
            "solo",
            default_settings("solo"),
            [Question("q1", "First", "one", "Physics"), Question("q2", "Second", "two", "Physics")],
        )
        await session.next_question()
        stale_view = QuestionView(bot, session)
        await session.skip()
        await session.next_question()
        bot.reveal = AsyncMock()

        await stale_view.reveal(interaction())

        assert session.state == "answering"
        assert session.current.id == "q2"
        assert len(session.attempts) == 1
        bot.reveal.assert_not_awaited()
    finally:
        await bot.close()
