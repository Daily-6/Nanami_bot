"""Framework-independent storage and media utilities. Never load API keys here."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import uuid
import warnings
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000


def clean_speech(text: str, limit: int = 200) -> str:
    text = re.sub(r"[（(][^）)]*[）)]|\*[^*]*\*|\[meme:.*?\]", "", text)
    text = re.sub(r"^七海千秋[：:]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    limit = max(20, min(int(limit), 1000))
    if len(text) > limit:
        cut = text[:limit]
        boundary = max(cut.rfind(c) for c in "。！？!?…")
        text = cut[: boundary + 1] if boundary > limit * 0.6 else cut + "…"
    return text


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ArchiveStore:
    """Preserve legacy per-group JSON data and serialize read/modify/write operations."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = asyncio.Lock()

    def path(self, group: str) -> Path:
        if not re.fullmatch(r"[0-9]{1,20}", str(group)):
            raise ValueError("无效的群号")
        return self.directory / f"{group}.json"

    def read(self, group: str) -> list[dict]:
        path = self.path(group)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list) or any(not isinstance(i, dict) for i in data):
            raise ValueError("存档格式不正确，已保留原文件")
        return data

    async def add(self, group: str, item: dict) -> int:
        async with self.lock:
            items = self.read(group)
            counter_path = self.directory / "_next_ids.json"
            counters = (
                json.loads(counter_path.read_text(encoding="utf-8"))
                if counter_path.exists()
                else {}
            )
            next_id = max(
                int(counters.get(group, 1)), max((int(i["id"]) for i in items), default=0) + 1
            )
            # Reserve the id first. A failed item write may leave a gap, never reuse an id.
            counters[group] = next_id + 1
            atomic_json(counter_path, counters)
            atomic_json(self.path(group), [*items, {**item, "id": next_id}])
            return next_id

    async def delete(self, group: str, item_id: int) -> bool:
        async with self.lock:
            items = self.read(group)
            remaining = [i for i in items if i["id"] != item_id]
            if len(items) == len(remaining):
                return False
            atomic_json(self.path(group), remaining)
            return True

    async def tag(self, group: str, item_id: int, tags: list[str]) -> list[str] | None:
        async with self.lock:
            items = self.read(group)
            for item in items:
                if item["id"] == item_id:
                    item["tags"] = list(dict.fromkeys([*(item.get("tags") or []), *tags]))
                    atomic_json(self.path(group), items)
                    return item["tags"]
            return None

    async def clear(self, group: str) -> None:
        async with self.lock:
            atomic_json(self.path(group), [])


def mirror_image(data: bytes, horizontal: bool) -> bytes:
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能超过 12 MB")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("图片像素过大，请缩小后重试")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            width, height = image.size
            if min(width, height) < 2:
                raise ValueError("图片尺寸过小")
            if horizontal:
                half = image.crop((0, 0, (width + 1) // 2, height))
                image.paste(ImageOps.mirror(half), (width // 2, 0))
            else:
                half = image.crop((0, 0, width, (height + 1) // 2))
                image.paste(ImageOps.flip(half), (0, height // 2))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()


def is_qq_image_url(url: str) -> bool:
    """Only fetch QQ's public media hosts, never arbitrary URLs or local files."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme in ("http", "https")
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 80, 443)
        and any(
            host == domain or host.endswith("." + domain)
            for domain in ("qpic.cn", "qlogo.cn", "gtimg.cn", "qq.com")
        )
    )


async def download_qq_image(client: httpx.AsyncClient, url: str) -> bytes:
    if not is_qq_image_url(url):
        raise ValueError("仅支持 QQ 图片链接，请直接上传图片")
    async with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("图片不能超过 12 MB")
        return bytes(data)
