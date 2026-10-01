"""Reading lifecycle checks use gated ticks and mocked Discord/storage."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from scibowl.discord_app import BowlBot, QuestionView
from scibowl.engine import Session
from scibowl.models import Judgment, Question, default_settings, validate_settings
from scibowl.reading import Reading, question_text
from scibowl.setup_ui import GameSetupView, NumericSetupModal
from scibowl.ui import SettingsNumbers, SettingsView


def question(text="What is 2 + 2?", choices=None):
    return Question("q", text, "4", "Mathematics", choices=choices or {})


def interaction(user=10, channel=1):
    return SimpleNamespace(
        user=SimpleNamespace(id=user),
        channel_id=channel,
        data={"values": []},
        response=SimpleNamespace(
            defer=AsyncMock(), send_message=AsyncMock(), edit_message=AsyncMock()
        ),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


@pytest.fixture
async def app(tmp_path):
    bot = BowlBot(tmp_path / "paced.sqlite3")
    bot.store = SimpleNamespace(
        save_session=AsyncMock(), track_message=AsyncMock(), close=AsyncMock()
    )
    bot.schedule_deadline = MagicMock()
    ticks = asyncio.Queue()
    bot.reading_tick = ticks.get
    sent = []

    async def send(**kwargs):
        msg = SimpleNamespace(id=len(sent) + 100, delete=AsyncMock(), payload=kwargs)

        async def edit(**changes):
            msg.payload.update(changes)

        msg.edit = AsyncMock(side_effect=edit)
        sent.append(msg)
        return msg

    bot.channels[1] = SimpleNamespace(id=1, send=AsyncMock(side_effect=send))
    try:
        yield bot, sent, ticks
    finally:
        await bot.close()


def session_for(bot, **settings):
    session = Session(
        "paced",
        1,
        10,
        "shared",
        dict(default_settings(), **settings),
        [question(), question("Next question has many more words to read.")],
    )
    bot.sessions[1] = session
    return session


async def test_reading_preserves_prefixes_math_choices_and_fractional_speed():
    text = "Solve (x + 2)/(3 − x) = 4.  Next?\n\nW) first choice\nX) second choice"
    reader = Reading(text, 60)
    reader.step()
    assert reader.visible == "Solve "
    for _ in range(4):
        reader.step()
        assert reader.visible == "Solve "
    reader.step()
    assert reader.visible == "Solve (x + 2)/(3 − x) "
    while not reader.done:
        before = reader.visible
        reader.step()
        assert reader.visible.startswith(before) and text.startswith(reader.visible)
    assert reader.visible == text
    spaced = Reading("One  two\nthree four five", 90)
    spaced.step()
    assert spaced.visible == "One  "
    spaced.step()
    assert spaced.visible == "One  two\nthree "
    spaced.finish()
    assert spaced.visible == spaced.text
    q = question("Choose", {"W": "first", "X": "last"})
    assert question_text(q) == "Choose\n\nW) first\nX) last"


async def test_shared_deadline_starts_after_successful_final_edit(app):
    bot, sent, ticks = app
    session = session_for(bot)
    await bot.advance(session)
    assert session.reading and session.remaining_seconds() is None
    assert sent[0].payload["embed"].description == "What is 2 "
    assert not await session.timeout(session.round_id)
    task = bot.reading_tasks[session.id]
    entered, release = asyncio.Event(), asyncio.Event()
    original = sent[0].edit.side_effect

    async def slow_edit(**changes):
        entered.set()
        await release.wait()
        await original(**changes)

    sent[0].edit.side_effect = slow_edit
    ticks.put_nowait(None)
    await asyncio.wait_for(entered.wait(), 1)
    assert session.remaining_seconds() is None
    release.set()
    await asyncio.wait_for(task, 1)
    assert not session.reading and 29 < session.remaining_seconds() <= 30
    assert sent[0].payload["embed"].description == question().text
    bot.schedule_deadline.assert_called_once_with(session)


async def test_buzz_freezes_and_rebounds_resume_without_full_text_leak(app):
    bot, sent, ticks = app
    session = session_for(bot, hide_seconds=0)
    await bot.advance(session)
    reading = bot.readings[session.id]
    prefix, task = reading.visible, bot.reading_tasks[session.id]
    await QuestionView(bot, session).buzz(interaction())
    await asyncio.gather(task, return_exceptions=True)
    assert session.state == "answering" and 14 < session.remaining_seconds() <= 15
    assert session.id not in bot.reading_tasks and reading.visible == prefix
    await asyncio.wait_for(bot.hide_tasks[session.id], 1)
    assert sent[0].delete.await_count == 1
    wrong = SimpleNamespace(judge=AsyncMock(return_value=Judgment("incorrect", "No", "local")))
    await session.submit(10, session.round_id, "wrong", wrong)
    await bot.reopen_question(session, "Incorrect answer")
    assert session.state == "open" and session.remaining_seconds() is None
    restored = bot.question_messages[session.id][0]
    assert restored.payload["embed"].description == prefix
    assert bot.readings[session.id] is reading and reading.wpm == 180
    assert not await session.buzz(10, session.round_id)
    await QuestionView(bot, session).buzz(interaction(user=11))
    session._deadline = 0
    assert await session.timeout(session.round_id)
    await bot.reopen_question(session, "Answer time expired")
    assert 11 in session.locked_out and session.remaining_seconds() is None
    task = bot.reading_tasks[session.id]
    ticks.put_nowait(None)
    await asyncio.wait_for(task, 1)
    assert reading.done and session.remaining_seconds() is not None
    await QuestionView(bot, session).buzz(interaction(user=12))
    await session.submit(12, session.round_id, "wrong", wrong)
    await bot.reopen_question(session, "Incorrect answer")
    assert 29 < session.remaining_seconds() <= 30
    assert bot.question_messages[session.id][0].payload["embed"].description == question().text


async def test_speed_owner_range_acknowledgement_and_next_question_persistence(app):
    bot, _, _ = app
    session = session_for(bot)
    await bot.advance(session)
    current = bot.readings[session.id]
    for request, speed in [
        (interaction(user=11), 240),
        (interaction(channel=2), 240),
        (interaction(), 301),
        (interaction(), True),
        (interaction(), 59),
    ]:
        await bot.set_reading_speed(request, speed)
        request.response.defer.assert_awaited_once_with(ephemeral=True)
        assert request.followup.send.await_args.kwargs["ephemeral"]
        assert session.settings["reading_wpm"] == 180
    saved = asyncio.Event()
    release = asyncio.Event()

    async def save(*args):
        saved.set()
        await release.wait()

    bot.store.save_session.side_effect = save
    request = interaction()
    task = asyncio.create_task(bot.set_reading_speed(request, 240))
    await asyncio.wait_for(saved.wait(), 1)
    request.response.defer.assert_awaited_once()
    release.set()
    await task
    assert current.wpm == 180 and session.settings["reading_wpm"] == 240
    assert bot.store.save_session.await_args.args[1]["settings"]["reading_wpm"] == 240
    await session.skip()
    await bot.advance(session)
    assert bot.readings[session.id].wpm == 240
    assert session.settings["reading_mode"] == "paced"
    assert bot.tree.get_command("game").get_command("speed") is not None


async def test_full_and_solo_behavior_and_reveal_full_text(app):
    bot, sent, _ = app
    full = session_for(bot, reading_mode="full")
    await bot.advance(full)
    assert full.remaining_seconds() is not None and full.id not in bot.readings
    assert sent[0].payload["embed"].description == question().text
    solo = Session("solo", 1, 10, "solo", default_settings("solo"), [question()])
    bot.sessions[1] = solo
    await bot.advance(solo)
    assert solo.state == "answering" and solo.remaining_seconds() is None
    assert solo.id not in bot.readings
    paced = session_for(bot)
    await bot.advance(paced)
    await paced.skip()
    await bot.reveal(paced, "Skipped")
    assert bot.readings[paced.id].done and paced.id not in bot.reading_tasks
    assert bot.question_messages[paced.id][0].payload["embed"].description == question().text


async def test_stale_tasks_and_delivery_failures_pause_safely(app):
    bot, _, ticks = app
    session = session_for(bot)
    await bot.advance(session)
    task = bot.reading_tasks[session.id]
    replacement = Reading("Replacement question", 60)
    bot.readings[session.id] = replacement
    ticks.put_nowait(None)
    await asyncio.wait_for(task, 1)
    assert replacement.position == 0
    session = session_for(bot)
    await bot.advance(session)
    task = bot.reading_tasks[session.id]
    bot.question_messages[session.id][0].edit.side_effect = discord.HTTPException(
        MagicMock(status=403, reason="Forbidden", headers={}), "denied"
    )
    ticks.put_nowait(None)
    await asyncio.wait_for(task, 1)
    assert session.state == "paused" and session.id not in bot.reading_tasks
    assert bot.store.save_session.await_args.args[1]["state"] == "paused"


async def test_overflow_reveals_only_prefix_and_preserves_stable_buzz_controls(app):
    bot, _, _ = app
    session = session_for(bot)
    session._queue.clear()
    session._queue.append(question("a " * 1800, {"W": "secret choice", "X": "other"}))
    await bot.advance(session)
    reading = bot.readings[session.id]
    # Grow near a chunk boundary without spending minutes in real time.
    while len(reading.visible) <= 3400:
        reading.step()
    await bot.render_question(session)
    messages = bot.question_messages[session.id]
    assert len(messages) == 2
    joined = "".join(msg.payload["embed"].description for msg in messages)
    assert joined == reading.visible and "secret" not in joined
    assert messages[0].payload["view"] is None
    custom_id = messages[-1].payload["view"].children[0].custom_id
    assert custom_id == f"game:{session.id}:{session.round_id}:buzz"
    previous_edits = messages[0].edit.await_count
    reading.step()
    await bot.render_question(session)
    assert messages[0].edit.await_count == previous_edits
    entered, release = asyncio.Event(), asyncio.Event()
    original = messages[-1].edit.side_effect

    async def slow_edit(**changes):
        entered.set()
        await release.wait()
        await original(**changes)

    messages[-1].edit.side_effect = slow_edit
    reading.step()

    async def update():
        async with bot.operation_lock(session):
            await bot.render_question(session)

    update_task = asyncio.create_task(update())
    await asyncio.wait_for(entered.wait(), 1)
    requests = [interaction(user=user) for user in range(20, 30)]
    buzzes = [asyncio.create_task(bot.dispatch_game_control(req, custom_id)) for req in requests]
    await asyncio.sleep(0)
    assert all(req.response.defer.await_count == 1 for req in requests)
    release.set()
    await asyncio.wait_for(asyncio.gather(update_task, *buzzes), 1)
    assert session.winner_id in range(20, 30)
    assert session.state == "answering" and session.id not in bot.reading_tasks


async def test_settings_setup_validation_and_legacy_defaults(app):
    bot, _, _ = app
    shared, solo = default_settings(), default_settings("solo")
    assert shared["reading_mode"] == "paced" and solo["reading_mode"] == "full"
    for invalid in [59, 301, True, 180.5, "180"]:
        with pytest.raises(ValueError):
            validate_settings(dict(shared, reading_wpm=invalid))
    with pytest.raises(ValueError):
        validate_settings(dict(shared, reading_mode="other"))
    legacy = {key: value for key, value in shared.items() if not key.startswith("reading_")}
    validate_settings(legacy)
    view = SettingsView(bot.store, 10, {"shared": shared, "solo": solo}, True)
    assert len(SettingsNumbers(view).children) == 5
    assert "reading_wpm" in SettingsNumbers(view).fields
    view.field = "reading_mode"
    view.build()
    mode_select = view.children[0]
    mode_select._values = ["solo"]
    await mode_select.callback(interaction())
    assert view.mode == "solo" and view.field == "categories"
    assert "reading_mode" not in [option.value for option in view.children[1].options]
    setup = GameSetupView(bot, 10, "shared", shared, [])
    assert "Reading speed (WPM)" in [getattr(item, "label", None) for item in setup.children]
    modal = NumericSetupModal(setup, "reading_wpm")
    modal.value_input._value = "240"
    await modal.on_submit(interaction())
    assert setup.settings["reading_wpm"] == 240 and shared["reading_wpm"] == 180
    private = GameSetupView(bot, 10, "solo", solo, [])
    assert "reading_mode" not in [option.value for option in private.children[1].options]
    assert "Reading speed (WPM)" not in [getattr(item, "label", None) for item in private.children]
