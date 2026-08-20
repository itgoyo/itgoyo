"""Generate a terminal-style GitHub + Spotify SVG for the profile README.

Spotify (optional, GitHub Actions secrets):
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET
    SPOTIFY_REFRESH_TOKEN
Scopes: user-read-currently-playing user-read-recently-played
Get a refresh token with: python src/spotifyAuth.py
"""
from __future__ import annotations

import base64
import datetime
import html
import os
import sys
import time
from collections import Counter
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dateutil import relativedelta
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
IMG_DIR = ROOT / "img"
DARK_SVG = IMG_DIR / "github_stats_dark.svg"
LIGHT_SVG = IMG_DIR / "github_stats_light.svg"

USER_NAME = os.environ.get("USER_NAME") or os.environ.get("GITHUB_ACTOR") or "itgoyo"
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")
TZ = ZoneInfo("Asia/Shanghai")
TOP_LANGUAGES = 4
TRACK_LIMIT = 5
LANG_ALIAS = {"JavaScript": "JS", "TypeScript": "TS", "Objective-C": "ObjC"}

THEMES = {
    "dark": {
        "bg": "#2e3440",
        "panel": "#3b4252",
        "border": "#c8c3e0",
        "label": "#d08770",
        "text": "#eceff4",
        "muted": "#7b88a1",
        "highlight": "#1DB954",
        "progress": "#1DB954",
        "prompt_a": "#4c566a",
        "prompt_b": "#81a1c1",
        "prompt_c": "#d08770",
        "capsule": "#eceff4",
        "capsule_text": "#2e3440",
        "palette": ["#bf616a", "#d08770", "#ebcb8b", "#a3be8c", "#88c0d0", "#81a1c1", "#b48ead", "#eceff4"],
    },
    "light": {
        "bg": "#eceff4",
        "panel": "#e5e9f0",
        "border": "#81a1c1",
        "label": "#bf616a",
        "text": "#2e3440",
        "muted": "#4c566a",
        "highlight": "#1DB954",
        "progress": "#1DB954",
        "prompt_a": "#4c566a",
        "prompt_b": "#81a1c1",
        "prompt_c": "#d08770",
        "capsule": "#2e3440",
        "capsule_text": "#eceff4",
        "palette": ["#bf616a", "#d08770", "#ebcb8b", "#a3be8c", "#88c0d0", "#81a1c1", "#b48ead", "#4c566a"],
    },
}


def github_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "itgoyo-github-stats"}
    if ACCESS_TOKEN:
        h["Authorization"] = f"token {ACCESS_TOKEN}"
    return h


def github_get(url: str):
    resp = requests.get(url, headers=github_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def graphql(query: str, variables: dict) -> dict:
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=github_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def format_plural(unit: int) -> str:
    return "s" if unit != 1 else ""


def account_uptime(created_at: str) -> str:
    created = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
    diff = relativedelta.relativedelta(datetime.datetime.utcnow(), created)
    return "{} {}, {} {}, {} {}".format(
        diff.years,
        "year" + format_plural(diff.years),
        diff.months,
        "month" + format_plural(diff.months),
        diff.days,
        "day" + format_plural(diff.days),
    )


def comma(n) -> str:
    if n in (None, "", "—"):
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def fetch_user() -> dict:
    return github_get(f"https://api.github.com/users/{USER_NAME}")


def fetch_repos() -> list[dict]:
    repos = []
    page = 1
    while True:
        batch = github_get(
            f"https://api.github.com/users/{USER_NAME}/repos?per_page=100&page={page}&type=owner&sort=updated"
        )
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_contributed_count() -> int | None:
    if not ACCESS_TOKEN:
        return None
    query = """
    query ($login: String!) {
      user(login: $login) {
        repositories(first: 1, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
          totalCount
        }
      }
    }
    """
    return int(graphql(query, {"login": USER_NAME})["user"]["repositories"]["totalCount"])


def fetch_commit_count(created_at: str) -> int | None:
    if not ACCESS_TOKEN:
        return None
    query = """
    query ($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    total = 0
    cursor = start
    while cursor < now:
        nxt = min(cursor.replace(year=cursor.year + 1), now)
        col = graphql(
            query,
            {
                "login": USER_NAME,
                "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )["user"]["contributionsCollection"]
        total += int(col["totalCommitContributions"]) + int(col["restrictedContributionsCount"])
        cursor = nxt
    return total


def top_languages(repos: list[dict]) -> str:
    langs = [repo["language"] for repo in repos if not repo.get("fork") and repo.get("language")]
    if not langs:
        return "Kotlin, Python, Java, JS"
    ranked = [LANG_ALIAS.get(name, name) for name, _ in Counter(langs).most_common(TOP_LANGUAGES)]
    return ", ".join(ranked)


def avatar_data_uri(avatar_url: str, size: int = 280) -> str:
    url = avatar_url
    sep = "&" if "?" in url else "?"
    resp = requests.get(f"{url}{sep}s={size}", headers={"User-Agent": "itgoyo-github-stats"}, timeout=20)
    resp.raise_for_status()
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def ms_to_duration(ms: int) -> str:
    seconds = max(0, int(ms) // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


_SPOTIFY_TOKEN = {"value": None, "exp": 0}


def parse_track(item: dict, is_current: bool = False, progress_ms: int | None = None, is_playing: bool = False) -> dict | None:
    track = item.get("item") if "item" in item and is_current else item.get("track") or item
    if not track or track.get("type") not in (None, "track"):
        return None
    artists = ", ".join(a.get("name", "") for a in (track.get("artists") or []) if a.get("name"))
    name = track.get("name") or "Unknown"
    duration_ms = int(track.get("duration_ms") or 0)
    return {
        "id": track.get("id") or f"{artists}-{name}",
        "label": f"{artists} - {name}" if artists else name,
        "duration": ms_to_duration(duration_ms),
        "duration_ms": duration_ms,
        "progress_ms": progress_ms,
        "current": is_current,
        "is_playing": bool(is_playing and is_current),
    }


def spotify_token() -> str | None:
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN):
        return None
    now = time.time()
    if _SPOTIFY_TOKEN["value"] and now < _SPOTIFY_TOKEN["exp"] - 60:
        return _SPOTIFY_TOKEN["value"]
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "refresh_token", "refresh_token": SPOTIFY_REFRESH_TOKEN},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    _SPOTIFY_TOKEN["value"] = token
    _SPOTIFY_TOKEN["exp"] = now + int(data.get("expires_in") or 3600)
    return token


def fetch_spotify_tracks() -> list[dict]:
    token = spotify_token()
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    current = None
    try:
        now = requests.get(
            "https://api.spotify.com/v1/me/player/currently-playing",
            headers=headers,
            timeout=20,
        )
        if now.status_code == 200 and now.content:
            payload = now.json()
            if payload.get("item"):
                current = parse_track(
                    payload,
                    True,
                    payload.get("progress_ms"),
                    payload.get("is_playing", False),
                )
    except Exception:
        current = None

    recent_raw = []
    try:
        recent = requests.get(
            "https://api.spotify.com/v1/me/player/recently-played",
            headers=headers,
            params={"limit": TRACK_LIMIT},
            timeout=20,
        )
        recent.raise_for_status()
        recent_raw = [
            parse_track(row, False)
            for row in (recent.json().get("items") or [])
        ]
        recent_raw = [row for row in recent_raw if row]
    except Exception:
        recent_raw = []

    current_id = current["id"] if current else None
    history = [row for row in recent_raw if row["id"] != current_id]
    if current:
        older = list(reversed(history[: TRACK_LIMIT - 1]))
        return older + [current]
    return list(reversed(history[:TRACK_LIMIT]))


def truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def kv_line(x: int, y: int, key: str, value: str, theme: dict) -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="14">'
        f'<tspan fill="{theme["label"]}">{html.escape(key)}</tspan>'
        f'<tspan fill="{theme["text"]}">{html.escape(value)}</tspan>'
        f"</text>"
    )


def build_svg(theme_name: str, avatar_uri: str, profile: dict, stats: dict, tracks: list[dict]) -> str:
    theme = THEMES[theme_name]
    now = datetime.datetime.now(TZ)
    stamp = now.strftime("%Y-%m-%d  %H:%M")
    login = profile["github"]

    info = [
        kv_line(326, 80, "OS: ", profile["os"], theme),
        kv_line(326, 100, "Host: ", profile["host"], theme),
        kv_line(326, 120, "Uptime: ", profile["uptime"], theme),
        kv_line(326, 140, "Lang: ", profile["lang_prog"], theme),
        kv_line(
            326,
            160,
            "GitHub: ",
            f"{comma(stats['repos'])} repos · {comma(stats['stars'])} stars · {comma(stats['followers'])} followers",
            theme,
        ),
    ]

    shown = tracks[-TRACK_LIMIT:]
    if not shown:
        shown = [
            {"label": "—", "duration": "--:--", "current": False, "duration_ms": 0, "progress_ms": None}
            for _ in range(TRACK_LIMIT - 1)
        ] + [
            {
                "label": "Spotify offline",
                "duration": "--:--",
                "current": True,
                "duration_ms": 0,
                "progress_ms": 0,
            }
        ]
    track_y0 = 204
    dash = "-" * 16
    track_lines = [
        (
            f'<text x="636" y="184" text-anchor="middle" font-size="13">'
            f'<tspan fill="{theme["muted"]}">{dash}  </tspan>'
            f'<tspan fill="#1DB954">Spotify</tspan>'
            f'<tspan fill="{theme["muted"]}"> recently played  {dash}</tspan>'
            f"</text>"
        )
    ]
    if shown:
        for i, track in enumerate(shown):
            y = track_y0 + i * 22
            current_row = bool(track.get("current") or i == len(shown) - 1)
            color = theme["highlight"] if current_row else theme["text"]
            prefix = "▶ " if current_row else "  "
            label = truncate(prefix + track["label"], 50)
            track_lines.append(
                f'<text x="326" y="{y}" font-size="14" fill="{color}">{html.escape(label)}</text>'
                f'<text x="940" y="{y}" font-size="14" fill="{color}" text-anchor="end">{html.escape(track["duration"])}</text>'
            )
    else:
        track_lines.append(
            f'<text x="326" y="{track_y0}" font-size="14" fill="{theme["muted"]}">Spotify offline</text>'
        )

    current = next((t for t in shown if t.get("current")), shown[-1] if shown else None)
    progress = 0.0
    if current and current.get("duration_ms"):
        raw = current.get("progress_ms")
        progress = min(1.0, max(0.0, (raw if raw is not None else current["duration_ms"]) / current["duration_ms"]))
    bar_x, bar_w, bar_y = 326, 614, 318
    knob_x = bar_x + int(bar_w * progress)

    palette = []
    for i, color in enumerate(theme["palette"]):
        palette.append(f'<rect x="{326 + i * 22}" y="334" width="16" height="16" rx="2" fill="{color}"/>')

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="980" height="420" viewBox="0 0 980 420" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
  <title>{html.escape(login)} GitHub terminal</title>
  <rect width="980" height="420" rx="18" fill="{theme["bg"]}"/>
  <rect x="16" y="16" width="276" height="340" rx="14" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="2"/>
  <clipPath id="avatarClip"><rect x="24" y="54" width="260" height="260" rx="10"/></clipPath>
  <image href="{avatar_uri}" xlink:href="{avatar_uri}" x="24" y="54" width="260" height="260" clip-path="url(#avatarClip)" preserveAspectRatio="xMidYMid slice"/>
  <rect x="308" y="16" width="656" height="340" rx="14" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="2"/>
  <text x="636" y="44" text-anchor="middle" font-size="16" fill="{theme["text"]}">&lt; {html.escape(login)} &gt;</text>
  <text x="636" y="60" text-anchor="middle" font-size="12" fill="{theme["muted"]}">--------------------------------</text>
  {''.join(info)}
  {''.join(track_lines)}
  <line x1="{bar_x}" y1="{bar_y}" x2="{bar_x + bar_w}" y2="{bar_y}" stroke="{theme["muted"]}" stroke-width="3" stroke-linecap="round"/>
  <line x1="{bar_x}" y1="{bar_y}" x2="{knob_x}" y2="{bar_y}" stroke="{theme["progress"]}" stroke-width="3" stroke-linecap="round"/>
  <circle cx="{knob_x}" cy="{bar_y}" r="5" fill="{theme["progress"]}"/>
  {''.join(palette)}
  <path d="M16 372 L78 372 L90 404 L16 404 Z" fill="{theme["prompt_a"]}"/>
  <path d="M70 372 L148 372 L160 404 L82 404 Z" fill="{theme["prompt_b"]}"/>
  <path d="M140 372 L248 372 L260 404 L152 404 Z" fill="{theme["prompt_c"]}"/>
  <text x="28" y="394" font-size="13" fill="{theme["text"]}">gh</text>
  <text x="92" y="394" font-size="13" fill="{theme["bg"]}">~/</text>
  <text x="164" y="394" font-size="13" fill="{theme["bg"]}">{html.escape(login)}</text>
  <text x="272" y="394" font-size="16" fill="{theme["text"]}">_</text>
  <rect x="668" y="376" width="296" height="28" rx="14" fill="{theme["capsule"]}"/>
  <text x="816" y="395" text-anchor="middle" font-size="13" fill="{theme["capsule_text"]}">{stamp}</text>
</svg>
"""


def apply_live_progress(tracks: list[dict], fetched_at: float) -> list[dict]:
    out = [dict(track) for track in tracks]
    if not out:
        return out
    current = out[-1]
    if current.get("is_playing") and current.get("duration_ms"):
        elapsed = int((time.time() - fetched_at) * 1000)
        current["progress_ms"] = min(
            int(current["duration_ms"]),
            int(current.get("progress_ms") or 0) + max(0, elapsed),
        )
    return out


def collect_github() -> dict:
    user = fetch_user()
    repos = fetch_repos()
    owned = [repo for repo in repos if not repo.get("fork")]
    stars = sum(int(repo.get("stargazers_count") or 0) for repo in owned)
    profile = {
        "os": "macOS, Linux, Windows",
        "uptime": account_uptime(user["created_at"]),
        "host": user.get("location") or "China",
        "lang_prog": top_languages(owned),
        "github": user.get("login") or USER_NAME,
    }
    stats = {
        "repos": user.get("public_repos") or len(owned),
        "stars": stars,
        "followers": user.get("followers") or 0,
    }
    avatar_url = user.get("avatar_url") or f"https://github.com/{USER_NAME}.png"
    return {
        "profile": profile,
        "stats": stats,
        "avatar_uri": avatar_data_uri(avatar_url),
    }


def render_card(theme: str, github: dict, tracks: list[dict], fetched_at: float | None = None) -> str:
    live = apply_live_progress(tracks, fetched_at or time.time())
    if live:
        live[-1]["current"] = True
    return build_svg(theme, github["avatar_uri"], github["profile"], github["stats"], live)


def main() -> int:
    github = collect_github()
    try:
        tracks = fetch_spotify_tracks()
    except Exception:
        tracks = []
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    DARK_SVG.write_text(render_card("dark", github, tracks), encoding="utf-8")
    LIGHT_SVG.write_text(render_card("light", github, tracks), encoding="utf-8")
    print(f"Wrote {DARK_SVG.relative_to(ROOT)} and {LIGHT_SVG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
