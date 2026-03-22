"""GitHub-specific helpers for probing and downloading skill repositories."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote, urlparse

import requests
from app.orchestration.skills.skill_files import (
    SKILL_MARKDOWN_FILENAMES,
    parse_front_matter,
)

_GITHUB_API_BASE = "https://api.github.com"
_HTTP_TIMEOUT_SECONDS = 12


@dataclass(frozen=True)
class GitHubSkillCandidate:
    """One valid skill folder discovered under a GitHub repository ``skills/`` root."""

    directory_name: str
    entry_filename: str
    suggested_name: str
    description: str

    def to_dict(self) -> dict[str, str]:
        """Serialize candidate data for API responses."""
        return asdict(self)


@dataclass(frozen=True)
class GitHubSkillProbeResult:
    """Structured result for one GitHub skill repository probe."""

    owner: str
    repo: str
    html_url: str
    description: str | None
    default_ref: str
    selected_ref: str
    branches: tuple[str, ...]
    tags: tuple[str, ...]
    has_skills_dir: bool
    candidates: tuple[GitHubSkillCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the probe result for transport over the API."""
        return {
            "repository": {
                "owner": self.owner,
                "repo": self.repo,
                "html_url": self.html_url,
                "description": self.description,
            },
            "default_ref": self.default_ref,
            "selected_ref": self.selected_ref,
            "branches": list(self.branches),
            "tags": list(self.tags),
            "has_skills_dir": self.has_skills_dir,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def parse_github_repository_url(github_url: str) -> tuple[str, str]:
    """Extract the owner/repo slug from a GitHub repository URL.

    Args:
        github_url: User-supplied GitHub repository URL.

    Returns:
        Tuple of ``(owner, repo)``.

    Raises:
        ValueError: If the URL does not point to a GitHub repository root.
    """
    parsed = urlparse(github_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "github.com":
        raise ValueError("Please enter a valid GitHub repository URL.")

    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(path_parts) < 2:
        raise ValueError("GitHub URL must point to a repository root.")
    if len(path_parts) > 2:
        raise ValueError("Only repository root URLs are supported for skill import.")

    owner = path_parts[0]
    repo = path_parts[1].removesuffix(".git")
    if not owner or not repo:
        raise ValueError("GitHub URL must include both owner and repository name.")
    return owner, repo


def probe_github_skill_repository(
    github_url: str,
    *,
    selected_ref: str | None = None,
) -> GitHubSkillProbeResult:
    """Probe a public GitHub repository for importable skill folders.

    Args:
        github_url: GitHub repository URL entered by the user.
        selected_ref: Optional branch or tag to inspect. Defaults to the repo's
            default branch when omitted.

    Returns:
        Structured repository, ref, and skill-candidate metadata.
    """
    owner, repo = parse_github_repository_url(github_url)
    repo_payload = _get_json(f"/repos/{owner}/{repo}")
    default_ref = _read_required_string(repo_payload, "default_branch")
    repo_description = _read_optional_string(repo_payload, "description")
    resolved_ref = selected_ref or default_ref

    branches_payload = _get_json(f"/repos/{owner}/{repo}/branches?per_page=100")
    tags_payload = _get_json(f"/repos/{owner}/{repo}/tags?per_page=100")
    branches = tuple(
        item["name"]
        for item in branches_payload
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    tags = tuple(
        item["name"]
        for item in tags_payload
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    branches, tags = _ensure_ref_options_include_selected(
        owner=owner,
        repo=repo,
        default_ref=default_ref,
        selected_ref=resolved_ref,
        branches=branches,
        tags=tags,
    )

    skills_root = _get_json(
        f"/repos/{owner}/{repo}/contents/skills?ref={quote(resolved_ref, safe='')}",
        allow_not_found=True,
    )
    if skills_root is None:
        return GitHubSkillProbeResult(
            owner=owner,
            repo=repo,
            html_url=f"https://github.com/{owner}/{repo}",
            description=repo_description,
            default_ref=default_ref,
            selected_ref=resolved_ref,
            branches=branches,
            tags=tags,
            has_skills_dir=False,
            candidates=(),
        )

    if not isinstance(skills_root, list):
        raise ValueError(
            "GitHub repository returned an unexpected skills directory shape."
        )

    candidates: list[GitHubSkillCandidate] = []
    for item in skills_root:
        if not isinstance(item, dict) or item.get("type") != "dir":
            continue
        directory_name = item.get("name")
        if not isinstance(directory_name, str) or not directory_name:
            continue
        candidate = _probe_skill_directory(
            owner=owner,
            repo=repo,
            ref=resolved_ref,
            directory_name=directory_name,
        )
        if candidate is not None:
            candidates.append(candidate)

    return GitHubSkillProbeResult(
        owner=owner,
        repo=repo,
        html_url=f"https://github.com/{owner}/{repo}",
        description=repo_description,
        default_ref=default_ref,
        selected_ref=resolved_ref,
        branches=branches,
        tags=tags,
        has_skills_dir=True,
        candidates=tuple(sorted(candidates, key=lambda item: item.directory_name)),
    )


def download_github_repository_archive(github_url: str, ref: str) -> bytes:
    """Download a public GitHub repository zip archive for one ref.

    Args:
        github_url: GitHub repository URL.
        ref: Selected branch or tag.

    Returns:
        Raw zip archive bytes.
    """
    owner, repo = parse_github_repository_url(github_url)
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/zipball/{quote(ref, safe='')}"
    response = requests.get(
        url,
        headers={"Accept": "application/vnd.github+json"},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    _raise_for_github_error(response)
    return response.content


def _probe_skill_directory(
    *,
    owner: str,
    repo: str,
    ref: str,
    directory_name: str,
) -> GitHubSkillCandidate | None:
    encoded_ref = quote(ref, safe="")
    encoded_directory = quote(directory_name, safe="")
    directory_payload = _get_json(
        f"/repos/{owner}/{repo}/contents/skills/{encoded_directory}?ref={encoded_ref}"
    )
    if not isinstance(directory_payload, list):
        return None

    matched_file: dict[str, Any] | None = None
    for item in directory_payload:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "file":
            continue
        filename = item.get("name")
        if isinstance(filename, str) and filename in SKILL_MARKDOWN_FILENAMES:
            matched_file = item
            break

    if matched_file is None:
        return None

    download_url = matched_file.get("download_url")
    if not isinstance(download_url, str) or not download_url:
        return None

    source = _get_text(download_url)
    metadata = parse_front_matter(source)
    suggested_name = metadata.get("name") or directory_name
    description = metadata.get("description", "")
    return GitHubSkillCandidate(
        directory_name=directory_name,
        entry_filename=str(matched_file["name"]),
        suggested_name=suggested_name,
        description=description,
    )


def _get_json(path: str, *, allow_not_found: bool = False) -> Any:
    url = f"{_GITHUB_API_BASE}{path}"
    response = requests.get(
        url,
        headers={"Accept": "application/vnd.github+json"},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    if allow_not_found and response.status_code == 404:
        return None
    _raise_for_github_error(response)
    return response.json()


def _get_text(url: str) -> str:
    response = requests.get(url, timeout=_HTTP_TIMEOUT_SECONDS)
    _raise_for_github_error(response)
    return response.text


def _ensure_ref_options_include_selected(
    *,
    owner: str,
    repo: str,
    default_ref: str,
    selected_ref: str,
    branches: tuple[str, ...],
    tags: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep default/selected refs visible even when GitHub list pagination clips them.

    GitHub's branch/tag list endpoints are paginated. We intentionally keep the
    probe lightweight, so we only fetch one page, but we still need the UI to
    offer the branch or tag the backend actually selected.
    """
    next_branches = _prepend_unique_ref(branches, default_ref)
    next_tags = tags

    if selected_ref in next_branches or selected_ref in next_tags:
        return next_branches, next_tags

    encoded_ref = quote(selected_ref, safe="")
    branch_payload = _get_json(
        f"/repos/{owner}/{repo}/branches/{encoded_ref}",
        allow_not_found=True,
    )
    if branch_payload is not None:
        return _prepend_unique_ref(next_branches, selected_ref), next_tags

    tag_payload = _get_json(
        f"/repos/{owner}/{repo}/git/ref/tags/{encoded_ref}",
        allow_not_found=True,
    )
    if tag_payload is not None:
        return next_branches, _prepend_unique_ref(next_tags, selected_ref)

    return next_branches, next_tags


def _prepend_unique_ref(refs: tuple[str, ...], ref_name: str) -> tuple[str, ...]:
    """Prepend one ref while preserving order and uniqueness."""
    if not ref_name:
        return refs
    if ref_name in refs:
        return refs
    return (ref_name, *refs)


def _raise_for_github_error(response: requests.Response) -> None:
    if response.ok:
        return

    message = _github_error_message(response)
    if response.status_code == 404:
        raise ValueError(message or "GitHub repository or ref was not found.")
    if (
        response.status_code == 403
        and response.headers.get("X-RateLimit-Remaining") == "0"
    ):
        raise ValueError("GitHub API rate limit reached. Please try again later.")
    raise ValueError(message or "GitHub request failed.")


def _github_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str):
            return message
    return ""


def _read_required_string(payload: Any, key: str) -> str:
    if not isinstance(payload, dict):
        raise ValueError("GitHub repository returned an unexpected payload.")

    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"GitHub repository payload is missing '{key}'.")
    return value


def _read_optional_string(payload: Any, key: str) -> str | None:
    """Read an optional string field from a GitHub API payload."""
    if not isinstance(payload, dict):
        return None

    value = payload.get(key)
    return value if isinstance(value, str) and value else None
