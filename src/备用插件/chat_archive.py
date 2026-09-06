import json
import os
import random
from datetime import datetime
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.params import CommandArg

# 数据存储目录
DATA_DIR = "data/chat_archive"
os.makedirs(DATA_DIR, exist_ok=True)

# 每页显示条数
PAGE_SIZE = 5

# 指令注册
savechat = on_command("savechat", aliases={"存档"}, priority=5)
listchat = on_command("listchat", aliases={"存档列表"}, priority=5)
rollchat = on_command("rollchat", aliases={"随机存档"}, priority=5)
findchat = on_command("findchat", aliases={"搜索存档"}, priority=5)


def get_group_data_path(group_id: int) -> str:
    """获取对应群的存档文件路径"""
    return os.path.join(DATA_DIR, f"{group_id}.json")


def load_archive(group_id: int) -> list:
    """加载群存档数据"""
    path = get_group_data_path(group_id)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_archive(group_id: int, data: list):
    """保存群存档数据"""
    path = get_group_data_path(group_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@savechat.handle()
async def _(bot: Bot, event: MessageEvent):
    """存档消息：必须回复目标消息触发"""
    # 仅群聊可用
    if event.message_type != "group":
        await savechat.finish("该功能仅在群聊中可用")
    
    # 检查是否回复了消息
    if not event.reply:
        await savechat.finish("请先回复目标消息，再发送指令进行存档")
    
    group_id = event.group_id
    archive_list = load_archive(group_id)
    
    # 生成新存档条目
    new_id = len(archive_list) + 1
    reply_msg = event.reply.message
    sender = event.reply.sender
    msg_time = datetime.fromtimestamp(event.reply.time).strftime("%Y-%m-%d %H:%M:%S")
    
    # 提取纯文本内容（非文本消息保留占位提示）
    msg_content = reply_msg.extract_plain_text()
    if not msg_content:
        msg_content = "[非文本消息]"
    
    archive_item = {
        "id": new_id,
        "time": msg_time,
        "user_id": sender.user_id,
        "nickname": sender.nickname,
        "content": msg_content
    }
    
    archive_list.append(archive_item)
    save_archive(group_id, archive_list)
    
    await savechat.finish(f"#{new_id} 消息已储存")


@listchat.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    """分页查看存档列表"""
    if event.message_type != "group":
        await listchat.finish("该功能仅在群聊中可用")
    
    group_id = event.group_id
    archive_list = load_archive(group_id)
    
    if not archive_list:
        await listchat.finish("当前群暂无存档消息")
    
    # 解析页码
    page_text = args.extract_plain_text().strip()
    page = int(page_text) if page_text.isdigit() else 1
    total = len(archive_list)
    total_page = (total + PAGE_SIZE - 1) // PAGE_SIZE
    
    if page < 1:
        page = 1
    if page > total_page:
        page = total_page
    
    # 切片取当前页数据，倒序展示（最新的在前）
    start = total - page * PAGE_SIZE
    end = total - (page - 1) * PAGE_SIZE
    current_items = list(reversed(archive_list[start:end]))
    
    # 组装回复
    reply = f"第 {page}/{total_page} 页，总计 {total} 条记录：\n"
    reply += "------------------\n"
    for item in current_items:
        reply += f"#{item['id']} [{item['time']}] {item['nickname']}:\n"
        reply += f"  {item['content']}\n"
    reply += "------------------\n"
    reply += "使用 /listchat 页码 查看其他页\n"
    reply += "使用 /findchat 关键词 搜索存档"
    
    await listchat.finish(reply)


@rollchat.handle()
async def _(event: MessageEvent):
    """随机抽取一条存档"""
    if event.message_type != "group":
        await rollchat.finish("该功能仅在群聊中可用")
    
    group_id = event.group_id
    archive_list = load_archive(group_id)
    
    if not archive_list:
        await rollchat.finish("当前群暂无存档消息")
    
    item = random.choice(archive_list)
    reply = f"[{item['time']}] {item['nickname']}:\n"
    reply += f"{item['content']}"
    
    await rollchat.finish(reply)


@findchat.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    """关键词搜索存档"""
    if event.message_type != "group":
        await findchat.finish("该功能仅在群聊中可用")
    
    keyword = args.extract_plain_text().strip()
    if not keyword:
        await findchat.finish("请输入要搜索的关键词，例如：/findchat 便士")
    
    group_id = event.group_id
    archive_list = load_archive(group_id)
    
    # 匹配关键词
    result = [item for item in archive_list if keyword in item["content"]]
    
    if not result:
        await findchat.finish("未找到包含该关键词的存档")
    
    # 最多显示10条结果
    show_num = min(len(result), 10)
    reply = f"找到 {len(result)} 条匹配记录，显示前 {show_num} 条：\n"
    reply += "------------------\n"
    for item in result[:show_num]:
        reply += f"#{item['id']} [{item['time']}] {item['nickname']}:\n"
        reply += f"  {item['content']}\n"
    
    await findchat.finish(reply)
