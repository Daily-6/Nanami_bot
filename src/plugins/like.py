from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="点赞戳一戳",
    description="群聊中发送 zanwo 点赞10次，发送 chuowo 戳一戳（系统动作）",
    usage="群聊中发送 zanwo 或 chuowo",
    type="application",
    supported_adapters={"~onebot.v11"},
)

zanwo = on_command("zanwo", priority=5, block=True)
chuowo = on_command("chuowo", priority=5, block=True)


@zanwo.handle()
async def handle_zanwo(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await zanwo.send("请在群聊中使用此命令")
        return

    try:
        # 为发送者主页点赞 10 次（OneBot 标准接口）
        await bot.call_api("send_like", user_id=event.user_id, times=10)
        await zanwo.send("已为你点赞 10 次！")  # 回复提示，不会抛异常
    except Exception as e:
        await zanwo.send(f"点赞失败：{e}")
    return


@chuowo.handle()
async def handle_chuowo(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await chuowo.send("请在群聊中使用此命令")
        return

    user_id = event.user_id
    group_id = event.group_id

    # 尝试调用标准 send_poke（Napcat 支持）
    try:
        await bot.call_api("send_poke", user_id=user_id, group_id=group_id)
        await chuowo.send("戳了你一下！(≧◡≦) ♡")  # 成功回复，同时系统会显示戳一戳消息
        return
    except Exception:
        # 若失败，尝试备用 group_poke
        try:
            await bot.call_api("group_poke", group_id=group_id, user_id=user_id)
            await chuowo.send("戳了你一下！(≧◡≦) ♡")
        except Exception as e:
            await chuowo.send(f"没戳成呢(╥﹏╥)：{e}")
    return