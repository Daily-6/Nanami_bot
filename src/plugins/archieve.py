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


# ---------- 指令处理 ----------
@savechat.handle()
async def _(bot: Bot, event: MessageEvent):
    """存档消息：将回复的消息以合并转发格式保存"""
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

    new_id = len(archive_list) + 1
    archive_item = {
        "id": new_id,
        "time": msg_time,
        "user_id": sender.user_id,
        "nickname": sender.nickname,
        "content_text": content_text,
        "content_raw": content_raw
    }

    archive_list.append(archive_item)
    save_archive(group_id, archive_list)

    await savechat.finish(f"#{new_id} 消息已储存（可随机抽发合并转发）")


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
        reply += f"#{item['id']} [{item['time']}] {item['nickname']}: {preview}\n"
    reply += "------------------\n"
    reply += "使用 /listchat 页码 翻页，/findchat 关键词 搜索"
    await listchat.finish(reply)


@rollchat.handle()
async def _(bot: Bot, event: MessageEvent):
    """随机抽取一条存档，以合并转发形式发送"""
    if event.message_type != "group":
        await rollchat.finish("该功能仅在群聊中可用")

    group_id = event.group_id
    archive_list = load_archive(group_id)
    if not archive_list:
        await rollchat.finish("当前群暂无存档消息")

    item = random.choice(archive_list)

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


@clearchat.handle()
async def _(event: MessageEvent):
    """清除当前群的所有存档（仅 SUPERUSERS 可用）"""
    if event.message_type != "group":
        await clearchat.finish("该功能仅在群聊中可用")

    # 仅机器人配置文件中的超级用户可使用
    superusers = get_driver().config.superusers
    if event.get_user_id() not in superusers:
        await clearchat.finish("仅机器人管理员（超级用户）可以使用此命令")

    group_id = event.group_id
    save_archive(group_id, [])
    await clearchat.finish("已清除本群所有聊天存档")