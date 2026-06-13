"""
backend/integrations/github_client.py
Wraps PyGithub for safe repo metadata extraction used by RepoAnalyst agent.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from github import Github, GithubException, UnknownObjectException
from github.Repository import Repository

from backend.config import settings

logger = logging.getLogger(__name__)


class GithubClient:
    def __init__(self, token: Optional[str] = None):
        tok = token or settings.github_token
        self._gh = Github(tok) if tok else Github()  # unauthenticated fallback (60 req/h)

    def _get_repo(self, github_url: str) -> Optional[Repository]:
        """Parse github.com/owner/repo URL and return Repository object."""
        try:
            # Strip trailing .git and split
            path = github_url.rstrip("/").replace("https://github.com/", "").replace("http://github.com/", "")
            path = path.removesuffix(".git")
            return self._gh.get_repo(path)
        except (GithubException, UnknownObjectException) as exc:
            logger.warning("GithubClient: cannot access repo %s — %s", github_url, exc)
            return None

    def get_readme(self, github_url: str) -> str:
        """Return decoded README text, empty string on failure."""
        repo = self._get_repo(github_url)
        if not repo:
            return ""
        try:
            return repo.get_readme().decoded_content.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("GithubClient: no README in %s — %s", github_url, exc)
            return ""

    def get_file_tree(self, github_url: str, max_files: int = 100) -> List[str]:
        """Return flat list of repo file paths (up to max_files)."""
        repo = self._get_repo(github_url)
        if not repo:
            return []
        try:
            tree = repo.get_git_tree(repo.default_branch, recursive=True)
            return [item.path for item in tree.tree if item.type == "blob"][:max_files]
        except Exception as exc:
            logger.warning("GithubClient: cannot get file tree — %s", exc)
            return []

    def get_commit_stats(self, github_url: str) -> Tuple[int, Optional[str]]:
        """Return (commit_count, last_commit_date_iso). Falls back to (0, None)."""
        repo = self._get_repo(github_url)
        if not repo:
            return 0, None
        try:
            commits = repo.get_commits()
            count = commits.totalCount
            last = commits[0].commit.author.date.isoformat() if count > 0 else None
            return count, last
        except Exception as exc:
            logger.warning("GithubClient: cannot get commit stats — %s", exc)
            return 0, None

    def get_top_files(self, github_url: str, top_n: int = 3) -> List[Dict]:
        """Return top_n source files by size: [{ path, size }]."""
        repo = self._get_repo(github_url)
        if not repo:
            return []
        try:
            tree = repo.get_git_tree(repo.default_branch, recursive=True)
            blobs = [{"path": i.path, "size": i.size or 0} for i in tree.tree if i.type == "blob"]
            blobs.sort(key=lambda x: x["size"], reverse=True)
            return blobs[:top_n]
        except Exception as exc:
            logger.warning("GithubClient: cannot get top files — %s", exc)
            return []

    def get_open_issues_count(self, github_url: str) -> int:
        """Return open issues count."""
        repo = self._get_repo(github_url)
        if not repo:
            return 0
        try:
            return repo.open_issues_count
        except Exception:
            return 0

    def is_fork_unchanged(self, github_url: str) -> bool:
        """Return True if repo is a fork with no additional commits."""
        repo = self._get_repo(github_url)
        if not repo or not repo.fork:
            return False
        try:
            parent_commits = repo.parent.get_commits().totalCount if repo.parent else 0
            own_commits, _ = self.get_commit_stats(github_url)
            return own_commits <= parent_commits
        except Exception:
            return False

    def get_full_analysis(self, github_url: str) -> Dict:
        """Convenience method: returns all repo metadata in one call."""
        readme = self.get_readme(github_url)
        file_tree = self.get_file_tree(github_url)
        commit_count, last_commit = self.get_commit_stats(github_url)
        top_files = self.get_top_files(github_url)
        open_issues = self.get_open_issues_count(github_url)

        flags: List[str] = []
        if not file_tree:
            flags.append("repo appears empty")
        elif len(file_tree) <= 1:
            flags.append("README only")
        if self.is_fork_unchanged(github_url):
            flags.append("forked with no changes")

        return {
            "readme": readme,
            "file_tree": file_tree,
            "commit_count": commit_count,
            "last_commit_date": last_commit,
            "top_files": top_files,
            "open_issues": open_issues,
            "flags": flags,
        }
