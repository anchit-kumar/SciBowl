from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scibowl.models import default_settings, validate_settings
from scibowl.ui import SettingsNumbers, SettingsSource, SettingsView


def settings_view():
    store = SimpleNamespace(save_preferences=AsyncMock())
    drafts = {mode: default_settings(mode) for mode in ("shared", "solo")}
    return SettingsView(store, 7, drafts, True), store


def interaction(user_id=7):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
    )


async def test_rebuilt_settings_selector_cannot_write_to_new_field():
    view, _ = settings_view()
    old_editor = view.children[2]
    old_editor._values = ["Physics"]

    view.mode = "solo"
    view.field = "pool"
    view.build()
    event = interaction()
    await old_editor.callback(event)

    assert view.drafts["solo"]["pool"] == "all"
    event.response.send_message.assert_awaited_once()


async def test_finished_settings_save_button_cannot_persist():
    view, store = settings_view()
    save = next(item for item in view.children if getattr(item, "label", None) == "Save")
    view.stop()

    event = interaction()
    await save.callback(event)

    store.save_preferences.assert_not_awaited()
    event.response.send_message.assert_awaited_once()


@pytest.mark.parametrize("modal_type", [SettingsNumbers, SettingsSource])
async def test_finished_settings_modals_are_rejected(modal_type):
    view, _ = settings_view()
    modal = modal_type(view)
    view.stop()

    event = interaction()
    await modal.on_submit(event)

    event.response.send_message.assert_awaited_once()


async def test_shared_settings_modal_saves_fractional_hide_delay():
    view, _ = settings_view()
    modal = SettingsNumbers(view)
    assert "hide_seconds" in modal.fields
    modal.fields["hide_seconds"]._value = "0.75"
    await modal.on_submit(interaction())
    assert view.drafts["shared"]["hide_seconds"] == 0.75
    assert "Hide after buzz: 0.75s" in view.summary()
    view.mode = "solo"
    assert "hide_seconds" not in SettingsNumbers(view).fields


@pytest.mark.parametrize("delay", [-0.1, 10.1, float("nan"), float("inf"), True, "0.5"])
def test_invalid_hide_delay_is_rejected(delay):
    with pytest.raises(ValueError, match="hide delay"):
        validate_settings(dict(default_settings(), hide_seconds=delay))
