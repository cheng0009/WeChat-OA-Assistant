"""
Optimized design v3: larger body, more line spacing, aligned footer
"""
from PIL import Image, ImageDraw, ImageFont
import os, textwrap, re

WIDTH, HEIGHT = 1230, 2048
ROOT = r"E:\AI_hot"
QR_PATH = r"E:\AI_hot\aihot-wechat\qrcode.jpg"

FONT_TITLE = None
FONT_BODY = None
FONT_SM = None
for sz_t, sz_b, sz_s in [(160, 54, 28), (128, 48, 24), (100, 40, 20)]:
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
BODY_LINE_H = 100       # was 66, +50%
FOOTER_LINE_H = 80

LEADING_PUNCT = set("，。、；：？！）】》」』】〙〗〃’\"》）.!?)]},;:")
ENGLISH_WORD = re.compile(r'[A-Za-z0-9]+(?:[\.\-\+][A-Za-z0-9]+)*')


def split_line_safe(text, max_width, font, draw):
    """Split text into lines. English words (e.g. GPT-4, OpenAI) are never split."""
    word_spans = [(m.start(), m.end()) for m in ENGLISH_WORD.finditer(text)]
    result = []
    pos = 0
    while pos < len(text):
        # Find max end that fits within width
        end = pos + 1
        while end <= len(text):
            w = draw.textlength(text[pos:end], font=font)
            if w > max_width:
                end -= 1
                break
            end += 1
        end = min(end, len(text))

        if end <= pos:
            result.append(text[pos])
            pos += 1
            continue

        # Don't split English words — push end back to word start
        for ws, we in word_spans:
            if ws < end < we:
                if ws > pos:
                    end = ws
                break

        if end <= pos:
            result.append(text[pos])
            pos += 1
            continue

        # Avoid orphan punctuation at next line's start
        while end > pos + 1 and end < len(text) and text[end] in LEADING_PUNCT:
            end -= 1

        result.append(text[pos:end])
        pos = end
    return result


def draw_body(draw, x, y, width, text, font, fill, line_h):
    lines = split_line_safe(text, width, font, draw)
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        y += line_h
    return y


def draw_footer(draw, qr_img, y0):
    """Footer with QR code vertically aligned to text center."""
    line1 = "文章来自：70后教你做自媒体"
    line2 = "扫码关注老成，日进一卒不焦虑"
    accent = (64, 150, 255)
    gray = (140, 160, 180)

    # Text block height: from top of line1 to bottom of line2
    _, _, _, lh1 = FONT_SM.getbbox(line1) if hasattr(FONT_SM, 'getbbox') else (0, 0, 0, FONT_SM.size)
    _, _, _, lh2 = FONT_SM.getbbox(line2) if hasattr(FONT_SM, 'getbbox') else (0, 0, 0, FONT_SM.size)
    text_block_h = FOOTER_LINE_H + max(lh1, lh2)

    qr_size = 200
    # Center of text block
    text_center_y = y0 + text_block_h / 2
    qr_y = int(text_center_y - qr_size / 2)

    draw.text((MARGIN, y0), line1, fill=gray, font=FONT_SM)
    draw.text((MARGIN, y0 + FOOTER_LINE_H), line2, fill=accent, font=FONT_SM)

    if qr_img:
        qr_resized = qr_img.resize((qr_size, qr_size))
        if qr_resized.mode == 'RGBA':
            img.paste(qr_resized, (WIDTH - MARGIN - qr_size, qr_y), qr_resized)
        else:
            img.paste(qr_resized, (WIDTH - MARGIN - qr_size, qr_y))


img = Image.new("RGB", (WIDTH, HEIGHT), color=(255, 255, 255))
draw = ImageDraw.Draw(img)

c = {"accent": (64, 150, 255), "dark": (25, 32, 45), "gray": (140, 160, 180), "text": (50, 50, 50)}

# Top dark section
draw.rectangle([(0, 0), (WIDTH, 900)], fill=c["dark"])
draw.rectangle([(0, 900), (WIDTH, 910)], fill=c["accent"])
draw.rectangle([(0, 910), (WIDTH, HEIGHT)], fill=(255, 255, 255))

# Title - line spacing doubled
lines = textwrap.wrap(TITLE, width=8) if TITLE else ["AI 资讯"]
y = 130
for line in lines:
    tw = FONT_TITLE.getlength(line) if hasattr(FONT_TITLE, 'getlength') else len(line) * 80
    draw.text(((WIDTH - tw) / 2, y), line, fill=(255, 255, 255), font=FONT_TITLE)
    y += 220  # +100% title line spacing

# Date
if FONT_SM:
    tw_date = FONT_SM.getlength(f"AI HOT · {DATE_STR}") if hasattr(FONT_SM, 'getlength') else FONT_SM.size * 10
    draw.text(((WIDTH - tw_date) / 2, 750), f"AI HOT · {DATE_STR}", fill=c["gray"], font=FONT_SM)

# Body - left aligned, safe line breaks, 50% more line spacing
draw_body(draw, MARGIN, 1020, TEXT_W, BODY, FONT_BODY, c["text"], BODY_LINE_H)

# Footer with aligned QR
qr = None
try:
    qr = Image.open(QR_PATH).convert("RGBA")
except:
    pass
draw_footer(draw, qr, 1780)

out = os.path.join(ROOT, "design-optimized-v3.png")
img.save(out, "PNG")
print(f"Done: {out}")
