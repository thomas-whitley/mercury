"""The GitHub REST calls Mercury makes, with the token as a header. A repo
chore lists and opens pull requests and comments on them. The CI watch reads a repo's default
branch and its completed workflow runs. The dependency audit lists a repo's
files and reads its lock files.
"""

import json
import urllib.error
import urllib.request
from urllib.parse import quote

GITHUB_TIMEOUT_SECONDS = 20.0

# A workflow whose newest completed run ended in one of these is failing.
# cancelled and skipped are not failures.
FAILED_CONCLUSIONS = ("failure", "timed_out", "startup_failure")


class GitHubError(Exception):
    """GitHub refused or could not be reached. The message never carries the token."""


class GitHubClient:
    def __init__(self, token: str | None, api_url: str = "https://api.github.com") -> None:
        self._token = token
        self._api_url = api_url.rstrip("/")

    def find_pull(self, repo: str, branch: str) -> str | None:
        owner = repo.split("/", 1)[0]
        pulls = self._call("GET", f"/repos/{repo}/pulls?state=open&head={owner}:{branch}")
        return pulls[0]["html_url"] if pulls else None

    def pull_state(self, repo: str, branch: str) -> str:
        """open, merged or closed for the pull request from the branch, or none
        when there is no such pull request. Merged wins over open, open over closed."""
        owner = repo.split("/", 1)[0]
        pulls = self._call("GET", f"/repos/{repo}/pulls?state=all&head={owner}:{branch}")
        if not pulls:
            return "none"
        if any(p.get("merged_at") for p in pulls):
            return "merged"
        return "open" if any(p.get("state") == "open" for p in pulls) else "closed"

    def open_pull(self, repo: str, branch: str, base: str, title: str, body: str) -> str:
        pull = self._call(
            "POST",
            f"/repos/{repo}/pulls",
            {"title": title, "head": branch, "base": base, "body": body},
        )
        return pull["html_url"]

    def comment_on_pull(self, repo: str, pull: int | str, body: str) -> None:
        """Comment on a pull request, given its number or its URL. A pull request
        is an issue to the comments API."""
        number = int(str(pull).rstrip("/").rsplit("/", 1)[-1])
        self._call("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})

    def default_branch(self, repo: str) -> str:
        return self._call("GET", f"/repos/{repo}")["default_branch"]

    def completed_workflow_runs(self, repo: str, branch: str, limit: int = 50) -> list[dict]:
        """The newest completed workflow runs on one branch, newest first."""
        path = (
            f"/repos/{repo}/actions/runs?branch={quote(branch)}&status=completed&per_page={limit}"
        )
        return self._call("GET", path)["workflow_runs"]

    def file_paths(self, repo: str, ref: str) -> list[str]:
        """Every file in the repo at ref."""
        tree = self._call("GET", f"/repos/{repo}/git/trees/{quote(ref)}?recursive=1")["tree"]
        return [entry["path"] for entry in tree if entry["type"] == "blob"]

    def raw_file(self, repo: str, path: str, ref: str) -> str:
        return self._call("GET", f"/repos/{repo}/contents/{quote(path)}?ref={quote(ref)}", raw=True)

    def _call(self, method: str, path: str, payload: dict | None = None, raw: bool = False):
        accept = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
        headers = {"Accept": accept, "User-Agent": "mercury"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(
            f"{self._api_url}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
                body = response.read()
                return body.decode() if raw else json.loads(body)
        except urllib.error.HTTPError as error:
            raise GitHubError(f"GitHub {method} {path.split('?')[0]}: HTTP {error.code}") from None
        except (OSError, ValueError) as error:
            raise GitHubError(f"GitHub {method}: {type(error).__name__}") from None
