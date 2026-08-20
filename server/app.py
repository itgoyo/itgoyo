"""Serve live SVG cards for the profile README.

Env: USER_NAME, ACCESS_TOKEN, SPOTIFY_*, PORT
     BILIBILI_COOKIE (optional)

Run:
    python -m uvicorn server.app:app --host 0.0.0.0 --port 8080

Paths:
    /api/profile.svg
    /api/bilibili.svg
    /api/youtube.svg
    /api/douban.svg
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
    render_bilibili,
    render_douban,
    render_youtube,
    theme_name,
)
from updateGithubStats import collect_github, fetch_spotify_tracks, render_card  # noqa: E402

SPOTIFY_INTERVAL = 10
GITHUB_INTERVAL = 1800
MEDIA_INTERVAL = 1800
PORT = int(os.environ.get("PORT", "8080"))

_lock = threading.Lock()
_state = {
    "github": None,
    "tracks": [],
    "fetched_at": 0.0,
    "github_at": 0.0,
    "bilibili": [],
    "youtube": [],
    "douban": {"books": [], "movies": [], "games": []},
    "media_at": 0.0,
}


def _refresh_github_spotify() -> None:
    while True:
        now = time.time()
        with _lock:
            github = _state["github"]
            github_at = _state["github_at"]
        if github is None or now - github_at > GITHUB_INTERVAL:
            try:
                github = collect_github()
                with _lock:
                    _state["github"] = github
                    _state["github_at"] = time.time()
            except Exception:
                pass
        try:
            tracks = fetch_spotify_tracks()
        except Exception:
            with _lock:
                tracks = list(_state["tracks"])
        with _lock:
            _state["tracks"] = tracks
            _state["fetched_at"] = time.time()
        time.sleep(SPOTIFY_INTERVAL)


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
threading.Thread(target=_refresh_github_spotify, daemon=True).start()
threading.Thread(target=_refresh_media, daemon=True).start()


def _svg_headers() -> dict[str, str]:
    return {
        "Cache-Control": "public, max-age=0, s-maxage=10, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Access-Control-Allow-Origin": "*",
    }


def _svg(body: str) -> Response:
    return Response(content=body, media_type="image/svg+xml; charset=utf-8", headers=_svg_headers())


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
        tracks = list(_state["tracks"])
        fetched_at = _state["fetched_at"]
    if github is None:
        github = collect_github()
        with _lock:
            _state["github"] = github
            _state["github_at"] = time.time()
    if fetched_at <= 0:
        try:
            tracks = fetch_spotify_tracks()
        except Exception:
            tracks = []
        fetched_at = time.time()
        with _lock:
            _state["tracks"] = tracks
            _state["fetched_at"] = fetched_at
    return _svg(render_card(theme, github, tracks, fetched_at or time.time()))


@app.get("/api/bilibili.svg")
def bilibili_svg(theme: str = Query("dark")):
    with _lock:
        items = list(_state["bilibili"])
    if not items:
        try:
            items = collect_bilibili()
            with _lock:
                _state["bilibili"] = items
                _state["media_at"] = time.time()
        except Exception:
            items = []
    return _svg(render_bilibili(theme, items))


@app.get("/api/youtube.svg")
def youtube_svg(theme: str = Query("dark")):
    with _lock:
        items = list(_state["youtube"])
    if not items:
        try:
            items = collect_youtube()
            with _lock:
                _state["youtube"] = items
                _state["media_at"] = time.time()
        except Exception:
            items = []
    return _svg(render_youtube(theme, items))


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
