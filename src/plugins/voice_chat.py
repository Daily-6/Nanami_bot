import os
import re
import random
import requests
from pathlib import Path
from nonebot import on_message, get_driver, logger
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    PrivateMessageEvent,
    MessageEvent,
    MessageSegment,
)
from nonebot.plugin import PluginMetadata

# 导入 GPT-SoVITS 插件的工具函数和配置
from nonebot_plugin_gpt_sovits.utils import generate_v2, encode_to_silk
from nonebot_plugin_gpt_sovits import plugin_config as gs_config

# ===================== 配置区 =====================
API_KEY = get_driver().config.deepseek_api_key
BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-v4-flash"

# 人设文件
PLUGIN_DIR = Path(__file__).parent
CHARACTER_FILE = PLUGIN_DIR / "voice_version_character_prompt.txt"

DEFAULT_PROMPT = """（你的默认人设，可以从 chat.py 复制）"""

def load_system_prompt():
    if not CHARACTER_FILE.exists():
        CHARACTER_FILE.write_text(DEFAULT_PROMPT.strip(), encoding="utf-8")
        logger.info(f"已创建默认人设文件：{CHARACTER_FILE}")
    try:
        content = CHARACTER_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return DEFAULT_PROMPT.strip()
        return content
    except Exception as e:
        logger.error(f"读取人设文件失败：{e}，使用内置默认人设")
        return DEFAULT_PROMPT.strip()

SYSTEM_PROMPT = load_system_prompt()

# 对话历史管理
MAX_HISTORY = 30
chat_history = {}

# ===================== 触发规则 =====================
voice_chat = on_message(rule=to_me(), priority=9, block=True)

__plugin_meta__ = PluginMetadata(
    name="语音聊天",
    description="七海千秋用语音回复 @ 消息",
    usage="@机器人 发送消息，自动语音回复",
    type="application",
    supported_adapters={"~onebot.v11"},
)

def get_user_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group_{event.group_id}_user_{event.user_id}"
    return f"private_{event.user_id}"

# ===================== 核心处理 =====================
@voice_chat.handle()
async def handle_voice_chat(event: MessageEvent):
    user_msg = event.get_message().extract_plain_text().strip()
    if not user_msg:
        return

    # 忽略命令
    if user_msg.lower().startswith(("tts", "重置对话", "reset", "清空记忆")):
        return

    user_id = get_user_id(event)

    if user_id not in chat_history:
        chat_history[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    chat_history[user_id].append({"role": "user", "content": user_msg})

    # 截断历史
    if len(chat_history[user_id]) > MAX_HISTORY * 2 + 1:
        chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-(MAX_HISTORY * 2):]

    # ---------- 调用 DeepSeek 生成回复 ----------
    try:
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": MODEL_NAME,
            "messages": chat_history[user_id],
            "temperature": 0.85,
        }
        resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        reply_text = result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"AI 生成回复失败: {e}")
        # 不发送任何文字，直接结束
        return

    # 保存历史
    chat_history[user_id].append({"role": "assistant", "content": reply_text})

    # ---------- 清理文本 ----------
    clean_text = re.sub(r'\[meme:.*?\]', '', reply_text).strip()
    if not clean_text:
        # 如果清理后为空，也不回复
        return

    # 缩短文本
    max_len = 150
    if len(clean_text) > max_len:
        clean_text = clean_text[:max_len] + "…"


    # ---------- 语音合成 ----------
    try:
        emotion_map = gs_config.gpt_sovits_emotion_map
        if not emotion_map:
            logger.error("未配置 GPT_SOVITS_EMOTION_MAP")
            return

        first_emotion = emotion_map[0]
        sentence = random.choice(first_emotion.sentences)
        refer_path = sentence.path
        prompt_text = sentence.text
        prompt_lang = sentence.language

        wav_bytes = await generate_v2(
            base_url=gs_config.gpt_sovits_api_base_url,
            text=clean_text,
            text_lang="auto",
            ref_audio_path=refer_path,
            prompt_text=prompt_text,
            prompt_lang=prompt_lang,
            top_k=gs_config.gpt_sovits_args.get("top_k", 5),
            top_p=gs_config.gpt_sovits_args.get("top_p", 0.8),
            temperature=gs_config.gpt_sovits_args.get("temperature",1.1),
            text_split_method=gs_config.gpt_sovits_args.get("text_split_method", "cut3"),
            speed_factor=gs_config.gpt_sovits_args.get("speed_factor", 0.9),
            volume=gs_config.gpt_sovits_args.get("volume", 1.0),
        )

        if gs_config.gpt_sovits_convert_to_silk:
            silk_bytes = encode_to_silk(wav_bytes)
            await voice_chat.finish(MessageSegment.record(silk_bytes))
        else:
            await voice_chat.finish(MessageSegment.record(wav_bytes))

    except Exception as e:
        logger.error(f"语音合成失败: {e}")
        # 语音失败，不发送任何消息，静默结束
        return