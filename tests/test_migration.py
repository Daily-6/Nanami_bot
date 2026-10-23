import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from nanami_plugin.main import NanamiPlugin
from nanami_plugin.nanami_core import ArchiveStore, clean_speech, is_qq_image_url, mirror_image
from PIL import Image


class Event:
    unified_msg_origin = "nanami_qq:GroupMessage:100"
    role = "member"

    def __init__(self, text="", raw=None, admin=False, group="100"):
        self.message_str = text
        self.message_obj = SimpleNamespace(
            raw_message=raw or {"post_type": "message", "message": [], "message_id": 3},
            message_id=3,
        )
        self.admin = admin
        self.group = group
        self.stopped = False
        self.calls = []
        self.bot = SimpleNamespace(call_action=self.call_action)

    async def call_action(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return {
            "group_id": 100,
            "sender": {"user_id": 2, "nickname": "群友"},
            "time": 0,
            "message": [{"type": "text", "data": {"text": "hello"}}],
        }

    def get_platform_name(self):
        return "aiocqhttp"

    def get_sender_id(self):
        return "2"

    def get_group_id(self):
        return self.group

    def get_messages(self):
        return []

    def is_admin(self):
        return self.admin

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text


@pytest.fixture
def plugin(tmp_path):
    # Avoid opening a network client: commands exercised here only use the fake OneBot API.
    instance = object.__new__(NanamiPlugin)
    instance.config = {}
    instance.pending = {}
    instance.cooldowns = {}
    instance.store = ArchiveStore(tmp_path)
    return instance


@pytest.mark.asyncio
async def test_archive_concurrent_writes_and_stable_ids(tmp_path):
    store = ArchiveStore(tmp_path)
    ids = await asyncio.gather(*(store.add("100", {"content_text": str(i)}) for i in range(20)))
    assert sorted(ids) == list(range(1, 21))
    assert len(store.read("100")) == 20
    await store.delete("100", 20)
    assert await store.add("100", {"content_text": "new"}) == 21
    await store.clear("100")
    assert await store.add("100", {"content_text": "after clear"}) == 22


@pytest.mark.asyncio
async def test_corrupt_archive_is_not_overwritten(tmp_path):
    path = tmp_path / "100.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        await ArchiveStore(tmp_path).add("100", {})
    assert path.read_text() == "broken"


def test_archive_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError):
        ArchiveStore(tmp_path).read("../credentials")


@pytest.mark.parametrize("action", ["delchat", "tagchat", "clearchat"])
@pytest.mark.asyncio
async def test_archive_mutations_require_admin(plugin, action):
    await plugin.store.add("100", {"content_text": "keep"})
    response = await plugin.archive(Event(), action, "确认")
    assert "管理员" in response
    assert len(plugin.store.read("100")) == 1


@pytest.mark.asyncio
async def test_clear_requires_explicit_confirmation(plugin):
    await plugin.store.add("100", {})
    event = Event(admin=True)
    assert "确定" in await plugin.archive(event, "clearchat", "")
    assert len(plugin.store.read("100")) == 1
    await plugin.archive(event, "clearchat", "确认")
    assert plugin.store.read("100") == []


@pytest.mark.asyncio
async def test_page_one_includes_small_archive(plugin):
    for i in range(3):
        await plugin.store.add(
            "100", {"time": "today", "nickname": "n", "content_text": f"item{i}"}
        )
    response = await plugin.archive(Event(), "listchat", "1")
    assert all(f"item{i}" in response for i in range(3))


@pytest.mark.asyncio
async def test_reply_archive_and_tag_compatibility(plugin):
    event = Event(
        raw={"post_type": "message", "message": [{"type": "reply", "data": {"id": "123"}}]}
    )
    assert "#1" in await plugin.archive(event, "savechat", "名场面 搞笑")
    assert plugin.store.read("100")[0]["content_text"] == "hello"
    await plugin.archive(Event(admin=True), "tagchat", "1 搞笑 新标签")
    assert plugin.store.read("100")[0]["tags"] == ["名场面", "搞笑", "新标签"]


@pytest.mark.asyncio
async def test_cross_group_archive_rejected(plugin):
    event = Event(group="200", raw={"message": [{"type": "reply", "data": {"id": "123"}}]})
    assert "当前群" in await plugin.archive(event, "savechat", "")
    assert plugin.store.read("200") == []


@pytest.mark.asyncio
async def test_poke_targets_only_sender_and_has_cooldown(plugin):
    event = Event("chuowo")
    responses = [r async for r in plugin.commands(event)]
    assert event.stopped
    assert len(responses) == 1
    assert event.calls == [("send_poke", {"group_id": 100, "user_id": 2})]
    second = Event("chuowo")
    assert "稍等" in "".join([r async for r in plugin.commands(second)])
    assert not second.calls


@pytest.mark.asyncio
async def test_ordinary_message_does_not_trigger_actions_or_stop_ai(plugin):
    event = Event("你好呀")
    assert [r async for r in plugin.commands(event)] == []
    assert not event.stopped
    assert not event.calls


@pytest.mark.asyncio
async def test_notice_is_ignored(plugin):
    event = Event("chuowo", {"post_type": "notice"})
    assert [r async for r in plugin.commands(event)] == []
    assert not event.calls


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9880/",
        "file:///C:/Windows/win.ini",
        "https://qq.com.evil.example/",
        "https://evil.example/img",
        "https://user:pass@gchat.qpic.cn/img",
        "https://gchat.qpic.cn:9880/img",
    ],
)
def test_media_rejects_local_and_untrusted_urls(url):
    assert not is_qq_image_url(url)


def test_media_accepts_qq_public_hosts():
    assert is_qq_image_url("https://gchat.qpic.cn/image.png")
    assert is_qq_image_url("https://multimedia.nt.qq.com.cn/image.png") is False
    assert is_qq_image_url("https://multimedia.nt.qq.com/image.png")


@pytest.mark.parametrize("horizontal", [True, False])
def test_odd_sized_image_is_symmetric(horizontal):
    import io

    image = Image.new("RGB", (5, 3))
    for x in range(5):
        for y in range(3):
            image.putpixel((x, y), (x * 40, y * 80, 0))
    source = io.BytesIO()
    image.save(source, format="PNG")
    result = Image.open(io.BytesIO(mirror_image(source.getvalue(), horizontal)))
    assert result.size == image.size
    for x in range(5):
        for y in range(3):
            opposite = (4 - x, y) if horizontal else (x, 2 - y)
            assert result.getpixel((x, y)) == result.getpixel(opposite)


def test_speech_cleaning():
    assert clean_speech("七海千秋：（挥手）你好！*微笑*[meme:开心]") == "你好！"
    assert len(clean_speech("字" * 250, 100)) <= 101


@pytest.mark.asyncio
async def test_local_migration_separates_secrets_and_is_not_overwriting(tmp_path, capsys):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("migration", root / "scripts/migrate_local.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "source"
    source.mkdir()
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"test")
    env = "DEEPSEEK_API_KEY=test-model-credential\nQWEN_API_KEY=unrelated-credential\nSUPERUSERS='[\"123456\"]'\n"
    emotions = json.dumps(
        [
            {
                "name": "default",
                "sentences": [{"path": reference.as_posix(), "text": "测试", "language": "zh"}],
            }
        ]
    )
    (source / ".env").write_text(env + f"GPT_SOVITS_EMOTION_MAP='{emotions}'\n", encoding="utf-8")
    prompt = source / "src/plugins/voice_version_character_prompt.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("test persona", encoding="utf-8")
    for name in module.PLUGIN_FILES:
        (source / name).write_bytes((root / name).read_bytes())
    runtime = tmp_path / "runtime"
    await module.configure(source, runtime)
    output = capsys.readouterr().out
    assert "test-model-credential" not in output
    config = json.loads((runtime / "data/cmd_config.json").read_text(encoding="utf-8"))
    assert config["dashboard"]["host"] == "127.0.0.1"
    assert config["platform"][0]["ws_reverse_token"]
    assert config["provider_sources"][0]["key"] == ["$DEEPSEEK_API_KEY"]
    assert "test-model-credential" in (runtime / ".env").read_text()
    assert "unrelated-credential" not in (runtime / ".env").read_text()
    assert "test-model-credential" not in (runtime / "data/cmd_config.json").read_text()
    assert config["provider_settings"]["computer_use_runtime"] == "none"
    with pytest.raises(ValueError):
        await module.configure(source, runtime)
