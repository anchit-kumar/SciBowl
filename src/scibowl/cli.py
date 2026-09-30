"""uv entry point for bot operation and offline question-bank maintenance."""

import argparse
import asyncio
import json
import logging
import os
import sqlite3
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from .bank import load_approved, parse_pdfs, validate_staging
from .replacements import apply_replacements
from .storage import Store


def parser():
    root = argparse.ArgumentParser(prog="scibowl")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("bot", help="Run the Discord bot")
    doctor = sub.add_parser(
        "doctor", help="Check configuration and local bank without connecting Discord"
    )
    doctor.add_argument(
        "--groq", action="store_true", help="Also send two synthetic answers to Groq"
    )
    commands = sub.add_parser("commands").add_subparsers(dest="action", required=True)
    commands.add_parser("sync", help="Register commands in DISCORD_GUILD_ID or globally")
    bank = sub.add_parser("bank").add_subparsers(dest="action", required=True)
    parse = bank.add_parser("parse")
    parse.add_argument("path", type=Path)
    parse.add_argument("--source", required=True)
    parse.add_argument("--pool", choices=["regional", "invitational"], default="regional")
    parse.add_argument("--source-url", default="")
    parse.add_argument("--output", type=Path, default=Path("staging/questions.json"))
    for name in ("validate", "import"):
        bank.add_parser(name).add_argument("path", type=Path)
    replace = bank.add_parser(
        "replace", help="Validate reviewed text replacements; dry run by default"
    )
    replace.add_argument("path", type=Path)
    replace.add_argument("--apply", action="store_true", help="Back up and apply atomically")
    db = sub.add_parser("db").add_subparsers(dest="action", required=True)
    for name in ("backup", "restore"):
        db.add_parser(name).add_argument("path", type=Path)
    return root


def configure_logging():
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        "logs/scibowl.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler, logging.StreamHandler()],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # HTTP debug logs may contain request data. Keep provider logs quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("groq").setLevel(logging.WARNING)


async def run(args):
    if args.command == "doctor":
        from .preflight import check

        if not await check(groq=args.groq):
            raise SystemExit(1)
        return
    db_path = Path(os.getenv("SCIBOWL_DB", "data/scibowl.sqlite3"))
    if args.command in ("bot", "commands"):
        from .discord_app import BowlBot

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("Set DISCORD_TOKEN in the ignored local .env before connecting.")
        configure_logging()
        bot = BowlBot(
            db_path,
            os.getenv("GROQ_API_KEY") or None,
            os.getenv("GROQ_MODEL") or "openai/gpt-oss-20b",
            os.getenv("DISCORD_GUILD_ID") or None,
            sync_only=args.command == "commands",
        )
        async with bot:
            if args.command == "commands":
                await bot.login(token)
                print("Discord commands registered.")
            else:
                await bot.start(token)
        return
    if args.command == "bank" and args.action == "parse":
        if not args.path.exists():
            raise ValueError("The PDF file or folder does not exist.")
        payload = parse_pdfs(args.path, args.source, args.pool, args.source_url)
        if args.output.exists():
            raise ValueError(
                "Output already exists; select a new --output path to preserve previous review work."
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"Staged {len(payload['questions'])} questions with {len(payload['issues'])} issues in {args.output}."
        )
        return
    if args.command == "bank" and args.action == "replace":
        payload = json.loads(args.path.read_text(encoding="utf-8"))
        print(json.dumps(apply_replacements(db_path, payload, apply=args.apply), indent=2))
        return
    if args.command == "bank":
        payload = json.loads(args.path.read_text(encoding="utf-8"))
        errors = validate_staging(payload)
        if errors:
            raise ValueError("\n".join(errors))
        if args.action == "validate":
            print(f"Validated {len(payload['questions'])} reviewed questions.")
            return
        questions = load_approved(payload)
        store = await Store(db_path).open()
        try:
            inserted = await store.import_questions(questions)
            print(f"Imported {inserted} questions; {len(questions) - inserted} duplicates skipped.")
        finally:
            await store.close()
        return
    if args.command == "db":
        if args.path.resolve() == db_path.resolve():
            raise ValueError("Backup path must differ from the live database.")
        if args.action == "restore":
            if not args.path.is_file():
                raise ValueError("Backup file does not exist.")
            if db_path.exists():
                raise ValueError(
                    "Restore requires a new SCIBOWL_DB path. Stop the bot and choose a new path; the existing database will not be overwritten."
                )
            with sqlite3.connect(
                f"file:{args.path.resolve().as_posix()}?mode=ro", uri=True
            ) as source:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed.")
                if source.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ValueError("Unsupported backup schema.")
                db_path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(db_path) as target:
                    source.backup(target)
            print(f"Restored database into {db_path}.")
        else:
            if not db_path.exists():
                raise ValueError("No database exists to back up.")
            if args.path.exists():
                raise ValueError("Backup target already exists; choose a new filename.")
            store = await Store(db_path).open()
            try:
                await store.backup(args.path)
            finally:
                await store.close()
            print(f"Backup saved to {args.path}.")


def main():
    load_dotenv()
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
