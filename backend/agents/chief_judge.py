"""
backend/agents/chief_judge.py
Orchestrator agent: waits for all 5 sub-agents, detects disputes,
computes weighted final score, generates overall verdict.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from groq import Groq

from backend.config import settings
from backend.models.schemas import (
    AgentStatus,
    ChiefJudgeOutput,
    ClaimVerifierOutput,
    DisputedCriterion,
    ImpactAgentOutput,
    RepoAnalystOutput,
    SlideAnalystOutput,
    TechnicalAgentOutput,
    CriterionWeight,
    Recommendation,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ChiefJudge, the lead evaluator synthesizing all sub-agent analyses for a hackathon.

You receive scores and analyses from 4 specialist agents. Generate a final holistic verdict.

Return ONLY valid JSON:
{
  "verdict_paragraph": "<comprehensive 4-6 sentence paragraph summarizing the team's overall performance>",
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "gaps": ["<gap 1>", "<gap 2>", "<gap 3>"]
}

Be specific, reference actual evidence from the analyses. Be fair but rigorous.
Strengths and gaps should each be exactly 3 items.
"""


class ChiefJudge:
    def __init__(self):
        key = settings.groq_api_key_chief or settings.groq_api_key
        self._client = Groq(api_key=key) if key else None

    def judge(
        self,
        slide_out: Optional[SlideAnalystOutput],
        repo_out: Optional[RepoAnalystOutput],
        impact_out: Optional[ImpactAgentOutput],
        tech_out: Optional[TechnicalAgentOutput],
        claim_out: Optional[ClaimVerifierOutput],
        weights: CriterionWeight,
        team_name: str,
        blind_alias: Optional[str] = None,
        blind_mode: bool = False,
    ) -> ChiefJudgeOutput:
        # Collect all criterion scores
        criteria_scores = self._collect_scores(slide_out, repo_out, impact_out, tech_out)

        # Compute weighted final score
        final_score = self._compute_weighted_score(criteria_scores, weights)

        # Detect disputed criteria (>20 point gap between any two agents on same dimension)
        disputed = self._detect_disputes(criteria_scores)

        # Determine recommendation
        recommendation = self._get_recommendation(final_score)

        # Build synthesis prompt
        display_name = blind_alias if (blind_mode and blind_alias) else team_name
        synthesis = self._synthesize(
            display_name, slide_out, repo_out, impact_out, tech_out, claim_out, final_score
        )

        return ChiefJudgeOutput(
            status=AgentStatus.DONE,
            final_score=final_score,
            verdict_paragraph=synthesis.get("verdict_paragraph", ""),
            strengths=synthesis.get("strengths", []),
            gaps=synthesis.get("gaps", []),
            recommendation=recommendation,
            disputed_criteria=disputed,
        )

    # ── Score collection ──────────────────────────────────────────────────────
    def _collect_scores(
        self,
        slide_out, repo_out, impact_out, tech_out
    ) -> Dict[str, Dict[str, int]]:
        """Returns { criterion: { agent: score } }"""
        scores: Dict[str, Dict[str, int]] = {}

        def add(criterion: str, agent: str, value: Optional[int]):
            if value is not None:
                scores.setdefault(criterion, {})[agent] = value

        if slide_out and slide_out.status == AgentStatus.DONE:
            if slide_out.clarity:
                add("clarity", "SlideAnalyst", slide_out.clarity.score)
            if slide_out.storytelling:
                add("storytelling", "SlideAnalyst", slide_out.storytelling.score)

        if repo_out and repo_out.status == AgentStatus.DONE:
            if repo_out.code_quality:
                add("code_quality", "RepoAnalyst", repo_out.code_quality.score)
            if repo_out.documentation:
                add("documentation", "RepoAnalyst", repo_out.documentation.score)
            if repo_out.commit_activity:
                add("commit_activity", "RepoAnalyst", repo_out.commit_activity.score)

        if impact_out and impact_out.status == AgentStatus.DONE:
            if impact_out.impact_potential:
                add("impact_potential", "ImpactAgent", impact_out.impact_potential.score)
            if impact_out.feasibility:
                add("feasibility", "ImpactAgent", impact_out.feasibility.score)

        if tech_out and tech_out.status == AgentStatus.DONE:
            if tech_out.technical_depth:
                add("technical_depth", "TechnicalAgent", tech_out.technical_depth.score)
            if tech_out.stack_authenticity:
                add("stack_authenticity", "TechnicalAgent", tech_out.stack_authenticity.score)

        return scores

    def _compute_weighted_score(
        self, criteria_scores: Dict[str, Dict[str, int]], weights: CriterionWeight
    ) -> float:
        weight_map = {
            "clarity": weights.clarity,
            "storytelling": weights.storytelling,
            "code_quality": weights.code_quality,
            "documentation": weights.documentation,
            "commit_activity": weights.commit_activity,
            "impact_potential": weights.impact_potential,
            "feasibility": weights.feasibility,
            "technical_depth": weights.technical_depth,
            "stack_authenticity": weights.stack_authenticity,
        }
        total_weight = 0.0
        weighted_sum = 0.0
        for criterion, agent_scores in criteria_scores.items():
            if not agent_scores:
                continue
            avg_score = sum(agent_scores.values()) / len(agent_scores)
            w = weight_map.get(criterion, 0.0)
            weighted_sum += avg_score * w
            total_weight += w

        if total_weight == 0:
            return 0.0
        return round(weighted_sum / total_weight, 2)

    def _detect_disputes(
        self, criteria_scores: Dict[str, Dict[str, int]]
    ) -> List[DisputedCriterion]:
        disputed = []
        for criterion, agent_scores in criteria_scores.items():
            if len(agent_scores) < 2:
                continue
            scores_list = list(agent_scores.values())
            gap = max(scores_list) - min(scores_list)
            if gap > 20:
                disputed.append(DisputedCriterion(
                    criterion=criterion,
                    scores=agent_scores,
                    disputed=True,
                ))
        return disputed

    def _get_recommendation(self, score: float) -> Recommendation:
        if score >= 70:
            return Recommendation.SHORTLIST
        elif score >= 45:
            return Recommendation.BORDERLINE
        else:
            return Recommendation.REJECT

    # ── LLM synthesis ─────────────────────────────────────────────────────────
    def _synthesize(
        self, team_name, slide_out, repo_out, impact_out, tech_out, claim_out, final_score
    ) -> dict:
        if not self._client:
            return {
                "verdict_paragraph": "Chief Judge LLM synthesis unavailable.",
                "strengths": ["Data unavailable"],
                "gaps": ["Data unavailable"],
            }

        # Build summary of sub-agent results
        summary_parts = [f"Team: {team_name}", f"Final weighted score: {final_score:.1f}/100\n"]

        if slide_out and slide_out.status == AgentStatus.DONE:
            clarity = slide_out.clarity.score if slide_out.clarity else "N/A"
            storytelling = slide_out.storytelling.score if slide_out.storytelling else "N/A"
            summary_parts.append(f"SlideAnalyst: Clarity={clarity}, Storytelling={storytelling}")
            if slide_out.problem_statement:
                summary_parts.append(f"  Problem: {slide_out.problem_statement[:200]}")

        if repo_out and repo_out.status == AgentStatus.DONE:
            cq = repo_out.code_quality.score if repo_out.code_quality else "N/A"
            doc = repo_out.documentation.score if repo_out.documentation else "N/A"
            ca = repo_out.commit_activity.score if repo_out.commit_activity else "N/A"
            summary_parts.append(f"RepoAnalyst: CodeQuality={cq}, Documentation={doc}, Commits={ca}")
            if repo_out.flags:
                summary_parts.append(f"  Flags: {', '.join(repo_out.flags)}")

        if impact_out and impact_out.status == AgentStatus.DONE:
            ip = impact_out.impact_potential.score if impact_out.impact_potential else "N/A"
            fe = impact_out.feasibility.score if impact_out.feasibility else "N/A"
            summary_parts.append(f"ImpactAgent: ImpactPotential={ip}, Feasibility={fe}")

        if tech_out and tech_out.status == AgentStatus.DONE:
            td = tech_out.technical_depth.score if tech_out.technical_depth else "N/A"
            sa = tech_out.stack_authenticity.score if tech_out.stack_authenticity else "N/A"
            summary_parts.append(f"TechnicalAgent: TechnicalDepth={td}, StackAuthenticity={sa}")
            if tech_out.flags:
                summary_parts.append(f"  Flags: {', '.join(tech_out.flags)}")

        if claim_out and claim_out.status == AgentStatus.DONE:
            unverified = [c.claim for c in claim_out.claims if c.status.value == "unverified"]
            if unverified:
                summary_parts.append(f"ClaimVerifier: {len(unverified)} unverified claims")

        prompt = "\n".join(summary_parts)
        user_message = f"""Synthesize the following multi-agent evaluation into a final verdict:

{prompt}

Return ONLY the JSON object with verdict_paragraph, strengths (3 items), gaps (3 items)."""

        try:
            response = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            raw = response.choices[0].message.content.strip()
            text = raw
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                return json.loads(match.group()) if match else {}
        except Exception as exc:
            logger.error("ChiefJudge synthesis failed: %s", exc)
            return {
                "verdict_paragraph": f"Synthesis failed: {exc}",
                "strengths": [],
                "gaps": [],
            }
