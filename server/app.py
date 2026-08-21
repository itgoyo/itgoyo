"""Serve live SVG cards for the profile README.

Env: USER_NAME, ACCESS_TOKEN, SPOTIFY_*, PORT
     BILIBILI_COOKIE (optional)

Run:
    python -m uvicorn server.app:app --host 0.0.0.0 --port 8080

Paths:
    /api/profile.svg
    /api/videos.svg
    /api/douban.svg

Nginx: do not cache /api/profile.svg; pass through Cache-Control; proxy_cache off for that location.
Cloudflare: Bypass cache for /api/profile.svg; Browser Cache TTL = Respect Existing Headers.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Response

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

from mediaCards import (  # noqa: E402
    collect_bilibili,
    collect_douban,
    collect_youtube,
    render_douban,
    render_videos,
    theme_name,
)
from updateGithubStats import collect_github, render_card  # noqa: E402

GITHUB_INTERVAL = 3600
MEDIA_INTERVAL = 1800
PORT = int(os.environ.get("PORT", "8080"))

_lock = threading.Lock()
_state = {
    "github": None,
    "github_at": 0.0,
    "bilibili": [],
    "youtube": [],
    "douban": {"books": [], "movies": [], "games": []},
    "media_at": 0.0,
}


def _refresh_github() -> None:
    while True:
        try:
            github = collect_github()
            with _lock:
                _state["github"] = github
                _state["github_at"] = time.time()
        except Exception:
            pass
        time.sleep(GITHUB_INTERVAL)


def _refresh_media() -> None:
    while True:
        try:
            bili = collect_bilibili()
            with _lock:
                _state["bilibili"] = bili
                _state["media_at"] = time.time()
        except Exception:
            pass
        try:
            youtube = collect_youtube()
            with _lock:
                _state["youtube"] = youtube
                _state["media_at"] = time.time()
        except Exception:
            pass
        try:
            douban = collect_douban()
            with _lock:
                _state["douban"] = douban
                _state["media_at"] = time.time()
        except Exception:
            pass
        time.sleep(MEDIA_INTERVAL)


app = FastAPI()
threading.Thread(target=_refresh_github, daemon=True).start()
threading.Thread(target=_refresh_media, daemon=True).start()


def _svg_headers(*, live: bool = False) -> dict[str, str]:
    headers = {
        "Cache-Control": "s-maxage=1" if live else "public, max-age=0, s-maxage=60, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Access-Control-Allow-Origin": "*",
    }
    if live:
        headers["Refresh"] = "5"
        headers["CDN-Cache-Control"] = "no-store"
        headers["Cloudflare-CDN-Cache-Control"] = "no-store"
    return headers


def _svg(body: str, *, live: bool = False) -> Response:
    return Response(
        content=body,
        media_type="image/svg+xml; charset=utf-8",
        headers=_svg_headers(live=live),
    )


@app.get("/health")
def health():
    with _lock:
        ready = _state["github"] is not None
    return {"ok": ready}


@app.get("/api/profile.svg")
def profile_svg(theme: str = Query("dark")):
    theme = theme_name(theme)
    with _lock:
        github = _state["github"]
    if github is None:
        github = collect_github()
        with _lock:
            _state["github"] = github
            _state["github_at"] = time.time()
    return _svg(render_card(theme, github))


def _videos_payload() -> tuple[list[dict], list[dict]]:
    with _lock:
        bili = list(_state["bilibili"])
        youtube = list(_state["youtube"])
    if not bili:
        try:
            bili = collect_bilibili()
            with _lock:
                _state["bilibili"] = bili
                _state["media_at"] = time.time()
        except Exception:
            bili = []
    if not youtube:
        try:
            youtube = collect_youtube()
            with _lock:
                _state["youtube"] = youtube
                _state["media_at"] = time.time()
        except Exception:
            youtube = []
    return bili, youtube


@app.get("/api/videos.svg")
def videos_svg(theme: str = Query("dark")):
    bili, youtube = _videos_payload()
    return _svg(render_videos(theme, bili, youtube))


@app.get("/api/bilibili.svg")
def bilibili_svg(theme: str = Query("dark")):
    return videos_svg(theme)


@app.get("/api/youtube.svg")
def youtube_svg(theme: str = Query("dark")):
    return videos_svg(theme)


@app.get("/api/douban.svg")
def douban_svg(theme: str = Query("dark")):
    with _lock:
        board = {
            "books": list(_state["douban"]["books"]),
            "movies": list(_state["douban"]["movies"]),
            "games": list(_state["douban"]["games"]),
        }
    if not any(board.values()):
        try:
            board = collect_douban()
            with _lock:
                _state["douban"] = board
                _state["media_at"] = time.time()
        except Exception:
            board = {"books": [], "movies": [], "games": []}
    return _svg(render_douban(theme, board))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.app:app", host="0.0.0.0", port=PORT, reload=False)
