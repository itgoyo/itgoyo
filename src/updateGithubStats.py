"""Generate Andrew6rant-style GitHub stats SVGs from the current user's GitHub data."""
from __future__ import annotations

import datetime
import html
import os
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

import requests
from dateutil import relativedelta
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "img"
DARK_SVG = IMG_DIR / "github_stats_dark.svg"
LIGHT_SVG = IMG_DIR / "github_stats_light.svg"

USER_NAME = os.environ.get("USER_NAME") or os.environ.get("GITHUB_ACTOR") or "itgoyo"
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
ASCII_WIDTH = 38
ASCII_HEIGHT = 25
TOP_LANGUAGES = 4
THEMES = {
    "dark": {
        "bg": "#161b22",
        "fg": "#c9d1d9",
        "key": "#ffa657",
        "value": "#a5d6ff",
        "add": "#3fb950",
        "del": "#f85149",
        "cc": "#616e7f",
        "invert_ascii": True,
    },
    "light": {
        "bg": "#f6f8fa",
        "fg": "#24292f",
        "key": "#953800",
        "value": "#0a3069",
        "add": "#1a7f37",
        "del": "#cf222e",
        "cc": "#8b949e",
        "invert_ascii": False,
    },
}


def headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "itgoyo-github-stats",
    }
    if ACCESS_TOKEN:
        h["Authorization"] = f"token {ACCESS_TOKEN}"
    return h


def github_get(url: str) -> dict | list:
    resp = requests.get(url, headers=headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def graphql(query: str, variables: dict) -> dict:
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=headers(),
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
    created = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(
        tzinfo=None
    )
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
    data = graphql(query, {"login": USER_NAME})
    return int(data["user"]["repositories"]["totalCount"])


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
        data = graphql(
            query,
            {
                "login": USER_NAME,
                "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        col = data["user"]["contributionsCollection"]
        total += int(col["totalCommitContributions"]) + int(col["restrictedContributionsCount"])
        cursor = nxt
    return total


LANG_ALIAS = {
    "JavaScript": "JS",
    "TypeScript": "TS",
    "Objective-C": "ObjC",
}


def top_languages(repos: list[dict]) -> str:
    langs = [
        repo["language"]
        for repo in repos
        if not repo.get("fork") and repo.get("language")
    ]
    if not langs:
        return "Kotlin, Python, Java, JS"
    ranked = [LANG_ALIAS.get(name, name) for name, _ in Counter(langs).most_common(TOP_LANGUAGES)]
    return ", ".join(ranked)


def fetch_loc(repos: list[dict]) -> tuple[int, int, int] | None:
    top = sorted(
        [repo for repo in repos if not repo.get("fork")],
        key=lambda repo: int(repo.get("stargazers_count") or 0),
        reverse=True,
    )[:15]
    added = 0
    deleted = 0
    found = False
    for repo in top:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        try:
            data = github_get(f"https://api.github.com/repos/{full_name}/stats/contributors")
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for contributor in data:
            author = (contributor.get("author") or {}).get("login") or ""
            if author.lower() != USER_NAME.lower():
                continue
            found = True
            for week in contributor.get("weeks") or []:
                added += int(week.get("a") or 0)
                deleted += int(week.get("d") or 0)
    if not found:
        return None
    return added, deleted, added - deleted


def avatar_to_ascii(avatar_url: str, invert: bool) -> list[str]:
    resp = requests.get(avatar_url, headers={"User-Agent": "itgoyo-github-stats"}, timeout=20)
    resp.raise_for_status()
    img = Image.open(BytesIO(resp.content)).convert("L")
    img = img.resize((ASCII_WIDTH, ASCII_HEIGHT))
    chars = "@%#*+=-:. "
    lines = []
    last = len(chars) - 1
    for y in range(ASCII_HEIGHT):
        row = []
        for x in range(ASCII_WIDTH):
            pixel = img.getpixel((x, y))
            idx = ((last - pixel * last // 255) if invert else (pixel * last // 255))
            row.append(chars[idx])
        lines.append("".join(row).rstrip())
    return lines


def dotted_line(key: str, value: str, width: int = 56) -> tuple[str, str, str]:
    prefix = f". {key}:"
    value = str(value)
    gap = width - len(prefix) - len(value)
    if gap <= 2:
        dots = " "
    else:
        dots = " " + "." * (gap - 2) + " "
    return key, dots, value


def tspan_row(y: int, key: str, value: str, width: int = 56) -> str:
    k, dots, v = dotted_line(key, value, width)
    return (
        f'<tspan x="390" y="{y}" class="cc">. </tspan>'
        f'<tspan class="key">{html.escape(k)}</tspan>:'
        f'<tspan class="cc">{html.escape(dots)}</tspan>'
        f'<tspan class="value">{html.escape(v)}</tspan>'
    )


def tspan_blank(y: int) -> str:
    return f'<tspan x="390" y="{y}" class="cc">. </tspan>'


def tspan_header(y: int, title: str) -> str:
    bar = "─" * max(8, 48 - len(title))
    return f'<tspan x="390" y="{y}">{html.escape(title)} {bar}</tspan>'


def build_svg(theme_name: str, ascii_lines: list[str], profile: dict, stats: dict) -> str:
    theme = THEMES[theme_name]
    left = []
    for i, line in enumerate(ascii_lines):
        y = 30 + i * 20
        left.append(
            f'<tspan x="15" y="{y}">{html.escape(line.ljust(ASCII_WIDTH))}</tspan>'
        )

    y = 30
    right = [f'<tspan x="390" y="{y}">{html.escape(profile["title"])}  {"─" * 40}</tspan>']
    rows = [
        ("OS", profile["os"]),
        ("Uptime", profile["uptime"]),
        ("Host", profile["host"]),
        ("Kernel", profile["kernel"]),
        ("IDE", profile["ide"]),
        None,
        ("Languages.Programming", profile["lang_prog"]),
        ("Languages.Computer", profile["lang_comp"]),
        ("Languages.Real", profile["lang_real"]),
        None,
        ("Hobbies.Software", profile["hobby_sw"]),
        ("Hobbies.Hardware", profile["hobby_hw"]),
        None,
        "Contact",
        ("Blog", profile["blog"]),
        ("X", profile["x"]),
        ("GitHub", profile["github"]),
        None,
        "GitHub Stats",
    ]
    y = 50
    for row in rows:
        if row is None:
            right.append(tspan_blank(y))
        elif isinstance(row, str):
            right.append(tspan_header(y, f"- {row}"))
        else:
            right.append(tspan_row(y, row[0], row[1]))
        y += 20

    loc = stats["loc"]
    loc_add = stats["loc_add"]
    loc_del = stats["loc_del"]
    right.append(
        f'<tspan x="390" y="{y}" class="cc">. </tspan>'
        f'<tspan class="key">Repos</tspan>:'
        f'<tspan class="cc" id="repo_data_dots"> .... </tspan>'
        f'<tspan class="value" id="repo_data">{html.escape(comma(stats["repos"]))}</tspan>'
        f' {{<tspan class="key">Contributed</tspan>: '
        f'<tspan class="value" id="contrib_data">{html.escape(comma(stats["contributed"]))}</tspan>}} | '
        f'<tspan class="key">Stars</tspan>:'
        f'<tspan class="cc" id="star_data_dots"> ...... </tspan>'
        f'<tspan class="value" id="star_data">{html.escape(comma(stats["stars"]))}</tspan>'
    )
    y += 20
    right.append(
        f'<tspan x="390" y="{y}" class="cc">. </tspan>'
        f'<tspan class="key">Commits</tspan>:'
        f'<tspan class="cc" id="commit_data_dots"> .............. </tspan>'
        f'<tspan class="value" id="commit_data">{html.escape(comma(stats["commits"]))}</tspan>'
        f' | <tspan class="key">Followers</tspan>:'
        f'<tspan class="cc" id="follower_data_dots"> ...... </tspan>'
        f'<tspan class="value" id="follower_data">{html.escape(comma(stats["followers"]))}</tspan>'
    )
    y += 20
    right.append(
        f'<tspan x="390" y="{y}" class="cc">. </tspan>'
        f'<tspan class="key">Lines of Code on GitHub</tspan>:'
        f'<tspan class="cc" id="loc_data_dots"> . </tspan>'
        f'<tspan class="value" id="loc_data">{html.escape(comma(loc))}</tspan>'
        f' ( <tspan class="addColor" id="loc_add">{html.escape(comma(loc_add))}</tspan>'
        f'<tspan class="addColor">++</tspan>, '
        f'<tspan class="delColor" id="loc_del">{html.escape(comma(loc_del))}</tspan>'
        f'<tspan class="delColor">--</tspan> )'
    )

    return f"""<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="985px" height="530px" font-size="16px">
<style>
@font-face {{
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}}
.key {{fill: {theme['key']};}}
.value {{fill: {theme['value']};}}
.addColor {{fill: {theme['add']};}}
.delColor {{fill: {theme['del']};}}
.cc {{fill: {theme['cc']};}}
text, tspan {{white-space: pre;}}
</style>
<rect width="985px" height="530px" fill="{theme['bg']}" rx="15"/>
<text x="15" y="30" fill="{theme['fg']}" class="ascii">
{''.join(left)}
</text>
<text x="390" y="30" fill="{theme['fg']}">
{''.join(right)}
</text>
</svg>
"""


def main() -> int:
    user = fetch_user()
    repos = fetch_repos()
    owned = [r for r in repos if not r.get("fork")]
    stars = sum(int(r.get("stargazers_count") or 0) for r in owned)
    try:
        contributed = fetch_contributed_count()
    except Exception:
        contributed = len(owned)
    try:
        commits = fetch_commit_count(user["created_at"])
    except Exception:
        commits = None
    try:
        loc_data = fetch_loc(owned)
    except Exception:
        loc_data = None

    profile = {
        "title": f"{user.get('login') or USER_NAME}@github",
        "os": "macOS, Linux, Windows",
        "uptime": account_uptime(user["created_at"]),
        "host": user.get("location") or "China",
        "kernel": "Product engineer",
        "ide": "Cursor, VS Code, Android Studio",
        "lang_prog": top_languages(owned),
        "lang_comp": "Markdown, XML, Shell",
        "lang_real": "Chinese, English",
        "hobby_sw": "Homelab, Dev tools, Writing",
        "hobby_hw": "Mini PCs, NAS, Cameras",
        "blog": (user.get("blog") or "https://itgoyo.github.io").replace("https://", ""),
        "x": user.get("twitter_username") or USER_NAME,
        "github": user.get("login") or USER_NAME,
    }
    stats = {
        "repos": user.get("public_repos") or len(owned),
        "contributed": contributed if contributed is not None else len(owned),
        "stars": stars,
        "commits": commits if commits is not None else "—",
        "followers": user.get("followers") or 0,
        "loc": loc_data[2] if loc_data else "—",
        "loc_add": loc_data[0] if loc_data else "—",
        "loc_del": loc_data[1] if loc_data else "—",
    }

    avatar_url = user.get("avatar_url") or f"https://github.com/{USER_NAME}.png"
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    DARK_SVG.write_text(
        build_svg("dark", avatar_to_ascii(avatar_url, True), profile, stats),
        encoding="utf-8",
    )
    LIGHT_SVG.write_text(
        build_svg("light", avatar_to_ascii(avatar_url, False), profile, stats),
        encoding="utf-8",
    )
    print(f"Wrote {DARK_SVG.relative_to(ROOT)} and {LIGHT_SVG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
