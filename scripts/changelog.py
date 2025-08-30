from __future__ import annotations

import os
import re
from collections import defaultdict

import httpx
import rich_click as click
from pandas.io.clipboard import clipboard_set  # type: ignore
from rich.console import Console
from rich.markdown import Markdown

from rich_menu import argument_menu, live_menu

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}
REPOS = ["holoviews", "panel", "hvplot", "datashader", "geoviews", "lumen", "spatialpandas"]
console = Console()
ME = "hoxbro"


def get_releases(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"

    with httpx.Client() as client:
        response = client.get(url, headers=HEADERS)
        response.raise_for_status()
    tags = [r["tag_name"] for r in response.json() if not r["prerelease"]]
    return tags


def run_query(query, variables):
    response = httpx.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise ValueError(data["errors"])
    return data["data"]


def get_commit_date(repo, oid):
    """Return committedDate of a commit."""
    owner, name = repo.split("/")
    query_gql = """
    query($owner:String!, $name:String!, $oid:GitObjectID!) {
      repository(owner:$owner, name:$name) {
        object(oid:$oid) { ... on Commit { committedDate } }
      }
    }
    """
    data = run_query(query_gql, {"owner": owner, "name": name, "oid": oid})
    return data["repository"]["object"]["committedDate"]


def get_prs_between_tags(repo, from_commit_date, to_commit_date):
    """
    Fetch all merged PRs between two commit dates using GraphQL search.
    Returns:
      - commit_lines: list of markdown-formatted PR lines
      - contributors: set of usernames
    """
    owner, name = repo.split("/")
    commit_lines = []
    contributors = set()
    cursor = None

    query_str = f"repo:{owner}/{name} is:pr is:merged merged:{from_commit_date}..{to_commit_date}"

    query_gql = """
    query($query: String!, $cursor: String) {
      search(type: ISSUE, first:100, query: $query, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on PullRequest {
            number
            title
            author { login }
            mergedAt
          }
        }
      }
    }
    """

    pr_format = "- {title} ([#{number}](https://github.com/{owner}/{repo}/pull/{number}))"
    while True:
        data = run_query(query_gql, {"query": query_str, "cursor": cursor})
        nodes = data["search"]["nodes"]
        for pr in nodes:
            username = pr["author"]["login"] if pr["author"] else "unknown"
            contributors.add(username)
            commit_lines.append(
                pr_format.format(title=pr["title"], number=pr["number"], owner=owner, repo=name)
            )

        page_info = data["search"]["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return commit_lines, contributors


def categorize_commits(commit_lines):
    """
    Categorize commit lines based on conventional commit prefixes.

    Returns:
        dict: Dictionary with categories as keys and lists of commits as values
    """

    # Define section order and display names
    section_names = {
        "feat": "Features",
        "enh": "Enhancements",
        "fix": "Bug Fixes",
        "perf": "Performance",
        "compat": "Compatibility",
        "refactor": "Refactoring",
        "build": "Build System",
        "ci": "CI/CD",
        "docs": "Documentation",
        "test": "Tests",
        "type": "Type Annotations",
        "chore": "Maintenance",
        "misc": "Miscellaneous",
    }

    regex = re.compile(r"^- ([a-zA-Z]+)(?:\([^)]*\))?:\s*(.+)$")
    categories = defaultdict(list)
    for line in commit_lines:
        match = regex.match(line)
        if match:
            categories[match.group(1).lower()].append(line)
        else:
            categories["misc"].append(line)

    # Return ordered dictionary
    ordered_categories = {}
    for section, name in section_names.items():
        if section in categories:
            ordered_categories[name] = categories[section]

    return ordered_categories


def sort_contributors(contributors_set, new_contributors_set):
    # Separate new and existing contributors
    new_users = [user for user in contributors_set if user in new_contributors_set and user != ME]
    existing_users = [
        user for user in contributors_set if user not in new_contributors_set and user != ME
    ]

    new_users_sorted = sorted(new_users, key=lambda x: x.lower())
    existing_users_sorted = sorted(existing_users, key=lambda x: x.lower())

    result = new_users_sorted + existing_users_sorted
    if ME in contributors_set:
        result.append(ME)

    return result


def format_contributors(contributors, new_contributors):
    """
    Format contributors section with proper sorting and first contribution notes.

    Args:
        contributors: set of all contributor usernames
        new_contributors: set of new contributor usernames
        repo_name: repository name (e.g., "panel", "holoviews")

    Returns:
        str: Formatted contributor text
    """

    sorted_contributors = sort_contributors(contributors, new_contributors)

    # Build contributors text
    contributor_text = "Many thanks to "
    contributor_mentions = []
    for user in sorted_contributors:
        if user in new_contributors:
            contributor_mentions.append(
                f"[@{user}](https://github.com/{user}) (first contribution)"
            )
        else:
            contributor_mentions.append(f"[@{user}](https://github.com/{user})")

    if len(contributor_mentions) > 1:
        contributor_text += (
            ", ".join(contributor_mentions[:-1])
            + f", and {contributor_mentions[-1]} for their contributions."
        )
    elif len(contributor_mentions) == 1:
        contributor_text += f"{contributor_mentions[0]} for their contributions."
    else:
        contributor_text = "No contributors found."

    return contributor_text


def is_new_contributor(repo, username, from_commit_date):
    """
    Determines if a contributor is new by checking first merged PR using search API.
    Caches results for efficiency.
    """
    owner, name = repo.split("/")
    search_query = f"repo:{owner}/{name} is:pr author:{username} is:merged sort:created-asc"
    query_gql = """
    query($query: String!) {
      search(type: ISSUE, first:1, query: $query) {
        nodes {
          ... on PullRequest {
            mergedAt
          }
        }
      }
    }
    """
    data = run_query(query_gql, {"query": search_query})
    nodes = data["search"]["nodes"]
    merged_at = nodes[0]["mergedAt"] if nodes else None

    if merged_at is None:
        return True

    return merged_at >= from_commit_date


def generate_changelog(repo, from_tag, to_tag):
    owner, name = repo.split("/")

    # Resolve tags → commit OIDs
    query_gql = """
    query($owner:String!, $name:String!, $from:String!, $to:String!) {
      repository(owner:$owner, name:$name) {
        from: object(expression:$from) { ... on Commit { oid } }
        to: object(expression:$to) { ... on Commit { oid } }
      }
    }
    """
    data = run_query(query_gql, {"owner": owner, "name": name, "from": from_tag, "to": to_tag})
    from_oid = data["repository"]["from"]["oid"]
    to_oid = data["repository"]["to"]["oid"]

    # Get commit dates of tags
    from_commit_date = get_commit_date(repo, from_oid)
    to_commit_date = get_commit_date(repo, to_oid)

    # Get PRs and contributors between tags
    commit_lines, contributors = get_prs_between_tags(repo, from_commit_date, to_commit_date)

    # Classify new vs existing contributors
    new_contributors = set()
    for username in contributors:
        if is_new_contributor(repo, username, from_commit_date):
            new_contributors.add(username)

    # Categorize commits
    categorized_commits = categorize_commits(commit_lines)

    # Format contributors section
    contributor_text = format_contributors(contributors, new_contributors)

    # Build changelog
    changelog = [f"## Changelog ({from_tag}..{to_tag})", ""]
    changelog.append(contributor_text)
    changelog.append("")

    # Add categorized sections
    for section_name, commits in categorized_commits.items():
        changelog.append(f"### {section_name}")
        changelog.extend(commits)
        changelog.append("")

    return "\n".join(changelog)


@click.command(context_settings={"show_default": True})
@argument_menu(
    "repo",
    console=console,
    choices=REPOS,
    title="Select a repo to generate changelog for",
)
@click.argument("use_latest", type=bool, default=True)
@click.argument("branch", type=str, default="main")
def cli(repo, use_latest, branch) -> None:
    owner = "holoviz"
    releases = get_releases(owner, repo)

    if use_latest:
        from_tag, to_tag = releases[0], branch
    else:
        from_tag = live_menu(
            releases,
            console=console,
            title="Select a previous release to generate changelog from",
        )
        to_tag = live_menu(
            releases,
            console=console,
            title="Select the target release to generate changelog to",
        )

    repo_full = f"{owner}/{repo}"

    with console.status(
        f"Generating changelog for {repo} for latest release {from_tag} to {to_tag}..."
    ):
        text = generate_changelog(repo_full, from_tag, to_tag)

    clipboard_set(text)
    console.print(Markdown(text))
    console.print("\nChangelog copied to clipboard", style="italic white")


if __name__ == "__main__":
    cli()  # pyright: ignore[reportCallIssue]
