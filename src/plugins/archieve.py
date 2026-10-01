import json
import os
import random
from datetime import datetime

from nonebot import on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot.log import logger

# ---------- 配置 ----------
DATA_DIR = "data/chat_archive"
os.makedirs(DATA_DIR, exist_ok=True)

PAGE_SIZE = 5

# ---------- 指令注册 ----------
savechat = on_command("savechat", aliases={"存档"}, priority=5)
listchat = on_command("listchat", aliases={"存档列表"}, priority=5)
rollchat = on_command("rollchat", aliases={"随机存档"}, priority=5)
findchat = on_command("findchat", aliases={"搜索存档"}, priority=5)
clearchat = on_command("clearchat", aliases={"清除存档", "clear"}, priority=5)
delchat = on_command("delchat", aliases={"删除存档", "删除记录"}, priority=5)
tagchat = on_command("tagchat", aliases={"打标签", "标记"}, priority=5)
archhelp = on_command("archhelp", aliases={"存档帮助", "存档说明"}, priority=5)


# ---------- 工具函数 ----------
def get_group_data_path(group_id: int) -> str:
    return os.path.join(DATA_DIR, f"{group_id}.json")


def load_archive(group_id: int) -> list:
    path = get_group_data_path(group_id)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_archive(group_id: int, data: list):
    path = get_group_data_path(group_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_id(archive_list: list) -> int:
    """生成不重复的新 id（最大 id + 1），删除单条后其它条目 id 不变"""
    if not archive_list:
        return 1
    return max(item.get("id", 0) for item in archive_list) + 1


def is_superuser(event: MessageEvent) -> bool:
    superusers = get_driver().config.superusers
    return event.get_user_id() in superusers


def find_by_id(archive_list: list, target_id: int):
    for item in archive_list:
        if item.get("id") == target_id:
            return item
    return None


# ---------- 指令处理 ----------
@savechat.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """存档消息：将回复的消息以合并转发格式保存，可附带标签"""
    if event.message_type != "group":
        await savechat.finish("该功能仅在群聊中可用")

    if not event.reply:
        await savechat.finish("请先回复目标消息，再发送指令进行存档")

    group_id = event.group_id
    archive_list = load_archive(group_id)

    sender = event.reply.sender
    msg_time = datetime.fromtimestamp(event.reply.time).strftime("%Y-%m-%d %H:%M:%S")

    raw_msg = event.reply.message
    content_raw = str(raw_msg)
    content_text = raw_msg.extract_plain_text().strip() or "[非文本消息]"

    tags = [t for t in args.extract_plain_text().split() if t]

    new_id = next_id(archive_list)
    archive_item = {
        "id": new_id,
        "time": msg_time,
        "user_id": sender.user_id,
        "nickname": sender.nickname,
        "content_text": content_text,
        "content_raw": content_raw,
        "tags": tags
    }

    archive_list.append(archive_item)
    save_archive(group_id, archive_list)

    tag_str = f"（标签：{', '.join(tags)}）" if tags else ""
    await savechat.finish(f"#{new_id} 消息已储存{tag_str}，可随机抽发合并转发")


@listchat.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    """分页查看存档列表"""
    if event.message_type != "group":
        await listchat.finish("该功能仅在群聊中可用")

    group_id = event.group_id
    archive_list = load_archive(group_id)
    if not archive_list:
        await listchat.finish("当前群暂无存档消息")

    page_text = args.extract_plain_text().strip()
    page = int(page_text) if page_text.isdigit() else 1
    total = len(archive_list)
    total_page = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(1, min(page, total_page))

    start = total - page * PAGE_SIZE
    end = total - (page - 1) * PAGE_SIZE
    current_items = list(reversed(archive_list[start:end]))

    reply = f"第 {page}/{total_page} 页，总计 {total} 条记录：\n"
    reply += "------------------\n"
    for item in current_items:
        preview = item["content_text"][:30] + ("..." if len(item["content_text"]) > 30 else "")
        tags = item.get("tags") or []
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        reply += f"#{item['id']} [{item['time']}] {item['nickname']}{tag_str}: {preview}\n"
    reply += "------------------\n"
    reply += "使用 /listchat 页码 翻页，/findchat 关键词 搜索"
    await listchat.finish(reply)


@rollchat.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    """随机抽取一条存档，以合并转发形式发送。

    无参数：从所有存档中随机选一条。
    带关键词：从带该标签的存档中随机选一条。
    """
    if event.message_type != "group":
        await rollchat.finish("该功能仅在群聊中可用")

    group_id = event.group_id
    archive_list = load_archive(group_id)
    if not archive_list:
        await rollchat.finish("当前群暂无存档消息")

    tag = args.extract_plain_text().strip()

    if tag:
        candidates = [
            item for item in archive_list
            if any(tag in t for t in (item.get("tags") or []))
        ]
        if not candidates:
            await rollchat.finish(f"没有找到带标签「{tag}」的存档")
    else:
        candidates = archive_list

    item = random.choice(candidates)

    try:
        node = MessageSegment.node_custom(
            user_id=int(item["user_id"]),
            nickname=item["nickname"],
            content=item["content_raw"]
        )
        await bot.send_group_forward_msg(group_id=group_id, messages=[node])
    except Exception as e:
        logger.error(f"合并转发发送失败: {e}")
        await rollchat.finish(
            f"[合并转发失败，原始内容] [{item['time']}] {item['nickname']}:\n{item['content_text']}"
        )


@findchat.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    """关键词搜索存档"""
    if event.message_type != "group":
        await findchat.finish("该功能仅在群聊中可用")

    keyword = args.extract_plain_text().strip()
    if not keyword:
        await findchat.finish("请输入要搜索的关键词，例如：/findchat 大家好")

    group_id = event.group_id
    archive_list = load_archive(group_id)
    result = [item for item in archive_list if keyword in item["content_text"]]

    if not result:
        await findchat.finish("未找到包含该关键词的存档")

    show_num = min(len(result), 10)
    reply = f"找到 {len(result)} 条匹配记录，显示前 {show_num} 条：\n"
    reply += "------------------\n"
    for item in result[:show_num]:
        preview = item["content_text"][:30] + ("..." if len(item["content_text"]) > 30 else "")
        reply += f"#{item['id']} [{item['time']}] {item['nickname']}: {preview}\n"
    await findchat.finish(reply)


@delchat.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    """删除单条存档（仅超级用户可用）"""
    if event.message_type != "group":
        await delchat.finish("该功能仅在群聊中可用")

    if not is_superuser(event):
        await delchat.finish("仅机器人管理员（超级用户）可以使用此命令")

    text = args.extract_plain_text().strip().lstrip("#")
    if not text.isdigit():
        await delchat.finish("请指定要删除的存档编号，例如：/delchat 3 或 /delchat #3")

    target_id = int(text)
    group_id = event.group_id
    archive_list = load_archive(group_id)

    if find_by_id(archive_list, target_id) is None:
        await delchat.finish(f"未找到编号 #{target_id} 的存档")

    archive_list = [item for item in archive_list if item.get("id") != target_id]
    save_archive(group_id, archive_list)
    await delchat.finish(f"已删除存档 #{target_id}")


@tagchat.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    """给单条存档打标签，可追加多个标签"""
    if event.message_type != "group":
        await tagchat.finish("该功能仅在群聊中可用")

    if not is_superuser(event):
        await tagchat.finish("仅机器人管理员（超级用户）可以使用此命令")

    text = args.extract_plain_text().strip()
    if not text:
        await tagchat.finish("用法：/tagchat 编号 标签，例如：/tagchat 3 名场面")

    parts = text.split(maxsplit=1)
    id_part = parts[0].lstrip("#")
    if not id_part.isdigit():
        await tagchat.finish("第一个参数应为存档编号，例如：/tagchat 3 名场面")

    target_id = int(id_part)
    new_tags = [t for t in parts[1].split() if t] if len(parts) > 1 else []
    if not new_tags:
        await tagchat.finish("请提供至少一个标签，例如：/tagchat 3 名场面")

    group_id = event.group_id
    archive_list = load_archive(group_id)
    item = find_by_id(archive_list, target_id)
    if item is None:
        await tagchat.finish(f"未找到编号 #{target_id} 的存档")

    existing = item.setdefault("tags", [])
    for t in new_tags:
        if t not in existing:
            existing.append(t)

    save_archive(group_id, archive_list)
    await tagchat.finish(f"已给存档 #{target_id} 打上标签：{', '.join(new_tags)}")


@clearchat.handle()
async def _(event: MessageEvent):
    """清除当前群的所有存档（仅 SUPERUSERS 可用）"""
    if event.message_type != "group":
        await clearchat.finish("该功能仅在群聊中可用")

    if not is_superuser(event):
        await clearchat.finish("仅机器人管理员（超级用户）可以使用此命令")

    group_id = event.group_id
    save_archive(group_id, [])
    await clearchat.finish("已清除本群所有聊天存档")


@archhelp.handle()
async def _(event: MessageEvent):
    """存档插件使用说明"""
    if event.message_type != "group":
        await archhelp.finish("该功能仅在群聊中可用")

    reply = "📚 聊天存档功能说明\n"
    reply += "------------------\n"
    reply += "⚪ 存档：回复某条消息后发送 savechat（或 存档）\n"
    reply += "     · savechat 标签 —— 存档时直接打标签\n"
    reply += "     · 例：savechat 名场面 搞笑\n"
    reply += "⚪ 列表：listchat [页码]（或 存档列表）\n"
    reply += "⚪ 随机抽：rollchat（或 随机存档）\n"
    reply += "     · rollchat 标签 —— 只从带该标签的记录里随机\n"
    reply += "⚪ 搜索：findchat 关键词（或 搜索存档）\n"
    reply += "⚪ 打标签：tagchat 编号 标签（或 打标签，仅管理员）\n"
    reply += "     · 例：tagchat 3 名场面 搞笑\n"
    reply += "⚪ 删除单条：delchat 编号（或 删除存档，仅管理员）\n"
    reply += "     · 例：delchat 3\n"
    reply += "⚪ 清空全部：clearchat（或 清除存档，仅管理员）\n"
    await archhelp.finish(reply)
