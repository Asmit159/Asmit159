#!/usr/bin/env python3
"""
Regenerates README.md as a "neofetch"-style profile card:
  - left column : ASCII art rendered from the user's GitHub avatar
  - right column: live stats pulled from the GitHub REST/GraphQL API
                  + static fields from profile.yml

Run locally:  GITHUB_TOKEN=xxx python3 scripts/update_readme.py
In CI:        the workflow supplies GITHUB_TOKEN automatically.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from ascii_magic import AsciiArt

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profile.yml"
README_PATH = ROOT / "README.md"
LOC_CACHE_PATH = ROOT / "scripts" / ".loc_cache.json"

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"


def gh_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def fetch_user(session: requests.Session, username: str) -> dict:
    r = session.get(f"{API}/users/{username}")
    r.raise_for_status()
    return r.json()


def fetch_all_repos(session: requests.Session, username: str) -> list:
    repos, page = [], 1
    while True:
        r = session.get(
            f"{API}/users/{username}/repos",
            params={"per_page": 100, "page": page, "type": "owner"},
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos


def fetch_contributed_repo_count(session: requests.Session, username: str) -> int:
    """Repos the user has contributed to (owned + external), via GraphQL."""
    query = """
    query($login: String!) {
      user(login: $login) {
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST]) {
          totalCount
        }
      }
    }
    """
    r = session.post(GRAPHQL, json={"query": query, "variables": {"login": username}})
    if r.status_code != 200:
        return 0
    data = r.json()
    return (
        data.get("data", {})
        .get("user", {})
        .get("repositoriesContributedTo", {})
        .get("totalCount", 0)
    )


def fetch_total_commits(session: requests.Session, username: str) -> int:
    """Approximate total commit count via the commit search API (default branches only)."""
    r = session.get(f"{API}/search/commits", params={"q": f"author:{username}"})
    if r.status_code != 200:
        return 0
    return r.json().get("total_count", 0)


def compute_uptime(created_at: str) -> str:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta_days = (now - created).days
    years, remainder = divmod(delta_days, 365)
    months, days = divmod(remainder, 30)
    return f"{years} years, {months} months, {days} days"


def load_loc_cache() -> dict:
    if LOC_CACHE_PATH.exists():
        return json.loads(LOC_CACHE_PATH.read_text())
    return {}


def save_loc_cache(cache: dict) -> None:
    LOC_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def compute_lines_of_code(username: str, repos: list, token: str, max_repos: int = 30) -> tuple:
    """
    Shallow-clones owned, non-fork repos and sums `git log --numstat`.
    Caches per-repo results keyed by the repo's latest pushed_at timestamp,
    so unchanged repos aren't re-cloned on every run.
    """
    cache = load_loc_cache()
    total_added, total_deleted = 0, 0

    candidates = [r for r in repos if not r.get("fork")][:max_repos]

    with tempfile.TemporaryDirectory() as tmp:
        for repo in candidates:
            name = repo["name"]
            pushed_at = repo.get("pushed_at", "")
            cache_key = f"{name}:{pushed_at}"

            if cache_key in cache:
                added, deleted = cache[cache_key]
                total_added += added
                total_deleted += deleted
                continue

            clone_url = repo["clone_url"].replace(
                "https://", f"https://x-access-token:{token}@"
            )
            dest = Path(tmp) / name
            try:
                subprocess.run(
                    ["git", "clone", "--quiet", "--depth", "500", clone_url, str(dest)],
                    check=True,
                    timeout=90,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                result = subprocess.run(
                    ["git", "-C", str(dest), "log", "--numstat", "--pretty=tformat:"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                added = deleted = 0
                for line in result.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                        added += int(parts[0])
                        deleted += int(parts[1])
                cache[cache_key] = (added, deleted)
                total_added += added
                total_deleted += deleted
            except Exception as e:
                print(f"  [skip] {name}: {e}", file=sys.stderr)
            finally:
                subprocess.run(["rm", "-rf", str(dest)])

    save_loc_cache(cache)
    return total_added, total_deleted


def generate_ascii_art(avatar_url: str, columns: int, monochrome: bool) -> str:
    resp = requests.get(avatar_url, timeout=30)
    resp.raise_for_status()
    img_bytes = io.BytesIO(resp.content)
    tmp_path = Path(tempfile.mkstemp(suffix=".png")[1])
    tmp_path.write_bytes(img_bytes.getvalue())
    try:
        art = AsciiArt.from_image(str(tmp_path))
        return art.to_ascii(columns=columns, monochrome=monochrome)
    finally:
        tmp_path.unlink(missing_ok=True)


def pad_lines(text: str, width: int) -> list:
    lines = text.rstrip("\n").split("\n")
    return [line.ljust(width) for line in lines]


def render_readme(profile: dict, stats: dict, ascii_lines: list) -> str:
    info_lines = [
        f"{stats['username']}@github",
        "─" * 40,
        f"OS: ................ {profile['system']['os']}",
        f"Uptime: ............ {stats['uptime']}",
        f"Host: ............... {profile['system']['host']}",
        f"Kernel: ............. {profile['system']['kernel']}",
        f"IDE: ................ {profile['system']['ide']}",
        "",
        f"Languages.Programming: {profile['languages']['programming']}",
        f"Languages.Computer: .. {profile['languages']['computer']}",
        f"Languages.Human: ..... {profile['languages']['human']}",
        "",
        f"Hobbies.Software: .... {profile['hobbies']['software']}",
        f"Hobbies.Hardware: .... {profile['hobbies']['hardware']}",
        "",
        "─ Contact " + "─" * 30,
        f"Email.Personal: ...... {profile['contact']['email_personal']}",
        f"Email.Work: .......... {profile['contact']['email_work']}",
        f"LinkedIn: ............ {profile['contact']['linkedin']}",
        f"Discord: ............. {profile['contact']['discord']}",
        f"Website: ............. {profile['contact']['website']}",
        "",
        "─ GitHub Stats " + "─" * 25,
        f"Repos: .......... {stats['repo_count']}  (Contributed: {stats['contributed_count']})",
        f"Stars: .......... {stats['stars']}",
        f"Followers: ...... {stats['followers']}",
        f"Commits: ........ {stats['commits']}",
        f"Lines of Code: .. {stats['loc_added'] + stats['loc_deleted']:,}  "
        f"(+{stats['loc_added']:,}, -{stats['loc_deleted']:,})",
    ]

    max_lines = max(len(ascii_lines), len(info_lines))
    ascii_lines = ascii_lines + [""] * (max_lines - len(ascii_lines))
    info_lines = info_lines + [""] * (max_lines - len(info_lines))
    art_width = max((len(l) for l in ascii_lines), default=0)

    body = "\n".join(
        f"{a.ljust(art_width)}   {b}" for a, b in zip(ascii_lines, info_lines)
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""### {stats['username']} / README.md

```text
{body}
```

<sub>Auto-generated by GitHub Actions · last updated {generated_at}</sub>
"""


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN environment variable is required.")

    profile = yaml.safe_load(PROFILE_PATH.read_text())
    username = profile["github_username"]

    session = gh_session(token)

    print(f"Fetching user info for {username}...")
    user = fetch_user(session, username)

    print("Fetching repos...")
    repos = fetch_all_repos(session, username)
    stars = sum(r.get("stargazers_count", 0) for r in repos)

    print("Fetching contributed-repo count...")
    contributed_count = fetch_contributed_repo_count(session, username)

    print("Fetching commit count (search API, approximate)...")
    commits = fetch_total_commits(session, username)

    print("Computing lines of code (this may take a while on first run)...")
    loc_added, loc_deleted = compute_lines_of_code(username, repos, token)

    stats = {
        "username": username,
        "uptime": compute_uptime(user["created_at"]),
        "repo_count": user.get("public_repos", len(repos)),
        "contributed_count": contributed_count,
        "stars": stars,
        "followers": user.get("followers", 0),
        "commits": commits,
        "loc_added": loc_added,
        "loc_deleted": loc_deleted,
    }

    print("Rendering ASCII art from avatar...")
    art_cfg = profile.get("ascii_art", {})
    ascii_art = generate_ascii_art(
        user["avatar_url"],
        columns=art_cfg.get("columns", 42),
        monochrome=art_cfg.get("monochrome", True),
    )
    ascii_lines = ascii_art.rstrip("\n").split("\n")

    new_readme = render_readme(profile, stats, ascii_lines)

    old_readme = README_PATH.read_text() if README_PATH.exists() else ""
    if new_readme.strip() == old_readme.strip():
        print("No changes.")
        return

    README_PATH.write_text(new_readme)
    print("README.md updated.")


if __name__ == "__main__":
    main()
