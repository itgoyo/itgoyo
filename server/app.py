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
from updateGithubStats import (  # noqa: E402
    collect_github,
    fetch_currently_playing,
    fetch_recently_played,
    merge_spotify_tracks,
    render_card,
)

SPOTIFY_INTERVAL = 5
SPOTIFY_RECENT_INTERVAL = 30
GITHUB_INTERVAL = 1800
MEDIA_INTERVAL = 1800
PORT = int(os.environ.get("PORT", "8080"))

_lock = threading.Lock()
_state = {
    "github": None,
    "tracks": [],
    "fetched_at": 0.0,
    "github_at": 0.0,
    "recent_at": 0.0,
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
            current = fetch_currently_playing()
            now = time.time()
            with _lock:
                prev = list(_state["tracks"])
                recent_at = _state["recent_at"]
            if now - recent_at > SPOTIFY_RECENT_INTERVAL or not prev:
                recent = list(reversed(fetch_recently_played()))
                recent_at = now
            else:
                recent = prev
            tracks = merge_spotify_tracks(current, recent)
        except Exception:
            time.sleep(SPOTIFY_INTERVAL)
            continue
        with _lock:
            _state["tracks"] = tracks
            _state["fetched_at"] = time.time()
            _state["recent_at"] = recent_at
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


def _svg_headers(*, live: bool = False) -> dict[str, str]:
    headers = {
        "Cache-Control": (
            "public, max-age=0, s-maxage=5, must-revalidate"
            if live
            else "public, max-age=0, s-maxage=60, must-revalidate"
        ),
        "Pragma": "no-cache",
        "Expires": "0",
        "Access-Control-Allow-Origin": "*",
    }
    if live:
        headers["Refresh"] = "5"
    return headers


def _svg(body: str, *, live: bool = False) -> Response:
    return Response(
        content=body,
        media_type="image/svg+xml; charset=utf-8",
        headers=_svg_headers(live=live),
    )


def _live_spotify() -> tuple[list[dict], float | None]:
    with _lock:
        cached = list(_state["tracks"])
        cached_at = _state["fetched_at"]
    try:
        current = fetch_currently_playing()
    except Exception:
        return cached, cached_at or None
    tracks = merge_spotify_tracks(current, cached)
    fetched_at = time.time()
    with _lock:
        _state["tracks"] = tracks
        _state["fetched_at"] = fetched_at
    return tracks, fetched_at


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
    tracks, fetched_at = _live_spotify()
    return _svg(render_card(theme, github, tracks, fetched_at), live=True)


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
