"""Start AstrBot without passing secrets in process arguments or console output."""

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

runtime = Path(
    os.environ.get("NANAMI_ASTRBOT_ROOT", Path(__file__).resolve().parents[2] / "AstrBot")
).resolve()
if not (runtime / "data/cmd_config.json").is_file():
    raise SystemExit("尚未迁移配置，请先运行 setup_astrbot.ps1。")
os.environ["ASTRBOT_ROOT"] = str(runtime)
load_dotenv(runtime / ".env", override=False)
os.chdir(runtime)
executable = (
    runtime / ".venv/Scripts/astrbot.exe" if os.name == "nt" else runtime / ".venv/bin/astrbot"
)
raise SystemExit(subprocess.call([str(executable), "run"], cwd=runtime))
