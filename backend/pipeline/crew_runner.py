"""
backend/pipeline/crew_runner.py
EvaluationPipeline: orchestrates all 5 agents + ChiefJudge for a team.
Agents 1-4 + ClaimVerifier run in parallel; ChiefJudge runs after all complete.
Maintains per-job SSE event queues for live frontend streaming.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from asyncio import Queue
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.agents.chief_judge import ChiefJudge
from backend.agents.claim_verifier import ClaimVerifier
from backend.agents.impact_agent import ImpactAgent
from backend.agents.repo_analyst import RepoAnalyst
from backend.agents.slide_analyst import SlideAnalyst
from backend.agents.technical_agent import TechnicalAgent
from backend.models.schemas import (
    AgentProgress,
    AgentStatus,
    EvaluationJob,
    JobStatus,
    RubricConfig,
    TeamRecord,
    TeamScorecard,
)
from backend.pipeline.rag import rag_pipeline

logger = logging.getLogger(__name__)

# In-memory job registry: job_id → EvaluationJob
JOB_REGISTRY: Dict[str, EvaluationJob] = {}

# SSE event queues: job_id → asyncio.Queue of SSE event dicts
SSE_QUEUES: Dict[str, Queue] = {}


def sanitize_prompt(text: str, real_name: str, alias: str) -> str:
    """Replace all case-insensitive occurrences of real_name with alias."""
    if not real_name or not alias:
        return text
    return re.sub(re.escape(real_name), alias, text, flags=re.IGNORECASE)


async def _emit(job_id: str, event: str, data: Any):
    """Push an SSE event to the job's queue."""
    q = SSE_QUEUES.get(job_id)
    if q:
        await q.put({"event": event, "data": data})


class EvaluationPipeline:
    def __init__(self, db_client=None, twilio_client=None):
        self._db = db_client
        self._twilio = twilio_client
        self._slide_analyst = SlideAnalyst()
        self._repo_analyst = RepoAnalyst()
        self._impact_agent = ImpactAgent()
        self._technical_agent = TechnicalAgent()
        self._claim_verifier = ClaimVerifier()
        self._chief_judge = ChiefJudge()

    def create_job(self, team_id: str) -> str:
        job_id = str(uuid.uuid4())
        job = EvaluationJob(
            job_id=job_id,
            team_id=team_id,
            status=JobStatus.PENDING,
            agent_progress=AgentProgress(),
        )
        JOB_REGISTRY[job_id] = job
        SSE_QUEUES[job_id] = asyncio.Queue()
        return job_id

    def get_job(self, job_id: str) -> Optional[EvaluationJob]:
        return JOB_REGISTRY.get(job_id)

    def get_jobs_for_team(self, team_id: str) -> List[EvaluationJob]:
        return [j for j in JOB_REGISTRY.values() if j.team_id == team_id]

    async def run(self, job_id: str, team: TeamRecord, config: RubricConfig):
        """
        Main pipeline entry point. Called as an asyncio background task.
        """
        job = JOB_REGISTRY.get(job_id)
        if not job:
            logger.error("run: job %s not found", job_id)
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        await _emit(job_id, "pipeline_start", {"team_id": team.team_id, "team_name": team.team_name})

        slide_text = team.slide_text or ""
        blind_mode = config.blind_mode
        alias = team.blind_alias

        # Apply blind mode to slide text
        if blind_mode:
            slide_text = sanitize_prompt(slide_text, team.team_name, alias)

        # Retrieve RAG context
        rag_context = " ".join(rag_pipeline.retrieve("project overview evaluation", team.team_id, top_k=3))

        # ── Run Agents 1-5 in parallel ────────────────────────────────────────
        await _emit(job_id, "agents_start", {"agents": ["SlideAnalyst", "RepoAnalyst", "ImpactAgent", "TechnicalAgent", "ClaimVerifier"]})

        results = await asyncio.gather(
            self._run_slide_analyst(job_id, team, slide_text, rag_context),
            self._run_repo_analyst(job_id, team),
            self._run_claim_verifier(job_id, team, slide_text, config),
            return_exceptions=True,
        )

        slide_out, repo_out_raw, claim_out = results
        if isinstance(slide_out, Exception):
            slide_out = None
        if isinstance(repo_out_raw, Exception):
            repo_out_raw = None
        if isinstance(claim_out, Exception):
            claim_out = None

        # Impact and Technical need repo output
        repo_analysis_dict = self._repo_to_dict(repo_out_raw)
        impact_out, tech_out = await asyncio.gather(
            self._run_impact_agent(job_id, team, slide_text, repo_analysis_dict, rag_context),
            self._run_technical_agent(job_id, team, slide_text, repo_analysis_dict, rag_context),
            return_exceptions=True,
        )
        if isinstance(impact_out, Exception):
            impact_out = None
        if isinstance(tech_out, Exception):
            tech_out = None

        # ── Chief Judge ───────────────────────────────────────────────────────
        await _emit(job_id, "agent_start", {"agent": "ChiefJudge"})
        job.agent_progress.chief_judge = AgentStatus.ANALYZING

        try:
            chief_out = self._chief_judge.judge(
                slide_out=slide_out,
                repo_out=repo_out_raw,
                impact_out=impact_out,
                tech_out=tech_out,
                claim_out=claim_out,
                weights=config.weights,
                team_name=team.team_name,
                blind_alias=alias,
                blind_mode=blind_mode,
            )
            job.agent_progress.chief_judge = AgentStatus.DONE
            await _emit(job_id, "agent_done", {"agent": "ChiefJudge", "score": chief_out.final_score})

            # Persist evaluation scores in background
            if self._db:
                self._persist_scores(team.team_id, slide_out, repo_out_raw, impact_out, tech_out, chief_out)

        except Exception as exc:
            logger.error("ChiefJudge failed: %s", exc)
            from backend.models.schemas import ChiefJudgeOutput
            chief_out = ChiefJudgeOutput(status=AgentStatus.ERROR, error=str(exc))
            job.agent_progress.chief_judge = AgentStatus.ERROR

        # ── Build scorecard ───────────────────────────────────────────────────
        scorecard = TeamScorecard(
            team_id=team.team_id,
            team_name=team.team_name if not blind_mode else alias,
            blind_alias=alias,
            slide_analyst=slide_out,
            repo_analyst=repo_out_raw,
            impact_agent=impact_out,
            technical_agent=tech_out,
            claim_verifier=claim_out,
            chief_judge=chief_out,
            evaluated_at=datetime.utcnow(),
        )

        job.scorecard = scorecard
        job.status = JobStatus.COMPLETE
        job.completed_at = datetime.utcnow()

        await _emit(job_id, "pipeline_complete", {
            "team_id": team.team_id,
            "final_score": chief_out.final_score,
            "recommendation": chief_out.recommendation.value if chief_out.recommendation else None,
        })

        # ── Twilio notification ────────────────────────────────────────────────
        if self._twilio and config.twilio_notifications and config.judge_phone_numbers and chief_out.final_score is not None:
            display = alias if blind_mode else team.team_name
            self._twilio.notify_all_judges(
                judge_phones=config.judge_phone_numbers,
                team_name=display,
                final_score=chief_out.final_score,
                recommendation=chief_out.recommendation.value if chief_out.recommendation else "Unknown",
                team_id=team.team_id,
                enabled=True,
            )
            if self._db:
                self._db.log_audit(
                    event_type="notification_sent",
                    team_id=team.team_id,
                    agent_name=None,
                    raw_prompt=f"Twilio notification to {config.judge_phone_numbers}",
                    raw_response=f"Score: {chief_out.final_score}, Verdict: {chief_out.recommendation}",
                )

        # Signal SSE stream end
        await _emit(job_id, "stream_end", {})

    # ── Agent runner helpers ──────────────────────────────────────────────────
    async def _run_slide_analyst(self, job_id, team, slide_text, rag_context):
        await _emit(job_id, "agent_start", {"agent": "SlideAnalyst"})
        JOB_REGISTRY[job_id].agent_progress.slide_analyst = AgentStatus.ANALYZING
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._slide_analyst.analyze(slide_text, team.team_id, rag_context)
        )
        JOB_REGISTRY[job_id].agent_progress.slide_analyst = result.status
        await _emit(job_id, "agent_done", {"agent": "SlideAnalyst", "status": result.status.value})
        self._audit_agent(team.team_id, result, "SlideAnalyst")
        return result

    async def _run_repo_analyst(self, job_id, team):
        await _emit(job_id, "agent_start", {"agent": "RepoAnalyst"})
        JOB_REGISTRY[job_id].agent_progress.repo_analyst = AgentStatus.ANALYZING
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._repo_analyst.analyze(team.github_url, team.team_id)
        )
        JOB_REGISTRY[job_id].agent_progress.repo_analyst = result.status
        await _emit(job_id, "agent_done", {"agent": "RepoAnalyst", "status": result.status.value})
        self._audit_agent(team.team_id, result, "RepoAnalyst")
        # Index repo content for RAG
        if result.readme_content:
            loop2 = asyncio.get_event_loop()
            combined = f"{result.readme_content}\n{' '.join(result.file_tree or [])}"
            await loop2.run_in_executor(None, lambda: rag_pipeline.index_team(team.team_id, combined))
        return result

    async def _run_impact_agent(self, job_id, team, slide_text, repo_dict, rag_context):
        await _emit(job_id, "agent_start", {"agent": "ImpactAgent"})
        JOB_REGISTRY[job_id].agent_progress.impact_agent = AgentStatus.ANALYZING
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._impact_agent.analyze(
                slide_text, repo_dict.get("readme_content", ""), team.team_id, rag_context
            )
        )
        JOB_REGISTRY[job_id].agent_progress.impact_agent = result.status
        await _emit(job_id, "agent_done", {"agent": "ImpactAgent", "status": result.status.value})
        self._audit_agent(team.team_id, result, "ImpactAgent")
        return result

    async def _run_technical_agent(self, job_id, team, slide_text, repo_dict, rag_context):
        await _emit(job_id, "agent_start", {"agent": "TechnicalAgent"})
        JOB_REGISTRY[job_id].agent_progress.technical_agent = AgentStatus.ANALYZING
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._technical_agent.analyze(slide_text, repo_dict, team.team_id, rag_context)
        )
        JOB_REGISTRY[job_id].agent_progress.technical_agent = result.status
        await _emit(job_id, "agent_done", {"agent": "TechnicalAgent", "status": result.status.value})
        self._audit_agent(team.team_id, result, "TechnicalAgent")
        return result

    async def _run_claim_verifier(self, job_id, team, slide_text, config):
        if not config.claim_verification:
            JOB_REGISTRY[job_id].agent_progress.claim_verifier = AgentStatus.DONE
            return None
        await _emit(job_id, "agent_start", {"agent": "ClaimVerifier"})
        JOB_REGISTRY[job_id].agent_progress.claim_verifier = AgentStatus.ANALYZING
        # ClaimVerifier needs repo data — fetch it from RAG context
        loop = asyncio.get_event_loop()
        repo_data = await loop.run_in_executor(
            None,
            lambda: self._repo_analyst._github.get_full_analysis(team.github_url)
        )
        result = await loop.run_in_executor(
            None,
            lambda: self._claim_verifier.analyze(slide_text, repo_data, team.team_id)
        )
        JOB_REGISTRY[job_id].agent_progress.claim_verifier = result.status
        await _emit(job_id, "agent_done", {"agent": "ClaimVerifier", "status": result.status.value})
        self._audit_agent(team.team_id, result, "ClaimVerifier")
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _repo_to_dict(self, repo_out) -> dict:
        if repo_out is None:
            return {}
        return {
            "readme_content": repo_out.readme_content or "",
            "file_tree": repo_out.file_tree or [],
            "commit_count": repo_out.commit_count,
            "flags": repo_out.flags,
        }

    def _audit_agent(self, team_id: str, result, agent_name: str):
        if not self._db:
            return
        raw_prompt = getattr(result, "_raw_prompt", None)
        raw_response = getattr(result, "_raw_response", None)
        self._db.log_audit(
            event_type="agent_run",
            team_id=team_id,
            agent_name=agent_name,
            raw_prompt=raw_prompt,
            raw_response=raw_response,
        )

    def _persist_scores(self, team_id, slide_out, repo_out, impact_out, tech_out, chief_out):
        if not self._db:
            return
        disputed_set = {d.criterion for d in (chief_out.disputed_criteria or [])}

        def save(agent, criterion, score_obj):
            if score_obj:
                self._db.save_evaluation(
                    team_id=team_id,
                    agent_name=agent,
                    criterion=criterion,
                    score=score_obj.score,
                    rationale=score_obj.rationale,
                    disputed=criterion in disputed_set,
                )

        if slide_out and slide_out.status == AgentStatus.DONE:
            save("SlideAnalyst", "clarity", slide_out.clarity)
            save("SlideAnalyst", "storytelling", slide_out.storytelling)
        if repo_out and repo_out.status == AgentStatus.DONE:
            save("RepoAnalyst", "code_quality", repo_out.code_quality)
            save("RepoAnalyst", "documentation", repo_out.documentation)
            save("RepoAnalyst", "commit_activity", repo_out.commit_activity)
        if impact_out and impact_out.status == AgentStatus.DONE:
            save("ImpactAgent", "impact_potential", impact_out.impact_potential)
            save("ImpactAgent", "feasibility", impact_out.feasibility)
        if tech_out and tech_out.status == AgentStatus.DONE:
            save("TechnicalAgent", "technical_depth", tech_out.technical_depth)
            save("TechnicalAgent", "stack_authenticity", tech_out.stack_authenticity)

        self._db.log_audit(
            event_type="score_finalized",
            team_id=team_id,
            agent_name="ChiefJudge",
            raw_prompt=None,
            raw_response=f"Score: {chief_out.final_score}, Recommendation: {chief_out.recommendation}",
        )


# Module-level singleton (initialized by FastAPI lifespan)
pipeline: Optional[EvaluationPipeline] = None
