import asyncio
from PIL import Image, ImageDraw, ImageFont
from dataclasses import dataclass, field
from typing import Optional
import os, textwrap, re
from datetime import datetime
from app.config import WECHAT_IMAGES_DIR, BASE_DIR

WIDTH, HEIGHT = 1230, 2048
MARGIN = 80
TEXT_W = WIDTH - MARGIN * 2
SM_FONT_SZ = 28
FOOTER_LINE_H = 80

LEADING_PUNCT = set("，。、；：？！）】》」』】〙〗〃'\"》）.!?)]},;:")
ENGLISH_WORD = re.compile(r'[A-Za-z0-9]+(?:[.\-+][A-Za-z0-9]+)*')

# Default fallback image paths (project-relative)
QR_SRC = os.path.join(str(BASE_DIR), "qrcode.jpg")
AVATAR_SRC = os.path.join(str(BASE_DIR), "头像.png")

# Per-channel overrides
_current_avatar = None
_current_qrcode = None


def set_channel_images(avatar_url: str | None = None, qrcode_url: str | None = None):
    """Set per-channel images. Converts /data/... URLs to local paths."""
    global _current_avatar, _current_qrcode
    from app.config import BASE_DIR, DATA_DIR
    _current_avatar = _url_to_local(avatar_url, BASE_DIR, DATA_DIR)
    _current_qrcode = _url_to_local(qrcode_url, BASE_DIR, DATA_DIR)


def _url_to_local(url: str | None, base_dir, data_dir=None) -> str | None:
    if not url:
        return None
    if os.path.exists(url):
        return url
    rel = url.lstrip("/")
    # Check bundled resources dir first
    local = base_dir / rel
    if os.path.exists(local):
        return str(local)
    # Check writable data dir (for frozen builds where uploads live alongside exe)
    if data_dir:
        local_d = data_dir / rel
        if os.path.exists(local_d):
            return str(local_d)
    return url


def _resolve_avatar():
    if _current_avatar:
        return _current_avatar
    return AVATAR_SRC


def _resolve_qrcode():
    if _current_qrcode:
        return _current_qrcode
    return QR_SRC
_FONT_CACHE = {}


@dataclass
class ImageStyle:
    name: str
    label: str
    desc: str
    # Title page
    header_bg: tuple = (25, 32, 45)
    header_height: int = 900
    accent_color: tuple = (64, 150, 255)
    accent_bar_height: int = 10
    title_color: tuple = (255, 255, 255)
    title_font_sz: int = 140
    title_line_h: int = 176
    title_wrap_max: int = 8
    title_y: int = 270
    date_color: tuple = (140, 160, 180)
    date_y: int = 80
    date_prefix: str = "AI HOT"
    body_preview_color: tuple = (50, 50, 50)
    body_preview_y: int = 1020
    # Content page
    content_bg: tuple = (255, 255, 255)
    content_text_color: tuple = (50, 50, 50)
    content_accent_bar: bool = True
    page_num_color: tuple = (140, 160, 180)
    body_font_sz: int = 54
    body_line_h: int = 100
    # Footer
    footer_line1: str = "文章来自：70后教你做自媒体"
    footer_line2: str = "扫码关注老成，日进一卒不焦虑"
    footer_line1_color: tuple = (140, 160, 180)
    footer_line2_color: tuple = (64, 150, 255)
    footer_y: int = 1780
    # Preview area
    preview_y_end: int = 1720


# ── 4 style presets ──────────────────────────────────────────

STYLES: dict[str, ImageStyle] = {}

def _reg(s: ImageStyle):
    STYLES[s.name] = s
    return s

_reg(ImageStyle(
    name="deep_blue",
    label="深蓝科技",
    desc="深色藏蓝头+亮蓝点缀，现代极简风",
    header_bg=(25, 32, 45),
    accent_color=(64, 150, 255),
    footer_line2_color=(64, 150, 255),
))

_reg(ImageStyle(
    name="warm_orange",
    label="暖阳橙韵",
    desc="暖棕头部+琥珀橙点缀，温暖亲和",
    header_bg=(55, 35, 25),
    accent_color=(230, 130, 50),
    header_height=860,
    date_color=(180, 150, 120),
    body_preview_color=(70, 50, 40),
    content_text_color=(70, 50, 40),
    page_num_color=(180, 150, 120),
    footer_line1_color=(180, 150, 120),
    footer_line2_color=(230, 130, 50),
    footer_y=1740,
    preview_y_end=1680,
))

_reg(ImageStyle(
    name="ink_gold",
    label="墨金典雅",
    desc="纯黑头部+香槟金点缀，高级感",
    header_bg=(18, 16, 14),
    accent_color=(200, 175, 90),
    title_wrap_max=7,
    title_font_sz=130,
    title_line_h=165,
    date_color=(160, 150, 130),
    body_preview_color=(50, 45, 40),
    content_text_color=(50, 45, 40),
    page_num_color=(160, 150, 130),
    footer_line1_color=(160, 150, 130),
    footer_line2_color=(200, 175, 90),
    footer_y=1760,
    preview_y_end=1700,
))

_reg(ImageStyle(
    name="mist_green",
    label="青绿自然",
    desc="深翠绿头部+翡翠绿点缀，清新宁静",
    header_bg=(30, 70, 55),
    accent_color=(75, 175, 120),
    header_height=880,
    date_color=(140, 190, 165),
    body_preview_color=(50, 65, 60),
    content_text_color=(50, 65, 60),
    page_num_color=(140, 190, 165),
    footer_line1_color=(140, 190, 165),
    footer_line2_color=(75, 175, 120),
    footer_y=1760,
    preview_y_end=1700,
))

DEFAULT_STYLE = "deep_blue"


# ── helpers ──────────────────────────────────────────────────

def _font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    paths = [
        os.path.join(str(BASE_DIR), "data", "fonts", name),
        f"C:\\Windows\\Fonts\\{name}",
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


def _load_img(path):
    try:
        return Image.open(path).convert("RGBA")
    except:
        return None


def _pick_footer_img(is_odd):
    return _load_img(_resolve_qrcode() if is_odd else _resolve_avatar())


def _split_lines(text, max_width, font, draw):
    text = text.replace("\n", " ").replace("\r", " ")
    word_spans = [(m.start(), m.end()) for m in ENGLISH_WORD.finditer(text)]
    result, pos = [], 0
    while pos < len(text):
        end = pos + 1
        while end <= len(text):
            w = draw.textlength(text[pos:end], font=font)
            if w > max_width:
                end -= 1
                break
            end += 1
        end = min(end, len(text))
        if end <= pos:
            result.append(text[pos]); pos += 1; continue
        for ws, we in word_spans:
            if ws < end < we and ws > pos:
                end = ws; break
        if end <= pos:
            result.append(text[pos]); pos += 1; continue
        while end > pos + 1 and end < len(text) and text[end] in LEADING_PUNCT:
            end -= 1
        result.append(text[pos:end])
        pos = end
    return result


def _safe_folder(date_str, title):
    safe = re.sub(r'[\\/:*?"<>|]', "", title)[:20]
    ds = date_str or datetime.now().strftime("%Y-%m-%d")
    return f"{ds}-{safe}"


# ── drawing ──────────────────────────────────────────────────

def _draw_title_page(img, viral_title, date_str, body_lines, max_preview_lines, style: ImageStyle, date_prefix: str | None = None):
    draw = ImageDraw.Draw(img)

    font_t = _font(style.title_font_sz, bold=True) or _font(128, bold=True)
    font_b = _font(style.body_font_sz) or _font(48)
    font_sm = _font(SM_FONT_SZ) or _font(24)

    # Header area
    draw.rectangle([(0, 0), (WIDTH, style.header_height)], fill=style.header_bg)
    # Accent bar
    ah = style.accent_bar_height
    draw.rectangle([(0, style.header_height), (WIDTH, style.header_height + ah)], fill=style.accent_color)
    # White below
    draw.rectangle([(0, style.header_height + ah), (WIDTH, HEIGHT)], fill=(255, 255, 255))

    # Title
    wrap_n = min(style.title_wrap_max, max(6, int((TEXT_W - 40) / (style.title_font_sz * 0.75))))
    lines = textwrap.wrap(viral_title, width=wrap_n) if viral_title else ["AI 资讯"]
    y = style.title_y
    for line in lines[:4]:
        tw = font_t.getlength(line) if hasattr(font_t, 'getlength') else len(line) * style.title_font_sz * 0.75
        draw.text(((WIDTH - tw) / 2, y), line, fill=style.title_color, font=font_t)
        y += style.title_line_h

    # Date
    if font_sm:
        ds = date_str or datetime.now().strftime("%Y-%m-%d")
        prefix = date_prefix if date_prefix else style.date_prefix
        txt = f"{prefix} · {ds}"
        draw.text((MARGIN, style.date_y), txt, fill=style.date_color, font=font_sm)

    # Body preview
    if font_b and body_lines:
        y = style.body_preview_y
        for line in body_lines[:max_preview_lines]:
            s = line[1] if isinstance(line, tuple) else line
            draw.text((MARGIN, y), s, fill=style.body_preview_color, font=font_b)
            y += style.body_line_h

    # Footer
    avatar = _load_img(_resolve_avatar())
    _draw_footer(draw, font_sm, avatar, style.footer_y, img, style)


def _draw_content_page(img, lines, page_num, total_pages, style: ImageStyle):
    draw = ImageDraw.Draw(img)
    font = _font(style.body_font_sz) or _font(48)
    font_sm = _font(SM_FONT_SZ) or _font(24)

    if style.content_accent_bar:
        draw.rectangle([(0, 0), (WIDTH, 6)], fill=style.accent_color)

    if font:
        y = MARGIN
        for is_text, line in lines:
            if is_text and line:
                draw.text((MARGIN, y), line, fill=style.content_text_color, font=font)
                y += style.body_line_h
            else:
                y += style.body_line_h // 2

    if font_sm:
        txt = f"— {page_num} / {total_pages} —"
        tw = font_sm.getlength(txt) if hasattr(font_sm, 'getlength') else font_sm.size * 6
        draw.text(((WIDTH - tw) / 2, HEIGHT - 50), txt, fill=style.page_num_color, font=font_sm)

    footer_img = _pick_footer_img(page_num % 2 == 1)
    _draw_footer(draw, font_sm, footer_img, HEIGHT - 300, img, style)


def _draw_footer(draw, font, qr_img, y0, target_img, style: ImageStyle):
    if font:
        _, _, _, lh1 = font.getbbox(style.footer_line1) if hasattr(font, 'getbbox') else (0, 0, 0, font.size)
        _, _, _, lh2 = font.getbbox(style.footer_line2) if hasattr(font, 'getbbox') else (0, 0, 0, font.size)
        text_block_h = FOOTER_LINE_H + max(lh1, lh2)
    else:
        text_block_h = FOOTER_LINE_H + 28

    qr_size = 200
    text_center_y = y0 + text_block_h / 2
    qr_y = int(text_center_y - qr_size / 2)

    draw.text((MARGIN, y0), style.footer_line1, fill=style.footer_line1_color, font=font)
    draw.text((MARGIN, y0 + FOOTER_LINE_H), style.footer_line2, fill=style.footer_line2_color, font=font)

    if qr_img and target_img:
        qr_resized = qr_img.resize((qr_size, qr_size))
        mask = qr_resized if qr_resized.mode == 'RGBA' else None
        target_img.paste(qr_resized, (WIDTH - MARGIN - qr_size, qr_y), mask)


def _render_wechat_images(viral_title, body, date_str, style_name, avatar_path, qrcode_path, date_prefix):
    set_channel_images(avatar_path, qrcode_path)
    style = STYLES.get(style_name) or STYLES[DEFAULT_STYLE]

    # Safety: ensure viral_title isn't truncated mid-sentence
    viral_title = viral_title.rstrip("，、；：,")
    if len(viral_title) < 5:
        viral_title = "AI 资讯"

    folder = _safe_folder(date_str, viral_title)
    out_dir = os.path.join(str(WECHAT_IMAGES_DIR), folder)
    os.makedirs(out_dir, exist_ok=True)

    font = _font(style.body_font_sz) or _font(48)
    draw_for_measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    paragraphs = [p.strip() for p in body.split("\n") if p.strip()]

    all_lines = []
    for para in paragraphs:
        wrapped = _split_lines(para, TEXT_W, font, draw_for_measure)
        for wl in wrapped:
            all_lines.append((True, wl))
        all_lines.append((False, ""))

    while all_lines and all_lines[-1] == (False, ""):
        all_lines.pop()

    # preview area
    preview_y_start = style.body_preview_y
    preview_y_end = style.preview_y_end
    max_preview_lines = max(1, (preview_y_end - preview_y_start) // style.body_line_h)
    preview_lines = all_lines[:max_preview_lines]
    remaining_lines = all_lines[max_preview_lines:]

    # Title page
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(255, 255, 255))
    _draw_title_page(img, viral_title, date_str, preview_lines, max_preview_lines, style, date_prefix)
    title_path = os.path.join(out_dir, "01-title.png")
    img.save(title_path, "PNG")
    files = [f"/data/wechat/{folder}/01-title.png"]

    # Content pages
    while remaining_lines and remaining_lines[-1] == (False, ""):
        remaining_lines.pop()

    lines_per_page = int((HEIGHT - MARGIN * 2 - 100) / style.body_line_h)
    chunks = [remaining_lines[i:i + lines_per_page] for i in range(0, len(remaining_lines), lines_per_page)]

    total = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        if not chunk:
            continue
        page_img = Image.new("RGB", (WIDTH, HEIGHT), color=style.content_bg)
        _draw_content_page(page_img, chunk, idx, total, style)
        path = os.path.join(out_dir, f"{idx+1:02d}-content.png")
        page_img.save(path, "PNG")
        files.append(f"/data/wechat/{folder}/{idx+1:02d}-content.png")

    if files:
        import json as _json
        meta = {"style": style_name, "generated_at": datetime.now().isoformat()}
        with open(os.path.join(out_dir, "style.json"), "w", encoding="utf-8") as f:
            _json.dump(meta, f)

    return files


async def generate_wechat_images(article_title, viral_title, body, date_str, style_name: str = DEFAULT_STYLE, avatar_path: str | None = None, qrcode_path: str | None = None, date_prefix: str | None = None):
    return await asyncio.to_thread(_render_wechat_images, viral_title, body, date_str, style_name, avatar_path, qrcode_path, date_prefix)
