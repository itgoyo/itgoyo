"""Serve the profile card SVG. Spotify is polled every 10 seconds.

Env:
    USER_NAME
    ACCESS_TOKEN / GITHUB_TOKEN
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET
    SPOTIFY_REFRESH_TOKEN
    PORT  default 8080

Run:
    uvicorn server.app:app --host 0.0.0.0 --port 8080

Nginx:
    location /api/profile.svg {
        proxy_pass http://127.0.0.1:8080/api/profile.svg;
        proxy_hide_header Cache-Control;
        add_header Cache-Control "public, max-age=0, must-revalidate" always;
    }
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Query, Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from updateGithubStats import collect_github, fetch_spotify_tracks, render_card  # noqa: E402

SPOTIFY_INTERVAL = 10
GITHUB_INTERVAL = 1800
PORT = int(os.environ.get("PORT", "8080"))

_lock = threading.Lock()
_state = {
    "github": None,
    "tracks": [],
    "fetched_at": 0.0,
    "github_at": 0.0,
}


def _refresh_loop() -> None:
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


app = FastAPI()
_worker = threading.Thread(target=_refresh_loop, daemon=True)
_worker.start()


def _svg_headers() -> dict[str, str]:
    return {
        "Cache-Control": "public, max-age=0, s-maxage=10, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Access-Control-Allow-Origin": "*",
    }


@app.get("/health")
def health():
    with _lock:
        ready = _state["github"] is not None
    return {"ok": ready}


@app.get("/api/profile.svg")
def profile_svg(theme: str = Query("dark")):
    theme = "light" if theme.lower() == "light" else "dark"
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
    body = render_card(theme, github, tracks, fetched_at or time.time())
    return Response(content=body, media_type="image/svg+xml; charset=utf-8", headers=_svg_headers())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.app:app", host="0.0.0.0", port=PORT, reload=False)
