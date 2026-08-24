from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.plugin import PluginMetadata
import regex

__plugin_meta__ = PluginMetadata(
    name="emoji-reaction",
    description="适配 Napcat 的 QQ 群消息贴表情插件，支持单次贴多个表情",
    usage="""
使用方法：
1. 直接发送指令：`/emoji [表情1] [表情2] ...`，给当前这条指令消息贴表情
   - 指令与第一个表情之间需要空格分隔，表情之间可以不加空格
   - 支持 QQ 自带小黄脸表情和单码点 Unicode 表情
2. 引用/回复某条消息后发送 `/emoji [表情...]`，给被引用的目标消息贴表情

注意事项：
- 仅支持 OneBot V11 协议（Napcat / Lagrange 等兼容客户端）
- 多码点 Unicode 表情可能显示异常（仅提取首个码点，属于协议接口限制）
- 依赖 regex 库实现 Unicode 表情精准匹配
""",
    type="application",
    supported_adapters={"~onebot.v11"},
)

# 注册 emoji 指令
emoji_cmd = on_command("emoji", priority=5, block=True)


@emoji_cmd.handle()
async def handle_emoji_reaction(bot: Bot, event: MessageEvent):
    # 确定目标消息 ID：优先使用引用回复的消息，否则使用当前指令消息
    target_msg_id = event.reply.message_id if event.reply else event.message_id

    emoji_ids: list[str] = []

    # 遍历消息段，提取两类表情 ID
    for seg in event.message:
        if seg.type == "face":
            # 处理 QQ 系统自带表情
            face_id = seg.data.get("id")
            if face_id:
                emoji_ids.append(str(face_id))

        elif seg.type == "text":
            # 处理 Unicode 表情，与原插件正则逻辑完全对齐
            text_content = seg.data.get("text", "")
            if not text_content:
                continue

            emoji_pattern = regex.compile(r"[\p{Emoji_Presentation}\p{Extended_Pictographic}]")
            matched_chars = emoji_pattern.findall(text_content)

            for char in matched_chars:
                code_point = ord(char)
                emoji_ids.append(str(code_point))

    if not emoji_ids:
        await emoji_cmd.finish("未找到有效的表情")

    # 按顺序逐个调用接口贴表情（与原插件串行逻辑一致）
    for emoji_id in emoji_ids:
        await bot.call_api(
            "set_msg_emoji_like",
            message_id=target_msg_id,
            emoji_id=emoji_id,
        )
