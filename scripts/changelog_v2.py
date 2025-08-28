from __future__ import annotations

import os

import httpx

GITHUB_API = "https://api.github.com/graphql"


def run_query(token, query, variables):
    headers = {"Authorization": f"Bearer {token}"}
    response = httpx.post(
        GITHUB_API, json={"query": query, "variables": variables}, headers=headers
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise ValueError(data["errors"])
    return data["data"]


def get_commit_date(token, repo, oid):
    """Return committedDate of a commit."""
    owner, name = repo.split("/")
    query_gql = """
    query($owner:String!, $name:String!, $oid:GitObjectID!) {
      repository(owner:$owner, name:$name) {
        object(oid:$oid) { ... on Commit { committedDate } }
      }
    }
    """
    data = run_query(token, query_gql, {"owner": owner, "name": name, "oid": oid})
    return data["repository"]["object"]["committedDate"]


def get_prs_between_tags(token, repo, from_commit_date, to_commit_date):
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

    while True:
        data = run_query(token, query_gql, {"query": query_str, "cursor": cursor})
        nodes = data["search"]["nodes"]
        for pr in nodes:
            username = pr["author"]["login"] if pr["author"] else "unknown"
            contributors.add(username)
            commit_lines.append(f"- {pr['title']} (#{pr['number']})")

        page_info = data["search"]["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return commit_lines, contributors


def is_new_contributor(token, repo, username, from_commit_date):
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
    data = run_query(token, query_gql, {"query": search_query})
    nodes = data["search"]["nodes"]
    merged_at = nodes[0]["mergedAt"] if nodes else None

    if merged_at is None:
        return True

    return merged_at >= from_commit_date


def generate_changelog(token, repo, from_tag, to_tag):
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
    data = run_query(
        token, query_gql, {"owner": owner, "name": name, "from": from_tag, "to": to_tag}
    )
    from_oid = data["repository"]["from"]["oid"]
    to_oid = data["repository"]["to"]["oid"]

    # Get commit dates of tags
    from_commit_date = get_commit_date(token, repo, from_oid)
    to_commit_date = get_commit_date(token, repo, to_oid)

    # Get PRs and contributors between tags
    commit_lines, contributors = get_prs_between_tags(
        token, repo, from_commit_date, to_commit_date
    )

    # Classify new vs existing contributors
    new_contributors = set()
    for username in contributors:
        if is_new_contributor(token, repo, username, from_commit_date):
            new_contributors.add(username)

    # # Build changelog
    changelog = [f"## Changelog ({from_tag}..{to_tag})", ""]
    changelog.extend(commit_lines)
    changelog.append("")
    changelog.append("### Contributors")
    for user in sorted(contributors, key=lambda x: x.lower()):
        changelog.append(f"- @{user}")

    if new_contributors:
        changelog.append("")
        changelog.append("### New Contributors")
        for user in sorted(new_contributors, key=lambda x: x.lower()):
            changelog.append(f"- @{user}")

    return "\n".join(changelog)


if __name__ == "__main__":
    # Example usage:
    token = os.environ["GITHUB_TOKEN"]
    repo = "holoviz/holoviews"  # owner/repo
    from_tag = "v1.20.0"
    to_tag = "v1.20.1"
    print(generate_changelog(token, repo, from_tag, to_tag))
