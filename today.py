import datetime
import os
import requests
from lxml import etree
from dateutil import relativedelta

USER_NAME = os.getenv("USER_NAME", "pedr0fsc")
HEADERS = {"authorization": f"token {os.getenv('ACCESS_TOKEN', '')}"}
BIRTHDAY = datetime.datetime(2007, 12, 27)


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
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
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
    end = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
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
        return

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


if __name__ == "__main__":
    config = get_config_txt()
    stats = get_github_stats()
    uptime = get_uptime(BIRTHDAY)
    print(
        f"Stats -> repos={stats['repos']}, commits={stats['commits']}, "
        f"stars={stats['stars']}, followers={stats['followers']}"
    )
    process_svg("dark_mode.svg", config, stats, uptime)
    process_svg("light_mode.svg", config, stats, uptime)
    print("SVG updated successfully!")
