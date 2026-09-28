"""Read-only configuration checks; never print credentials or provider errors."""

import os
import sqlite3
import time
from pathlib import Path

from .judging import AnswerJudge
from .models import Question


async def check(*, groq: bool = False) -> bool:
    ready = True
    for name in ("DISCORD_TOKEN", "GROQ_API_KEY"):
        present = bool(os.getenv(name, "").strip())
        print(f"{name}: {'configured' if present else 'missing'}")
        ready &= present
    guild = os.getenv("DISCORD_GUILD_ID", "").strip()
    valid_guild = not guild or (guild.isdecimal() and int(guild) > 0)
    print(
        "Commands: " + ("test guild" if guild else "global") if valid_guild else "Guild ID: invalid"
    )
    ready &= valid_guild
    path = Path(os.getenv("SCIBOWL_DB") or "data/scibowl.sqlite3")
    if not path.is_file():
        print("Question bank: missing; import reviewed questions before playing.")
        ready = False
    else:
        try:
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
                count = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
                print(f"Question bank: {count} questions")
                ready &= count > 0
        except sqlite3.Error:
            print("Question bank: could not read the expected schema.")
            ready = False
    if groq:
        judge = AnswerJudge(
            os.getenv("GROQ_API_KEY") or None, os.getenv("GROQ_MODEL") or "openai/gpt-oss-20b"
        )
        question = Question(
            id="preflight",
            text="Which organelle is the main site of aerobic ATP production in eukaryotic cells?",
            answer="mitochondrion",
            category="Biology",
            format="short_answer",
        )
        try:
            for answer, expected in (("mitochondria", "correct"), ("nucleus", "incorrect")):
                start = time.perf_counter()
                result = await judge.judge(question, answer)
                passed = result.method == "groq" and result.verdict == expected
                print(
                    f"Groq {expected} probe: {'PASS' if passed else 'FAIL'} ({time.perf_counter() - start:.2f}s; {result.verdict})"
                )
                ready &= passed
        finally:
            await judge.close()
    print("Preflight passed." if ready else "Preflight needs attention.")
    return bool(ready)
