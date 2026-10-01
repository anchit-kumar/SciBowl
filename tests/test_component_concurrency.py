"""Concurrency regressions for Discord component dispatch and acknowledgements."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from scibowl.discord_app import BowlBot, QuestionView
from scibowl.engine import Session
from scibowl.models import Judgment, Question, default_settings
from scibowl.ui import SettingsView


class Response:
    def __init__(self):
        self.done = False
        self.defer = AsyncMock(side_effect=self._done)
        self.send_message = AsyncMock(side_effect=self._done)
        self.send_modal = AsyncMock(side_effect=self._done)
        self.edit_message = AsyncMock(side_effect=self._done)

    def _done(self, *args, **kwargs):
        self.done = True

    def is_done(self):
        return self.done


def request(user=10, channel=1, custom_id=""):
    return SimpleNamespace(
        user=SimpleNamespace(id=user),
        channel_id=channel,
        data={"custom_id": custom_id},
        response=Response(),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
        message=SimpleNamespace(id=99, edit=AsyncMock()),
    )


@pytest.fixture
async def bot(tmp_path):
    app = BowlBot(tmp_path / "components.sqlite3")
    await app.store.open()
    messages = []

    async def send(**kwargs):
        message = SimpleNamespace(id=100 + len(messages), edit=AsyncMock(), delete=AsyncMock())
        messages.append(message)
        return message

    app.channels[1] = SimpleNamespace(id=1, send=AsyncMock(side_effect=send))
    try:
        yield app
    finally:
        await app.close()


def shared_game(app, *, mode="shared", starter=10):
    session = Session(
        "component-game",
        1,
        starter,
        mode,
        default_settings(mode),
        [
            Question("q1", "Name the element", "helium", "Chemistry"),
            Question("q2", "Next question", "oxygen", "Chemistry"),
        ],
    )
    app.sessions[1] = session
    return session


async def click(app, view, user, action="buzz", channel=1):
    custom_id = next(
        item.custom_id for item in view.children if item.custom_id.endswith(f":{action}")
    )
    interaction = request(user, channel, custom_id)
    # A finished layout is skipped by message.send and is unknown to the view store;
    # the gateway still emits on_interaction for the app's central dispatcher.
    app._connection._view_store.dispatch_view(
        discord.ComponentType.button.value, custom_id, interaction
    )
    await app.on_interaction(interaction)
    return interaction


async def test_finished_view_dispatch_and_many_buzzes_ack_before_edit_with_one_winner(bot):
    session = shared_game(bot)
    await session.next_question()
    view = QuestionView(bot, session)
    assert view.is_finished()
    assert next(x.custom_id for x in view.children if x.label == "Buzz") == (
        f"game:{session.id}:{session.round_id}:buzz"
    )
    # Sending a finished View does not register its bound callbacks, as with real send().
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_edit(*args, **kwargs):
        entered.set()
        await release.wait()

    bot.schedule_question_hide = MagicMock()
    bot.persist = AsyncMock()
    bot.messages[session.id] = SimpleNamespace(edit=AsyncMock(side_effect=delayed_edit))
    bot.schedule_deadline = MagicMock()
    bot.private_reply = AsyncMock()
    bot.send_session_message = AsyncMock()
    interactions = [
        request(i, custom_id=f"game:{session.id}:{session.round_id}:buzz") for i in range(15)
    ]
    all_deferred = asyncio.Event()
    deferred_count = 0

    async def acknowledge(interaction, *args, **kwargs):
        nonlocal deferred_count
        interaction.response.done = True
        deferred_count += 1
        if deferred_count == len(interactions):
            all_deferred.set()

    def deferred_response(interaction):
        async def defer(*args, **kwargs):
            await acknowledge(interaction, *args, **kwargs)

        return defer

    for interaction in interactions:
        interaction.response.defer = AsyncMock(side_effect=deferred_response(interaction))
    calls = []
    for interaction in interactions:
        bot._connection._view_store.dispatch_view(
            discord.ComponentType.button.value, interaction.data["custom_id"], interaction
        )
        calls.append(asyncio.create_task(bot.on_interaction(interaction)))
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(all_deferred.wait(), 1)
    assert all(i.response.is_done() and i.response.defer.await_count == 1 for i in interactions)
    release.set()
    await asyncio.gather(*calls)
    assert sum(i.user.id == session.winner_id for i in interactions) == 1
    assert session.winner_id in range(15)
    assert all(
        i.response.defer.await_count + i.response.send_message.await_count == 1
        for i in interactions
    )


async def test_restored_round_rejects_old_button_and_current_button_can_claim(bot):
    session = shared_game(bot)
    await session.next_question()
    bot.schedule_deadline = MagicMock()
    bot.schedule_question_hide = MagicMock()
    await bot.post_question(session)
    old = bot.question_views[session.id]
    assert await session.buzz(10, session.round_id)
    await session.submit(
        10,
        session.round_id,
        "wrong",
        SimpleNamespace(judge=AsyncMock(return_value=Judgment("incorrect", "Incorrect", "local"))),
    )
    bot.hidden_questions.add(session.id)
    bot.update_controls = AsyncMock(wraps=bot.update_controls)
    await bot.reopen_question(session, "Incorrect answer.")
    restored = bot.question_views[session.id]
    assert restored is not old
    assert [x.custom_id for x in restored.children] == [x.custom_id for x in old.children]
    bot.update_controls.assert_not_awaited()
    denied = await click(bot, restored, 10)
    assert denied.followup.send.await_args.kwargs["ephemeral"] is True
    valid = await click(bot, restored, 20)
    assert session.winner_id == 20
    assert valid.response.defer.await_count == 1
    await session.skip()
    await session.next_question()
    stale = await click(bot, old, 10)
    assert stale.response.is_done()
    assert "invalid or expired" in stale.response.send_message.await_args.args[0]


async def test_restart_wrong_channel_locked_out_and_solo_owner_checks_are_private(bot):
    missing = request(10, custom_id="game:gone:1:buzz")
    await bot.on_interaction(missing)
    assert missing.response.send_message.await_count == 1

    shared = shared_game(bot)
    await shared.next_question()
    wrong_channel = await click(bot, QuestionView(bot, shared), 10, channel=2)
    assert wrong_channel.response.send_message.await_count == 1

    shared.locked_out.add(11)
    bot.schedule_question_hide = MagicMock()
    bot.persist = AsyncMock()
    bot.update_controls = AsyncMock()
    bot.schedule_deadline = MagicMock()
    bot.private_reply = AsyncMock()
    bot.send_session_message = AsyncMock()
    locked_out = await click(bot, QuestionView(bot, shared), 11)
    assert locked_out.response.defer.await_count == 1
    assert bot.private_reply.await_count == 1

    solo = shared_game(bot, mode="solo", starter=10)
    await solo.next_question()
    nonowner = await click(bot, QuestionView(bot, solo), 20, "stop")
    assert nonowner.response.send_message.await_count == 1
    assert "no longer available" in nonowner.response.send_message.await_args.args[0]

    failed_session = shared_game(bot)
    await failed_session.next_question()
    bot.persist = AsyncMock(side_effect=RuntimeError("storage broke"))
    failed = request(10, custom_id=f"game:{failed_session.id}:{failed_session.round_id}:buzz")
    await bot.on_interaction(failed)
    assert failed.response.defer.await_count == 1
    assert failed.followup.send.await_count == 1
    assert failed.followup.send.await_args.kwargs["ephemeral"] is True


async def test_review_and_board_defer_before_slow_database_reads(bot):
    review_entered, review_release = asyncio.Event(), asyncio.Event()

    async def slow_review(*args):
        review_entered.set()
        await review_release.wait()

    bot.store.review = slow_review
    review = request(10, custom_id="reviewopen:some-game")
    task = asyncio.create_task(bot.on_interaction(review))
    await asyncio.wait_for(review_entered.wait(), 1)
    assert review.response.defer.await_count == 1
    review_release.set()
    await task
    assert review.response.defer.await_count + review.response.send_message.await_count == 1

    board_entered, board_release = asyncio.Event(), asyncio.Event()

    async def slow_load(_session_id):
        board_entered.set()
        await board_release.wait()

    bot.store.load_session = slow_load
    board = request(10, custom_id="board:some-game:0")
    task = asyncio.create_task(bot.on_interaction(board))
    await asyncio.wait_for(board_entered.wait(), 1)
    assert board.response.defer.await_count == 1
    board_release.set()
    await task
    assert board.response.defer.await_count == 1
    assert board.followup.send.await_count == 1


async def test_answer_modal_is_immediate_and_stale_modal_submission_is_rejected(bot):
    session = shared_game(bot)
    await session.next_question()
    assert await session.buzz(10, session.round_id)
    view = QuestionView(bot, session)
    lock = bot.operation_lock(session)
    await lock.acquire()
    try:
        interaction = await click(bot, view, 10, "answer")
    finally:
        lock.release()
    interaction.response.send_modal.assert_awaited_once()
    old_round = session.round_id
    session.round_id += 1  # Simulate a restored/new round arriving before modal submission.
    session.winner_id = None
    session.state = "open"
    stale = request(10)
    await bot.submit_answer(stale, session, old_round, "helium")
    assert stale.response.send_message.await_count + stale.response.defer.await_count == 1
    assert session.winner_id is None


async def test_settings_save_defers_before_storage_and_failure_keeps_view_active(bot):
    profiles = {mode: await bot.store.get_settings(10, mode) for mode in ("shared", "solo")}
    dm = True
    view = SettingsView(bot.store, 10, profiles, dm)
    save = next(item for item in view.children if getattr(item, "label", None) == "Save")
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_save(*args):
        entered.set()
        await release.wait()

    bot.store.save_preferences = delayed_save
    first = request(10)
    task = asyncio.create_task(save.callback(first))
    await asyncio.wait_for(entered.wait(), 1)
    assert first.response.defer.await_count == 1
    release.set()
    await task
    assert first.edit_original_response.await_count == 1
    assert view.is_finished()

    failed_view = SettingsView(bot.store, 10, profiles, dm)
    failed_save = next(
        item for item in failed_view.children if getattr(item, "label", None) == "Save"
    )

    async def fail(*args):
        raise OSError("database unavailable")

    bot.store.save_preferences = fail
    failed = request(10)
    await failed_save.callback(failed)
    assert failed.response.defer.await_count == 1
    failed.followup.send.assert_awaited_once()
    assert failed.followup.send.await_args.kwargs["ephemeral"] is True
    assert not failed_view.is_finished()
    owner_check = request(99)
    await failed_save.callback(owner_check)
    assert owner_check.response.send_message.await_count == 1
    assert owner_check.response.send_message.await_args.kwargs["ephemeral"] is True
