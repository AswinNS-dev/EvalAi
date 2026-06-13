"""
backend/agents/slide_analyst.py
Agent 1: Analyzes slide/presentation text for clarity, storytelling, and structure.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from groq import Groq

from backend.config import settings
from backend.models.schemas import AgentStatus, CriterionScore, SlideAnalystOutput

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are SlideAnalyst, an expert hackathon pitch evaluator specializing in 
presentation quality, storytelling, and communication clarity. 

You evaluate slide decks/presentations and return ONLY valid JSON matching this exact structure:
{
  "clarity": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "storytelling": {"score": <0-100>, "rationale": "<exactly 2 sentences>"},
  "problem_statement": "<extracted problem statement or null>",
  "solution_narrative": "<extracted solution description or null>",
  "business_model": "<extracted business model or null>"
}

Scoring rubric:
- Clarity (0-100): How clearly is the problem and solution communicated? Is the structure logical?
- Storytelling (0-100): Does the pitch have a compelling narrative arc? Does it create urgency?
- 0-20: Incomprehensible or missing. 21-40: Very poor. 41-60: Average. 61-80: Good. 81-100: Exceptional.
"""


class SlideAnalyst:
    def __init__(self):
        key = settings.groq_api_key_slide or settings.groq_api_key
        self._client = Groq(api_key=key) if key else None

    def analyze(
        self,
        slide_text: str,
        team_id: str,
        rag_context: Optional[str] = None,
    ) -> SlideAnalystOutput:
        if not self._client:
            return SlideAnalystOutput(
                status=AgentStatus.UNAVAILABLE,
                error="Groq API key not configured",
            )

        context_block = f"\n\nAdditional context from submission:\n{rag_context}" if rag_context else ""
        user_message = f"""Analyze the following slide/presentation text and return the JSON evaluation.

SLIDE TEXT:
{slide_text[:8000]}{context_block}

Return ONLY the JSON object, no markdown, no explanation."""

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
            parsed = self._parse(raw)
            parsed["_raw_prompt"] = user_message
            parsed["_raw_response"] = raw
            return parsed
        except Exception as exc:
            logger.error("SlideAnalyst failed: %s", exc)
            return SlideAnalystOutput(status=AgentStatus.ERROR, error=str(exc))

    def _parse(self, raw: str) -> SlideAnalystOutput:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract first JSON block
            import re
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Cannot parse JSON from SlideAnalyst output: {text[:200]}")

        clarity_raw = data.get("clarity", {})
        story_raw = data.get("storytelling", {})

        return SlideAnalystOutput(
            status=AgentStatus.DONE,
            clarity=CriterionScore(
                score=int(clarity_raw.get("score", 0)),
                rationale=clarity_raw.get("rationale", ""),
            ) if clarity_raw else None,
            storytelling=CriterionScore(
                score=int(story_raw.get("score", 0)),
                rationale=story_raw.get("rationale", ""),
            ) if story_raw else None,
            problem_statement=data.get("problem_statement"),
            solution_narrative=data.get("solution_narrative"),
            business_model=data.get("business_model"),
        )
