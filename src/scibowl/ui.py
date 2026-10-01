"""Discord presentation: private settings and stateless, owner-checked review pages."""

import copy
import logging

import discord

from .models import CATEGORIES, default_settings, validate_settings

logger = logging.getLogger(__name__)


def button(label, callback, *, style=discord.ButtonStyle.secondary, row=None):
    item = discord.ui.Button(label=label, style=style, row=row)
    item.callback = callback
    return item


def chunks(text: str, limit=3400):
    text = discord.utils.escape_mentions(str(text))
    return [text[i : i + limit] for i in range(0, len(text), limit)] or ["—"]


def review_pages(payload, user_id, kind="missed"):
    wanted = {"missed": {"incorrect", "timeout"}, "skipped": {"skipped"}, "ungraded": {"ungraded"}}[
        kind
    ]
    attempts = [
        a for a in payload.get("attempts", []) if a["user_id"] == user_id and a["verdict"] in wanted
    ]
    pages = []
    for index, attempt in enumerate(attempts, 1):
        q = attempt["question"]
        options = "\n".join(f"{key}) {value}" for key, value in q.get("choices", {}).items())
        content = (
            f"{q['category']} · {q['source']} · page {q.get('page', 1)}\n\n"
            f"{q['text']}\n{options}\n\nYour answer: {attempt.get('answer') or 'No answer submitted'}\n"
            f"Official answer: {q['answer']}\nOutcome: {attempt['verdict']}\n"
            f"{attempt.get('explanation', '')}"
        )
        for part, fragment in enumerate(chunks(content), 1):
            pages.append(
                discord.Embed(
                    title=f"Question {index} of {len(attempts)} · part {part}", description=fragment
                )
            )
    if not pages:
        pages = [
            discord.Embed(title="Your review", description=f"No {kind} questions in this session.")
        ]
    return pages


def review_view(session_id, owner, page, total, kind):
    view = discord.ui.View(timeout=None)
    for label, target in [
        ("First", 0),
        ("Previous", max(0, page - 1)),
        ("Next", min(total - 1, page + 1)),
        ("Last", total - 1),
    ]:
        view.add_item(
            discord.ui.Button(
                label=label,
                custom_id=f"review:{session_id}:{owner}:{target}:{kind}:{label.lower()}",
                disabled=target == page,
                row=0,
            )
        )
    for option in ("missed", "skipped", "ungraded"):
        view.add_item(
            discord.ui.Button(
                label=option.title(),
                custom_id=f"review:{session_id}:{owner}:0:{option}",
                disabled=option == kind,
                row=1,
            )
        )
    return view


def result_view(session_id):
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="My Review", custom_id=f"reviewopen:{session_id}"))
    return view


class SettingsNumbers(discord.ui.Modal, title="Counts and timers"):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.profile = parent.mode
        self.fields = {}
        fields = [
            ("count", "Question count (1–100)"),
            ("buzz_seconds", "Buzz seconds (5–120)"),
            ("answer_seconds", "Answer seconds (5–120)"),
        ]
        if self.profile == "shared":
            fields.append(("hide_seconds", "Hide after buzz (0–10 seconds)"))
        for name, label in fields:
            field = discord.ui.TextInput(
                label=label,
                default=str(parent.drafts[self.profile][name]),
                max_length=24 if name == "hide_seconds" else 3,
            )
            self.fields[name] = field
            self.add_item(field)

    async def on_submit(self, interaction):
        if interaction.user.id != self.parent.owner or self.parent.is_finished():
            return await interaction.response.send_message(
                "These settings belong to another player.", ephemeral=True
            )
        draft = dict(self.parent.drafts[self.profile])
        try:
            draft.update(
                {
                    key: float(field.value) if key == "hide_seconds" else int(field.value)
                    for key, field in self.fields.items()
                }
            )
            validate_settings(draft)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        self.parent.drafts[self.profile] = draft
        await interaction.response.edit_message(content=self.parent.summary(), view=self.parent)


class SettingsSource(discord.ui.Modal, title="Default source"):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.profile = parent.mode
        self.source = discord.ui.TextInput(
            label="Source name from /sources, or all",
            default=parent.drafts[self.profile]["source"],
            max_length=100,
        )
        self.add_item(self.source)

    async def on_submit(self, interaction):
        if interaction.user.id != self.parent.owner or self.parent.is_finished():
            return await interaction.response.send_message(
                "These settings belong to another player.", ephemeral=True
            )
        source = self.source.value.strip()
        sources = await self.parent.store.sources()
        if source != "all" and source not in {s["source"] for s in sources}:
            return await interaction.response.send_message(
                "Unknown source. Use /sources for available names.", ephemeral=True
            )
        self.parent.drafts[self.profile]["source"] = source
        await interaction.response.edit_message(content=self.parent.summary(), view=self.parent)


class SettingsView(discord.ui.View):
    def __init__(self, store, owner, profiles, dm):
        super().__init__(timeout=600)
        self.store, self.owner = store, owner
        self.drafts = copy.deepcopy(profiles)
        self.dm = dm
        self.mode = "shared"
        self.field = "categories"
        self.build()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message(
                "These settings belong to another player.", ephemeral=True
            )
            return False
        return True

    def summary(self):
        value = self.drafts[self.mode]
        timing = (
            f"Buzz: {value['buzz_seconds']}s · Answer: {value['answer_seconds']}s · "
            f"Hide after buzz: {value.get('hide_seconds', 0.5):g}s"
            if self.mode == "shared"
            else "Private practice is untimed."
        )
        return (
            f"**Personal settings · {self.mode}** (unsaved until Save)\n"
            f"{value['count']} questions · {value['pool']} · {value['format']} · {value['role']}\n"
            f"Categories: {', '.join(value['categories'])}\nSource: {value['source']}\n"
            f"{timing}\n"
            f"DM reviews: **{'On' if self.dm else 'Off'}**"
        )

    async def refresh(self, interaction):
        self.build()
        await interaction.response.edit_message(content=self.summary(), view=self)

    def build(self):
        self._generation = getattr(self, "_generation", 0) + 1
        generation = self._generation
        self.clear_items()

        async def current(interaction):
            if interaction.user.id != self.owner:
                await interaction.response.send_message(
                    "These settings belong to another player.", ephemeral=True
                )
                return False
            if self.is_finished() or generation != self._generation:
                await interaction.response.send_message(
                    "These settings controls have expired. Reopen /settings.", ephemeral=True
                )
                return False
            return True

        mode = discord.ui.Select(
            placeholder="Settings profile",
            options=[
                discord.SelectOption(label=x.title(), value=x, default=x == self.mode)
                for x in ("shared", "solo")
            ],
            row=0,
        )

        async def change_mode(interaction):
            if not await current(interaction):
                return
            self.mode = mode.values[0]
            if self.mode == "shared" and self.field == "role":
                self.field = "categories"
            await self.refresh(interaction)

        mode.callback = change_mode
        self.add_item(mode)
        fields = ["categories", "pool", "format", "numbers", "source"]
        if self.mode == "solo":
            fields.append("role")
        field = discord.ui.Select(
            placeholder="Preference to edit",
            options=[
                discord.SelectOption(label=x.title(), value=x, default=x == self.field)
                for x in fields
            ],
            row=1,
        )

        async def change_field(interaction):
            if not await current(interaction):
                return
            self.field = field.values[0]
            if self.field == "numbers":
                await interaction.response.send_modal(SettingsNumbers(self))
            elif self.field == "source":
                await interaction.response.send_modal(SettingsSource(self))
            else:
                await self.refresh(interaction)

        field.callback = change_field
        self.add_item(field)
        values = {
            "categories": CATEGORIES,
            "pool": ("regional", "invitational", "all"),
            "format": ("short_answer", "multiple_choice", "all"),
            "role": ("tossup", "bonus", "all"),
        }
        if self.field in values:
            selected = self.drafts[self.mode][self.field]
            if not isinstance(selected, list):
                selected = [selected]
            editor = discord.ui.Select(
                placeholder=self.field.title(),
                min_values=1,
                max_values=len(CATEGORIES) if self.field == "categories" else 1,
                options=[
                    discord.SelectOption(
                        label=x.replace("_", " ").title(), value=x, default=x in selected
                    )
                    for x in values[self.field]
                ],
                row=2,
            )

            editor_mode, editor_field = self.mode, self.field

            async def change_value(interaction):
                if not await current(interaction):
                    return
                if self.mode != editor_mode or self.field != editor_field:
                    return await interaction.response.send_message(
                        "This preference control has expired. Select the preference again.",
                        ephemeral=True,
                    )
                self.drafts[editor_mode][editor_field] = (
                    editor.values if self.field == "categories" else editor.values[0]
                )
                await self.refresh(interaction)

            editor.callback = change_value
            self.add_item(editor)

        async def save(interaction):
            if not await current(interaction):
                return
            await interaction.response.defer()
            try:
                await self.store.save_preferences(self.owner, self.drafts, self.dm)
            except Exception as exc:  # noqa: BLE001 -- keep the private panel usable on failure
                logger.error("Settings save failed (%s)", type(exc).__name__)
                await interaction.followup.send(
                    "Settings could not be saved. Please try again.", ephemeral=True
                )
                return
            await interaction.edit_original_response(
                content="Personal settings saved. Future games use these defaults.", view=None
            )
            self.stop()

        async def cancel(interaction):
            if not await current(interaction):
                return
            await interaction.response.edit_message(content="Unsaved changes discarded.", view=None)
            self.stop()

        async def reset(interaction):
            if not await current(interaction):
                return
            self.drafts[self.mode] = default_settings(self.mode)
            await self.refresh(interaction)

        async def toggle(interaction):
            if not await current(interaction):
                return
            self.dm = not self.dm
            await self.refresh(interaction)

        self.add_item(button("Save", save, style=discord.ButtonStyle.success, row=4))
        self.add_item(button("Cancel", cancel, row=4))
        self.add_item(button("Reset profile", reset, row=4))
        self.add_item(button(f"DM reviews: {'On' if self.dm else 'Off'}", toggle, row=4))
