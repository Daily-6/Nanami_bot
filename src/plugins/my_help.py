from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Message
from nonebot.plugin import get_loaded_plugins

help_cmd = on_command("help", aliases={"帮助", "功能"}, priority=5)

@help_cmd.handle()
async def help_reply(event: MessageEvent):
    plugin_list = [p.name for p in get_loaded_plugins()]
    reply_text = "🤖 Nanami Bot 功能列表\n"
    reply_text += "------------------\n"
    reply_text += "⚪help - 查看帮助\n"
    reply_text += "⚪test - 连通测试\n"
    reply_text += "⚪emoji ❤ - 直接发可以给自己贴表情 回复其他人的消息可以贴别人  \n"
    reply_text += "⚪如果想跟我聊天的话 直接@我就好 我会一直陪伴你喔\n"
    reply_text += "⚪支持点歌！发送“网易云/点歌 +歌名  会弹出搜索结果  再发送序号即可喔\n"
    reply_text += "⚪还可以处理图片！发送“上下对称/左右对称“ 即可触发 说不定会有奇妙的效果喔\n"
    reply_text += "------------------\n"
    reply_text += f"已加载插件数：{len(plugin_list)}"
    await help_cmd.send(Message(reply_text))
