"""
backend/agents/repo_analyst.py
Agent 2: Analyzes GitHub repository for code quality, docs, and commit activity.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from groq import Groq

from backend.config import settings
from backend.integrations.github_client import GithubClient
from backend.models.schemas import AgentStatus, CriterionScore, RepoAnalystOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are RepoAnalyst, an expert code reviewer evaluating hackathon GitHub repositories.

Given repository metadata, return ONLY valid JSON:
{
  "code_quality": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "documentation": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "commit_activity": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "additional_flags": ["<flag1>", ...]
}

Scoring rubric:
- Code Quality (0-100): Architecture, naming conventions, separation of concerns, no spaghetti code.
- Documentation (0-100): README completeness, inline comments, setup instructions, API docs.
- Commit Activity (0-100): Number of commits, recency, meaningful commit messages, not just one big dump.
- additional_flags: ONLY include relevant ones from: ["claimed ML but no model files found", "no requirements.txt or package.json", "repo appears empty", "README only", "forked with no changes"]
"""


class RepoAnalyst:
    def __init__(self):
        key = settings.groq_api_key_repo or settings.groq_api_key
        self._client = Groq(api_key=key) if key else None
        self._github = GithubClient()

    def analyze(self, github_url: str, team_id: str) -> RepoAnalystOutput:
        if not self._client:
            return RepoAnalystOutput(status=AgentStatus.UNAVAILABLE, error="Groq API key not configured")

        # Fetch repo data
        repo_data = self._github.get_full_analysis(github_url)

        # Build prompt context
        file_tree_str = "\n".join(repo_data["file_tree"][:50]) if repo_data["file_tree"] else "No files found"
        readme_snippet = (repo_data["readme"] or "No README found")[:3000]
        top_files_str = "\n".join(
            f"  {f['path']} ({f['size']} bytes)" for f in repo_data.get("top_files", [])
        ) or "None"

        user_message = f"""Evaluate this GitHub repository:

URL: {github_url}
README (first 3000 chars):
{readme_snippet}

File tree (first 50 files):
{file_tree_str}

Stats:
- Total commits: {repo_data['commit_count']}
- Last commit: {repo_data['last_commit_date'] or 'unknown'}
- Open issues: {repo_data['open_issues']}
- Top 3 files by size:
{top_files_str}
- Auto-detected flags: {repo_data['flags']}

Return ONLY the JSON evaluation."""

        try:
            response = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            raw = response.choices[0].message.content.strip()
            result = self._parse(raw, repo_data)
            result._raw_prompt = user_message  # type: ignore[attr-defined]
            result._raw_response = raw  # type: ignore[attr-defined]
            return result
        except Exception as exc:
            logger.error("RepoAnalyst failed: %s", exc)
            return RepoAnalystOutput(status=AgentStatus.ERROR, error=str(exc))

    def _parse(self, raw: str, repo_data: dict) -> RepoAnalystOutput:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Cannot parse JSON from RepoAnalyst: {text[:200]}")

        # Merge auto-detected flags with LLM-suggested flags
        all_flags = list(set(repo_data.get("flags", []) + data.get("additional_flags", [])))

        cq = data.get("code_quality", {})
        doc = data.get("documentation", {})
        ca = data.get("commit_activity", {})

        return RepoAnalystOutput(
            status=AgentStatus.DONE,
            code_quality=CriterionScore(score=int(cq.get("score", 0)), rationale=cq.get("rationale", "")) if cq else None,
            documentation=CriterionScore(score=int(doc.get("score", 0)), rationale=doc.get("rationale", "")) if doc else None,
            commit_activity=CriterionScore(score=int(ca.get("score", 0)), rationale=ca.get("rationale", "")) if ca else None,
            readme_content=repo_data.get("readme", ""),
            file_tree=repo_data.get("file_tree", []),
            commit_count=repo_data.get("commit_count"),
            last_commit_date=repo_data.get("last_commit_date"),
            open_issues=repo_data.get("open_issues"),
            flags=all_flags,
        )
