"""Double-click on Windows to run offline checks without console windows.

Results are written to ignored logs/verification.txt and logs/verification.json.
Uses only the existing virtual environment; does not install dependencies or
connect Discord/Groq. No credentials are read.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    artifacts = root / ".test-artifacts"
    artifacts.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    python = root / ".venv" / "Scripts" / "python.exe"
    ruff = root / ".venv" / "Scripts" / "ruff.exe"
    checks = [
        ("lint", [str(ruff), "check", "src", "tests"]),
        ("format", [str(ruff), "format", "--check", "src", "tests"]),
        (
            "tests",
            [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
             f"--basetemp=.test-artifacts/quiet-{stamp}", "--tb=short"],
        ),
    ]
    results = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (logs / "verification.txt").open("w", encoding="utf-8") as output:
        for name, command in checks:
            output.write(f"\n=== {name} ===\n")
            output.flush()
            try:
                completed = subprocess.run(
                    command, cwd=root, stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT, creationflags=flags, timeout=300,
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
                results.append({"check": name, "exit_code": completed.returncode})
            except (OSError, subprocess.TimeoutExpired) as error:
                output.write(f"Unable to complete check: {type(error).__name__}\n")
                results.append({"check": name, "exit_code": -1})
        passed = all(item["exit_code"] == 0 for item in results)
        output.write("\nALL CHECKS PASSED\n" if passed else "\nCHECKS NEED ATTENTION\n")
    (logs / "verification.json").write_text(
        json.dumps({"completed_at": stamp, "passed": passed, "results": results}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
