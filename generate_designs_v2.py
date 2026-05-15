"""
Generate 5 revised title page designs
Body: 48pt justified, equal margins
Footer: 3x line spacing, QR code on the right
"""
from PIL import Image, ImageDraw, ImageFont
import os, textwrap

WIDTH, HEIGHT = 1230, 2048
ROOT = r"E:\AI_hot"
QR_PATH = r"E:\AI_hot\aihot-wechat\qrcode.jpg"

FONT_TITLE = None
FONT_BODY = None
FONT_SM = None
for sz_t, sz_b, sz_s in [(160, 52, 28), (128, 48, 24), (100, 40, 20)]:
    try:
        FONT_TITLE = ImageFont.truetype("C:\\Windows\\Fonts\\msyhbd.ttc", sz_t)
        FONT_BODY = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", sz_b)
        FONT_SM = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", sz_s)
        break
    except:
        continue

TITLE = "AI看病比医生准？但别高兴太早"
BODY = ("今天刷到几条AI新闻，说实话给我看愣了。Kimi的性能已经追上GPT-4，"
        "但成本只有几分之一。苹果在秘密研发带AI的耳机。OpenAI又被告上法庭了。")
DATE_STR = "2026-05-08"


def draw_justified_text(draw, x, y, width, text, font, fill):
    chars = list(text)
    if not chars:
        return y
    char_widths = [draw.textlength(c, font=font) for c in chars]
    total_w = sum(char_widths)
    if len(chars) <= 1 or total_w >= width:
        draw.text((x, y), text, fill=fill, font=font)
        return y
    gap = (width - total_w) / (len(chars) - 1)
    cx = x
    for i, c in enumerate(chars):
        draw.text((cx, y), c, fill=fill, font=font)
        cx += char_widths[i] + gap


def wrap_and_justify(draw, x, y, width, text, font, fill, max_lines=20, line_h=68):
    max_chars = int(width / (font.size * 0.85))
    lines = textwrap.wrap(text, width=max_chars) if len(text) > max_chars else [text]
    for line in lines[:max_lines]:
        draw_justified_text(draw, x, y, width, line, font, fill)
        y += line_h
    return y


def draw_footer(draw, qr_img):
    """Footer: text on left, QR on right, 3x line spacing"""
    y0 = 1780
    if qr_img:
        qr_size = 200
        qr_resized = qr_img.resize((qr_size, qr_size))
        draw.text((80, y0), "文章来自：70后教你做自媒体", fill=(140, 160, 180), font=FONT_SM)
        draw.text((80, y0 + 75), "扫码关注老成，日进一卒不焦虑", fill=(64, 150, 255), font=FONT_SM)
        img.paste(qr_resized, (WIDTH - 80 - qr_size, y0 - 20))
    else:
        draw.text((80, y0), "文章来自：70后教你做自媒体", fill=(140, 160, 180), font=FONT_SM)
        draw.text((80, y0 + 75), "扫码关注老成，日进一卒不焦虑", fill=(64, 150, 255), font=FONT_SM)


def make_variant(name, draw_fn):
    global img
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    qr = None
    try:
        qr = Image.open(QR_PATH).convert("RGBA")
    except:
        pass
    draw_fn(draw, qr)
    path = os.path.join(ROOT, f"design-v2-{name}.png")
    img.save(path, "PNG")
    print(f"  OK {path}")
    return path

MARGIN = 80
TEXT_W = WIDTH - MARGIN * 2


def v2_A(draw, qr):
    c = {"accent": (64, 150, 255), "dark": (25, 32, 45), "gray": (140, 160, 180), "text": (50, 50, 50)}
    draw.rectangle([(0, 0), (WIDTH, 900)], fill=c["dark"])
    draw.rectangle([(0, 900), (WIDTH, 910)], fill=c["accent"])
    lines = textwrap.wrap(TITLE, width=8)
    y = 150
    for line in lines:
        tw = FONT_TITLE.getlength(line) if hasattr(FONT_TITLE, 'getlength') else len(line) * 80
        draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_TITLE)
        y += 160
    if FONT_SM:
        draw.text((80, 780), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    y = wrap_and_justify(draw, MARGIN, 1020, TEXT_W, BODY, FONT_BODY, c["text"], line_h=72)
    draw_footer(draw, qr)


def v2_B(draw, qr):
    c = {"accent": (255, 180, 50), "dark": (22, 26, 36), "gray": (150, 165, 180), "text": (230, 235, 240)}
    draw.rectangle([(0, 0), (WIDTH, HEIGHT)], fill=c["dark"])
    draw.rectangle([(0, 0), (12, HEIGHT)], fill=c["accent"])
    lines = textwrap.wrap(TITLE, width=7)
    y = 140
    for line in lines:
        draw.text((MARGIN, y), line, fill=(255, 255, 255), font=FONT_TITLE)
        y += 160
    draw.rectangle([(MARGIN, y + 10), (MARGIN + 500, y + 14)], fill=c["accent"])
    if FONT_SM:
        draw.text((MARGIN, 740), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    y = wrap_and_justify(draw, MARGIN, 820, TEXT_W, BODY, FONT_BODY, c["text"], line_h=72)
    draw_footer(draw, qr)


def v2_C(draw, qr):
    c = {"accent": (220, 60, 60), "dark": (40, 18, 22), "gray": (190, 155, 155), "card": (250, 242, 240), "text": (50, 40, 40)}
    draw.rectangle([(0, 0), (WIDTH, 780)], fill=c["dark"])
    draw.rectangle([(0, 780), (WIDTH, 788)], fill=c["accent"])
    draw.rectangle([(0, 788), (WIDTH, HEIGHT)], fill=(247, 242, 240))
    lines = textwrap.wrap(TITLE, width=8)
    y = 120
    for line in lines:
        tw = FONT_TITLE.getlength(line) if hasattr(FONT_TITLE, 'getlength') else len(line) * 80
        draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_TITLE)
        y += 160
    card_x = MARGIN
    draw.rectangle([(card_x, 860), (WIDTH - card_x, 1480)], fill=c["card"])
    draw.rectangle([(card_x, 860), (WIDTH - card_x, 866)], fill=c["accent"])
    y = wrap_and_justify(draw, MARGIN + 20, 930, TEXT_W - 40, BODY, FONT_BODY, c["text"], line_h=72)
    if FONT_SM:
        draw.text((MARGIN, 800), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    draw_footer(draw, qr)


def v2_D(draw, qr):
    c = {"accent": (0, 150, 136), "dark": (18, 40, 36), "gray": (140, 175, 170), "text": (50, 50, 50)}
    draw.rectangle([(0, 0), (WIDTH, 680)], fill=c["dark"])
    draw.rectangle([(0, 680), (WIDTH, 686)], fill=c["accent"])
    draw.rectangle([(0, 686), (WIDTH, HEIGHT)], fill=(247, 250, 249))
    lines = textwrap.wrap(TITLE, width=9)
    y = 100
    for line in lines:
        tw = FONT_TITLE.getlength(line) if hasattr(FONT_TITLE, 'getlength') else len(line) * 80
        draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_TITLE)
        y += 155
    if FONT_SM:
        draw.text((MARGIN, 550), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    y = wrap_and_justify(draw, MARGIN, 800, TEXT_W, BODY, FONT_BODY, c["text"], line_h=72)
    draw_footer(draw, qr)


def v2_E(draw, qr):
    c = {"accent": (40, 40, 50), "dark": (30, 30, 35), "gray": (160, 160, 160), "text": (50, 50, 50)}
    draw.rectangle([(0, 0), (WIDTH, HEIGHT)], fill=(250, 250, 250))
    draw.rectangle([(40, 0), (48, HEIGHT)], fill=c["dark"])
    lines = textwrap.wrap(TITLE, width=8)
    y = 140
    for line in lines:
        draw.text((MARGIN + 20, y), line, fill=c["dark"], font=FONT_TITLE)
        y += 155
    draw.rectangle([(MARGIN + 20, y + 5), (MARGIN + 20 + 600, y + 9)], fill=c["accent"])
    if FONT_SM:
        draw.text((MARGIN + 20, 620), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)
    y = wrap_and_justify(draw, MARGIN + 20, 740, TEXT_W - 20, BODY, FONT_BODY, c["text"], line_h=72)
    draw_footer(draw, qr)


if __name__ == "__main__":
    print("Generating 5 revised designs...")
    make_variant("A-居中标题+底部正文", v2_A)
    make_variant("B-深色标题左上", v2_B)
    make_variant("C-红色系暖卡", v2_C)
    make_variant("D-绿白分屏", v2_D)
    make_variant("E-极简左对齐", v2_E)
    print("\nSaved to E:\\AI_hot\\ as design-v2-*.png")
