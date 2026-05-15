"""
Single optimized design based on design-v2-A
"""
from PIL import Image, ImageDraw, ImageFont
import os, textwrap, re

WIDTH, HEIGHT = 1230, 2048
ROOT = r"E:\AI_hot"
QR_PATH = r"E:\AI_hot\aihot-wechat\qrcode.jpg"

FONT_TITLE = None
FONT_BODY = None
FONT_SM = None
for sz_t, sz_b, sz_s in [(160, 48, 28), (128, 42, 24), (100, 36, 20)]:
    try:
        FONT_TITLE = ImageFont.truetype("C:\\Windows\\Fonts\\msyhbd.ttc", sz_t)
        FONT_BODY = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", sz_b)
        FONT_SM = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", sz_s)
        break
    except:
        continue

TITLE = "AI看病比医生准？但别高兴太早"
BODY = ("今天刷到几条AI新闻，说实话给我看愣了。Kimi的性能已经追上GPT-4，"
        "但成本只有几分之一。苹果在秘密研发带AI的耳机。OpenAI又被告上法庭了。"
        "欧盟推迟了AI监管，美国也在建立审查体系。"
        "Moonshot的API使用量暴增，越来越多企业开始用AI处理日常事务。")
DATE_STR = "2026-05-08"
MARGIN = 80
TEXT_W = WIDTH - MARGIN * 2

LEADING_PUNCT = set("，。、；：？！）】》」』】〙〗〃’\"》）.!?)]},;:")
NON_LEADING = set("，。、；：？！）】》」』】〙〗〃’\"》）.!?)]},;:%—…")


def split_line_no_orphan_punct(text, max_width, font, draw):
    """Split text into lines that don't exceed max_width, avoiding leading punctuation."""
    result = []
    while text:
        if not text:
            break
        # Find max chars that fit
        for end in range(len(text), 0, -1):
            line = text[:end]
            w = draw.textlength(line, font=font)
            if w <= max_width:
                # Check next line doesn't start with bad punctuation
                next_start = text[end:]
                if next_start and next_start[0] in LEADING_PUNCT and next_start[0] not in ('"', '"', "'", '「', '『', '（', '【'):
                    continue
                result.append(line)
                text = text[end:]
                break
        else:
            # Force take at least 1 char
            result.append(text[0])
            text = text[1:]
    return result


def draw_left_text(draw, x, y, width, text, font, fill, max_lines=30, line_h=66):
    """Left-aligned text with no orphan punctuation at line starts."""
    lines = split_line_no_orphan_punct(text, width, font, draw)
    for line in lines[:max_lines]:
        draw.text((x, y), line, fill=fill, font=font)
        y += line_h
    return y


def draw_footer(draw, qr_img):
    y0 = 1780
    if qr_img and FONT_SM:
        qr_size = 200
        qr_resized = qr_img.resize((qr_size, qr_size))
        draw.text((MARGIN, y0), "文章来自：70后教你做自媒体", fill=(140, 160, 180), font=FONT_SM)
        draw.text((MARGIN, y0 + 75), "扫码关注老成，日进一卒不焦虑", fill=(64, 150, 255), font=FONT_SM)
        img.paste(qr_resized, (WIDTH - MARGIN - qr_size, y0 - 20), qr_resized if qr_resized.mode == 'RGBA' else None)
    elif FONT_SM:
        draw.text((MARGIN, y0), "文章来自：70后教你做自媒体", fill=(140, 160, 180), font=FONT_SM)
        draw.text((MARGIN, y0 + 75), "扫码关注老成，日进一卒不焦虑", fill=(64, 150, 255), font=FONT_SM)


img = Image.new("RGB", (WIDTH, HEIGHT), color=(255, 255, 255))
draw = ImageDraw.Draw(img)

c = {"accent": (64, 150, 255), "dark": (25, 32, 45), "gray": (140, 160, 180), "text": (50, 50, 50)}

# Top dark section
draw.rectangle([(0, 0), (WIDTH, 900)], fill=c["dark"])
draw.rectangle([(0, 900), (WIDTH, 910)], fill=c["accent"])
draw.rectangle([(0, 910), (WIDTH, HEIGHT)], fill=(255, 255, 255))

# Title - line spacing increased by 100% (double)
lines = textwrap.wrap(TITLE, width=8) if TITLE else ["AI 资讯"]
y = 130
for line in lines:
    tw = FONT_TITLE.getlength(line) if hasattr(FONT_TITLE, 'getlength') else len(line) * 80
    draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_TITLE)
    y += 220  # was 160, now +100% = 220

# Date
if FONT_SM:
    draw.text((MARGIN, 750), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)

# Body text - left aligned, no orphan punctuation, constrained to TEXT_W
y = draw_left_text(draw, MARGIN, 1020, TEXT_W, BODY, FONT_BODY, c["text"], max_lines=15, line_h=66)

# Footer
qr = None
try:
    qr = Image.open(QR_PATH).convert("RGBA")
except:
    pass
draw_footer(draw, qr)

out = os.path.join(ROOT, "design-optimized.png")
img.save(out, "PNG")
print(f"Done: {out}")
