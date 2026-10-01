"""Private setup panels used before starting a game or private practice."""

from __future__ import annotations

from typing import Any

import discord

from .models import CATEGORIES, validate_settings


def help_embed() -> discord.Embed:
    return discord.Embed(
        title="Science Bowl commands",
        description="```\n/game start        Set up a shared game\n/practice start    Set up private practice\n/game pause | resume | skip | stop\n/game speed        Set next question reading speed\n/practice stop     End private practice\n/answer             Submit after buzzing\n/review             Open your saved review\n/clear              Clear latest session messages\n/settings           Set defaults and review DMs\n/score | /stats     View your results\n/sources | /status  Inspect the question bank\n/admin settings     Configure allowed channels\n```",
        color=discord.Color.blurple(),
    ).set_footer(
        text="Setup choices apply only to this session. /settings changes future defaults."
    )


class NumericSetupModal(discord.ui.Modal):
    def __init__(self, view: GameSetupView, field: str):
        label = {
            "count": "Question count (1-100)",
            "buzz_seconds": "Buzz time (5-120)",
            "answer_seconds": "Answer time (5-120)",
            "hide_seconds": "Hide after buzz (0-10 seconds)",
            "reading_wpm": "Reading speed (60-300 WPM)",
        }[field]
        super().__init__(title=label)
        self.view, self.field = view, field
        self.value_input = discord.ui.TextInput(
            label=label,
            default=str(view.settings[field]),
            max_length=24 if field == "hide_seconds" else 3,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.view.owner:
            await interaction.response.send_message(
                "This setup belongs to another player.", ephemeral=True
            )
            return
        if self.view.closed or self.view.starting:
            await interaction.response.send_message(
                "This setup panel is no longer editable.", ephemeral=True
            )
            return
        try:
            value = (
                float(self.value_input.value.strip())
                if self.field == "hide_seconds"
                else int(self.value_input.value.strip())
            )
            candidate = dict(self.view.settings)
            candidate[self.field] = value
            validate_settings(candidate)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                "Use 1-100 questions, 5-120 timer seconds, 0-10 hide seconds, or 60-300 WPM.",
                ephemeral=True,
            )
            return
        self.view.settings[self.field] = value
        await self.view._redraw_from_modal(interaction)


class GameSetupView(discord.ui.View):
    """Owner-only, disposable setup UI. It never persists personal defaults."""

    fields = ("pool", "format", "source", "role", "reading_mode")

    def __init__(
        self,
        app: Any,
        owner: int,
        mode: str,
        settings: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=300)
        self.app, self.owner, self.mode = app, owner, mode
        self.settings = dict(settings)
        self.settings["categories"] = list(settings["categories"])
        self.sources, self.selected_field, self.source_page = list(sources), "pool", 0
        self.generation, self.closed, self.starting = 0, False, False
        self._build()

    def embed(self, error: str | None = None) -> discord.Embed:
        text = (
            f"**Questions:** {self.settings['count']}\n**Categories:** {', '.join(self.settings['categories'])}\n"
            f"**Pool:** {self.settings['pool']} | **Source:** {self.settings.get('source', 'all')}\n"
            f"**Format:** {self.settings['format']} | **Role:** {self.settings['role']}\n"
        )
        text += (
            f"**Buzz:** {self.settings['buzz_seconds']}s | **Answer:** {self.settings['answer_seconds']}s"
            f" | **Hide after buzz:** {self.settings.get('hide_seconds', 0.5):g}s"
            f" | **Reading:** {self.settings.get('reading_mode', 'paced')} at {self.settings.get('reading_wpm', 180)} WPM"
            if self.mode == "shared"
            else "**Timing:** Untimed private practice"
        )
        if error:
            text += f"\n\nWarning: {error}"
        return discord.Embed(
            title="Game setup" if self.mode == "shared" else "Practice setup",
            description=text,
            color=discord.Color.blurple(),
        ).set_footer(
            text="These choices apply only to this session. /settings changes future defaults."
        )

    def _guard(self, generation: int, callback):
        async def guarded(interaction: discord.Interaction) -> None:
            if generation != self.generation or self.closed:
                await interaction.response.send_message(
                    "This setup control is no longer current.", ephemeral=True
                )
            elif self.starting:
                await interaction.response.send_message(
                    "This session is starting now.", ephemeral=True
                )
            else:
                await callback(interaction)

        return guarded

    def _build(self) -> None:
        self.clear_items()
        generation = self.generation
        cats = discord.ui.Select(
            placeholder="Categories (choose one or more)",
            min_values=1,
            max_values=len(CATEGORIES),
            row=0,
            options=[
                discord.SelectOption(label=x, value=x, default=x in self.settings["categories"])
                for x in CATEGORIES
            ],
        )
        cats.callback = self._guard(generation, self._choose_categories)
        self.add_item(cats)
        fields = [
            x
            for x in self.fields
            if (self.mode == "solo" and x != "reading_mode")
            or (self.mode == "shared" and x != "role")
        ]
        field = discord.ui.Select(
            placeholder="Choose a setting to edit",
            row=1,
            options=[
                discord.SelectOption(
                    label=x.replace("_", " ").title(), value=x, default=x == self.selected_field
                )
                for x in fields
            ],
        )
        field.callback = self._guard(generation, self._choose_field)
        self.add_item(field)
        self._add_value_select(generation)
        if self.selected_field == "source" and len(self._source_names()) > 24:
            self._add_source_navigation(generation)
        else:
            names = (
                ("count", "buzz_seconds", "answer_seconds", "reading_wpm")
                if self.mode == "shared"
                else ("count",)
            )
            labels = {
                "count": "Question count",
                "buzz_seconds": "Buzz time",
                "answer_seconds": "Answer time",
                "reading_wpm": "Reading speed (WPM)",
            }
            for name in names:
                button = discord.ui.Button(label=labels[name], row=3)
                button.callback = self._guard(generation, self._numeric_callback(name))
                self.add_item(button)
        if self.mode == "shared":
            hide = discord.ui.Button(label="Hide after buzz", row=4)
            hide.callback = self._guard(generation, self._numeric_callback("hide_seconds"))
            self.add_item(hide)
        start = discord.ui.Button(
            label="Start game" if self.mode == "shared" else "Start practice",
            style=discord.ButtonStyle.success,
            row=4,
        )
        start.callback = self._guard(generation, self._start)
        self.add_item(start)

    def _source_names(self) -> list[str]:
        names = []
        for source in self.sources:
            name = str(source.get("source", source.get("name", ""))).strip()
            if name and name not in names:
                names.append(name)
        return names

    def _add_value_select(self, generation: int) -> None:
        if self.selected_field == "source":
            names, offset = self._source_names(), self.source_page * 24
            options = [
                discord.SelectOption(
                    label="All sources", value="all", default=self.settings["source"] == "all"
                )
            ]
            options += [
                discord.SelectOption(
                    label=name[:100], value=str(i), default=self.settings["source"] == name
                )
                for i, name in enumerate(names[offset : offset + 24], offset)
            ]
        else:
            values = {
                "pool": ("regional", "invitational", "all"),
                "format": ("short_answer", "multiple_choice", "all"),
                "role": ("tossup", "bonus", "all"),
                "reading_mode": ("paced", "full"),
            }[self.selected_field]
            options = [
                discord.SelectOption(
                    label=x.replace("_", " ").title(),
                    value=x,
                    default=self.settings[self.selected_field] == x,
                )
                for x in values
            ]
        select = discord.ui.Select(
            placeholder=f"Set {self.selected_field.replace('_', ' ')}", options=options, row=2
        )
        select.callback = self._guard(generation, self._choose_value)
        self.add_item(select)

    def _add_source_navigation(self, generation: int) -> None:
        pages = (len(self._source_names()) + 23) // 24
        for label, change, disabled in (
            ("Previous sources", -1, self.source_page == 0),
            ("More sources", 1, self.source_page >= pages - 1),
        ):
            button = discord.ui.Button(label=label, disabled=disabled, row=3)
            button.callback = self._guard(generation, self._page_callback(change))
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner:
            await interaction.response.send_message(
                "This setup belongs to another player.", ephemeral=True
            )
            return False
        if self.closed or self.starting:
            await interaction.response.send_message(
                "This setup panel is no longer editable.", ephemeral=True
            )
            return False
        return True

    async def _redraw(self, interaction: discord.Interaction) -> None:
        self.generation += 1
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _redraw_from_modal(self, interaction: discord.Interaction) -> None:
        self.generation += 1
        self._build()
        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(embed=self.embed(), view=self)

    async def _choose_categories(self, interaction):
        self.settings["categories"] = list(interaction.data.get("values", []))
        await self._redraw(interaction)

    async def _choose_field(self, interaction):
        self.selected_field = interaction.data.get("values", [self.selected_field])[0]
        self.source_page = 0
        await self._redraw(interaction)

    async def _choose_value(self, interaction):
        value = interaction.data.get("values", [""])[0]
        if self.selected_field == "source" and value != "all":
            try:
                value = self._source_names()[int(value)]
            except (IndexError, ValueError):
                await interaction.response.send_message(
                    "That source is no longer available.", ephemeral=True
                )
                return
        self.settings[self.selected_field] = value
        await self._redraw(interaction)

    def _page_callback(self, change):
        async def callback(interaction):
            pages = (len(self._source_names()) + 23) // 24
            self.source_page = max(0, min(pages - 1, self.source_page + change))
            await self._redraw(interaction)

        return callback

    def _numeric_callback(self, field):
        async def callback(interaction):
            await interaction.response.send_modal(NumericSetupModal(self, field))

        return callback

    async def _start(self, interaction):
        if self.starting:
            await interaction.response.send_message(
                "Starting this session already.", ephemeral=True
            )
            return
        self.starting = True
        await interaction.response.defer(ephemeral=True)
        try:
            started = await self.app.start_session(interaction, self.mode, dict(self.settings))
        except ValueError as error:
            started, message = False, str(error)
        except Exception:  # noqa: BLE001 - leave the private setup editable after adapter failure
            started, message = (
                False,
                "Could not start this session. See the private error above and adjust the setup.",
            )
        else:
            message = (
                "Could not start this session. See the private error above and adjust the setup."
            )
        finally:
            self.starting = False
        if started:
            self.closed = True
            self.stop()
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="Session created",
                    description="See your session channel and any recovery notice below.",
                ),
                view=None,
            )
        else:
            await interaction.edit_original_response(embed=self.embed(message), view=self)

    async def on_timeout(self):
        self.closed = True
        self.stop()
