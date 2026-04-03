import datetime
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


def github_get(url: str, token: str | None = None):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "itgoyo-readme-bot")
    if token:
        req.add_header("Authorization", f"token {token}")

    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_latest_release_line(user: str, token: str | None = None) -> str:
    try:
        repos = github_get(
            f"https://api.github.com/users/{user}/repos?sort=updated&per_page=10", token
        )
    except Exception:
        return "- Shipping steady updates across open-source projects."

    release_candidates = []
    for repo in repos:
        if repo.get("fork"):
            continue
        releases_url = (
            f"https://api.github.com/repos/{user}/{repo['name']}/releases?per_page=1"
        )
        try:
            releases = github_get(releases_url, token)
        except Exception:
            continue
        if not releases:
            continue
        rel = releases[0]
        published_at = rel.get("published_at") or rel.get("created_at") or ""
        release_candidates.append(
            {
                "repo": repo["name"],
                "name": rel.get("name") or rel.get("tag_name") or "latest",
                "url": rel.get("html_url") or repo.get("html_url", ""),
                "published_at": published_at,
            }
        )

    if not release_candidates:
        return "- Shipping steady updates across open-source projects."

    release_candidates.sort(key=lambda x: x["published_at"], reverse=True)
    rel = release_candidates[0]
    return (
        f"- Shipping updates, latest: [{rel['repo']} · {rel['name']}]({rel['url']})."
    )


def fetch_recent_repos_line(user: str, token: str | None = None) -> str:
    try:
        events = github_get(
            f"https://api.github.com/users/{user}/events/public?per_page=50", token
        )
    except Exception:
        return "- Maintaining active repositories and long-term tooling projects."

    seen = []
    for event in events:
        repo = event.get("repo", {}).get("name", "")
        if not repo.startswith(f"{user}/"):
            continue
        repo_name = repo.split("/", 1)[1]
        if repo_name not in seen:
            seen.append(repo_name)
        if len(seen) >= 3:
            break

    if not seen:
        return "- Maintaining active repositories and long-term tooling projects."

    links = [f"[{name}](https://github.com/{user}/{name})" for name in seen]
    return "- Maintaining active projects: " + ", ".join(links) + "."


def fetch_latest_post_line() -> str:
    feed_urls = [
        "https://itgoyo.github.io/atom.xml",
        "https://itgoyo.github.io/rss.xml",
        "https://itgoyo.github.io/feed.xml",
    ]

    for feed_url in feed_urls:
        try:
            with urllib.request.urlopen(feed_url, timeout=8) as resp:
                xml_text = resp.read().decode("utf-8", errors="ignore")
            root = ET.fromstring(xml_text)

            # Atom
            entry = root.find("{http://www.w3.org/2005/Atom}entry")
            if entry is not None:
                title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                href = link_el.attrib.get("href", "") if link_el is not None else ""
                if title and href:
                    return f"- Writing and sharing notes, latest post: [{title}]({href})."

            # RSS
            item = root.find("channel/item")
            if item is not None:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if title and link:
                    return f"- Writing and sharing notes, latest post: [{title}]({link})."
        except Exception:
            continue

    return "- Writing and sharing practical notes on engineering, tools, and life."


def update_readme(readme_path: str, lines: list[str]):
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    block = "\n" + "\n".join(lines) + "\n"
    pattern = (
        r"(?<=<!--START_SECTION:now-building-->)[\s\S]*"
        r"(?=<!--END_SECTION:now-building-->)"
    )
    new_content = re.sub(pattern, block, content)

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def main():
    if len(sys.argv) != 4:
        print("Usage: updateNowBuilding.py <github_user> <token_or_dash> <readme_path>")
        sys.exit(1)

    user = sys.argv[1]
    token_raw = sys.argv[2].strip()
    token = None if token_raw == "-" else token_raw
    readme_path = sys.argv[3]

    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    lines = [
        fetch_latest_release_line(user, token),
        fetch_recent_repos_line(user, token),
        fetch_latest_post_line(),
        f"- Updated automatically on {today} (UTC).",
    ]

    update_readme(readme_path, lines)


if __name__ == "__main__":
    main()
