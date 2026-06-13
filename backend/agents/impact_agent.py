"""
backend/agents/impact_agent.py
Agent 3: Evaluates real-world impact, market viability, and feasibility.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from groq import Groq

from backend.config import settings
from backend.models.schemas import AgentStatus, CriterionScore, ImpactAgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ImpactAgent, a venture capital analyst and impact evaluator assessing 
hackathon projects for real-world applicability and market potential.

Return ONLY valid JSON:
{
  "impact_potential": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "feasibility": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "verdict_paragraph": "<one paragraph (3-5 sentences) overall impact verdict>"
}

Scoring rubric:
- Impact Potential (0-100): Real-world problem significance, market size reasoning, user benefit clarity.
  - 0-20: No meaningful impact or relevance. 21-40: Trivial or niche problem. 41-60: Moderate impact.
  - 61-80: Significant real-world benefit. 81-100: Transformative potential.
- Feasibility (0-100): Is the solution implementable? Are the technical claims realistic? Timeline reasonable?
  - 0-20: Impossible or fantasy. 21-40: Highly implausible. 41-60: Possible with caveats.
  - 61-80: Feasible with effort. 81-100: Very achievable.
"""


class ImpactAgent:
    def __init__(self):
        key = settings.groq_api_key_impact or settings.groq_api_key
        self._client = Groq(api_key=key) if key else None

    def analyze(
        self,
        slide_text: str,
        readme_content: str,
        team_id: str,
        rag_context: Optional[str] = None,
    ) -> ImpactAgentOutput:
        if not self._client:
            return ImpactAgentOutput(status=AgentStatus.UNAVAILABLE, error="Groq API key not configured")

        context_block = f"\n\nAdditional retrieved context:\n{rag_context}" if rag_context else ""
        user_message = f"""Evaluate the real-world impact and feasibility of this project.

SLIDE TEXT:
{slide_text[:4000]}

README / TECHNICAL DESCRIPTION:
{readme_content[:3000]}{context_block}

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
            logger.error("ImpactAgent failed: %s", exc)
            return ImpactAgentOutput(status=AgentStatus.ERROR, error=str(exc))

    def _parse(self, raw: str) -> ImpactAgentOutput:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group()) if match else {}

        ip = data.get("impact_potential", {})
        fe = data.get("feasibility", {})

        return ImpactAgentOutput(
            status=AgentStatus.DONE,
            impact_potential=CriterionScore(score=int(ip.get("score", 0)), rationale=ip.get("rationale", "")) if ip else None,
            feasibility=CriterionScore(score=int(fe.get("score", 0)), rationale=fe.get("rationale", "")) if fe else None,
            verdict_paragraph=data.get("verdict_paragraph"),
        )
