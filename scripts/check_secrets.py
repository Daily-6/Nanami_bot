"""Scan Git content without ever printing candidate secret values."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

PATTERNS = [
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{25,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
]
PRIVATE_NAMES = {".env", ".env.prod", "local-access.txt", "cmd_config.json", "napcat-rollback.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    git = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo)]
    known = set()
    for path in (repo / ".env", repo / ".env.prod", repo.parent / "AstrBot/.env"):
        if path.is_file():
            data = path.read_bytes()
            known.update(match.group() for pattern in PATTERNS for match in pattern.finditer(data))
            for name, value in dotenv_values(path).items():
                if (
                    value
                    and any(marker in name.lower() for marker in ("api_key", "token", "secret"))
                    and len(value) >= 12
                    and not value.startswith("your_")
                ):
                    known.add(value.encode("utf-8"))
    runtime_config = repo.parent / "AstrBot/data/cmd_config.json"
    if runtime_config.is_file():

        def collect(obj):
            if isinstance(obj, dict):
                for name, value in obj.items():
                    if (
                        isinstance(value, str)
                        and len(value) >= 12
                        and any(
                            marker in name.lower() for marker in ("token", "secret", "password")
                        )
                    ):
                        known.add(value.encode("utf-8"))
                    collect(value)
            elif isinstance(obj, list):
                for value in obj:
                    collect(value)

        collect(json.loads(runtime_config.read_text(encoding="utf-8-sig")))
    names = subprocess.check_output(
        git + ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
        if args.staged
        else git + ["ls-files", "-z"]
    ).split(b"\0")
    findings = []
    for raw in filter(None, names):
        name = raw.decode("utf-8")
        path = Path(name)
        if (
            path.name in PRIVATE_NAMES
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.parts[0] in {"data", "backups", "venv", ".venv", "aitalk_config"}
        ):
            findings.append(f"{name}: private/runtime file")
            continue
        data = (
            subprocess.check_output(git + ["show", f":{name}"])
            if args.staged
            else (repo / name).read_bytes()
        )
        for line, content in enumerate(data.splitlines(), 1):
            if any(pattern.search(content) for pattern in PATTERNS) or any(
                secret in content for secret in known
            ):
                findings.append(f"{name}:{line}: possible credential (value hidden)")
    if findings:
        print("\n".join(findings))
        raise SystemExit(1)
    print(
        f"PASS: scanned {len(list(filter(None, names)))} Git files; no matching credentials or private runtime files."
    )


if __name__ == "__main__":
    main()
