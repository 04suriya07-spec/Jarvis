"""
GitHub skill — repos, issues, PRs, releases, code search via GitHub REST API.
Inspired by openclaw/skills/github SKILL.md — ported to Python + Javris pattern.
"""

from __future__ import annotations

import httpx

from skills.base import BaseSkill
from core.logger import get_logger
from core.config import get_config

logger = get_logger("javris.skill.github")
cfg = get_config()

GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cfg.github_token:
        h["Authorization"] = f"Bearer {cfg.github_token}"
    return h


class GitHubSkill(BaseSkill):
    name = "github"
    description = "Interact with GitHub repos, issues, PRs, releases, and code search"

    tool_definition = {
        "name": "github",
        "description": (
            "Interact with GitHub. Actions: list_repos, list_issues, create_issue, "
            "list_prs, get_pr, list_releases, search_code, get_repo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_repos", "get_repo", "list_issues", "create_issue",
                        "list_prs", "get_pr", "list_releases", "search_code",
                    ],
                    "description": "GitHub operation to perform",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format (e.g. 'torvalds/linux')",
                },
                "title": {"type": "string", "description": "Title for a new issue"},
                "body": {"type": "string", "description": "Body/description for a new issue"},
                "query": {"type": "string", "description": "Search query for search_code"},
                "number": {"type": "integer", "description": "Issue or PR number"},
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Filter by state",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (1-30)",
                    "default": 10,
                },
            },
            "required": ["action"],
        },
    }

    async def run(
        self,
        action: str,
        repo: str = "",
        title: str = "",
        body: str = "",
        query: str = "",
        number: int = 0,
        state: str = "open",
        limit: int = 10,
    ) -> dict | list | str:
        limit = max(1, min(30, limit))
        logger.info(f"GitHub:{action} repo={repo or '-'}")

        try:
            async with httpx.AsyncClient(timeout=20, headers=_headers()) as client:
                match action:
                    case "list_repos":
                        r = await client.get(
                            f"{GITHUB_API}/user/repos",
                            params={"per_page": limit, "sort": "updated", "direction": "desc"},
                        )
                        r.raise_for_status()
                        return [
                            {
                                "name": i["full_name"],
                                "stars": i["stargazers_count"],
                                "language": i["language"],
                                "private": i["private"],
                                "updated": i["updated_at"][:10],
                                "url": i["html_url"],
                            }
                            for i in r.json()
                        ]

                    case "get_repo":
                        r = await client.get(f"{GITHUB_API}/repos/{repo}")
                        r.raise_for_status()
                        d = r.json()
                        return {
                            "name": d["full_name"],
                            "description": d["description"],
                            "stars": d["stargazers_count"],
                            "forks": d["forks_count"],
                            "open_issues": d["open_issues_count"],
                            "language": d["language"],
                            "license": (d.get("license") or {}).get("spdx_id"),
                            "url": d["html_url"],
                        }

                    case "list_issues":
                        if not repo:
                            return "repo parameter required"
                        r = await client.get(
                            f"{GITHUB_API}/repos/{repo}/issues",
                            params={"state": state, "per_page": limit},
                        )
                        r.raise_for_status()
                        return [
                            {
                                "number": i["number"],
                                "title": i["title"],
                                "state": i["state"],
                                "labels": [lb["name"] for lb in i["labels"]],
                                "created": i["created_at"][:10],
                                "url": i["html_url"],
                            }
                            for i in r.json()
                            if "pull_request" not in i  # exclude PR entries
                        ]

                    case "create_issue":
                        if not repo or not title:
                            return "repo and title required"
                        r = await client.post(
                            f"{GITHUB_API}/repos/{repo}/issues",
                            json={"title": title, "body": body},
                        )
                        r.raise_for_status()
                        d = r.json()
                        return {"number": d["number"], "url": d["html_url"]}

                    case "list_prs":
                        if not repo:
                            return "repo parameter required"
                        r = await client.get(
                            f"{GITHUB_API}/repos/{repo}/pulls",
                            params={"state": state, "per_page": limit},
                        )
                        r.raise_for_status()
                        return [
                            {
                                "number": p["number"],
                                "title": p["title"],
                                "state": p["state"],
                                "author": p["user"]["login"],
                                "draft": p.get("draft", False),
                                "url": p["html_url"],
                            }
                            for p in r.json()
                        ]

                    case "get_pr":
                        if not repo or not number:
                            return "repo and number required"
                        r = await client.get(f"{GITHUB_API}/repos/{repo}/pulls/{number}")
                        r.raise_for_status()
                        p = r.json()
                        return {
                            "number": p["number"],
                            "title": p["title"],
                            "state": p["state"],
                            "body": (p.get("body") or "")[:500],
                            "author": p["user"]["login"],
                            "additions": p["additions"],
                            "deletions": p["deletions"],
                            "changed_files": p["changed_files"],
                            "mergeable": p.get("mergeable"),
                            "url": p["html_url"],
                        }

                    case "list_releases":
                        if not repo:
                            return "repo parameter required"
                        r = await client.get(
                            f"{GITHUB_API}/repos/{repo}/releases",
                            params={"per_page": limit},
                        )
                        r.raise_for_status()
                        return [
                            {
                                "tag": rel["tag_name"],
                                "name": rel["name"],
                                "published": (rel["published_at"] or "")[:10],
                                "prerelease": rel["prerelease"],
                                "url": rel["html_url"],
                            }
                            for rel in r.json()
                        ]

                    case "search_code":
                        if not query:
                            return "query parameter required"
                        q = f"{query} repo:{repo}" if repo else query
                        r = await client.get(
                            f"{GITHUB_API}/search/code",
                            params={"q": q, "per_page": limit},
                        )
                        r.raise_for_status()
                        return [
                            {
                                "path": i["path"],
                                "repo": i["repository"]["full_name"],
                                "url": i["html_url"],
                            }
                            for i in r.json().get("items", [])
                        ]

                    case _:
                        return f"Unknown action: {action}"

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return "GitHub auth failed — set GITHUB_TOKEN in .env"
            if e.response.status_code == 403:
                return "GitHub rate limit hit — add GITHUB_TOKEN for higher limits"
            return f"GitHub API error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            logger.error(f"GitHub skill error: {e}")
            return f"GitHub error: {e}"
