"""Nord-style SVG cards for Bilibili, YouTube, and Douban."""
from __future__ import annotations

import base64
import html
import os
import unicodedata
from io import BytesIO

import requests
from PIL import Image

from updateDouban import fetch_douban, referer_for
from updateVideos import fetch_bilibili_videos, fetch_youtube_videos

HOST = os.environ.get("MEDIA_SVG_BASE", "https://231590.xyz")
CARD_W = 980
PAD_X = 22
PAD_Y = 18
HEADER_H = 36
COL_GAP = 16
COLS = 4
TITLE_LINES = 2
TITLE_SIZE = 12
TITLE_LH = 16
FONT = "ui-sans-serif, system-ui, PingFang SC, Microsoft YaHei, Noto Sans SC, sans-serif"

THEMES = {
    "dark": {
        "bg": "#2e3440",
        "panel": "#3b4252",
        "border": "#c8c3e0",
        "text": "#eceff4",
        "muted": "#7b88a1",
        "placeholder": "#434c5e",
        "item": "#434c5e",
        "star": "#ebcb8b",
        "star_empty": "#4c566a",
    },
    "light": {
        "bg": "#eceff4",
        "panel": "#e5e9f0",
        "border": "#81a1c1",
        "text": "#2e3440",
        "muted": "#4c566a",
        "placeholder": "#d8dee9",
        "item": "#d8dee9",
        "star": "#d08770",
        "star_empty": "#aeb6c4",
    },
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def theme_name(value: str) -> str:
    return "light" if str(value).lower() == "light" else "dark"


def col_width() -> int:
    inner = CARD_W - PAD_X * 2
    return (inner - COL_GAP * (COLS - 1)) // COLS


def image_data_uri(url: str, width: int, height: int, referer: str = "") -> str:
    if not url:
        return ""
    src = url.replace("http://", "https://")
    if src.startswith("//"):
        src = "https:" + src
    headers = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    try:
        resp = requests.get(src, headers=headers, timeout=20)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img = _cover_crop(img, width, height)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=74, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _cover_crop(img: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return img.resize((width, height), Image.Resampling.LANCZOS)
    target = width / height
    ratio = src_w / src_h
    if ratio > target:
        new_w = max(1, int(src_h * target))
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        new_h = max(1, int(src_w / target))
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))
    return img.resize((width, height), Image.Resampling.LANCZOS)


def _char_px(ch: str, size: int) -> float:
    return float(size) if unicodedata.east_asian_width(ch) in ("W", "F") else size * 0.56


def wrap_title(text: str, max_px: float, size: int = TITLE_SIZE, lines: int = TITLE_LINES) -> list[str]:
    raw = " ".join((text or "").split())
    if not raw:
        return [""]
    out: list[str] = []
    remain = raw
    for i in range(lines):
        last = i == lines - 1
        budget = max_px - (size if last else 0)
        acc: list[str] = []
        used = 0.0
        for ch in remain:
            w = _char_px(ch, size)
            if acc and used + w > budget:
                break
            acc.append(ch)
            used += w
        piece = "".join(acc) or remain[:1]
        remain = remain[len(piece) :]
        if last and remain:
            piece = piece.rstrip() + "…"
        out.append(piece)
        if not remain:
            break
    return out or [""]


def _hydrate(items: list[dict], width: int, height: int, referer: str = "") -> list[dict]:
    out = []
    for item in items:
        src = item.get("thumb") or item.get("image") or ""
        ref = referer or referer_for(src)
        out.append(
            {
                "title": item.get("title") or "",
                "subtitle": item.get("subtitle") or "",
                "url": item.get("url") or "#",
                "image_uri": image_data_uri(src, width, height, ref),
                "rating": int(item.get("rating") or 0),
                "year": item.get("year") or "",
            }
        )
    return out


def collect_bilibili() -> list[dict]:
    w = col_width()
    return _hydrate(fetch_bilibili_videos(COLS), w * 2, int(w * 2 * 9 / 16))


def collect_youtube() -> list[dict]:
    w = col_width()
    return _hydrate(fetch_youtube_videos(COLS), w * 2, int(w * 2 * 9 / 16))


def collect_douban() -> dict[str, list[dict]]:
    cover_w, cover_h = 104, 140
    data = fetch_douban()
    return {
        "books": _hydrate(data["books"], cover_w, cover_h),
        "movies": _hydrate(data["movies"], cover_w, cover_h),
        "games": _hydrate(data["games"], cover_w, cover_h),
    }


def readme_picture(path: str, href: str, alt: str) -> str:
    return (
        f'<p align="center">\n'
        f'  <a href="{href}">\n'
        f"    <picture>\n"
        f'      <source media="(prefers-color-scheme: dark)" srcset="{HOST}/api/{path}?theme=dark">\n'
        f'      <img alt="{html.escape(alt)}" src="{HOST}/api/{path}?theme=light">\n'
        f"    </picture>\n"
        f"  </a>\n"
        f"</p>"
    )


def _header(cx: int, y: int, label: str, accent: str, muted: str) -> str:
    dash = "-" * 18
    return (
        f'<text x="{cx}" y="{y}" text-anchor="middle" font-size="13">'
        f'<tspan fill="{muted}">{dash}  </tspan>'
        f'<tspan fill="{accent}">{html.escape(label)}</tspan>'
        f'<tspan fill="{muted}">  {dash}</tspan>'
        f"</text>"
    )


def _title_block(cx: int, y: int, title: str, max_px: float, fill: str, anchor: str = "middle") -> str:
    lines = wrap_title(title, max_px)
    parts = []
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else TITLE_LH
        parts.append(
            f'<tspan x="{cx}" dy="{dy}">{html.escape(line)}</tspan>'
        )
    return (
        f'<text x="{cx}" y="{y}" text-anchor="{anchor}" font-size="{TITLE_SIZE}" fill="{fill}">'
        f"{''.join(parts)}</text>"
    )


def _thumb(x: int, y: int, w: int, h: int, item: dict, clip_id: str, theme: dict) -> tuple[str, str]:
    rx = 10
    clip = f'<clipPath id="{clip_id}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/></clipPath>'
    frame = (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{theme["placeholder"]}" stroke="{theme["border"]}" stroke-width="1"/>'
    )
    uri = item.get("image_uri") or ""
    if uri:
        img = (
            f'<image href="{uri}" xlink:href="{uri}" x="{x}" y="{y}" '
            f'width="{w}" height="{h}" clip-path="url(#{clip_id})" preserveAspectRatio="xMidYMid slice"/>'
        )
    else:
        img = (
            f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle" '
            f'font-size="11" fill="{theme["muted"]}">暂无封面</text>'
        )
    href = html.escape(item.get("url") or "#", quote=True)
    return clip, f'<a href="{href}">{frame}{img}</a>'


def render_video_svg(theme_key: str, brand: str, accent: str, items: list[dict]) -> str:
    theme = THEMES[theme_name(theme_key)]
    tw = col_width()
    th = int(tw * 9 / 16)
    title_h = TITLE_LH * TITLE_LINES + 6
    body_y = PAD_Y + HEADER_H
    height = int(body_y + th + 10 + title_h + PAD_Y)
    cx = CARD_W // 2
    defs: list[str] = []
    cards: list[str] = []
    for i in range(COLS):
        item = items[i] if i < len(items) else None
        x = PAD_X + i * (tw + COL_GAP)
        if not item:
            continue
        clip, body = _thumb(x, body_y, tw, th, item, f"v{i}", theme)
        defs.append(clip)
        cards.append(body)
        cards.append(
            f'<a href="{html.escape(item["url"], quote=True)}">'
            + _title_block(x + tw // 2, body_y + th + 18, item["title"], tw - 12, theme["text"])
            + "</a>"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{CARD_W}" height="{height}" viewBox="0 0 {CARD_W} {height}" font-family="{FONT}">
  <rect width="{CARD_W}" height="{height}" rx="18" fill="{theme["bg"]}"/>
  <rect x="16" y="12" width="{CARD_W - 32}" height="{height - 24}" rx="14" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="2"/>
  <defs>{''.join(defs)}</defs>
  {_header(cx, PAD_Y + 22, brand, accent, theme["muted"])}
  {''.join(cards)}
</svg>
"""


def render_bilibili(theme_key: str, items: list[dict]) -> str:
    return render_video_svg(theme_key, "Bilibili", "#00A1D6", items)


def render_youtube(theme_key: str, items: list[dict]) -> str:
    return render_video_svg(theme_key, "YouTube", "#FF0000", items)


def _stars(x: int, y: int, rating: int, theme: dict) -> str:
    n = max(0, min(5, int(rating or 0)))
    if n <= 0:
        return ""
    return (
        f'<text x="{x}" y="{y}" font-size="11">'
        f'<tspan fill="{theme["star"]}">{"★" * n}</tspan>'
        f'<tspan fill="{theme["star_empty"]}">{"★" * (5 - n)}</tspan>'
        f"</text>"
    )


def render_douban(theme_key: str, board: dict[str, list[dict]]) -> str:
    theme = THEMES[theme_name(theme_key)]
    cols_n = 3
    outer = 18
    gap = 14
    inner_w = CARD_W - outer * 2
    col_w = (inner_w - gap * (cols_n - 1)) // cols_n
    used = col_w * cols_n + gap * (cols_n - 1)
    origin_x = outer + (inner_w - used) // 2

    cover_w, cover_h = 52, 70
    item_h = 88
    item_gap = 8
    col_pad = 14
    col_header = 34
    max_items = 4
    col_h = col_pad + col_header + max_items * item_h + (max_items - 1) * item_gap + col_pad
    header_h = 62
    height = outer + header_h + col_h + outer
    cx = CARD_W // 2
    columns = [
        ("读过", "#a3be8c", board.get("books") or []),
        ("看过", "#d08770", board.get("movies") or []),
        ("想玩", "#b48ead", board.get("games") or []),
    ]

    defs: list[str] = []
    parts = [
        f'<text x="{cx}" y="{outer + 24}" text-anchor="middle" font-size="18" fill="{theme["text"]}">Douban · 我的清单</text>',
        f'<text x="{cx}" y="{outer + 46}" text-anchor="middle" font-size="12" fill="{theme["muted"]}">阅读 | 观影 | 游戏</text>',
    ]
    col_y = outer + header_h
    for c, (label, accent, items) in enumerate(columns):
        x = origin_x + c * (col_w + gap)
        parts.append(
            f'<rect x="{x}" y="{col_y}" width="{col_w}" height="{col_h}" rx="16" '
            f'fill="{theme["panel"]}" stroke="{accent}" stroke-width="1.6"/>'
            f'<circle cx="{x + col_pad + 5}" cy="{col_y + col_pad + 10}" r="4" fill="{accent}"/>'
            f'<text x="{x + col_pad + 16}" y="{col_y + col_pad + 15}" font-size="14" fill="{theme["text"]}">{html.escape(label)}</text>'
        )
        shown = items[:max_items]
        text_w = col_w - col_pad * 2 - cover_w - 10
        for i, item in enumerate(shown):
            iy = col_y + col_pad + col_header + i * (item_h + item_gap)
            ix = x + col_pad
            clip, body = _thumb(ix, iy, cover_w, cover_h, item, f"d{c}{i}", theme)
            defs.append(clip)
            href = html.escape(item.get("url") or "#", quote=True)
            tx = ix + cover_w + 10
            title_svg = _title_block(tx, iy + 18, item.get("title") or "", text_w, theme["text"], "start")
            rating = int(item.get("rating") or 0)
            year = item.get("year") or ""
            meta = ""
            meta_y = iy + 52
            if rating:
                meta += _stars(tx, meta_y, rating, theme)
                meta_y += 16
            if year:
                meta += (
                    f'<text x="{tx}" y="{meta_y}" font-size="11" fill="{theme["muted"]}">{html.escape(year)}</text>'
                )
            parts.append(
                f'<rect x="{ix - 2}" y="{iy - 4}" width="{col_w - col_pad * 2 + 4}" height="{item_h - 2}" '
                f'rx="10" fill="{theme["item"]}"/>'
                f'{body}'
                f'<a href="{href}">{title_svg}{meta}</a>'
            )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{CARD_W}" height="{height}" viewBox="0 0 {CARD_W} {height}" font-family="{FONT}">
  <rect width="{CARD_W}" height="{height}" rx="18" fill="{theme["bg"]}"/>
  <defs>{''.join(defs)}</defs>
  {''.join(parts)}
</svg>
"""
