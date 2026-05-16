import asyncio
from PIL import Image, ImageDraw, ImageFont
import os, random
from datetime import datetime

from app.config import IMAGES_DIR, BASE_DIR

COVER_W, COVER_H = 1200, 630
MARGIN = 80
TEXT_W = COVER_W - MARGIN * 2  # 1040 px for title text

COLOR_SCHEMES = [
    {"bg": (18, 25, 35), "accent": (64, 150, 255), "date": (140, 160, 180), "text": (240, 245, 250), "stripe": (22, 32, 45)},
    {"bg": (35, 20, 25), "accent": (255, 100, 100), "date": (200, 150, 150), "text": (250, 235, 235), "stripe": (45, 25, 30)},
    {"bg": (20, 35, 25), "accent": (100, 200, 120), "date": (150, 190, 160), "text": (235, 250, 235), "stripe": (25, 42, 30)},
    {"bg": (25, 25, 40), "accent": (180, 130, 255), "date": (170, 160, 200), "text": (240, 240, 250), "stripe": (32, 30, 48)},
    {"bg": (40, 30, 15), "accent": (255, 180, 50), "date": (200, 175, 140), "text": (250, 245, 235), "stripe": (48, 36, 20)},
]
LAYOUTS = ["gradient", "accent-left", "minimal-card"]

_FONT_CACHE = {}


def _font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    paths = [
        os.path.join(str(BASE_DIR), "data", "fonts", "msyhbd.ttc" if bold else "msyh.ttc"),
        f"C:\\Windows\\Fonts\\{'msyhbd.ttc' if bold else 'msyh.ttc'}",
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf",
    ]
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
            _FONT_CACHE[key] = f
            return f
        except:
            continue
    return None


def _wrap_by_px(text, font, max_px, draw):
    """Wrap text so each line fits within max_px pixels. Handles mixed CJK + Latin."""
    if not text or not font:
        return [text] if text else []
    result, line = [], ""
    for ch in text:
        test = line + ch
        w = draw.textlength(test, font=font)
        if w > max_px and line:
            result.append(line)
            line = ch
        else:
            line = test
    if line:
        result.append(line)
    return result


def _draw_centered_text(draw, lines, font, color, center_x, y_start, line_gap):
    """Draw each line centered at center_x."""
    y = y_start
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text((center_x - tw / 2, y), line, fill=color, font=font)
        y += line_gap


def _render_cover(title: str, date_str: str, source_name: str) -> str:
    scheme = random.choice(COLOR_SCHEMES)
    layout = random.choice(LAYOUTS)

    img = Image.new("RGB", (COVER_W, COVER_H), color=scheme["bg"])
    draw = ImageDraw.Draw(img)

    font_lg = _font(72, bold=True) or _font(56, bold=True) or _font(48, bold=True)
    font_md = _font(40) or _font(32)
    font_sm = _font(28) or _font(22)

    if layout == "gradient":
        _draw_gradient(draw, img, title, date_str, source_name, scheme, font_lg, font_md, font_sm)
    elif layout == "accent-left":
        _draw_accent_left(draw, title, date_str, source_name, scheme, font_lg, font_md, font_sm)
    else:
        _draw_minimal_card(draw, title, date_str, source_name, scheme, font_lg, font_md, font_sm)

    filename = f"cover_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    filepath = os.path.join(str(IMAGES_DIR), filename)
    img.save(filepath, "PNG")
    return f"/data/images/{filename}"


async def generate_cover_image(title: str, date_str: str = "", source_name: str = "AI HOT") -> str:
    return await asyncio.to_thread(_render_cover, title, date_str, source_name)


# ── Layout: gradient (modern gradient + centered title) ──────

def _draw_gradient(draw, img, title, date_str, source_name, scheme, font_lg, font_md, font_sm):
    for y in range(COVER_H):
        ratio = y / COVER_H
        r = int(scheme["bg"][0] * (1 - ratio) + scheme["accent"][0] * 0.3 * ratio)
        g = int(scheme["bg"][1] * (1 - ratio) + scheme["accent"][1] * 0.3 * ratio)
        b = int(scheme["bg"][2] * (1 - ratio) + scheme["accent"][2] * 0.3 * ratio)
        draw.line([(0, y), (COVER_W, y)], fill=(r, g, b))

    # Decorative circle (top-right)
    draw.ellipse([(COVER_W - 220, -80), (COVER_W - 20, 120)], fill=scheme["accent"] + (40,))
    draw.ellipse([(COVER_W - 160, -40), (COVER_W - 60, 60)], fill=scheme["accent"] + (60,))

    d = date_str or datetime.now().strftime("%Y-%m-%d")
    if font_sm:
        draw.text((MARGIN, 50), f"{source_name} · {d}", fill=scheme["date"], font=font_sm)

    lines = _wrap_by_px(title, font_lg, TEXT_W, draw)
    lines = lines[:3]
    if lines:
        total_h = len(lines) * 90 - 10
        y0 = (COVER_H - total_h) // 2 - 20
        _draw_centered_text(draw, lines, font_lg, scheme["text"], COVER_W / 2, y0, 90)


# ── Layout: accent-left (bold left accent + clean) ───────────

def _draw_accent_left(draw, title, date_str, source_name, scheme, font_lg, font_md, font_sm):
    # Left accent bar
    draw.rectangle([(0, 0), (12, COVER_H)], fill=scheme["accent"])
    # Subtle diagonal line decoration
    for i in range(0, COVER_W + COVER_H, 30):
        x = i
        y = i * 0.4
        if x < COVER_W and y < COVER_H:
            draw.point((x, int(y)), fill=scheme["stripe"])

    d = date_str or datetime.now().strftime("%Y-%m-%d")
    if font_sm:
        draw.text((MARGIN + 20, 60), f"{source_name} · {d}", fill=scheme["date"], font=font_sm)

    right_w = COVER_W - MARGIN - 100
    lines = _wrap_by_px(title, font_lg, right_w, draw)
    lines = lines[:3]
    if lines:
        total_h = len(lines) * 90 - 10
        y0 = (COVER_H - total_h) // 2
        _draw_centered_text(draw, lines, font_lg, scheme["text"], 100 + right_w / 2, y0, 90)


# ── Layout: minimal-card (clean card style) ──────────────────

def _draw_minimal_card(draw, title, date_str, source_name, scheme, font_lg, font_md, font_sm):
    # Card background
    card_l, card_t, card_w, card_h = 100, 140, COVER_W - 200, COVER_H - 260
    draw.rounded_rectangle(
        [(card_l, card_t), (card_l + card_w, card_t + card_h)],
        radius=16, fill=scheme["stripe"]
    )
    # Accent top bar on card
    draw.rounded_rectangle(
        [(card_l, card_t), (card_l + card_w, card_t + 6)],
        radius=3, fill=scheme["accent"]
    )

    d = date_str or datetime.now().strftime("%Y-%m-%d")
    if font_sm:
        label = f"{source_name} · {d}"
        tw = draw.textlength(label, font=font_sm)
        draw.text((COVER_W / 2 - tw / 2, card_t + 30), label, fill=scheme["date"], font=font_sm)

    lines = _wrap_by_px(title, font_lg, card_w - 80, draw)
    lines = lines[:3]
    if lines:
        total_h = len(lines) * 85 - 10
        y0 = card_t + (card_h - total_h) // 2 + 20
        _draw_centered_text(draw, lines, font_lg, scheme["text"], COVER_W / 2, y0, 85)
