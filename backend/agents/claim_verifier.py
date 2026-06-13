"""
backend/agents/claim_verifier.py
Agent 5: Extracts and verifies every quantitative/superlative claim from slides.
Runs in parallel with Agents 1-4.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from groq import Groq

from backend.config import settings
from backend.models.schemas import AgentStatus, ClaimResult, ClaimStatus, ClaimVerifierOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ClaimVerifier, a fact-checker for hackathon project submissions.

Your job:
1. Extract EVERY quantitative or superlative claim from the slide text (e.g. "99% accuracy", "processes 1M records/sec", "winner of X hackathon", "10x faster", "used by 500 users").
2. Cross-check each claim against the repository evidence.
3. Return ONLY valid JSON:
{
  "claims": [
    {
      "claim": "<exact claim text>",
      "status": "verified" | "unverified" | "partial",
      "evidence": "<1-2 sentences explaining the verification result>"
    }
  ]
}

Status definitions:
- "verified": Direct evidence found in repo (model files, test results, metrics, benchmarks, user lists, etc.)
- "partial": Some supporting evidence but not conclusive
- "unverified": No supporting evidence found in repo — claim is unsubstantiated
- If no claims found, return {"claims": [{"claim": "No quantitative claims detected", "status": "verified", "evidence": "No specific metrics or superlatives were made in the submission."}]}
"""


class ClaimVerifier:
    def __init__(self):
        key = settings.groq_api_key_claim or settings.groq_api_key
        self._client = Groq(api_key=key) if key else None

    def analyze(
        self,
        slide_text: str,
        repo_analysis: dict,
        team_id: str,
    ) -> ClaimVerifierOutput:
        if not self._client:
            return ClaimVerifierOutput(status=AgentStatus.UNAVAILABLE, error="Groq API key not configured")

        file_tree = repo_analysis.get("file_tree") or []
        file_tree_str = "\n".join(file_tree[:60]) if file_tree else "No files"
        readme_snippet = (repo_analysis.get("readme_content") or "")[:2000]

        user_message = f"""Extract and verify all quantitative/superlative claims.

SLIDE TEXT:
{slide_text[:5000]}

REPOSITORY EVIDENCE:
File tree: 
{file_tree_str}

README:
{readme_snippet}

Commit count: {repo_analysis.get('commit_count', 'unknown')}

Return ONLY the JSON with claims array."""

        try:
            response = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=2048,
            )
            raw = response.choices[0].message.content.strip()
            result = self._parse(raw)
            result._raw_prompt = user_message  # type: ignore[attr-defined]
            result._raw_response = raw  # type: ignore[attr-defined]
            return result
        except Exception as exc:
            logger.error("ClaimVerifier failed: %s", exc)
            return ClaimVerifierOutput(status=AgentStatus.ERROR, error=str(exc))

    def _parse(self, raw: str) -> ClaimVerifierOutput:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group()) if match else {"claims": []}

        claims = []
        for c in data.get("claims", []):
            try:
                status_str = c.get("status", "unverified").lower()
                status = ClaimStatus(status_str) if status_str in [s.value for s in ClaimStatus] else ClaimStatus.UNVERIFIED
                claims.append(ClaimResult(
                    claim=c.get("claim", ""),
                    status=status,
                    evidence=c.get("evidence", ""),
                ))
            except Exception:
                continue

        return ClaimVerifierOutput(status=AgentStatus.DONE, claims=claims)
