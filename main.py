"""Nanami utilities for AstrBot. LLM, persona and TTS are managed by AstrBot."""

from __future__ import annotations

import asyncio
import base64
import random
import time
from datetime import datetime
from pathlib import Path

import httpx
import regex
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain, Record
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .nanami_core import ArchiveStore, clean_speech, download_qq_image, mirror_image

ARCHIVE_HELP = """📚 存档命令（支持加 /，群聊内使用）
回复消息后：存档 [标签...]
listchat [页码] / rollchat [标签] / findchat 关键词
管理员：tagchat 编号 标签... / delchat 编号
管理员清空：clearchat 确认
旧存档保留编号、标签和原始消息；过期的 QQ 图片可能无法恢复。"""
HELP = """🎮 Nanami · 七海千秋
@我聊天，模型、人格、语音在 AstrBot 面板管理。
tts 文本：直接朗读；/reset：重置当前对话。
存档 / listchat / rollchat / findchat / tagchat / delchat / archhelp
左右对称 / 上下对称：随后在 30 秒内上传图片。
点歌 歌名 / 网易云 歌名 / QQ点歌 歌名：随后回序号。
zanwo：点赞；chuowo：戳自己；emoji ❤：贴表情（可引用消息）。
/test：检查连接；nanamihelp：显示本帮助。
AstrBot 原生 /help 仍显示所有插件的指令。"""
ALIASES = {
    "存档": "savechat",
    "存档列表": "listchat",
    "随机存档": "rollchat",
    "搜索存档": "findchat",
    "删除存档": "delchat",
    "删除记录": "delchat",
    "打标签": "tagchat",
    "标记": "tagchat",
    "清除存档": "clearchat",
    "clear": "clearchat",
    "存档帮助": "archhelp",
    "存档说明": "archhelp",
    "帮助": "nanamihelp",
    "功能": "nanamihelp",
}


class NanamiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.store = ArchiveStore(
            Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_nanami" / "chat_archive"
        )
        self.client = httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False)
        self.pending: dict[tuple[str, str], tuple[float, str, object]] = {}
        self.cooldowns: dict[tuple[str, str, str], float] = {}

    async def terminate(self):
        await self.client.aclose()

    def enabled(self, feature: str) -> bool:
        return bool(self.config.get(f"enable_{feature}", True))

    @staticmethod
    def raw(event: AstrMessageEvent) -> dict:
        return event.message_obj.raw_message or {}

    async def api(self, event: AstrMessageEvent, action: str, **kwargs):
        if event.get_platform_name() != "aiocqhttp" or not hasattr(event, "bot"):
            raise ValueError("此功能需要 NapCat / OneBot v11")
        return await event.bot.call_action(action, **kwargs)

    def consume_cooldown(self, event: AstrMessageEvent, action: str) -> bool:
        now = time.monotonic()
        self.cooldowns = {k: expiry for k, expiry in self.cooldowns.items() if expiry > now}
        key = (event.unified_msg_origin, event.get_sender_id(), action)
        if self.cooldowns.get(key, 0) > now:
            return False
        self.cooldowns[key] = now + max(1, int(self.config.get("interaction_cooldown_seconds", 10)))
        return True

    @filter.command("nanamihelp")
    async def nanamihelp(self, event: AstrMessageEvent):
        """查看七海千秋自定义功能。"""
        event.stop_event()
        yield event.plain_result(HELP)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def commands(self, event: AstrMessageEvent):
        """Recognize legacy commands; leave unrelated messages to AstrBot's AI."""
        if event.get_platform_name() != "aiocqhttp":
            return
        raw = self.raw(event)
        if raw.get("post_type") not in (None, "message", "message_sent"):
            return
        text = event.message_str.strip().lstrip("/").strip()
        head, _, args = text.partition(" ")
        action = ALIASES.get(head, head)
        key = (event.unified_msg_origin, event.get_sender_id())
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
        pending = self.pending.get(key)
        if pending:
            _, kind, payload = pending
            if kind == "image" and any(isinstance(c, Image) for c in event.get_messages()):
                self.pending.pop(key, None)
                event.stop_event()
                try:
                    yield await self.process_image(event, payload == "左右对称")
                except Exception as exc:
                    logger.warning("Nanami image failed: %s", type(exc).__name__)
                    yield event.plain_result("图片处理失败，请确认图片有效且不超过 12 MB。")
                return
            if kind == "music" and text.isdigit():
                event.stop_event()
                songs = payload
                index = int(text) - 1
                if not 0 <= index < len(songs):
                    yield event.plain_result("序号超出范围，请重新选择。")
                    return
                self.pending.pop(key, None)
                song = songs[index]
                try:
                    await self.send_music(event, song)
                except Exception as exc:
                    logger.warning("Nanami music send failed: %s", type(exc).__name__)
                    yield event.plain_result(f"音乐卡片发送失败，可打开：{song['url']}")
                return

        known = {
            "nanamihelp",
            "test",
            "savechat",
            "listchat",
            "rollchat",
            "findchat",
            "delchat",
            "tagchat",
            "clearchat",
            "archhelp",
            "zanwo",
            "chuowo",
            "emoji",
            "tts",
            "左右对称",
            "上下对称",
            "点歌",
            "网易云",
            "QQ点歌",
            "qq点歌",
        }
        if action not in known:
            return
        event.stop_event()
        try:
            if action == "nanamihelp":
                yield event.plain_result(HELP)
            elif action == "test":
                yield event.plain_result("七海千秋在线，AstrBot 与 NapCat 连接正常。")
            elif action == "archhelp":
                yield event.plain_result(ARCHIVE_HELP)
            elif action in {
                "savechat",
                "listchat",
                "rollchat",
                "findchat",
                "delchat",
                "tagchat",
                "clearchat",
            }:
                if not self.enabled("archive"):
                    yield event.plain_result("存档功能已在面板关闭。")
                else:
                    result = await self.archive(event, action, args.strip())
                    if result:
                        yield event.plain_result(result)
            elif action in {"zanwo", "chuowo", "emoji"}:
                if not self.enabled("interactions"):
                    yield event.plain_result("互动功能已在面板关闭。")
                elif not self.consume_cooldown(event, action):
                    yield event.plain_result("稍等一下再试喔。")
                else:
                    yield event.plain_result(await self.interact(event, action))
            elif action == "tts":
                if not self.enabled("tts_command"):
                    yield event.plain_result("直接朗读已在面板关闭。")
                elif not args.strip():
                    yield event.plain_result("用法：tts 要朗读的文字")
                else:
                    provider = await self.context.get_using_tts_provider_async(
                        event.unified_msg_origin
                    )
                    if not provider:
                        yield event.plain_result("请先在 AstrBot 面板启用并选择语音合成模型。")
                    else:
                        audio = await provider.get_audio(
                            clean_speech(args, self.config.get("speech_max_chars", 200))
                        )
                        yield event.chain_result([Record.fromFileSystem(audio)])
            elif action in {"左右对称", "上下对称"}:
                if self.enabled("mirror"):
                    if any(isinstance(c, Image) for c in event.get_messages()):
                        yield await self.process_image(event, action == "左右对称")
                    else:
                        self.pending[key] = (now + self.wait_seconds(), "image", action)
                        yield event.plain_result(f"请在 {self.wait_seconds()} 秒内上传图片。")
            elif self.enabled("music"):
                if not args.strip():
                    yield event.plain_result("用法：点歌 歌名；QQ点歌 歌名")
                else:
                    songs = await self.search_music(args.strip(), action.lower() == "qq点歌")
                    if not songs:
                        yield event.plain_result("没有找到歌曲，请换个关键词。")
                    else:
                        self.pending[key] = (now + self.wait_seconds(), "music", songs)
                        lines = [
                            f"{i}. {s['name']} — {s['artist']}" for i, s in enumerate(songs, 1)
                        ]
                        yield event.plain_result(
                            "\n".join(lines) + f"\n请在 {self.wait_seconds()} 秒内回复序号。"
                        )
        except Exception as exc:
            # Never echo remote response bodies, signed media URLs, credentials or local paths.
            logger.warning("Nanami command %s failed: %s", action, type(exc).__name__)
            yield event.plain_result("这次操作没有完成，请稍后重试；管理员可查看本机日志。")

    def wait_seconds(self) -> int:
        return max(10, min(int(self.config.get("selection_timeout_seconds", 30)), 120))

    async def archive(self, event: AstrMessageEvent, action: str, args: str) -> str | None:
        group = event.get_group_id()
        if not group:
            return "该功能仅在群聊中可用。"
        if action in {"delchat", "tagchat", "clearchat"} and not event.is_admin():
            return "仅机器人管理员可以使用此命令。"
        if action == "savechat":
            segments = self.raw(event).get("message", [])
            reply = next(
                (s for s in segments if isinstance(s, dict) and s.get("type") == "reply"), None
            )
            if not reply:
                return "请回复目标消息后再发送存档指令。"
            message = await self.api(event, "get_msg", message_id=int(reply["data"]["id"]))
            if message.get("group_id") and str(message["group_id"]) != str(group):
                return "只能存档当前群内的消息。"
            sender = message.get("sender", {})
            content = message.get("message", [])
            content_text = (
                "".join(
                    s.get("data", {}).get("text", "")
                    for s in content
                    if isinstance(s, dict) and s.get("type") == "text"
                )
                if isinstance(content, list)
                else str(content)
            )
            item = {
                "time": datetime.fromtimestamp(int(message.get("time", time.time()))).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "user_id": sender.get("user_id", event.get_sender_id()),
                "nickname": sender.get("card") or sender.get("nickname") or "群友",
                "content_text": content_text.strip() or "[非文本消息]",
                "content_raw": message.get("raw_message") or content,
                "tags": list(dict.fromkeys(args.split())),
            }
            item_id = await self.store.add(group, item)
            return f"#{item_id} 消息已存档。"
        if action == "clearchat":
            if args != "确认":
                return "清空将删除本群所有存档；确定请发送 clearchat 确认。"
            await self.store.clear(group)
            return "已清空本群存档。"
        if action in {"delchat", "tagchat"}:
            parts = args.split()
            if not parts or not parts[0].lstrip("#").isdigit():
                return f"用法：{action} 编号" + (" 标签..." if action == "tagchat" else "")
            item_id = int(parts[0].lstrip("#"))
            if action == "delchat":
                return (
                    f"已删除 #{item_id}。"
                    if await self.store.delete(group, item_id)
                    else "未找到该存档。"
                )
            if len(parts) < 2:
                return "请提供至少一个标签。"
            tags = await self.store.tag(group, item_id, parts[1:])
            return f"#{item_id} 标签：{'、'.join(tags)}" if tags is not None else "未找到该存档。"
        items = self.store.read(group)
        if not items:
            return "当前群暂无存档消息。"
        if action == "rollchat":
            candidates = [i for i in items if not args or any(args in t for t in i.get("tags", []))]
            if not candidates:
                return "没有找到带该标签的存档。"
            item = random.choice(candidates)
            node = {
                "type": "node",
                "data": {
                    "user_id": str(item["user_id"]),
                    "nickname": item["nickname"],
                    "content": item["content_raw"],
                },
            }
            try:
                await self.api(
                    event, "send_group_forward_msg", group_id=int(group), messages=[node]
                )
            except Exception:
                return f"[原始图片或转发已失效] {item['nickname']}：{item['content_text']}"
            return None
        if action == "findchat":
            if not args:
                return "用法：findchat 关键词"
            found = [i for i in items if args in i["content_text"]]
            return f"找到 {len(found)} 条记录：\n" + "\n".join(self.preview(i) for i in found[:10])
        pages = (len(items) + 4) // 5
        page = max(1, min(int(args) if args.isdigit() else 1, pages))
        selected = list(reversed(items))[(page - 1) * 5 : page * 5]
        return f"第 {page}/{pages} 页，共 {len(items)} 条：\n" + "\n".join(
            self.preview(i) for i in selected
        )

    @staticmethod
    def preview(item: dict) -> str:
        tags = "、".join(item.get("tags") or [])
        return f"#{item['id']} [{item['time']}] {item['nickname']} [{tags}]：{item['content_text'][:60]}"

    async def interact(self, event: AstrMessageEvent, action: str) -> str:
        if not event.get_group_id():
            return "此互动命令请在群聊中使用。"
        if action == "zanwo":
            await self.api(event, "send_like", user_id=int(event.get_sender_id()), times=10)
            return "已为你点赞 10 次！"
        if action == "chuowo":
            params = {"group_id": int(event.get_group_id()), "user_id": int(event.get_sender_id())}
            try:
                await self.api(event, "send_poke", **params)
            except Exception:
                await self.api(event, "group_poke", **params)
            return "戳了你一下！(≧◡≦)"
        raw = self.raw(event)
        segments = raw.get("message", [])
        reply = next((s for s in segments if s.get("type") == "reply"), None)
        target = (
            reply["data"]["id"] if reply else raw.get("message_id", event.message_obj.message_id)
        )
        ids = []
        for seg in segments:
            data = seg.get("data", {})
            if seg.get("type") == "face" and data.get("id"):
                ids.append(str(data["id"]))
            elif seg.get("type") == "text":
                ids.extend(
                    str(ord(c))
                    for c in regex.findall(
                        r"[\p{Emoji_Presentation}\p{Extended_Pictographic}]", data.get("text", "")
                    )
                )
        if not ids:
            return "未找到有效表情，例如：emoji ❤"
        for emoji_id in list(dict.fromkeys(ids))[:10]:
            await self.api(event, "set_msg_emoji_like", message_id=int(target), emoji_id=emoji_id)
        return "已贴表情。"

    async def process_image(self, event: AstrMessageEvent, horizontal: bool):
        image = next(c for c in event.get_messages() if isinstance(c, Image))
        data = await download_qq_image(self.client, image.url or image.file or "")
        result = await asyncio.to_thread(mirror_image, data, horizontal)
        return event.chain_result([Image.fromBase64(base64.b64encode(result).decode("ascii"))])

    async def search_music(self, keyword: str, qq: bool) -> list[dict]:
        limit = max(1, min(int(self.config.get("music_result_count", 5)), 10))
        if qq:
            response = await self.client.get(
                "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                params={"w": keyword[:100], "format": "json", "n": limit, "p": 1},
            )
            response.raise_for_status()
            data = response.json().get("data", {}).get("song", {}).get("list", [])
            return [
                {
                    "type": "qq",
                    "id": s["songid"],
                    "name": s["songname"],
                    "artist": "/".join(a["name"] for a in s.get("singer", [])),
                    "url": f"https://y.qq.com/n/ryqq/songDetail/{s['songmid']}",
                }
                for s in data[:limit]
            ]
        response = await self.client.post(
            "https://music.163.com/api/search/get/web",
            data={"s": keyword[:100], "type": 1, "limit": limit, "offset": 0},
            headers={"Referer": "https://music.163.com/"},
        )
        response.raise_for_status()
        data = response.json().get("result", {}).get("songs", [])
        return [
            {
                "type": "163",
                "id": s["id"],
                "name": s["name"],
                "artist": "/".join(a["name"] for a in s.get("artists", [])),
                "url": f"https://music.163.com/#/song?id={s['id']}",
            }
            for s in data[:limit]
        ]

    async def send_music(self, event: AstrMessageEvent, song: dict):
        params = (
            {"group_id": int(event.get_group_id())}
            if event.get_group_id()
            else {"user_id": int(event.get_sender_id())}
        )
        await self.api(
            event,
            "send_msg",
            **params,
            message=[{"type": "music", "data": {"type": song["type"], "id": str(song["id"])}}],
        )

    @filter.on_decorating_result()
    async def spoken_reply(self, event: AstrMessageEvent):
        """Preserve the old voice style while using AstrBot's own model and TTS settings."""
        if event.get_platform_name() != "aiocqhttp" or not self.config.get(
            "clean_spoken_reply", True
        ):
            return
        if (
            not self.context.get_config(event.unified_msg_origin)
            .get("provider_tts_settings", {})
            .get("enable")
        ):
            return
        result = event.get_result()
        if result and result.is_llm_result():
            for segment in result.chain:
                if isinstance(segment, Plain):
                    segment.text = clean_speech(
                        segment.text, self.config.get("speech_max_chars", 200)
                    )
