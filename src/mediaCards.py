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

HOST = os.environ.get("MEDIA_SVG_BASE", "https://github.231590.xyz")
CARD_W = 980
COLS = 4
TITLE_LINES = 2
TITLE_SIZE = 12
TITLE_LH = 16
FONT = "ui-sans-serif, system-ui, PingFang SC, Microsoft YaHei, Noto Sans SC, sans-serif"

THEMES = {
    "dark": {
        "bg": "#0d1117",
        "panel": "#161b22",
        "border": "#30363d",
        "text": "#e6edf3",
        "muted": "#8b949e",
        "placeholder": "#21262d",
        "item": "#21262d",
        "item_border": "#30363d",
        "star": "#d29922",
        "star_empty": "#30363d",
        "title_from": "#58a6ff",
        "title_to": "#a371f7",
    },
    "light": {
        "bg": "#f3efe8",
        "panel": "#fffdf8",
        "border": "#e4ddd2",
        "text": "#2c2a26",
        "heading": "#2c2a26",
        "muted": "#8a847a",
        "placeholder": "#efe8dc",
        "item": "#f7f3ec",
        "item_border": "#e8e1d5",
        "star": "#c4a035",
        "star_empty": "#ddd6c8",
    },
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def theme_name(value: str) -> str:
    return "light" if str(value).lower() == "light" else "dark"


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
    return _hydrate(fetch_bilibili_videos(COLS), 240, 135)


def collect_youtube() -> list[dict]:
    return _hydrate(fetch_youtube_videos(COLS), 240, 135)


def collect_douban() -> dict[str, list[dict]]:
    cover_w, cover_h = 104, 140
    data = fetch_douban()
    return {
        "books": _hydrate(data["books"], cover_w, cover_h),
        "movies": _hydrate(data["movies"], cover_w, cover_h),
        "games": _hydrate(data["games"], cover_w, cover_h),
    }


def readme_picture(path: str, href: str, alt: str) -> str:
    picture = (
        "    <picture>\n"
        f'      <source media="(prefers-color-scheme: dark)" srcset="{HOST}/api/{path}?theme=dark">\n'
        f'      <img alt="{html.escape(alt)}" src="{HOST}/api/{path}">\n'
        "    </picture>"
    )
    if href:
        return (
            f'<p align="center">\n'
            f'  <a href="{href}">\n'
            f"{picture}\n"
            f"  </a>\n"
            f"</p>"
        )
    return f'<p align="center">\n{picture}\n</p>'


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
        f'fill="{theme["placeholder"]}" stroke="{theme["item_border"]}" stroke-width="1"/>'
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


def render_board(
    theme_key: str,
    title: str,
    subtitle: str,
    columns: list[tuple[str, str, list[dict]]],
    cover_w: int,
    cover_h: int,
    item_h: int,
    show_meta: bool,
    clip_prefix: str,
) -> str:
    theme = THEMES[theme_name(theme_key)]
    dark = theme_name(theme_key) == "dark"
    cols_n = max(1, len(columns))
    outer = 18
    gap = 14
    inner_w = CARD_W - outer * 2
    col_w = (inner_w - gap * (cols_n - 1)) // cols_n
    used = col_w * cols_n + gap * (cols_n - 1)
    origin_x = outer + (inner_w - used) // 2
    item_gap = 8
    col_pad = 14
    col_header = 34
    max_items = 4
    col_h = col_pad + col_header + max_items * item_h + (max_items - 1) * item_gap + col_pad
    header_h = 62
    height = outer + header_h + col_h + outer
    cx = CARD_W // 2
    defs: list[str] = []
    title_fill = theme["text"]
    if dark and theme.get("title_from"):
        defs.append(
            '<linearGradient id="titleGrad" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0%" stop-color="{theme["title_from"]}"/>'
            f'<stop offset="100%" stop-color="{theme["title_to"]}"/>'
            "</linearGradient>"
        )
        title_fill = "url(#titleGrad)"
    parts = [
        f'<text x="{cx}" y="{outer + 24}" text-anchor="middle" font-size="18" fill="{title_fill}">{html.escape(title)}</text>',
        f'<text x="{cx}" y="{outer + 46}" text-anchor="middle" font-size="12" fill="{theme["muted"]}">{html.escape(subtitle)}</text>',
    ]
    col_y = outer + header_h
    for c, (label, accent, items) in enumerate(columns):
        x = origin_x + c * (col_w + gap)
        label_fill = accent if dark else theme["text"]
        parts.append(
            f'<rect x="{x}" y="{col_y}" width="{col_w}" height="{col_h}" rx="16" '
            f'fill="{theme["panel"]}" stroke="{accent}" stroke-width="1.6"/>'
            f'<circle cx="{x + col_pad + 5}" cy="{col_y + col_pad + 10}" r="4" fill="{accent}"/>'
            f'<text x="{x + col_pad + 16}" y="{col_y + col_pad + 15}" font-size="14" fill="{label_fill}">{html.escape(label)}</text>'
        )
        shown = items[:max_items]
        text_w = col_w - col_pad * 2 - cover_w - 10
        for i, item in enumerate(shown):
            iy = col_y + col_pad + col_header + i * (item_h + item_gap)
            ix = x + col_pad
            clip, body = _thumb(ix, iy, cover_w, cover_h, item, f"{clip_prefix}{c}{i}", theme)
            defs.append(clip)
            href = html.escape(item.get("url") or "#", quote=True)
            tx = ix + cover_w + 10
            title_svg = _title_block(tx, iy + 20, item.get("title") or "", text_w, theme["text"], "start")
            meta = ""
            if show_meta:
                meta_y = iy + 54
                rating = int(item.get("rating") or 0)
                year = item.get("year") or ""
                if rating:
                    meta += _stars(tx, meta_y, rating, theme)
                    meta_y += 16
                if year:
                    meta += (
                        f'<text x="{tx}" y="{meta_y}" font-size="11" fill="{theme["muted"]}">{html.escape(year)}</text>'
                    )
            parts.append(
                f'<rect x="{ix - 2}" y="{iy - 4}" width="{col_w - col_pad * 2 + 4}" height="{item_h - 2}" '
                f'rx="10" fill="{theme["item"]}" stroke="{theme["item_border"]}" stroke-width="1"/>'
                f"{body}"
                f'<a href="{href}">{title_svg}{meta}</a>'
            )
    shell = f'<rect width="{CARD_W}" height="{height}" rx="18" fill="{theme["bg"]}"'
    if dark:
        shell += f' stroke="{theme["border"]}" stroke-width="1"'
    shell += "/>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{CARD_W}" height="{height}" viewBox="0 0 {CARD_W} {height}" font-family="{FONT}">
  {shell}
  <defs>{''.join(defs)}</defs>
  {''.join(parts)}
</svg>
"""


def _column_accents(theme_key: str) -> dict[str, str]:
    if theme_name(theme_key) == "light":
        return {
            "bili": "#00A1D6",
            "yt": "#FF0000",
            "read": "#5b8c5a",
            "watch": "#c27a4a",
            "play": "#7a6aa6",
        }
    return {
        "bili": "#39c5cf",
        "yt": "#f85149",
        "read": "#3fb950",
        "watch": "#d29922",
        "play": "#a371f7",
    }


def render_videos(theme_key: str, bili: list[dict], youtube: list[dict]) -> str:
    a = _column_accents(theme_key)
    return render_board(
        theme_key,
        "Latest Videos · 最新视频",
        "Bilibili | YouTube",
        [
            ("Bilibili", a["bili"], bili or []),
            ("YouTube", a["yt"], youtube or []),
        ],
        cover_w=120,
        cover_h=68,
        item_h=80,
        show_meta=False,
        clip_prefix="v",
    )


def render_bilibili(theme_key: str, items: list[dict]) -> str:
    return render_videos(theme_key, items, [])


def render_youtube(theme_key: str, items: list[dict]) -> str:
    return render_videos(theme_key, [], items)


def render_douban(theme_key: str, board: dict[str, list[dict]]) -> str:
    a = _column_accents(theme_key)
    return render_board(
        theme_key,
        "Douban · 我的清单",
        "阅读 | 观影 | 游戏",
        [
            ("读过", a["read"], board.get("books") or []),
            ("看过", a["watch"], board.get("movies") or []),
            ("玩过", a["play"], board.get("games") or []),
        ],
        cover_w=52,
        cover_h=70,
        item_h=88,
        show_meta=True,
        clip_prefix="d",
    )
