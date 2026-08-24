import io
import httpx
from PIL import Image
from nonebot import on_regex
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.params import RegexGroup
from nonebot_plugin_waiter import prompt

mirror_matcher = on_regex(
    r"^\s*(左右对称|上下对称)\s*$",
    priority=10,
    block=True,
)


@mirror_matcher.handle()
async def handle_mirror(event: GroupMessageEvent, regex_group: tuple = RegexGroup()):
    if not regex_group:
        return

    direction = regex_group[0]  # "左右对称" 或 "上下对称"

    # 使用 prompt 等待用户图片，它会自动发送提示并等待回复
    resp = await prompt("请发送需要处理的图片(*´0`)", timeout=30)
    if resp is None:
        await mirror_matcher.finish("太慢啦，我要睡了(｡-ω-)zzz")
        return

    # resp 就是 Message 对象，直接迭代
    image_seg = None
    for seg in resp:
        if seg.type == "image":
            image_seg = seg
            break

    if not image_seg:
        await mirror_matcher.finish("未检测到图片，请重新发送指令。")
        return

    url = image_seg.data.get("url")
    if not url:
        await mirror_matcher.finish("无法获取图片 URL，请重试。")
        return

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url)
            response.raise_for_status()
            img_bytes = response.content
    except Exception:
        await mirror_matcher.finish("下载图片失败，请重试。")
        return

    try:
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode not in ('RGBA', 'RGB'):
            img = img.convert('RGB')
        width, height = img.size

        if direction == "左右对称":
            left_half = img.crop((0, 0, width // 2, height))
            flipped_left = left_half.transpose(Image.FLIP_LEFT_RIGHT)
            img.paste(flipped_left, (width // 2, 0))
        else:  # 上下对称
            top_half = img.crop((0, 0, width, height // 2))
            flipped_top = top_half.transpose(Image.FLIP_TOP_BOTTOM)
            img.paste(flipped_top, (0, height // 2))

        output = io.BytesIO()
        img.save(output, format='PNG')
        output.seek(0)
        img_data = output.getvalue()
    except Exception as e:
        await mirror_matcher.finish(f"处理图片失败: {e}")
        return

    await mirror_matcher.finish(MessageSegment.image(img_data))