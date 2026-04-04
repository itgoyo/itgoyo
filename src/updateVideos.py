"""
updateVideos.py — Fetch latest Bilibili & YouTube videos and inject into README.md.

Data sources (priority order):
  Bilibili: 1) Self-hosted RSSHub  2) Bilibili public API (mobile UA fallback)
  YouTube:  Self-hosted RSSHub /youtube/user/:handle  (no API key needed)

Usage:
    python src/updateVideos.py <readme_path>

Env vars (optional):
    BILIBILI_COOKIE  — raw Cookie header for direct Bilibili API fallback
"""

import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

# ─── Constants ────────────────────────────────────────────────────────────────

RSSHUB_BASE = "https://rsshub.231590.xyz"
BILIBILI_UID = "12767066"
YOUTUBE_HANDLE = "@goudan-tech"
VIDEO_COUNT = 4
# Max display width units for title (CJK=2, ASCII=1).
# 25 CJK chars × 2 = 50 display width units.
TITLE_MAX_DISPLAY_WIDTH = 50

# RSSHub routes
RSSHUB_BILIBILI_URL = f"{RSSHUB_BASE}/bilibili/user/video/{BILIBILI_UID}"
RSSHUB_YOUTUBE_URL = f"{RSSHUB_BASE}/youtube/user/{YOUTUBE_HANDLE}"

# Bilibili direct API fallback (mobile UA bypasses 412)
BILIBILI_API_URL = (
    "https://api.bilibili.com/x/space/arc/search"
    f"?mid={BILIBILI_UID}&ps={VIDEO_COUNT}&pn=1&order=pubdate"
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _http_get(url: str, headers: dict | None = None, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; readme-bot/1.0)")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _char_width(c: str) -> int:
    """Return display width of a single character (wide CJK = 2, others = 1)."""
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1


def _display_width(s: str) -> int:
    return sum(_char_width(c) for c in s)


def truncate_title(title: str, max_width: int = TITLE_MAX_DISPLAY_WIDTH) -> str:
    """Truncate title so it fits within ~2 lines in a 4-column GitHub table cell."""
    title = title.strip()
    if _display_width(title) <= max_width:
        return title
    result: list[str] = []
    used = 0
    ellipsis_width = 3  # "..." = 3 ASCII chars
    for c in title:
        cw = _char_width(c)
        if used + cw > max_width - ellipsis_width:
            break
        result.append(c)
        used += cw
    return "".join(result) + "..."


def build_video_table(videos: list[dict]) -> str:
    """
    4-column HTML table with clickable thumbnail + title per cell.
    Video dict keys: title, url, thumb
    """
    cells = []
    for v in videos:
        title = truncate_title(v["title"])
        thumb = v["thumb"]
        url = v["url"]
        # Ensure HTTPS (GitHub blocks mixed-content images)
        if thumb.startswith("http://"):
            thumb = "https://" + thumb[7:]
        # Escape double-quotes in alt/title attributes
        safe_title = title.replace('"', "&quot;")
        cells.append(
            f'<td align="center" valign="top" width="25%">\n'
            f'<a href="{url}">\n'
            f'<img src="{thumb}" width="180" alt="{safe_title}"/>\n'
            f'</a>\n'
            f'<br/>\n'
            f'<a href="{url}">{title}</a>\n'
            f'</td>'
        )

    row = "\n".join(f"  {c}" for c in cells)
    return f"<table>\n<tr>\n{row}\n</tr>\n</table>"


def update_readme_section(readme_path: str, section_name: str, content: str) -> None:
    """Replace content between <!--START_SECTION:name--> … <!--END_SECTION:name-->."""
    with open(readme_path, "r", encoding="utf-8") as f:
        text = f.read()

    start_marker = f"<!--START_SECTION:{section_name}-->"
    end_marker = f"<!--END_SECTION:{section_name}-->"
    pattern = rf"(?<={re.escape(start_marker)})[\s\S]*?(?={re.escape(end_marker)})"
    new_text, n = re.subn(pattern, f"\n{content}\n", text)
    if n == 0:
        raise ValueError(
            f"Markers not found in {readme_path}: {start_marker} … {end_marker}"
        )
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_text)


def _parse_rss_items(raw: bytes, count: int) -> list[dict]:
    """
    Parse a standard RSS 2.0 feed produced by RSSHub.
    Thumbnail is taken from <enclosure type="image/..."> or <media:thumbnail>.
    """
    root = ET.fromstring(raw.decode("utf-8", errors="ignore"))
    items = root.findall("channel/item")
    videos = []
    for item in items[:count]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()

        # Thumbnail: prefer enclosure image, then media:thumbnail
        thumb = ""
        enc = item.find("enclosure")
        if enc is not None and (enc.attrib.get("type", "").startswith("image")):
            thumb = enc.attrib.get("url", "")

        if not thumb:
            media_ns = "http://search.yahoo.com/mrss/"
            mt = item.find(f"{{{media_ns}}}thumbnail")
            if mt is not None:
                thumb = mt.attrib.get("url", "")

        if title and link:
            videos.append({"title": title, "url": link, "thumb": thumb})
    return videos


# ─── Bilibili ─────────────────────────────────────────────────────────────────


def _bilibili_via_rsshub(count: int) -> list[dict]:
    """Primary: self-hosted RSSHub /bilibili/user/video/:uid"""
    raw = _http_get(RSSHUB_BILIBILI_URL)
    return _parse_rss_items(raw, count)


def _bilibili_via_direct_api(count: int) -> list[dict]:
    """
    Fallback: call Bilibili public API directly.
    Must use a mobile User-Agent to avoid HTTP 412.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://m.bilibili.com/",
        "Accept": "application/json",
    }
    cookie = os.environ.get("BILIBILI_COOKIE", "")
    if cookie:
        headers["Cookie"] = cookie

    raw = _http_get(BILIBILI_API_URL, headers=headers)
    data = json.loads(raw.decode("utf-8"))
    if data.get("code") != 0:
        raise RuntimeError(
            f"Bilibili API error code={data.get('code')}: {data.get('message')}"
        )
    vlist = data.get("data", {}).get("list", {}).get("vlist", [])
    videos = []
    for v in vlist[:count]:
        bvid = v.get("bvid", "")
        thumb = v.get("pic", "")
        if thumb.startswith("//"):
            thumb = "https:" + thumb
        # http→https is handled centrally in build_video_table
        videos.append({
            "title": v.get("title", "").strip(),
            "url": f"https://www.bilibili.com/video/{bvid}",
            "thumb": thumb,
        })
    return videos


def fetch_bilibili_videos(count: int = VIDEO_COUNT) -> list[dict]:
    # Try RSSHub first
    try:
        videos = _bilibili_via_rsshub(count)
        if videos:
            print(f"[bilibili] fetched {len(videos)} videos via RSSHub")
            return videos
        print("[bilibili] RSSHub returned 0 items, trying direct API …")
    except Exception as exc:
        print(f"[bilibili] RSSHub failed ({exc}), trying direct API …", file=sys.stderr)

    # Fallback: direct Bilibili API
    try:
        videos = _bilibili_via_direct_api(count)
        print(f"[bilibili] fetched {len(videos)} videos via direct API")
        return videos
    except Exception as exc:
        print(f"[bilibili] direct API failed: {exc}", file=sys.stderr)
        return []


# ─── YouTube ──────────────────────────────────────────────────────────────────


def fetch_youtube_videos(count: int = VIDEO_COUNT) -> list[dict]:
    """Use self-hosted RSSHub /youtube/user/:handle (no API key required)."""
    try:
        raw = _http_get(RSSHUB_YOUTUBE_URL)
        videos = _parse_rss_items(raw, count)
        print(f"[youtube] fetched {len(videos)} videos via RSSHub")
        return videos
    except Exception as exc:
        print(f"[youtube] fetch failed: {exc}", file=sys.stderr)
        return []


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python src/updateVideos.py <readme_path>")
        sys.exit(1)

    readme_path = sys.argv[1]

    # --- Bilibili ---
    print("[bilibili] fetching videos …")
    bili_videos = fetch_bilibili_videos()
    if bili_videos:
        update_readme_section(readme_path, "bilibili-videos", build_video_table(bili_videos))
        print(f"[bilibili] README updated")
    else:
        print("[bilibili] no videos fetched, section left unchanged")

    # --- YouTube ---
    print("[youtube] fetching videos …")
    yt_videos = fetch_youtube_videos()
    if yt_videos:
        update_readme_section(readme_path, "youtube-videos", build_video_table(yt_videos))
        print(f"[youtube] README updated")
    else:
        print("[youtube] no videos fetched, section left unchanged")


if __name__ == "__main__":
    main()
