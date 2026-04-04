"""Update README with user-specific Douban book/movie/game cards.

Data source (public user pages):
    - Book  wish:     https://book.douban.com/people/:user/wish
    - Movie collect:  https://movie.douban.com/people/:user/collect
    - Game  wish:     https://www.douban.com/people/:user/games?action=wish

Images are downloaded locally to img/douban/ to bypass hotlink protection.

Usage:
        python src/updateDouban.py <readme_path>

Env vars (optional):
        DOUBAN_USER_ID     default: itgoyo
        DOUBAN_ITEM_COUNT  default: 4
"""

from __future__ import annotations

import hashlib
import html
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
from typing import Callable

DOUBAN_USER_ID = os.environ.get("DOUBAN_USER_ID", "itgoyo")
ITEM_COUNT = int(os.environ.get("DOUBAN_ITEM_COUNT", "4"))

BOOK_WISH_URL = f"https://book.douban.com/people/{DOUBAN_USER_ID}/wish"
MOVIE_COLLECT_URL = f"https://movie.douban.com/people/{DOUBAN_USER_ID}/collect"
GAME_WISH_URL = f"https://www.douban.com/people/{DOUBAN_USER_ID}/games?action=wish"

IMAGE_DIR = "img/douban"

REFERER_MAP = {
    "book.douban.com": "https://book.douban.com/",
    "movie.douban.com": "https://movie.douban.com/",
    "www.douban.com": "https://www.douban.com/",
    "img1.doubanio.com": "https://www.douban.com/",
    "img2.doubanio.com": "https://www.douban.com/",
    "img3.doubanio.com": "https://www.douban.com/",
    "img9.doubanio.com": "https://www.douban.com/",
}

Parser = Callable[[str, int], list[dict[str, str]]]


def _http_get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url)
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _referer_for(url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    return REFERER_MAP.get(host, "https://www.douban.com/")


def _download_image(url: str, dest_dir: pathlib.Path) -> str:
    """Download image with correct Referer and return the local relative path."""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    ext = pathlib.PurePosixPath(url).suffix or ".jpg"
    local_name = f"{url_hash}{ext}"
    local_path = dest_dir / local_name

    if local_path.exists():
        return f"{IMAGE_DIR}/{local_name}"

    req = urllib.request.Request(url)
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    )
    req.add_header("Referer", _referer_for(url))

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        local_path.write_bytes(data)
        print(f"  [img] downloaded {local_name} ({len(data)} bytes)")
    except Exception as exc:
        print(f"  [img] failed {url}: {exc}", file=sys.stderr)
        return url

    return f"{IMAGE_DIR}/{local_name}"


def _normalize_image(url: str) -> str:
    value = html.unescape(url.strip())
    if value.startswith("//"):
        return "https:" + value
    return value


def _safe_text(value: str) -> str:
    return html.escape(html.unescape(value.strip()), quote=True)


def _parse_book_items(page: str, count: int) -> list[dict[str, str]]:
    blocks = re.findall(r'<li class="subject-item"[\s\S]*?</li>', page)
    result: list[dict[str, str]] = []
    for block in blocks:
        m = re.search(
            r'<img[^>]+src="([^"]+)"[\s\S]*?<a\s+href="([^"]+)"\s+title="([^"]+)"',
            block,
        )
        if not m:
            continue
        img, url, title = m.group(1), m.group(2), m.group(3)
        result.append(
            {
                "title": _safe_text(title),
                "url": html.unescape(url),
                "image": _normalize_image(img),
            }
        )
        if len(result) >= count:
            break
    return result


def _parse_movie_items(page: str, count: int) -> list[dict[str, str]]:
    """Parse movie collect page (看过的影视)."""
    matches = re.findall(
        r'<a\s+title="([^"]+)"\s+href="([^"]+)"\s+class="nbg">\s*'
        r'<img[^>]+src="([^"]+)"',
        page,
    )
    result: list[dict[str, str]] = []
    for title, url, img in matches[:count]:
        cn_title = title
        m = re.search(
            rf'<a href="{re.escape(html.unescape(url))}">\s*<em>([^<]+)</em>',
            page,
        )
        if m:
            cn_title = m.group(1).split("/")[0].strip()
        result.append(
            {
                "title": _safe_text(cn_title),
                "url": html.unescape(url),
                "image": _normalize_image(img),
            }
        )
    return result


def _parse_game_items(page: str, count: int) -> list[dict[str, str]]:
    matches = re.findall(
        r'<a href="(https://www\.douban\.com/game/[^"]+/)"><img src="([^"]+)"'
        r'[^>]*></a>[\s\S]*?<div class="title">\s*<a href="[^"]+">([^<]+)</a>',
        page,
    )
    result: list[dict[str, str]] = []
    for url, img, title in matches[:count]:
        result.append(
            {
                "title": _safe_text(title),
                "url": html.unescape(url),
                "image": _normalize_image(img),
            }
        )
    return result


def _localize_images(
    items: list[dict[str, str]], dest_dir: pathlib.Path
) -> list[dict[str, str]]:
    """Download remote images and replace URL with local path."""
    result = []
    for item in items:
        local_img = _download_image(item["image"], dest_dir)
        result.append({**item, "image": local_img})
    return result


def _build_cell(items: list[dict[str, str]]) -> str:
    if not items:
        return "暂无更新"
    cards = []
    for item in items:
        cards.append(
            f'<a href="{item["url"]}"><img src="{item["image"]}" width="92" '
            f'alt="{item["title"]}"/></a><br/>'
            f'<a href="{item["url"]}">{item["title"]}</a>'
        )
    return "<br/><br/>".join(cards)


def _build_dashboard(
    book_items: list[dict[str, str]],
    movie_items: list[dict[str, str]],
    game_items: list[dict[str, str]],
) -> str:
    book_cell = _build_cell(book_items)
    movie_cell = _build_cell(movie_items)
    game_cell = _build_cell(game_items)

    return (
        "<table>\n"
        "  <tr>\n"
        '    <th align="left">📚 想读</th>\n'
        '    <th align="left">🎬 看过</th>\n'
        '    <th align="left">🎮 想玩</th>\n'
        "  </tr>\n"
        "  <tr>\n"
        f"    <td valign=\"top\">{book_cell}</td>\n"
        f"    <td valign=\"top\">{movie_cell}</td>\n"
        f"    <td valign=\"top\">{game_cell}</td>\n"
        "  </tr>\n"
        "</table>"
    )


def _update_readme_section(readme_path: str, section_name: str, content: str) -> None:
    with open(readme_path, "r", encoding="utf-8") as f:
        text = f.read()

    start_marker = f"<!--START_SECTION:{section_name}-->"
    end_marker = f"<!--END_SECTION:{section_name}-->"
    pattern = rf"(?<={re.escape(start_marker)})[\s\S]*?(?={re.escape(end_marker)})"
    new_text, replaced = re.subn(pattern, f"\n{content}\n", text)
    if replaced == 0:
        raise ValueError(f"Markers not found: {start_marker} ... {end_marker}")

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_text)


def _fetch_items(url: str, label: str, parser: Parser, count: int) -> list[dict[str, str]]:
    try:
        page = _http_get_text(url)
        items = parser(page, count)
        print(f"[{label}] fetched {len(items)} items from {url}")
        return items
    except urllib.error.URLError as exc:
        print(f"[{label}] network error: {exc}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"[{label}] parse failed: {exc}", file=sys.stderr)
        return []


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python src/updateDouban.py <readme_path>")
        sys.exit(1)

    readme_path = sys.argv[1]

    if ITEM_COUNT <= 0:
        print("[douban] DOUBAN_ITEM_COUNT must be > 0", file=sys.stderr)
        sys.exit(1)

    readme_dir = pathlib.Path(readme_path).resolve().parent
    img_dir = readme_dir / IMAGE_DIR
    img_dir.mkdir(parents=True, exist_ok=True)

    book_items = _fetch_items(BOOK_WISH_URL, "douban-book", _parse_book_items, ITEM_COUNT)
    movie_items = _fetch_items(MOVIE_COLLECT_URL, "douban-movie", _parse_movie_items, ITEM_COUNT)
    game_items = _fetch_items(GAME_WISH_URL, "douban-game", _parse_game_items, ITEM_COUNT)

    book_items = _localize_images(book_items, img_dir)
    movie_items = _localize_images(movie_items, img_dir)
    game_items = _localize_images(game_items, img_dir)

    dashboard = _build_dashboard(book_items, movie_items, game_items)
    try:
        _update_readme_section(readme_path, "douban-dashboard", dashboard)
    except Exception as exc:
        print(f"[douban] update README failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("[douban] README sections updated")


if __name__ == "__main__":
    main()
