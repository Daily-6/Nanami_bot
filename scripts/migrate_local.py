"""One-time local migration; secrets and runtime data are NEVER written to the repo."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

PLUGIN_FILES = (
    "__init__.py",
    "main.py",
    "nanami_core.py",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
)


def write_json(path: Path, obj: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def local_path(value: str, workspace: Path) -> str:
    """Repair moved Windows references only when the matching file exists."""
    source = Path(value)
    if source.is_file():
        return str(source.resolve())
    parts = source.parts
    for index, part in enumerate(parts):
        if part.lower() in ("gpt-sovits", "gpt_sovits"):
            candidate = workspace.joinpath(*parts[index:])
            if candidate.is_file():
                return str(candidate.resolve())
    # No heuristic broad filesystem search or silent substitution of a different voice.
    raise ValueError("参考音频路径已失效，请在 AstrBot 的 GPT-SoVITS 设置中重新选择原文件")


async def configure(source: Path, runtime: Path):
    if runtime == source or runtime.is_relative_to(source):
        raise ValueError("AstrBot 运行目录必须在 Git 仓库之外")
    os.environ["ASTRBOT_ROOT"] = str(runtime)
    data = runtime / "data"
    data.mkdir(parents=True, exist_ok=True)
    config_path = data / "cmd_config.json"
    if config_path.exists():
        raise ValueError(
            "运行配置已存在；为保护面板中的修改，迁移不会覆盖。更新插件请使用 --sync-only"
        )

    env = {**dotenv_values(source / ".env.prod"), **dotenv_values(source / ".env")}
    key = env.get("DEEPSEEK_API_KEY") or ""
    if not key or key.startswith("your_"):
        raise ValueError("原项目缺少有效的 DEEPSEEK_API_KEY；没有写入任何迁移配置")
    admins = [str(s) for s in json.loads(env.get("SUPERUSERS") or "[]")]
    if not admins:
        raise ValueError("原项目 SUPERUSERS 为空，先明确管理员后再迁移")
    emotions = json.loads(env.get("GPT_SOVITS_EMOTION_MAP") or "[]")
    if not emotions or not emotions[0].get("sentences"):
        raise ValueError("原项目没有配置 GPT-SoVITS 参考音色")
    reference = emotions[0]["sentences"][0]
    reference_path = local_path(reference["path"], source.parent)
    prompt = (source / "src/plugins/voice_version_character_prompt.txt").read_text(
        encoding="utf-8-sig"
    )
    archives = []
    for file in (source / "data/chat_archive").glob("*.json"):
        if file.stem.isdigit():
            items = json.loads(file.read_text(encoding="utf-8-sig"))
            if not isinstance(items, list):
                raise TypeError("原项目存档格式异常，原文件未修改")
            archives.append((file, len(items)))
    # Import after ASTRBOT_ROOT is set so AstrBot never initializes data in the repo.
    from astrbot.core.config.default import DEFAULT_CONFIG
    from astrbot.core.db.sqlite import SQLiteDatabase
    from astrbot.core.utils.auth_password import (
        generate_dashboard_password,
        hash_dashboard_password,
    )

    config = copy.deepcopy(DEFAULT_CONFIG)
    config["dashboard"].update({"host": "127.0.0.1", "port": 6185})
    password = generate_dashboard_password()
    config["dashboard"].update(
        {
            "username": "nanami",
            "password": "",
            "pbkdf2_password": hash_dashboard_password(password),
            "password_storage_upgraded": True,
            "password_change_required": False,
            "jwt_secret": secrets.token_urlsafe(48),
        }
    )
    ws_token = secrets.token_urlsafe(32)
    config["platform"] = [
        {
            "id": "nanami_qq",
            "type": "aiocqhttp",
            "enable": True,
            "ws_reverse_host": "127.0.0.1",
            "ws_reverse_port": 8080,
            "ws_reverse_token": ws_token,
        }
    ]
    config["platform_settings"].update(
        {
            "unique_session": True,
            "enable_id_white_list": False,
            "ignore_bot_self_message": True,
            "ignore_at_all": True,
        }
    )
    config["admins_id"] = admins
    config["provider_sources"] = [
        {
            "id": "nanami_deepseek_source",
            "provider": "openai",
            "type": "openai_chat_completion",
            "provider_type": "chat_completion",
            "enable": True,
            "key": ["$DEEPSEEK_API_KEY"],
            "api_base": "https://api.deepseek.com/v1",
            "timeout": 30,
            "proxy": "",
            "custom_headers": {},
        }
    ]
    config["provider"] = [
        {
            "id": "nanami_deepseek",
            "provider_source_id": "nanami_deepseek_source",
            "type": "openai_chat_completion",
            "provider_type": "chat_completion",
            "enable": True,
            "model": "deepseek-v4-flash",
            "modalities": ["text"],
            "custom_extra_body": {"temperature": 0.85, "max_tokens": 260},
        }
    ]
    runner = config["agent_runner"]["config"]
    runner["model"]["provider_id"] = "nanami_deepseek"
    runner["persona"]["persona_id"] = "nanami"
    runner["compression"].update({"max_turns": 30, "overflow_strategy": "truncate_by_turns"})
    runner["misc"].update({"max_steps": 4, "tool_call_timeout": 30})
    config["provider_settings"].update(
        {
            "computer_use_runtime": "none",
            "web_search": False,
            "streaming_response": False,
            "show_tool_call_result": False,
        }
    )
    config["provider_settings"]["proactive_capability"]["add_cron_tools"] = False
    config["provider_settings"]["computer_use_local_permissions"]["member"].update(
        {"allow_execution": False, "allow_network": False, "filesystem_scope": "none"}
    )
    config["provider_ltm_settings"]["active_reply"]["enable"] = False
    config["provider_tts_settings"].update(
        {"enable": True, "provider_id": "nanami_gsv", "dual_output": False}
    )
    parameters = {
        "gsv_ref_audio_path": reference_path,
        "gsv_prompt_text": reference["text"],
        "gsv_prompt_lang": reference.get("language", "zh"),
        "gsv_text_lang": "zh",
        "gsv_top_k": 3,
        "gsv_top_p": 0.7,
        "gsv_temperature": 0.8,
        "gsv_text_split_method": "cut3",
        "gsv_speed_factor": 0.95,
        "gsv_media_type": "wav",
        "gsv_streaming_mode": False,
    }
    custom_args = json.loads(env.get("GPT_SOVITS_ARGS") or "{}")
    parameters.update(
        {
            f"gsv_{k}": v
            for k, v in custom_args.items()
            if k
            in {
                "top_k",
                "top_p",
                "temperature",
                "text_split_method",
                "speed_factor",
                "seed",
                "repetition_penalty",
            }
        }
    )
    config["provider"].append(
        {
            "id": "nanami_gsv",
            "enable": True,
            "provider": "gpt_sovits",
            "type": "gsv_tts_selfhost",
            "provider_type": "text_to_speech",
            "api_base": env.get("GPT_SOVITS_API_BASE_URL") or "http://127.0.0.1:9880",
            "gpt_weights_path": "",
            "sovits_weights_path": "",
            "timeout": 90,
            "gsv_default_parms": parameters,
        }
    )
    config["log_file_enable"] = False
    config["trace_enable"] = False
    config["pypi_index_url"] = "https://pypi.org/simple/"
    db = SQLiteDatabase(str(data / "data_v4.db"))
    try:
        await db.initialize()
        if not await db.get_persona_by_id("nanami"):
            await db.insert_persona(
                "nanami",
                prompt,
                tools=[],
                skills=[],
                custom_error_message="刚才没接上，请稍后再试一下喔。",
            )
    finally:
        await db.engine.dispose()
    # Only the needed model credential is copied; unrelated Qwen and other credentials stay put.
    (runtime / ".env").write_text(f"DEEPSEEK_API_KEY={json.dumps(key)}\n", encoding="utf-8")
    (runtime / "local-access.txt").write_text(
        f"仅在本机保管，不上传、不截图分享。\n面板：http://127.0.0.1:6185\n用户名：nanami\n密码：{password}\n",
        encoding="utf-8",
    )
    write_json(config_path, config)
    (runtime / ".astrbot").touch(exist_ok=True)
    sync_plugin(source, runtime)
    archive_dir = data / "plugin_data/astrbot_plugin_nanami/chat_archive"
    count = 0
    for file, item_count in archives:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, archive_dir / file.name)
        count += item_count
    print(f"已迁移人格、模型、语音配置、管理员和 {count} 条存档；密钥未输出。")
    print("面板：http://127.0.0.1:6185；登录信息只写入运行目录的 local-access.txt。")


def sync_plugin(source: Path, runtime: Path):
    plugin = runtime / "data/plugins/astrbot_plugin_nanami"
    plugin.mkdir(parents=True, exist_ok=True)
    for name in PLUGIN_FILES:
        shutil.copy2(source / name, plugin / name)


def activate_napcat(runtime: Path, napcat_root: Path):
    config = json.loads((runtime / "data/cmd_config.json").read_text(encoding="utf-8"))
    platform = next(p for p in config["platform"] if p["id"] == "nanami_qq")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest = []
    for path in napcat_root.glob("versions/*/resources/app/napcat/config/onebot11_*.json"):
        original = json.loads(path.read_text(encoding="utf-8-sig"))
        updated = copy.deepcopy(original)
        changed = False
        for client in updated.get("network", {}).get("websocketClients", []):
            if client.get("enable") and client.get("url") == "ws://127.0.0.1:8080/onebot/v11/ws":
                client.update(
                    {"url": "ws://127.0.0.1:8080/ws", "token": platform["ws_reverse_token"]}
                )
                changed = True
        if changed:
            backup = runtime / "backups" / timestamp / path.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            write_json(path, updated)
            manifest.append({"source": str(path.resolve()), "backup": str(backup.resolve())})
    if manifest:
        write_json(runtime / "backups" / "napcat-rollback.json", manifest)
    print(f"已切换 {len(manifest)} 个启用的 NapCat 连接；旧配置已备份。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument(
        "--activate-napcat", type=Path, help="可选：将已有 NoneBot 连接切换到 AstrBot，先保存备份"
    )
    parser.add_argument("--sync-only", action="store_true")
    args = parser.parse_args()
    source, runtime = args.source.resolve(), args.runtime.resolve()
    if args.sync_only:
        sync_plugin(source, runtime)
    else:
        asyncio.run(configure(source, runtime))
    if args.activate_napcat:
        activate_napcat(runtime, args.activate_napcat.resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not print exception repr: a parser error could embed credential contents.
        print(
            f"迁移未完成（{type(exc).__name__}）。检查路径、管理员和参考音频配置；没有输出密钥。",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
