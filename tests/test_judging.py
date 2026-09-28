import asyncio

from scibowl.judging import AnswerJudge
from scibowl.models import Question


def test_local_alias_and_formula_case():
    judge = AnswerJudge()
    assert (
        asyncio.run(
            judge.judge(
                Question("1", "", "DNA", "Biology", aliases=["deoxyribonucleic acid"]),
                " Deoxyribonucleic   acid ",
            )
        ).verdict
        == "correct"
    )
    assert (
        asyncio.run(judge.judge(Question("2", "", "H2O", "Chemistry"), "h2o")).verdict == "ungraded"
    )
    assert (
        asyncio.run(judge.judge(Question("3", "", "5 mW", "Physics"), "5 MW")).verdict == "ungraded"
    )
    assert (
        asyncio.run(judge.judge(Question("4", "", "5 mW", "Physics"), "5 mW")).verdict == "correct"
    )
    assert (
        asyncio.run(judge.judge(Question("4a", "", "5mW", "Physics"), "5MW")).verdict == "ungraded"
    )
    assert (
        asyncio.run(judge.judge(Question("4b", "", "m/s", "Physics"), "M/s")).verdict == "ungraded"
    )
    assert (
        asyncio.run(judge.judge(Question("5", "", "Co", "Chemistry"), "co")).verdict == "ungraded"
    )
    assert (
        asyncio.run(judge.judge(Question("6", "", "positive", "Physics"), "not positive")).verdict
        == "ungraded"
    )


def test_multiple_choice_is_local():
    question = Question(
        "1", "", "B", "Physics", format="multiple_choice", choices={"A": "one", "B": "two"}
    )
    assert asyncio.run(AnswerJudge().judge(question, "two")).verdict == "correct"
    assert asyncio.run(AnswerJudge().judge(question, "A")).verdict == "incorrect"
    packet_question = Question(
        "2",
        "",
        "W) MITOCHONDRIA",
        "Biology",
        format="multiple_choice",
        choices={"W": "MITOCHONDRIA"},
    )
    assert asyncio.run(AnswerJudge().judge(packet_question, "w")).verdict == "correct"
    assert asyncio.run(AnswerJudge().judge(packet_question, "mitochondria")).verdict == "correct"


async def test_groq_json_and_failure_are_safe():
    judge = AnswerJudge()

    class FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs["temperature"] == 0
            assert kwargs["reasoning_effort"] == "low"
            assert kwargs["max_completion_tokens"] == 512
            assert kwargs["response_format"]["json_schema"]["strict"] is True
            return {
                "choices": [
                    {"message": {"content": '{"verdict":"correct","explanation":"equivalent"}'}}
                ]
            }

    class FakeClient:
        class chat:
            completions = FakeCompletions()

    judge._client = FakeClient()
    assert (
        await judge.judge(Question("1", "why", "answer", "Physics"), "equivalent answer")
    ).verdict == "correct"

    class Broken:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise RuntimeError("secret")

    judge._client = Broken()
    result = await judge.judge(Question("2", "why", "answer", "Physics"), "unknown")
    assert result.verdict == "ungraded"
    assert "secret" not in result.explanation


async def test_non_gpt_oss_omits_model_specific_options():
    judge = AnswerJudge(model="llama-3.3-70b-versatile")

    class FakeCompletions:
        async def create(self, **kwargs):
            assert "reasoning_effort" not in kwargs
            assert kwargs["response_format"] == {"type": "json_object"}
            return {
                "choices": [{"message": {"content": '{"verdict":"incorrect","explanation":"no"}'}}]
            }

    class FakeClient:
        class chat:
            completions = FakeCompletions()

    judge._client = FakeClient()
    verdict = await judge.judge(Question("1", "why", "answer", "Physics"), "other")
    assert verdict.verdict == "incorrect"


async def test_rate_limit_cooldown_skips_requests():
    judge = AnswerJudge()
    calls = 0

    class RateLimited(Exception):
        status_code = 429

        def __init__(self):
            self.response = type("Response", (), {"headers": {"Retry-After": "60"}})()

    class FakeCompletions:
        async def create(self, **kwargs):
            nonlocal calls
            calls += 1
            raise RateLimited()

    class FakeClient:
        class chat:
            completions = FakeCompletions()

    judge._client = FakeClient()
    question = Question("1", "why", "answer", "Physics")
    assert (await judge.judge(question, "first")).verdict == "ungraded"
    assert (await judge.judge(question, "second")).verdict == "ungraded"
    assert calls == 1
