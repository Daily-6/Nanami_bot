from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, Message
from nonebot.plugin import get_loaded_plugins

help_cmd = on_command("help", aliases={"帮助", "功能"}, priority=5)

@help_cmd.handle()
async def help_reply(event: MessageEvent):
    plugin_list = [p.name for p in get_loaded_plugins()]
    reply_text = "🤖 Nanami Bot 功能列表\n"
    reply_text += "------------------\n"
    reply_text += "⚪想找我聊天的话 直接@我就好啦 我会用声音陪着你喔🎮\n"
    reply_text += "⚪发 tts+文字 就能让我直接念出来那段话\n"
    reply_text += "------------------\n"
    reply_text += "⚪想点歌？发 网易云/点歌+歌名 我会弹出搜索结果 再回我序号就行啦\n"
    reply_text += "⚪图片也能玩！发 上下对称 或者 左右对称 说不定有奇妙的效果喔\n"
    reply_text += "------------------\n"
    reply_text += "⚪聊天存档：回复某条消息发 存档 就能存起来啦\n"
    reply_text += "⚪想随机抽一条回忆 发 /rollchat 带标签还能指定方向喔\n"
    reply_text += "⚪想知道存档的更多玩法 发 /archhelp 我慢慢讲给你听\n"
    reply_text += "------------------\n"
    reply_text += "⚪发 /emoji ❤ 可以给消息贴表情 回复别人的消息也能贴他喔\n"
    reply_text += "⚪发 zanwo 我给你点赞 发 chuowo 我就戳你一下(≧◡≦)\n"
    reply_text += "⚪发 /test 看看我是不是还醒着\n"
    reply_text += "------------------\n"
    reply_text += f"现在我带着 {len(plugin_list)} 个插件在运行哦"
    await help_cmd.send(Message(reply_text))
