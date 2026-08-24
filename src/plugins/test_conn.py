from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent

test_cmd = on_command("test", priority=1)

@test_cmd.handle()
async def test_reply(event: MessageEvent):
    await test_cmd.send("✅ 通道连通正常，机器人响应成功！")
