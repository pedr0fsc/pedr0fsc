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
BIRTHDAY = datetime.date(2007, 12, 27)
STATE_FILE = ".profile_state.json"
SVG_FILES = ("dark_mode.svg", "light_mode.svg")
PROFILE_REPO = USER_NAME  # username/username profile README repo

# Commits created by the SVG update workflow (never counted in the card)
AUTOMATION_EMAILS = (
    "41898282+github-actions[bot]@users.noreply.github.com",
    "github-actions[bot]@users.noreply.github.com",
    "action@github.com",
    "profile-bot@users.noreply.github.com",
)
AUTOMATION_MESSAGE_PREFIXES = (
    "chore: update profile SVG stats",
    "chore(profile-bot):",
    "Update SVG",
)


def now_sp():
    return datetime.datetime.now(SP_TZ)


def graphql(query, variables=None):
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables or {}},
        headers=HEADERS,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def get_uptime(birthday):
    """Age/uptime from birthday to today's date in America/Sao_Paulo."""
    today = now_sp().date()
    born = birthday if isinstance(birthday, datetime.date) else birthday.date()
    diff = relativedelta.relativedelta(today, born)
    years = f"{diff.years} year{'s' if diff.years != 1 else ''}"
    months = f"{diff.months} month{'s' if diff.months != 1 else ''}"
    days = f"{diff.days} day{'s' if diff.days != 1 else ''}"
    return f"{years}, {months}, {days}"


def get_user_meta():
    data = graphql(
        """
        query($login: String!) {
            user(login: $login) {
                id
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
        "id": user["id"],
        "created_at": user["createdAt"],
        "followers": user["followers"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
        "stars": stars,
    }


def get_contribution_commits(created_at):
    """Sum the account's own commit contributions year-by-year."""
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


def is_automation_commit(message, email=None):
    msg = (message or "").strip()
    if any(msg.startswith(prefix) for prefix in AUTOMATION_MESSAGE_PREFIXES):
        return True
    if email and email.lower() in {e.lower() for e in AUTOMATION_EMAILS}:
        return True
    return False


def count_automation_commits_on_profile(user_id):
    """
    Count update-system commits on the profile README repo.

    Returns (automation_total, user_authored_automation_total).
    Only user-authored automation commits are subtracted from contribution totals.
    """
    data = graphql(
        """
        query($owner: String!, $name: String!, $userId: ID!, $emails: [String!]) {
            repository(owner: $owner, name: $name) {
                defaultBranchRef {
                    target {
                        ... on Commit {
                            bot: history(author: {emails: $emails}) {
                                totalCount
                            }
                            mine: history(first: 100, author: {id: $userId}) {
                                nodes { messageHeadline }
                            }
                        }
                    }
                }
            }
        }
        """,
        {
            "owner": USER_NAME,
            "name": PROFILE_REPO,
            "userId": user_id,
            "emails": list(AUTOMATION_EMAILS),
        },
    )

    target = (
        data["repository"]["defaultBranchRef"]["target"]
        if data["repository"]["defaultBranchRef"]
        else None
    )
    if not target:
        return 0, 0

    bot_total = target["bot"]["totalCount"]
    user_automation = sum(
        1
        for node in target["mine"]["nodes"]
        if is_automation_commit(node.get("messageHeadline"))
    )
    return bot_total + user_automation, user_automation


def get_commit_count(created_at, user_id):
    raw = get_contribution_commits(created_at)
    automation_total, user_automation = count_automation_commits_on_profile(user_id)
    counted = max(0, raw - user_automation)
    print(
        f"Commits -> contributions={raw}, profile-bot={automation_total}, "
        f"excluded_user_automation={user_automation}, counted={counted}"
    )
    return counted


def get_github_stats():
    meta = get_user_meta()
    commits = get_commit_count(meta["created_at"], meta["id"])
    return {
        "repos": meta["repos"],
        "followers": meta["followers"],
        "stars": meta["stars"],
        "commits": commits,
    }


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
    try:
        stats = get_github_stats()
    except Exception as exc:
        print(f"GitHub stats failed; leaving SVGs unchanged ({exc})")
        raise SystemExit(1)

    uptime = get_uptime(BIRTHDAY)
    sp_now = now_sp()
    print(f"Sao Paulo now: {sp_now.isoformat()}")
    print(f"Sao Paulo date: {sp_now.date().isoformat()}")
    print(f"Uptime (birthday {BIRTHDAY.isoformat()}): {uptime}")
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
