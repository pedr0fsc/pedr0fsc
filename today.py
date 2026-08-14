import datetime
import hashlib
import json
import os

import requests
from dateutil import relativedelta
from lxml import etree

try:
    from zoneinfo import ZoneInfo

    SP_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    # Windows without tzdata, or minimal images: Sao Paulo is UTC-3 year-round
    SP_TZ = datetime.timezone(datetime.timedelta(hours=-3))

USER_NAME = os.getenv("USER_NAME", "pedr0fsc")
HEADERS = {"authorization": f"token {os.getenv('ACCESS_TOKEN', '')}"}
BIRTHDAY = datetime.datetime(2007, 12, 27)
STATE_FILE = ".profile_state.json"
SVG_FILES = ("dark_mode.svg", "light_mode.svg")


def now_sp():
    return datetime.datetime.now(SP_TZ)


def graphql(query, variables=None):
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables or {}},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def get_uptime(birthday):
    today = now_sp().replace(tzinfo=None)
    diff = relativedelta.relativedelta(today, birthday)
    years = f"{diff.years} year{'s' if diff.years != 1 else ''}"
    months = f"{diff.months} month{'s' if diff.months != 1 else ''}"
    days = f"{diff.days} day{'s' if diff.days != 1 else ''}"
    return f"{years}, {months}, {days}"


def get_user_meta():
    data = graphql(
        """
        query($login: String!) {
            user(login: $login) {
                createdAt
                followers { totalCount }
                repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
                    totalCount
                    nodes { stargazerCount }
                }
            }
        }
        """,
        {"login": USER_NAME},
    )
    user = data["user"]
    stars = sum(repo["stargazerCount"] for repo in user["repositories"]["nodes"])
    return {
        "created_at": user["createdAt"],
        "followers": user["followers"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
        "stars": stars,
    }


def get_commit_count(created_at):
    """Sum commit contributions year-by-year since account creation."""
    start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(
        tzinfo=None
    )
    end = now_sp().astimezone(datetime.timezone.utc).replace(tzinfo=None)
    total = 0
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
                totalCommitContributions
            }
        }
    }
    """

    while start < end:
        nxt = min(start + relativedelta.relativedelta(years=1), end)
        data = graphql(
            query,
            {
                "login": USER_NAME,
                "from": start.isoformat() + "Z",
                "to": nxt.isoformat() + "Z",
            },
        )
        total += data["user"]["contributionsCollection"]["totalCommitContributions"]
        start = nxt

    return total


def get_github_stats():
    try:
        meta = get_user_meta()
        commits = get_commit_count(meta["created_at"])
        return {
            "repos": meta["repos"],
            "followers": meta["followers"],
            "stars": meta["stars"],
            "commits": commits,
        }
    except Exception as exc:
        print(f"GitHub stats fallback ({exc})")
        return {"repos": 0, "followers": 0, "stars": 0, "commits": 0}


def get_config_txt():
    conf = {}
    if os.path.exists("config.txt"):
        with open("config.txt", "r", encoding="utf-8") as f:
            for line in f:
                if ":" in line:
                    key, value = line.split(":", 1)
                    conf[key.strip().lower()] = value.strip()
    return conf


def config_fingerprint(config):
    payload = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def should_update(config, stats, uptime):
    """Update only when SP day rolls over, stats change, or config.txt changes."""
    state = load_state()
    sp_date = now_sp().date().isoformat()
    conf_hash = config_fingerprint(config)
    reasons = []

    if state.get("sp_date") != sp_date:
        reasons.append(f"new Sao Paulo day ({sp_date})")
    if state.get("config_hash") != conf_hash:
        reasons.append("config.txt changed")
    if state.get("stats") != stats:
        reasons.append("GitHub stats changed")
    if state.get("uptime") != uptime:
        reasons.append("uptime changed")

    # First run / missing SVGs should always refresh
    if not state or any(not os.path.exists(path) for path in SVG_FILES):
        reasons.append("initial sync")

    # Deduplicate while keeping order
    unique = list(dict.fromkeys(reasons))
    return unique, {
        "sp_date": sp_date,
        "config_hash": conf_hash,
        "stats": stats,
        "uptime": uptime,
    }


def justify_svg(root, element_id, text, max_len=30):
    value = str(text)
    val_el = root.find(f".//*[@id='{element_id}']")
    if val_el is not None:
        val_el.text = value

    dots_id = element_id.replace("_val", "") + "_dots"
    dots_el = root.find(f".//*[@id='{dots_id}']")
    if dots_el is not None:
        num_dots = max(1, max_len - len(value))
        dots_el.text = " " + ("." * num_dots) + " "


def process_svg(filename, config, stats, uptime):
    if not os.path.exists(filename):
        print(f"Skipping missing file: {filename}")
        return False

    tree = etree.parse(filename)
    root = tree.getroot()

    justify_svg(root, "os_val", config.get("os", "Windows 11, Ubuntu"), 28)
    justify_svg(root, "age_data", uptime, 28)
    justify_svg(root, "host_val", config.get("host", "Student"), 28)
    justify_svg(root, "ide_val", config.get("ide", "VSCode"), 28)
    justify_svg(root, "lang_prog_val", config.get("languages_prog", "Python"), 22)
    justify_svg(root, "lang_comp_val", config.get("languages_comp", "HTML, CSS"), 22)
    justify_svg(root, "lang_real_val", config.get("languages_real", "English"), 22)
    justify_svg(root, "hobbies_val", config.get("hobbies", "Coding"), 28)
    justify_svg(root, "email_val", config.get("email", ""), 40)

    justify_svg(root, "repo_data", f"{stats['repos']:,}", 28)
    justify_svg(root, "commit_data", f"{stats['commits']:,}", 26)
    justify_svg(root, "star_data", f"{stats['stars']:,}", 28)
    justify_svg(root, "follower_data", f"{stats['followers']:,}", 24)

    tree.write(filename, encoding="utf-8", xml_declaration=True)
    print(f"Updated {filename}")
    return True


if __name__ == "__main__":
    config = get_config_txt()
    stats = get_github_stats()
    uptime = get_uptime(BIRTHDAY)
    print(f"Sao Paulo date: {now_sp().date().isoformat()}")
    print(
        f"Stats -> repos={stats['repos']}, commits={stats['commits']}, "
        f"stars={stats['stars']}, followers={stats['followers']}"
    )

    reasons, new_state = should_update(config, stats, uptime)
    if not reasons:
        print("No update needed (same day, stats, and config).")
    else:
        print("Updating because: " + "; ".join(reasons))
        for svg in SVG_FILES:
            process_svg(svg, config, stats, uptime)
        save_state(new_state)
        print("SVG updated successfully!")
