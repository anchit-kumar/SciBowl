import pytest

from scibowl import preflight
from scibowl.models import Judgment, Question
from scibowl.storage import Store


@pytest.mark.asyncio
async def test_missing_bank_is_read_only_and_credentials_are_hidden(tmp_path, monkeypatch, capsys):
    path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("SCIBOWL_DB", str(path))
    monkeypatch.setenv("DISCORD_TOKEN", "secret-discord-value")
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq-value")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456")
    assert not await preflight.check()
    output = capsys.readouterr().out
    assert "secret-" not in output
    assert "test guild" in output
    assert not path.exists()


@pytest.mark.asyncio
async def test_preflight_mocked_groq_failure_and_cleanup(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bank.sqlite3"
    store = await Store(path).open()
    await store.import_questions([Question("q", "Question", "Answer", "Biology")])
    await store.close()
    monkeypatch.setenv("SCIBOWL_DB", str(path))
    monkeypatch.setenv("DISCORD_TOKEN", "secret-discord")
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq")
    monkeypatch.setenv("DISCORD_GUILD_ID", "")

    class Judge:
        closed = False

        def __init__(self, *args):
            pass

        async def judge(self, *args):
            return Judgment("ungraded", "", "groq")

        async def close(self):
            Judge.closed = True

    monkeypatch.setattr(preflight, "AnswerJudge", Judge)
    assert await preflight.check()
    assert not await preflight.check(groq=True)
    assert Judge.closed
    assert "FAIL" in capsys.readouterr().out
