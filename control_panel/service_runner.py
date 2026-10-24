"""A gated child entry point. It never launches a service until assigned to a job."""

import json
import subprocess
import sys
import time


def main():
    command = json.loads(sys.argv[1])
    if not isinstance(command, list) or not command or not all(isinstance(s, str) for s in command):
        return 2
    if sys.stdin.readline().strip() != "GO":
        return 3
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL)
    result = child.wait()
    # NapCat's bootstrap may hand off to QQ and return. Remain in the job so the
    # controller owns the complete group until the user explicitly stops it.
    if command[0].lower().endswith("napcatwinbootmain.exe") and result == 0:
        while True:
            time.sleep(1)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
