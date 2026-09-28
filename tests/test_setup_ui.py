from types import SimpleNamespace
from unittest.mock import AsyncMock

from scibowl.models import default_settings
from scibowl.setup_ui import GameSetupView, NumericSetupModal, help_embed


def request(values=()):
    return SimpleNamespace(
        user=SimpleNamespace(id=1),
        data={"values": list(values)},
        response=SimpleNamespace(
            edit_message=AsyncMock(), send_message=AsyncMock(), defer=AsyncMock()
        ),
        edit_original_response=AsyncMock(),
    )


async def test_category_subset_persists_and_starts_without_changing_defaults():
    app = SimpleNamespace(start_session=AsyncMock(return_value=True))
    defaults = default_settings()
    view = GameSetupView(app, 1, "solo", defaults, [])
    await view._choose_categories(request(("Physics", "Chemistry")))
    assert view.settings["categories"] == ["Physics", "Chemistry"]
    assert defaults["categories"] != view.settings["categories"]
    start = request()
    await view._start(start)
    assert app.start_session.await_args.args[2]["categories"] == ["Physics", "Chemistry"]


async def test_numeric_modal_rejects_invalid_value():
    view = GameSetupView(SimpleNamespace(), 1, "shared", default_settings(), [])
    modal = NumericSetupModal(view, "count")
    modal.value_input._value = "101"
    interaction = request()
    await modal.on_submit(interaction)
    interaction.response.send_message.assert_awaited_once()


async def test_numeric_modal_redraw_keeps_start_control_current():
    app = SimpleNamespace(start_session=AsyncMock(return_value=True))
    view = GameSetupView(app, 1, "shared", default_settings(), [])
    modal = NumericSetupModal(view, "count")
    modal.value_input._value = "9"
    update = request()
    await modal.on_submit(update)
    assert view.settings["count"] == 9
    start = request()
    await view._start(start)
    assert app.start_session.await_args.args[2]["count"] == 9


async def test_hide_delay_modal_accepts_fractional_seconds():
    app = SimpleNamespace(start_session=AsyncMock(return_value=True))
    view = GameSetupView(app, 1, "shared", default_settings(), [])
    modal = NumericSetupModal(view, "hide_seconds")
    modal.value_input._value = "0.75"
    await modal.on_submit(request())
    assert view.settings["hide_seconds"] == 0.75
    assert "**Hide after buzz:** 0.75s" in view.embed().description
    await view._start(request())
    assert app.start_session.await_args.args[2]["hide_seconds"] == 0.75


async def test_modal_rejects_wrong_owner_and_starting_panel_cannot_mutate():
    view = GameSetupView(SimpleNamespace(), 1, "shared", default_settings(), [])
    modal = NumericSetupModal(view, "count")
    other = request()
    other.user.id = 2
    await modal.on_submit(other)
    other.response.send_message.assert_awaited_once()
    view.starting = True
    await view.children[0].callback(request(("Physics",)))
    assert view.settings["categories"] != ["Physics"]


async def test_stale_source_index_is_rejected():
    view = GameSetupView(SimpleNamespace(), 1, "shared", default_settings(), [])
    view.selected_field = "source"
    interaction = request(("0",))
    await view._choose_value(interaction)
    interaction.response.send_message.assert_awaited_once()


def test_help_embed_has_command_list():
    assert "/clear" in help_embed().description
