"""
Generate wechat title page design variations
"""
from PIL import Image, ImageDraw, ImageFont
import os, textwrap

WIDTH, HEIGHT = 1230, 2048
ROOT = r"E:\AI_hot"

FONT_BOLD = None
FONT_MED = None
FONT_SM = None
for sz_b, sz_m, sz_s in [(120, 72, 48), (96, 56, 36), (80, 48, 30)]:
    try:
        FONT_BOLD = ImageFont.truetype("C:\\Windows\\Fonts\\msyhbd.ttc", sz_b)
        FONT_MED = ImageFont.truetype("C:\\Windows\\Fonts\\msyhbd.ttc", sz_m)
        FONT_SM = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", sz_s)
        break
    except:
        continue
FONT_BODY = FONT_SM
for s in [30]:
    try:
        FONT_BODY = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", s)
        break
    except:
        continue

TITLE = "AI看病比医生准？但别高兴太早"
BODY_PREVIEW = "今天刷到几条AI新闻，说实话给我看愣了。Kimi的性能已经追上GPT-4，但成本只有几分之一。苹果在秘密研发带AI的耳机。OpenAI又被告上法庭了。"
DATE_STR = "2026-05-08"


def make_variant(name, draw_fn):
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw_fn(draw)
    path = os.path.join(ROOT, f"design-{name}.png")
    img.save(path, "PNG")
    print(f"  OK {path}")
    return path


# ─── 版式 A：居中标题 + 底部正文 ───
def design_a(draw):
    c = {"accent": (64, 150, 255), "dark": (30, 35, 45), "gray": (140, 160, 180), "text": (50, 50, 50)}
    # 上半深色背景
    draw.rectangle([(0, 0), (WIDTH, 900)], fill=c["dark"])
    # 底部白色
    draw.rectangle([(0, 900), (WIDTH, HEIGHT)], fill=(255, 255, 255))
    # 分割线
    draw.rectangle([(0, 900), (WIDTH, 906)], fill=c["accent"])
    # 标题
    lines = textwrap.wrap(TITLE, width=9)
    y = 180
    for line in lines:
        tw = FONT_BOLD.getlength(line) if FONT_BOLD else len(line) * 60
        draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_BOLD)
        y += 130
    # 装饰线
    if FONT_BOLD:
        tw = FONT_BOLD.getlength(lines[0]) if FONT_BOLD else 200
        draw.rectangle([((WIDTH - tw) / 2, y), ((WIDTH + tw) / 2, y + 4)], fill=c["accent"])
    # 日期
    if FONT_SM:
        draw.text((60, 780), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    # 正文预览
    paras = textwrap.wrap(BODY_PREVIEW, width=30)
    y = 1000
    for line in paras[:6]:
        if FONT_BODY:
            draw.text((80, y), line, fill=c["text"], font=FONT_BODY)
        y += 50
    # 页脚
    if FONT_SM:
        draw.text((80, 1850), "文章来自：70后教你做自媒体", fill=c["gray"], font=FONT_SM)
        draw.text((80, 1900), "扫码关注老成，日进一卒不焦虑", fill=c["accent"], font=FONT_SM)


# ─── 版式 B：全屏深色，标题左上，正文左下 ───
def design_b(draw):
    c = {"accent": (255, 180, 50), "dark": (25, 28, 38), "gray": (160, 170, 185), "text": (235, 240, 245)}
    draw.rectangle([(0, 0), (WIDTH, HEIGHT)], fill=c["dark"])
    # 装饰条
    draw.rectangle([(0, 0), (10, HEIGHT)], fill=c["accent"])
    # 标题
    lines = textwrap.wrap(TITLE, width=8)
    y = 200
    for line in lines:
        draw.text((80, y), line, fill=(255, 255, 255), font=FONT_BOLD)
        y += 140
    # 下划线
    draw.rectangle([(80, y), (600, y + 3)], fill=c["accent"])
    # 正文
    paras = textwrap.wrap(BODY_PREVIEW, width=32)
    y = 750
    for line in paras[:6]:
        if FONT_BODY:
            draw.text((80, y), line, fill=c["text"], font=FONT_BODY)
        y += 50
    # 页脚
    if FONT_SM:
        draw.text((80, 1850), "文章来自：70后教你做自媒体", fill=c["gray"], font=FONT_SM)
        draw.text((80, 1900), "扫码关注老成，日进一卒不焦虑", fill=c["accent"], font=FONT_SM)


# ─── 版式 C：红色系，标题居中大号，正文在暖色卡片上 ───
def design_c(draw):
    c = {"accent": (220, 60, 60), "dark": (38, 20, 22), "gray": (200, 165, 165), "card": (248, 242, 240), "text": (55, 40, 40)}
    # 背景渐变感
    draw.rectangle([(0, 0), (WIDTH, 750)], fill=c["dark"])
    draw.rectangle([(0, 750), (WIDTH, HEIGHT)], fill=(245, 240, 238))
    # 标题
    lines = textwrap.wrap(TITLE, width=8)
    y = 160
    for line in lines:
        tw = FONT_BOLD.getlength(line) if FONT_BOLD else len(line) * 60
        draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_BOLD)
        y += 140
    # 装饰圆点
    for i, x in enumerate([(WIDTH / 2 - 40 + i * 40) for i in range(3)]):
        draw.ellipse([(x, y + 10), (x + 16, y + 26)], fill=c["accent"])
    # 正文卡片
    card_margin = 50
    draw.rectangle([(card_margin, 850), (WIDTH - card_margin, 1400)], fill=c["card"])
    draw.rectangle([(card_margin, 850), (WIDTH - card_margin, 855)], fill=c["accent"])
    paras = textwrap.wrap(BODY_PREVIEW, width=28)
    y = 920
    for line in paras[:6]:
        if FONT_BODY:
            draw.text((100, y), line, fill=c["text"], font=FONT_BODY)
        y += 50
    # 页脚
    if FONT_SM:
        draw.text((80, 1850), "文章来自：70后教你做自媒体", fill=c["gray"], font=FONT_SM)
        draw.text((80, 1900), "扫码关注老成，日进一卒不焦虑", fill=c["accent"], font=FONT_SM)


# ─── 版式 D：绿白分屏，标题大字在绿色块 ───
def design_d(draw):
    c = {"accent": (0, 150, 136), "dark": (20, 42, 38), "gray": (150, 180, 175), "text": (50, 50, 50)}
    draw.rectangle([(0, 0), (WIDTH, 620)], fill=c["dark"])
    draw.rectangle([(0, 620), (WIDTH, 626)], fill=c["accent"])
    draw.rectangle([(0, 626), (WIDTH, HEIGHT)], fill=(248, 250, 249))
    # 标题
    lines = textwrap.wrap(TITLE, width=10)
    y = 100
    for line in lines:
        tw = FONT_BOLD.getlength(line) if FONT_BOLD else len(line) * 60
        draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_BOLD)
        y += 140
    # 标签
    if FONT_SM:
        draw.text((60, 470), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    # 正文
    paras = textwrap.wrap(BODY_PREVIEW, width=30)
    y = 740
    for line in paras[:7]:
        if FONT_BODY:
            draw.text((80, y), line, fill=c["text"], font=FONT_BODY)
        y += 50
    # 页脚
    if FONT_SM:
        draw.text((80, 1850), "文章来自：70后教你做自媒体", fill=c["gray"], font=FONT_SM)
        draw.text((80, 1900), "扫码关注老成，日进一卒不焦虑", fill=c["accent"], font=FONT_SM)


# ─── 版式 E：极简风，纯白背景，标题左对齐 ───
def design_e(draw):
    c = {"accent": (50, 50, 50), "dark": (30, 30, 30), "gray": (160, 160, 160), "text": (50, 50, 50)}
    draw.rectangle([(0, 0), (WIDTH, HEIGHT)], fill=(252, 252, 252))
    # 左边竖线
    draw.rectangle([(40, 0), (48, HEIGHT)], fill=c["dark"])
    # 标题
    lines = textwrap.wrap(TITLE, width=10)
    y = 160
    for line in lines:
        draw.text((100, y), line, fill=c["dark"], font=FONT_BOLD)
        y += 130
    # 分隔线
    draw.rectangle([(100, y + 10), (700, y + 14)], fill=c["accent"])
    # 正文
    paras = textwrap.wrap(BODY_PREVIEW, width=30)
    y = 750
    for line in paras[:7]:
        if FONT_BODY:
            draw.text((100, y), line, fill=c["text"], font=FONT_BODY)
        y += 50
    # 日期
    if FONT_SM:
        draw.text((100, 600), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    # 页脚
    if FONT_SM:
        draw.text((100, 1850), "文章来自：70后教你做自媒体", fill=c["gray"], font=FONT_SM)
        draw.text((100, 1900), "扫码关注老成，日进一卒不焦虑", fill=c["accent"], font=FONT_SM)


if __name__ == "__main__":
    print("生成 5 版标题页设计...")
    make_variant("A-居中标题+底部正文", design_a)
    make_variant("B-深色标题左上", design_b)
    make_variant("C-红色系暖卡", design_c)
    make_variant("D-绿白分屏", design_d)
    make_variant("E-极简左对齐", design_e)
    print("\n已保存到 E:\\AI_hot\\ 下，文件名 design-*.png")
