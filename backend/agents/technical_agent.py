"""
backend/agents/technical_agent.py
Agent 4: Verifies technical claims against actual repo content.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from groq import Groq

from backend.config import settings
from backend.models.schemas import AgentStatus, CriterionScore, TechnicalAgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are TechnicalAgent, a senior software architect evaluating hackathon projects.
Your job is to cross-reference technical claims made in slides against what actually exists in the repository.

Return ONLY valid JSON:
{
  "technical_depth": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "stack_authenticity": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "flags": ["<flag1>", ...]
}

Scoring:
- Technical Depth (0-100): Architecture sophistication, proper use of patterns, scalability considerations.
- Stack Authenticity (0-100): Do the tech stack claims in slides match what's actually in the repo?
  100 = perfect match. 0 = complete fabrication.

Possible flags (include only if applicable):
- "claimed ML but no model files found"
- "claimed AI but no ML libraries in requirements"  
- "no requirements.txt or package.json"
- "tech stack not verifiable from repo"
- "only boilerplate code found"
- "impressive architecture present"
"""


class TechnicalAgent:
    def __init__(self):
        key = settings.groq_api_key_tech or settings.groq_api_key
        self._client = Groq(api_key=key) if key else None

    def analyze(
        self,
        slide_text: str,
        repo_analysis: dict,  # raw dict from RepoAnalystOutput
        team_id: str,
        rag_context: Optional[str] = None,
    ) -> TechnicalAgentOutput:
        if not self._client:
            return TechnicalAgentOutput(status=AgentStatus.UNAVAILABLE, error="Groq API key not configured")

        file_tree = repo_analysis.get("file_tree") or []
        file_tree_str = "\n".join(file_tree[:60]) if file_tree else "No files"
        context_block = f"\n\nAdditional context:\n{rag_context}" if rag_context else ""

        user_message = f"""Cross-check technical claims against repository evidence.

SLIDE TECH CLAIMS (slide text):
{slide_text[:3000]}

REPOSITORY FILE TREE:
{file_tree_str}

REPO README:
{(repo_analysis.get('readme_content') or '')[:2000]}

REPO COMMIT COUNT: {repo_analysis.get('commit_count', 'unknown')}
EXISTING FLAGS: {repo_analysis.get('flags', [])}{context_block}

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
            result = self._parse(raw)
            result._raw_prompt = user_message  # type: ignore[attr-defined]
            result._raw_response = raw  # type: ignore[attr-defined]
            return result
        except Exception as exc:
            logger.error("TechnicalAgent failed: %s", exc)
            return TechnicalAgentOutput(status=AgentStatus.ERROR, error=str(exc))

    def _parse(self, raw: str) -> TechnicalAgentOutput:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group()) if match else {}

        td = data.get("technical_depth", {})
        sa = data.get("stack_authenticity", {})

        return TechnicalAgentOutput(
            status=AgentStatus.DONE,
            technical_depth=CriterionScore(score=int(td.get("score", 0)), rationale=td.get("rationale", "")) if td else None,
            stack_authenticity=CriterionScore(score=int(sa.get("score", 0)), rationale=sa.get("rationale", "")) if sa else None,
            flags=data.get("flags", []),
        )
