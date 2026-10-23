"""Restore backed-up NapCat connection files, without touching archives or models."""

import json
import shutil
import sys
from pathlib import Path

runtime = (
    Path(sys.argv[1]).resolve()
    if len(sys.argv) > 1
    else Path(__file__).resolve().parents[2] / "AstrBot"
)
workspace = runtime.parent.resolve()
manifest = runtime / "backups/napcat-rollback.json"
if not manifest.is_file():
    raise SystemExit("没有找到切换前的 NapCat 备份。")
for item in json.loads(manifest.read_text(encoding="utf-8")):
    source, backup = Path(item["source"]).resolve(), Path(item["backup"]).resolve()
    if not source.is_relative_to(workspace) or not backup.is_relative_to(runtime / "backups"):
        raise SystemExit("备份路径超出工作目录，拒绝恢复。")
    if not source.name.startswith("onebot11_") or source.name != backup.name:
        raise SystemExit("备份文件名不匹配，拒绝恢复。")
    shutil.copy2(backup, source)
print("已恢复原 NapCat 连接。关闭 AstrBot，启动 start-nonebot.bat 并重启 NapCat 后生效。")
