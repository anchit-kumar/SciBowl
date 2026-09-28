"""Discord adapter. The engine owns scoring; this layer owns delivery and timers."""

import asyncio
import contextlib
import logging
import sqlite3
import time
import uuid
from datetime import UTC, datetime

import discord
from discord import app_commands

from .engine import Session
from .judging import AnswerJudge
from .models import CATEGORIES, validate_settings
from .session_messages import PrivateMessages
from .setup_ui import GameSetupView, help_embed
from .storage import Store
from .ui import SettingsView, button, chunks, result_view, review_pages, review_view

log = logging.getLogger(__name__)


class AnswerModal(discord.ui.Modal, title="Your answer"):
    answer = discord.ui.TextInput(label="Answer", max_length=1000)

    def __init__(self, app, session, round_id):
        super().__init__()
        self.app, self.session, self.round_id = app, session, round_id

    async def on_submit(self, interaction):
        await self.app.submit_answer(interaction, self.session, self.round_id, self.answer.value)


class QuestionView(discord.ui.View):
    def __init__(self, app, session):
        super().__init__(timeout=None)
        self.app, self.session = app, session
        self.round_id = session.round_id
        if session.mode == "shared" and session.state == "open":
            self.add_item(button("Buzz", self.buzz, style=discord.ButtonStyle.primary))
        if session.state in ("answering", "open"):
            self.add_item(button("Answer", self.answer, style=discord.ButtonStyle.success))
        if session.mode == "solo":
            if session.state == "answering":
                self.add_item(button("Reveal", self.reveal))
            if session.state == "revealed":
                self.add_item(button("Next", self.next_question, style=discord.ButtonStyle.primary))
            self.add_item(button("Stop", self.stop_game, style=discord.ButtonStyle.danger))

    async def interaction_check(self, interaction):
        session = self.session
        valid = (
            self.app.sessions.get(session.channel_id) is session
            and session.round_id == self.round_id
            and session.state not in ("paused", "finished")
        )
        if session.mode == "solo" and interaction.user.id != session.starter_id:
            valid = False
        if not valid:
            await interaction.response.send_message(
                "This control is no longer available to you.", ephemeral=True
            )
        else:
            self.app.touch(session)
        return valid

    async def buzz(self, interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.app.operation_lock(self.session):
            if self.app.sessions.get(
                self.session.channel_id
            ) is not self.session or not await self.session.buzz(
                interaction.user.id, self.round_id
            ):
                return await self.app.private_reply(
                    interaction,
                    self.session.id,
                    "Another player claimed this question, you already missed it, or its timer expired.",
                )
            self.app.schedule_question_hide(self.session)
            await self.app.persist(self.session)
            await self.app.update_controls(self.session)
            self.app.schedule_deadline(self.session)
            await self.app.private_reply(
                interaction,
                self.session.id,
                "You buzzed first. The question disappears for everyone in "
                f"{self.session.settings.get('hide_seconds', 0.5):g} seconds. "
                "Press Answer or use /answer before time runs out.",
                view=self.app.answer_view(self.session),
            )
            await self.app.send_session_message(
                self.session.id,
                self.app.channel(self.session),
                content=f"<@{interaction.user.id}> buzzed first.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def answer(self, interaction):
        if self.session.state != "answering" or self.session.winner_id != interaction.user.id:
            return await interaction.response.send_message(
                "Only the player who claimed this question can answer.", ephemeral=True
            )
        await interaction.response.send_modal(AnswerModal(self.app, self.session, self.round_id))

    async def reveal(self, interaction):
        await interaction.response.defer()
        async with self.app.operation_lock(self.session):
            if (
                self.app.sessions.get(self.session.channel_id) is not self.session
                or self.session.state != "answering"
                or self.session.round_id != self.round_id
            ):
                return
            await self.session.skip()
            await self.app.reveal(self.session, "Skipped")

    async def next_question(self, interaction):
        await interaction.response.defer()
        async with self.app.operation_lock(self.session):
            if (
                self.app.sessions.get(self.session.channel_id) is self.session
                and self.session.state == "revealed"
                and self.round_id == self.session.round_id
            ):
                await self.app.advance(self.session)

    async def stop_game(self, interaction):
        await interaction.response.defer()
        async with self.app.operation_lock(self.session):
            if (
                self.app.sessions.get(self.session.channel_id) is not self.session
                or self.session.round_id != self.round_id
            ):
                return
            await self.app.finalize(self.session, early=True)


class BowlBot(discord.Client):
    def __init__(
        self, db_path, api_key=None, model="openai/gpt-oss-20b", guild_id=None, sync_only=False
    ):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.store = Store(db_path)
        self.judge = AnswerJudge(api_key, model)
        self.guild_id = int(guild_id) if guild_id else None
        self.sync_only = sync_only
        self.sessions = {}
        self.operations = {}
        self.timers = {}
        self.messages = {}
        self.question_views = {}
        self.question_messages = {}
        self.hide_tasks = {}
        self.hiding_started = set()
        self.hidden_questions = set()
        self.answer_views = {}
        self.channels = {}
        self.last_activity = {}
        self.background = set()
        self.start_lock = asyncio.Lock()
        self.private_messages = PrivateMessages()
        self.started = time.monotonic()
        self.install_commands()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.background.add(task)

        def done(completed):
            self.background.discard(completed)
            if not completed.cancelled() and completed.exception():
                log.error("Background task failed (%s)", type(completed.exception()).__name__)

        task.add_done_callback(done)
        return task

    async def setup_hook(self):
        await self.store.open()
        if self.sync_only:
            if self.guild_id:
                guild = discord.Object(id=self.guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
            return
        for payload in await self.store.unfinished_sessions():
            session = Session.restore(payload)
            self.sessions[session.channel_id] = session
            self.touch(session)
        self.spawn(self.maintenance())

    async def close(self):
        for task in list(self.background):
            task.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)
        await self.judge.close()
        await self.store.close()
        await super().close()

    def operation_lock(self, session):
        return self.operations.setdefault(session.id, asyncio.Lock())

    def channel(self, session):
        channel = self.channels.get(session.channel_id) or self.get_channel(session.channel_id)
        if channel is None:
            raise ValueError("Session channel is unavailable. Check bot permissions.")
        return channel

    async def resolve_channel(self, session):
        channel = self.channels.get(session.channel_id) or self.get_channel(session.channel_id)
        if channel is None:
            channel = await self.fetch_channel(session.channel_id)
        self.channels[session.channel_id] = channel
        return channel

    def touch(self, session):
        self.last_activity[session.id] = time.monotonic()

    async def private_reply(self, interaction, session_id, content, **kwargs):
        message = await interaction.followup.send(content, ephemeral=True, wait=True, **kwargs)
        self.private_messages.remember(session_id, interaction.user.id, message)
        return message

    def answer_view(self, session):
        previous = self.answer_views.pop(session.id, None)
        if previous:
            previous.stop()
        view = QuestionView(self, session)
        self.answer_views[session.id] = view
        return view

    def schedule_question_hide(self, session):
        round_id, owner = session.round_id, session.winner_id

        async def hide():
            await asyncio.sleep(session.settings.get("hide_seconds", 0.5))
            if (
                self.sessions.get(session.channel_id) is not session
                or session.round_id != round_id
                or session.winner_id != owner
                or session.state not in ("answering", "judging")
            ):
                return True
            self.hiding_started.add(session.id)
            self.hidden_questions.add(session.id)
            failed = False
            for message in self.question_messages.get(session.id, []):
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    failed = True
            if failed:
                # Do not wait on the operation lock here: a judgment may hold it
                # and then wait for this deletion task before restoring the question.
                async def pause_failed_claim():
                    async with self.operation_lock(session):
                        if (
                            self.sessions.get(session.channel_id) is session
                            and session.round_id == round_id
                            and session.winner_id == owner
                            and session.state in ("answering", "judging")
                        ):
                            self.cancel_timer(session)
                            await session.pause()
                            await self.persist(session)
                            await self.update_controls(session)
                            await self.send_session_message(
                                session.id,
                                self.channel(session),
                                content="I could not hide the question. The game is paused; "
                                "restore message access and use /game resume.",
                            )

                self.spawn(pause_failed_claim())
                return False
            self.messages.pop(session.id, None)
            self.stop_question_view(session)
            return True

        self.hide_tasks[session.id] = self.spawn(hide())

    async def finish_question_hide(self, session):
        task = self.hide_tasks.pop(session.id, None)
        success = True
        if task:
            if session.id not in self.hiding_started and not task.done():
                task.cancel()
            result = (await asyncio.gather(task, return_exceptions=True))[0]
            success = result is not False and (
                not isinstance(result, BaseException) or isinstance(result, asyncio.CancelledError)
            )
        self.hiding_started.discard(session.id)
        view = self.answer_views.pop(session.id, None)
        if view:
            view.stop()
        return success

    async def restore_question(self, session):
        if not await self.finish_question_hide(session):
            self.cancel_timer(session)
            await session.pause()
            await self.persist(session)
            await self.update_controls(session)
            await self.send_session_message(
                session.id,
                self.channel(session),
                content="Question deletion failed. The game is paused; use /game resume after restoring message access.",
            )
            return False
        if session.id in self.hidden_questions and session.current:
            if not await self.post_question(session):
                return False
            self.hidden_questions.discard(session.id)
        return True

    async def send_session_message(self, session_id, channel, **kwargs):
        message = await channel.send(**kwargs)
        if isinstance(getattr(message, "id", None), int):
            try:
                await self.store.track_message(session_id, channel.id, message.id)
            except (sqlite3.Error, OSError):
                session = self.sessions.get(channel.id)
                if session and session.id == session_id:
                    self.cancel_timer(session)
                    await session.pause()
                    self.stop_question_view(session)
                raise
        return message

    async def persist(self, session):
        try:
            await self.store.save_session(session.id, session.snapshot())
        except (sqlite3.Error, OSError):
            self.cancel_timer(session)
            await session.pause()
            self.stop_question_view(session)
            raise

    def stop_question_view(self, session):
        view = self.question_views.pop(session.id, None)
        if view:
            view.stop()

    def question_view(self, session):
        self.stop_question_view(session)
        view = QuestionView(self, session)
        self.question_views[session.id] = view
        return view

    def cancel_timer(self, session):
        task = self.timers.pop(session.id, None)
        if task and task is not asyncio.current_task():
            task.cancel()

    def schedule_deadline(self, session):
        self.cancel_timer(session)
        if session.mode != "shared":
            return
        round_id = session.round_id
        seconds = session.remaining_seconds()
        if seconds is None:
            return

        async def timer():
            await asyncio.sleep(seconds + 0.05)
            async with self.operation_lock(session):
                if await session.timeout(round_id):
                    if session.state == "open":
                        await self.reopen_question(
                            session, "Answer time expired. That attempt counts as a miss."
                        )
                    else:
                        await self.reveal(session, "Time expired")

        self.timers[session.id] = self.spawn(timer())

    async def update_controls(self, session):
        if session.state in ("paused", "finished"):
            await self.finish_question_hide(session)
        self.stop_question_view(session)
        message = self.messages.get(session.id)
        if message:
            with contextlib.suppress(discord.HTTPException):
                await message.edit(
                    view=self.question_view(session)
                    if session.state not in ("paused", "finished")
                    else None
                )

    async def advance(self, session, already_open=False):
        self.cancel_timer(session)
        await self.finish_question_hide(session)
        self.hidden_questions.discard(session.id)
        self.stop_question_view(session)
        question = session.current if already_open else await session.next_question()
        if question is None:
            if session.state == "finished":
                await self.finalize(session)
            return
        await self.persist(session)
        if not await self.post_question(session):
            return
        await session.refresh_deadline(session.round_id)
        self.schedule_deadline(session)

    async def post_question(self, session):
        question = session.current
        self.question_messages[session.id] = []
        text = question.text
        if question.choices:
            text += "\n\n" + "\n".join(f"{key}) {value}" for key, value in question.choices.items())
        parts = chunks(text)
        for index, part in enumerate(parts):
            embed = discord.Embed(
                title=f"Question {session.round_id} · {question.category}", description=part
            )
            embed.set_footer(text=f"{question.format} · {question.source}"[:2048])
            try:
                message = await self.send_session_message(
                    session.id,
                    self.channel(session),
                    embed=embed,
                    view=self.question_view(session) if index == len(parts) - 1 else None,
                )
                self.question_messages[session.id].append(message)
            except discord.HTTPException:
                await session.pause()
                await self.persist(session)
                log.warning("Question delivery failed; session %s paused", session.id)
                return False
        self.messages[session.id] = message
        return True

    async def reveal(self, session, label):
        self.cancel_timer(session)
        await self.persist(session)
        if not await self.restore_question(session):
            return
        await self.update_controls(session)
        if session.current:
            for part in chunks(f"{label}\n\nOfficial answer: {session.current.answer}"):
                try:
                    await self.send_session_message(
                        session.id,
                        self.channel(session),
                        embed=discord.Embed(title="Result", description=part),
                    )
                except discord.HTTPException:
                    await session.pause()
                    await self.persist(session)
                    log.warning("Result delivery failed; session %s paused", session.id)
                    return
        if session.mode == "shared" and session.state == "revealed":
            round_id = session.round_id

            async def next_later():
                await asyncio.sleep(5)
                async with self.operation_lock(session):
                    if session.state == "revealed" and session.round_id == round_id:
                        await self.advance(session)

            self.timers[session.id] = self.spawn(next_later())

    async def reopen_question(self, session, label):
        """Offer a rebound without leaking the official answer or judge explanation."""
        self.cancel_timer(session)
        await self.persist(session)
        if not await self.restore_question(session):
            return
        await self.update_controls(session)
        try:
            await self.send_session_message(
                session.id,
                self.channel(session),
                embed=discord.Embed(
                    title="Buzz again",
                    description=f"{label}\nOther players can buzz. The previous player cannot retry this question.",
                ),
            )
        except discord.HTTPException:
            await session.pause()
            await self.persist(session)
            await self.update_controls(session)
            return
        await session.refresh_deadline(session.round_id)
        self.schedule_deadline(session)

    async def submit_answer(self, interaction, session, round_id, text):
        await interaction.response.defer(ephemeral=True)
        async with self.operation_lock(session):
            if (
                self.sessions.get(session.channel_id) is not session
                or session.state != "answering"
                or session.winner_id != interaction.user.id
                or session.round_id != round_id
            ):
                return await interaction.followup.send(
                    "This answer control is no longer active for you.", ephemeral=True
                )
            self.touch(session)
            result = await session.submit(interaction.user.id, round_id, text, self.judge)
            if session.state == "open":
                try:
                    await self.reopen_question(
                        session,
                        "Answer time expired."
                        if result.verdict == "timeout"
                        else "Incorrect answer.",
                    )
                except (sqlite3.Error, OSError):
                    return await self.private_reply(
                        interaction,
                        session.id,
                        "Could not save the attempt. The game is paused; restore database access and resume before restarting.",
                    )
                return await self.private_reply(
                    interaction,
                    session.id,
                    "Your attempt was recorded. Other players may now buzz; you cannot retry this question.",
                )
            if session.state == "revealed":
                label = f"{result.verdict.title()}: {result.explanation}"
                if result.verdict == "ungraded" and result.method != "state":
                    label = (
                        "Sorry, I couldn’t check that answer. This question won’t count. Moving on."
                    )
                try:
                    await self.reveal(session, label)
                except (sqlite3.Error, OSError):
                    return await interaction.followup.send(
                        "Sorry, I couldn't save your answer. The session is paused and the "
                        "result is held in memory. Restore database access and use /game resume "
                        "before restarting the bot.",
                        ephemeral=True,
                    )
            await self.private_reply(
                interaction,
                session.id,
                "Answer saved, but I could not post the result. The session is paused; "
                "restore channel permissions and use /game resume."
                if session.state == "paused"
                else "Answer processed.",
            )

    async def finalize(self, session, early=False):
        if self.sessions.get(session.channel_id) is not session:
            return
        self.cancel_timer(session)
        await session.finish()
        payload = dict(session.snapshot(), leaderboard=session.leaderboard(), ended_early=early)
        await self.store.finish_session(session.id, payload, session.attempts)
        self.sessions.pop(session.channel_id, None)
        try:
            await self.update_controls(session)
            channel = await self.resolve_channel(session)
            await self.post_leaderboard(channel, payload)
        except discord.HTTPException:
            # Results are already committed; Discord delivery must not undo them
            # or prevent unrelated sessions and private reviews from progressing.
            log.warning("Leaderboard delivery failed for saved session %s", session.id)
        finally:
            self.spawn(self.deliver_reviews(payload))
            if session.channel_id not in self.sessions:
                self.channels.pop(session.channel_id, None)
            self.messages.pop(session.id, None)
            self.question_messages.pop(session.id, None)
            self.hidden_questions.discard(session.id)
            self.last_activity.pop(session.id, None)
            self.operations.pop(session.id, None)

    @staticmethod
    def board_pages(payload):
        rows = payload.get("leaderboard", [])
        lines = []
        for row in rows:
            accuracy = "—" if row["accuracy"] is None else f"{row['accuracy']:.0%}"
            lines.append(
                f"**{row['rank']}.** <@{row['user_id']}> · **{row['points']} pts** · {row['correct']} correct / {row['incorrect']} incorrect / {row['timeout']} timed out · {accuracy}"
            )
        return ["\n".join(lines[i : i + 12]) for i in range(0, len(lines), 12)] or [
            "No graded attempts."
        ]

    async def post_leaderboard(self, channel, payload):
        pages = self.board_pages(payload)
        view = self.leaderboard_view(payload["id"], 0, len(pages))
        await self.send_session_message(
            payload["id"],
            channel,
            embed=discord.Embed(
                title="Leaderboard · "
                + ("ended early" if payload.get("ended_early") else "finished"),
                description=pages[0],
            ).set_footer(text=f"Game {payload['id']} · 1/{len(pages)}"),
            view=view,
        )

    @staticmethod
    def leaderboard_view(session_id, page, total):
        view = result_view(session_id)
        if total > 1:
            for label, target in [
                ("Previous", max(0, page - 1)),
                ("Next", min(total - 1, page + 1)),
            ]:
                view.add_item(
                    discord.ui.Button(
                        label=label,
                        custom_id=f"board:{session_id}:{target}",
                        disabled=target == page,
                    )
                )
        return view

    async def deliver_reviews(self, payload):
        for owner in payload["participants"]:
            if not await self.store.dm_enabled(owner):
                await self.store.mark_delivery(payload["id"], owner, "opted_out")
                continue
            if await self.store.delivery_status(payload["id"], owner) in ("sent", "blocked"):
                continue
            try:
                user = self.get_user(owner) or await self.fetch_user(owner)
                pages = review_pages(payload, owner)
                await user.send(
                    content=f"Your Science Bowl review · game {payload['id']}\nUse /settings to turn review DMs off.",
                    embed=pages[0],
                    view=review_view(payload["id"], owner, 0, len(pages), "missed"),
                )
                await self.store.mark_delivery(payload["id"], owner, "sent")
            except discord.Forbidden:
                await self.store.mark_delivery(payload["id"], owner, "blocked")
            except discord.HTTPException:
                await self.store.mark_delivery(payload["id"], owner, "failed")
            await asyncio.sleep(0.25)

    async def show_review(self, interaction, session_id=None, page=0, kind="missed", edit=False):
        payload = await self.store.review(interaction.user.id, session_id)
        if not payload:
            return await interaction.response.send_message(
                "No saved review found for you.", ephemeral=True
            )
        pages = review_pages(payload, interaction.user.id, kind)
        page = max(0, min(page, len(pages) - 1))
        embed = pages[page].set_footer(text=f"Game {payload['id']} · page {page + 1}/{len(pages)}")
        view = review_view(payload["id"], interaction.user.id, page, len(pages), kind)
        if edit:
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_interaction(self, interaction):
        # IDs contain no answer text. This dispatcher keeps reviews working after restart.
        custom_id = (interaction.data or {}).get("custom_id", "")
        try:
            if custom_id.startswith("reviewopen:"):
                await self.show_review(interaction, custom_id.split(":")[1])
            elif custom_id.startswith("review:"):
                _, session_id, owner, page, kind, *_ = custom_id.split(":")
                if int(owner) != interaction.user.id:
                    return await interaction.response.send_message(
                        "This review belongs to another player.", ephemeral=True
                    )
                if kind not in ("missed", "skipped", "ungraded"):
                    return await interaction.response.send_message(
                        "This control is invalid or expired.", ephemeral=True
                    )
                await self.show_review(interaction, session_id, int(page), kind, edit=True)
            elif custom_id.startswith("board:"):
                _, session_id, page = custom_id.split(":")
                payload = await self.store.load_session(session_id)
                # Only permit public boards in their original game channel.
                if not payload or payload["channel_id"] != interaction.channel_id:
                    return await interaction.response.send_message(
                        "Leaderboard unavailable here.", ephemeral=True
                    )
                pages = self.board_pages(payload)
                page = max(0, min(int(page), len(pages) - 1))
                await interaction.response.edit_message(
                    embed=discord.Embed(title="Leaderboard", description=pages[page]).set_footer(
                        text=f"Game {session_id} · {page + 1}/{len(pages)}"
                    ),
                    view=self.leaderboard_view(session_id, page, len(pages)),
                )
        except (ValueError, KeyError):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "This control is invalid or expired.", ephemeral=True
                )

    async def start_session(self, interaction, mode, settings):
        async with self.start_lock:
            validate_settings(settings)
            if not interaction.guild or not isinstance(
                interaction.channel, (discord.TextChannel, discord.Thread)
            ):
                await interaction.followup.send(
                    "Start games in a server text channel.", ephemeral=True
                )
                return False
            parent_id = (
                interaction.channel.parent_id
                if isinstance(interaction.channel, discord.Thread)
                else interaction.channel_id
            )
            if not await self.store.allowed(interaction.guild_id, parent_id):
                await interaction.followup.send(
                    "Games are not enabled in this channel.", ephemeral=True
                )
                return False
            if mode == "shared" and interaction.channel_id in self.sessions:
                await interaction.followup.send(
                    "A session already exists here. Use /game resume or /game stop.", ephemeral=True
                )
                return False
            if mode == "solo" and any(
                s.mode == "solo" and s.starter_id == interaction.user.id
                for s in self.sessions.values()
            ):
                await interaction.followup.send(
                    "You already have a practice session. Finish it first.", ephemeral=True
                )
                return False
            questions = await self.store.questions(settings)
            if not questions:
                await interaction.followup.send(
                    "No questions match these settings. Import reviewed packets or edit /settings.",
                    ephemeral=True,
                )
                return False
            channel = interaction.channel
            if mode == "solo":
                if not isinstance(channel, discord.TextChannel):
                    await interaction.followup.send(
                        "Start private practice from a regular text channel.", ephemeral=True
                    )
                    return False
                try:
                    channel = await channel.create_thread(
                        name=f"Practice · {interaction.user.display_name}"[:100],
                        type=discord.ChannelType.private_thread,
                        invitable=False,
                    )
                    await channel.add_user(interaction.user)
                except discord.Forbidden:
                    await interaction.followup.send(
                        "Private practice needs Create Private Threads and Send Messages in Threads permissions.",
                        ephemeral=True,
                    )
                    return False
            session = Session(
                uuid.uuid4().hex[:16], channel.id, interaction.user.id, mode, settings, questions
            )
            self.channels[channel.id] = channel
            self.sessions[channel.id] = session
            self.touch(session)
            await self.persist(session)
            if getattr(interaction, "message", None) is not None:
                with contextlib.suppress(discord.HTTPException):
                    setup_message = await interaction.original_response()
                    self.private_messages.remember(session.id, interaction.user.id, setup_message)
            try:
                await self.private_reply(
                    interaction,
                    session.id,
                    f"Starting {len(questions)} questions in {channel.mention}.\nCategories: {', '.join(settings['categories'])}\nPool: {settings['pool']} · Source: {settings['source']} · Format: {settings['format']}",
                )
            except discord.HTTPException:
                log.warning("Start acknowledgment failed for session %s", session.id)
            async with self.operation_lock(session):
                await self.advance(session)
            if session.state == "paused":
                await interaction.followup.send(
                    "I could not post the question. The session is paused; restore channel "
                    "permissions and use /game resume in the session channel.",
                    ephemeral=True,
                )

            return True

    async def control(self, interaction, action, mode=None):
        await interaction.response.defer(ephemeral=True)
        session = self.sessions.get(interaction.channel_id)
        if mode == "solo" and (session is None or session.mode != "solo"):
            session = next(
                (
                    s
                    for s in self.sessions.values()
                    if s.mode == "solo" and s.starter_id == interaction.user.id
                ),
                None,
            )
        if not session or (mode and session.mode != mode):
            return await interaction.followup.send("No matching active session.", ephemeral=True)
        manager = interaction.guild and interaction.permissions.manage_guild
        if interaction.user.id != session.starter_id and not manager:
            return await interaction.followup.send(
                "Only the starter or a server manager can do that.", ephemeral=True
            )
        async with self.operation_lock(session):
            if self.sessions.get(session.channel_id) is not session:
                return await interaction.followup.send(
                    "No matching active session.", ephemeral=True
                )
            self.touch(session)
            if action == "stop":
                await self.finalize(session, early=True)
            elif action == "pause":
                self.cancel_timer(session)
                await session.pause()
                await self.persist(session)
                await self.update_controls(session)
            elif action == "resume":
                if session.state != "paused":
                    return await interaction.followup.send(
                        "The session is not paused.", ephemeral=True
                    )
                try:
                    await self.resolve_channel(session)
                except discord.HTTPException:
                    return await interaction.followup.send(
                        "The session channel is unavailable. Restore permissions before resuming.",
                        ephemeral=True,
                    )
                await session.resume()
                await self.advance(session, already_open=True)
            elif action == "skip":
                if session.state not in ("open", "answering"):
                    return await interaction.followup.send(
                        "No open question to skip.", ephemeral=True
                    )
                await session.skip()
                await self.reveal(session, "Skipped")
        await self.private_reply(
            interaction,
            session.id,
            "Delivery failed and the session is paused. Restore channel permissions "
            "and use /game resume."
            if action in ("resume", "skip") and session.state == "paused"
            else f"Session {action} processed.",
        )

    async def clear_session_messages(self, interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            return await interaction.followup.send(
                "Use /clear in the session's server channel.", ephemeral=True
            )
        async with self.start_lock:
            if interaction.channel_id in self.sessions:
                return await interaction.followup.send(
                    "Stop the active game before clearing its messages.", ephemeral=True
                )
            payload = await self.store.latest_channel_session(interaction.channel_id)
            if not payload:
                return await interaction.followup.send(
                    "No saved session found in this channel.", ephemeral=True
                )
            if (
                interaction.user.id != payload["starter_id"]
                and not interaction.permissions.manage_guild
            ):
                return await interaction.followup.send(
                    "Only the session starter or a server manager can clear it.", ephemeral=True
                )
            entries = [
                entry
                for entry in await self.store.session_messages(payload["id"])
                if entry["channel_id"] == interaction.channel_id
            ]
            practice_thread = (
                payload.get("mode") == "solo"
                and isinstance(interaction.channel, discord.Thread)
                and interaction.channel.type == discord.ChannelType.private_thread
            )
            thread_delete_error = ""
            if practice_thread:
                await interaction.followup.send(
                    "Deleting this practice thread. Saved scores and reviews remain available.",
                    ephemeral=True,
                )
                try:
                    await interaction.channel.delete(reason="Practice session cleared")
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    thread_delete_error = "Could not delete the practice thread. Give the bot Manage Threads permission. "
                except discord.HTTPException:
                    thread_delete_error = "Discord could not delete the practice thread. "
                if not thread_delete_error:
                    for entry in entries:
                        await self.store.forget_message(payload["id"], entry["message_id"])
                    await self.private_messages.clear(payload["id"], interaction.user.id)
                    return
            removed, failed = 0, 0
            for entry in entries:
                try:
                    await interaction.channel.get_partial_message(entry["message_id"]).delete()
                    removed += 1
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    failed += 1
                    continue
                await self.store.forget_message(payload["id"], entry["message_id"])
            private_removed, private_failed = await self.private_messages.clear(
                payload["id"], interaction.user.id
            )
        await interaction.followup.send(
            thread_delete_error
            + f"Cleared {removed} session messages and {private_removed} of your recent private replies. "
            f"{failed + private_failed} could not be removed. Saved scores and reviews are kept. "
            "Older private replies (or replies from before a restart) may need Dismiss message. "
            "Only messages tracked by this version can be cleared.",
            ephemeral=True,
        )

    async def maintenance(self):
        await self.wait_until_ready()
        last_backup = None
        while not self.is_closed():
            self.private_messages.prune()
            today = datetime.now(UTC).date().isoformat()
            if today != last_backup:
                try:
                    folder = self.store.path.parent / "backups"
                    await self.store.backup(folder / f"scibowl-{today}.sqlite3")
                    for old in sorted(folder.glob("scibowl-*.sqlite3"))[:-7]:
                        old.unlink()
                    last_backup = today
                except Exception as error:  # noqa: BLE001 - keep the supervisor alive; log no secrets
                    log.warning("Backup maintenance failed (%s); will retry", type(error).__name__)
            for session in list(self.sessions.values()):
                if time.monotonic() - self.last_activity.get(session.id, 0) > 1800:
                    try:
                        async with self.operation_lock(session):
                            # A user may have acted while maintenance waited for
                            # an in-flight judgment or another session operation.
                            if time.monotonic() - self.last_activity.get(session.id, 0) > 1800:
                                await self.finalize(session, early=True)
                    except Exception as error:  # noqa: BLE001 - isolate failures between sessions
                        log.warning(
                            "Idle session cleanup failed for %s (%s); will retry",
                            session.id,
                            type(error).__name__,
                        )
            await asyncio.sleep(30)

    def install_commands(self):
        game = app_commands.Group(name="game", description="Shared Science Bowl games")
        practice = app_commands.Group(name="practice", description="Private solo practice")
        admin = app_commands.Group(
            name="admin",
            description="Server administration",
            default_permissions=discord.Permissions(manage_guild=True),
        )

        async def options(user_id, mode, **overrides):
            value = await self.store.get_settings(user_id, mode)
            for key, item in overrides.items():
                if item is not None:
                    value[key] = item
            if mode == "shared":
                value["role"] = "tossup"
            validate_settings(value)
            return value

        @game.command(
            name="start", description="Open shared game setup using your personal defaults"
        )
        @app_commands.choices(
            pool=[
                app_commands.Choice(name=x.title(), value=x)
                for x in ("regional", "invitational", "all")
            ],
            format=[
                app_commands.Choice(name=x.replace("_", " ").title(), value=x)
                for x in ("short_answer", "multiple_choice", "all")
            ],
        )
        @app_commands.describe(
            category="Comma-separated categories, or choose multiple in the setup panel",
            hide_seconds="Seconds before hiding the question after a buzz (0–10; default 0.5)",
        )
        async def game_start(
            interaction: discord.Interaction,
            count: app_commands.Range[int, 1, 100] | None = None,
            category: str | None = None,
            pool: str | None = None,
            source: str | None = None,
            format: str | None = None,
            buzz_seconds: app_commands.Range[int, 5, 120] | None = None,
            answer_seconds: app_commands.Range[int, 5, 120] | None = None,
            hide_seconds: app_commands.Range[float, 0.0, 10.0] | None = None,
        ):
            await interaction.response.defer(ephemeral=True)
            names = {item.casefold(): item for item in CATEGORIES}
            cats = None
            if category:
                cats = (
                    list(CATEGORIES)
                    if category.casefold().strip() == "all"
                    else list(
                        dict.fromkeys(
                            names.get(part.strip().casefold(), part.strip())
                            for part in category.split(",")
                        )
                    )
                )
            settings = await options(
                interaction.user.id,
                "shared",
                count=count,
                categories=cats,
                pool=pool,
                source=source,
                format=format,
                buzz_seconds=buzz_seconds,
                answer_seconds=answer_seconds,
                hide_seconds=hide_seconds,
            )
            view = GameSetupView(
                self, interaction.user.id, "shared", settings, await self.store.sources()
            )
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

        @practice.command(name="start", description="Choose categories for private practice")
        @app_commands.choices(
            pool=[
                app_commands.Choice(name=x.title(), value=x)
                for x in ("regional", "invitational", "all")
            ],
            format=[
                app_commands.Choice(name=x.replace("_", " ").title(), value=x)
                for x in ("short_answer", "multiple_choice", "all")
            ],
            role=[app_commands.Choice(name=x.title(), value=x) for x in ("tossup", "bonus", "all")],
        )
        async def practice_start(
            interaction: discord.Interaction,
            count: app_commands.Range[int, 1, 100] | None = None,
            pool: str | None = None,
            source: str | None = None,
            format: str | None = None,
            role: str | None = None,
        ):
            await interaction.response.defer(ephemeral=True)
            settings = await options(
                interaction.user.id,
                "solo",
                count=count,
                pool=pool,
                source=source,
                format=format,
                role=role,
            )
            view = GameSetupView(
                self, interaction.user.id, "solo", settings, await self.store.sources()
            )
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

        @game_start.autocomplete("category")
        async def categories_autocomplete(interaction, current: str):
            parts = current.split(",")
            selected = [part.strip() for part in parts[:-1] if part.strip()]
            query = parts[-1].strip().casefold()
            choices = []
            for name in CATEGORIES:
                if name not in selected and query in name.casefold():
                    value = ", ".join([*selected, name])
                    if len(value) <= 100:
                        choices.append(app_commands.Choice(name=value, value=value))
            if not selected and (not query or "all".startswith(query)):
                choices.append(app_commands.Choice(name="All categories", value="all"))
            return choices[:25]

        async def source_autocomplete(interaction, current: str):
            names = ["all", *dict.fromkeys(item["source"] for item in await self.store.sources())]
            return [
                app_commands.Choice(name=name[:100], value=name)
                for name in names
                if len(name) <= 100 and current.casefold() in name.casefold()
            ][:25]

        game_start.autocomplete("source")(source_autocomplete)
        practice_start.autocomplete("source")(source_autocomplete)

        @game.command(name="pause", description="Pause your session")
        async def pause(interaction: discord.Interaction):
            await self.control(interaction, "pause")

        @game.command(name="resume", description="Resume with a fresh question")
        async def resume(interaction: discord.Interaction):
            await self.control(interaction, "resume")

        @game.command(name="skip", description="Skip the open question")
        async def skip(interaction: discord.Interaction):
            await self.control(interaction, "skip")

        @game.command(name="stop", description="End your session and save results")
        async def stop(interaction: discord.Interaction):
            await self.control(interaction, "stop")

        @practice.command(name="stop", description="End your private practice")
        async def practice_stop(interaction: discord.Interaction):
            await self.control(interaction, "stop", "solo")

        @self.tree.command(
            name="settings", description="Personal game defaults and DM review preference"
        )
        async def settings_command(interaction: discord.Interaction):
            profiles = {
                mode: await self.store.get_settings(interaction.user.id, mode)
                for mode in ("shared", "solo")
            }
            view = SettingsView(
                self.store,
                interaction.user.id,
                profiles,
                await self.store.dm_enabled(interaction.user.id),
            )
            await interaction.response.send_message(view.summary(), view=view, ephemeral=True)

        @admin.command(
            name="settings",
            description="Allow games in this channel only, or reset to all channels",
        )
        @app_commands.checks.has_permissions(manage_guild=True)
        async def admin_settings(
            interaction: discord.Interaction,
            channel: discord.TextChannel | None = None,
            allow_all: bool = False,
        ):
            if not interaction.guild:
                return await interaction.response.send_message(
                    "Use this in a server.", ephemeral=True
                )
            if channel is None and not allow_all:
                return await interaction.response.send_message(
                    "Choose a channel, or set allow_all:true.", ephemeral=True
                )
            await self.store.set_channels(interaction.guild_id, [] if allow_all else [channel.id])
            await interaction.response.send_message(
                "Allowed game channels updated.", ephemeral=True
            )

        @self.tree.command(name="answer", description="Submit your answer after buzzing")
        async def answer_command(
            interaction: discord.Interaction, text: app_commands.Range[str, 1, 1000]
        ):
            session = self.sessions.get(interaction.channel_id)
            if not session:
                return await interaction.response.send_message(
                    "No active game here.", ephemeral=True
                )
            await self.submit_answer(interaction, session, session.round_id, text)

        @self.tree.command(
            name="review", description="Privately review your latest game or a game ID"
        )
        async def review_command(interaction: discord.Interaction, game: str | None = None):
            await self.show_review(interaction, game)

        @self.tree.command(name="score", description="Current session leaderboard")
        async def score(interaction: discord.Interaction):
            session = self.sessions.get(interaction.channel_id)
            if not session:
                return await interaction.response.send_message("No active session.", ephemeral=True)
            pages = self.board_pages({"leaderboard": session.leaderboard()})
            await interaction.response.send_message(pages[0], ephemeral=True)

        @self.tree.command(name="sources", description="Locally imported sources")
        async def sources(interaction: discord.Interaction):
            items = await self.store.sources()
            text = (
                "\n".join(f"{s['source']} · {s['pool']} · {s['count']} questions" for s in items)
                or "No sources imported yet."
            )
            await interaction.response.send_message(text[:1900], ephemeral=True)

        @self.tree.command(
            name="clear", description="Clear bot messages from this channel's last session"
        )
        async def clear_command(interaction: discord.Interaction):
            await self.clear_session_messages(interaction)

        @self.tree.command(name="stats", description="Your saved accuracy by mode and category")
        async def stats(interaction: discord.Interaction):
            sessions = await self.store.stats(interaction.user.id)
            buckets = {}
            for payload in sessions:
                for attempt in payload.get("attempts", []):
                    if attempt["user_id"] != interaction.user.id or attempt["verdict"] not in (
                        "correct",
                        "incorrect",
                        "timeout",
                    ):
                        continue
                    key = (payload["mode"], attempt["question"]["category"])
                    bucket = buckets.setdefault(key, [0, 0])
                    bucket[0] += attempt["verdict"] == "correct"
                    bucket[1] += 1
            text = "\n".join(
                f"{mode} · {category}: {good}/{total} ({good / total:.0%})"
                for (mode, category), (good, total) in sorted(buckets.items())
            )
            await interaction.response.send_message(
                text or "No graded attempts yet.", ephemeral=True
            )

        @self.tree.command(name="status", description="Bot and question bank health")
        async def status(interaction: discord.Interaction):
            sources = await self.store.sources()
            await interaction.response.send_message(
                f"Uptime: {int(time.monotonic() - self.started)}s\nDiscord: {self.latency * 1000:.0f}ms\nQuestions: {sum(s['count'] for s in sources)}\nActive sessions: {len(self.sessions)}\nGroq: {'configured' if self.judge._client else 'not configured'}",
                ephemeral=True,
            )

        @self.tree.command(name="help", description="Science Bowl controls")
        async def help_command(interaction: discord.Interaction):
            await interaction.response.send_message(
                embed=help_embed(),
                ephemeral=True,
            )

        self.tree.add_command(game)
        self.tree.add_command(practice)
        self.tree.add_command(admin)

        @self.tree.error
        async def on_error(interaction, error):
            original = getattr(error, "original", error)
            message = (
                str(original)
                if isinstance(original, (ValueError, app_commands.CheckFailure))
                else "Sorry, that action failed. Check bot permissions and try again."
            )
            log.warning("Command failed (%s)", type(original).__name__)
            if interaction.response.is_done():
                await interaction.followup.send(message[:1800], ephemeral=True)
            else:
                await interaction.response.send_message(message[:1800], ephemeral=True)
