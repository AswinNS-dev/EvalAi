"""
backend/models/schemas.py
All Pydantic v2 models for EvalAI API I/O and inter-agent data exchange.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

# ── Generic API Envelope ──────────────────────────────────────────────────────
T = TypeVar("T")


class APIEnvelope(BaseModel, Generic[T]):
    status: str = "ok"
    data: Optional[T] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# ── Enums ─────────────────────────────────────────────────────────────────────
class Recommendation(str, Enum):
    SHORTLIST = "Shortlist"
    BORDERLINE = "Borderline"
    REJECT = "Reject"


class ClaimStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    PARTIAL = "partial"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class AgentStatus(str, Enum):
    READY = "ready"
    ANALYZING = "analyzing"
    DONE = "done"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


# ── Team ──────────────────────────────────────────────────────────────────────
class TeamRegistration(BaseModel):
    team_name: str = Field(..., min_length=1, max_length=120)
    github_url: str = Field(..., pattern=r"^https?://github\.com/.+")
    slide_text: Optional[str] = None  # extracted text from uploaded PDF/PPTX


class TeamRecord(BaseModel):
    team_id: str
    team_name: str
    github_url: str
    registered_at: datetime
    blind_alias: str
    slide_text: Optional[str] = None


# ── Agent Outputs ─────────────────────────────────────────────────────────────
class CriterionScore(BaseModel):
    score: int = Field(..., ge=0, le=100)
    rationale: str


class SlideAnalystOutput(BaseModel):
    agent_name: str = "SlideAnalyst"
    status: AgentStatus = AgentStatus.DONE
    clarity: Optional[CriterionScore] = None
    storytelling: Optional[CriterionScore] = None
    problem_statement: Optional[str] = None
    solution_narrative: Optional[str] = None
    business_model: Optional[str] = None
    error: Optional[str] = None


class RepoAnalystOutput(BaseModel):
    agent_name: str = "RepoAnalyst"
    status: AgentStatus = AgentStatus.DONE
    code_quality: Optional[CriterionScore] = None
    documentation: Optional[CriterionScore] = None
    commit_activity: Optional[CriterionScore] = None
    readme_content: Optional[str] = None
    file_tree: Optional[List[str]] = None
    commit_count: Optional[int] = None
    last_commit_date: Optional[str] = None
    open_issues: Optional[int] = None
    flags: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class ImpactAgentOutput(BaseModel):
    agent_name: str = "ImpactAgent"
    status: AgentStatus = AgentStatus.DONE
    impact_potential: Optional[CriterionScore] = None
    feasibility: Optional[CriterionScore] = None
    verdict_paragraph: Optional[str] = None
    error: Optional[str] = None


class TechnicalAgentOutput(BaseModel):
    agent_name: str = "TechnicalAgent"
    status: AgentStatus = AgentStatus.DONE
    technical_depth: Optional[CriterionScore] = None
    stack_authenticity: Optional[CriterionScore] = None
    flags: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class ClaimResult(BaseModel):
    claim: str
    status: ClaimStatus
    evidence: str


class ClaimVerifierOutput(BaseModel):
    agent_name: str = "ClaimVerifier"
    status: AgentStatus = AgentStatus.DONE
    claims: List[ClaimResult] = Field(default_factory=list)
    error: Optional[str] = None


class DisputedCriterion(BaseModel):
    criterion: str
    scores: Dict[str, int]  # { agent_name: score }
    disputed: bool = True


class ChiefJudgeOutput(BaseModel):
    agent_name: str = "ChiefJudge"
    status: AgentStatus = AgentStatus.DONE
    final_score: Optional[float] = None
    verdict_paragraph: Optional[str] = None
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    recommendation: Optional[Recommendation] = None
    disputed_criteria: List[DisputedCriterion] = Field(default_factory=list)
    error: Optional[str] = None


# ── Full Scorecard ─────────────────────────────────────────────────────────────
class TeamScorecard(BaseModel):
    team_id: str
    team_name: str
    blind_alias: str
    slide_analyst: Optional[SlideAnalystOutput] = None
    repo_analyst: Optional[RepoAnalystOutput] = None
    impact_agent: Optional[ImpactAgentOutput] = None
    technical_agent: Optional[TechnicalAgentOutput] = None
    claim_verifier: Optional[ClaimVerifierOutput] = None
    chief_judge: Optional[ChiefJudgeOutput] = None
    evaluated_at: Optional[datetime] = None


# ── Evaluation Job ─────────────────────────────────────────────────────────────
class AgentProgress(BaseModel):
    slide_analyst: AgentStatus = AgentStatus.READY
    repo_analyst: AgentStatus = AgentStatus.READY
    impact_agent: AgentStatus = AgentStatus.READY
    technical_agent: AgentStatus = AgentStatus.READY
    claim_verifier: AgentStatus = AgentStatus.READY
    chief_judge: AgentStatus = AgentStatus.READY


class EvaluationJob(BaseModel):
    job_id: str
    team_id: str
    status: JobStatus = JobStatus.PENDING
    agent_progress: AgentProgress = Field(default_factory=AgentProgress)
    scorecard: Optional[TeamScorecard] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# ── Leaderboard ───────────────────────────────────────────────────────────────
class LeaderboardEntry(BaseModel):
    rank: int
    team_id: str
    team_name: str
    blind_alias: str
    final_score: Optional[float] = None
    recommendation: Optional[Recommendation] = None
    disputed_count: int = 0
    job_status: JobStatus = JobStatus.PENDING


# ── Similarity ────────────────────────────────────────────────────────────────
class SimilarityAlert(BaseModel):
    alert_id: str
    team_a_id: str
    team_a_name: str
    team_b_id: str
    team_b_name: str
    similarity_score: float
    flagged: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Audit Log ─────────────────────────────────────────────────────────────────
class AuditLogEntry(BaseModel):
    log_id: str
    event_type: str
    team_id: Optional[str] = None
    agent_name: Optional[str] = None
    raw_prompt: Optional[str] = None
    raw_response: Optional[str] = None
    created_at: datetime


# ── Config ────────────────────────────────────────────────────────────────────
class CriterionWeight(BaseModel):
    clarity: float = 10.0
    storytelling: float = 10.0
    code_quality: float = 15.0
    documentation: float = 10.0
    commit_activity: float = 10.0
    impact_potential: float = 15.0
    feasibility: float = 10.0
    technical_depth: float = 10.0
    stack_authenticity: float = 10.0

    def total(self) -> float:
        return sum([
            self.clarity, self.storytelling, self.code_quality,
            self.documentation, self.commit_activity, self.impact_potential,
            self.feasibility, self.technical_depth, self.stack_authenticity
        ])


class RubricConfig(BaseModel):
    weights: CriterionWeight = Field(default_factory=CriterionWeight)
    blind_mode: bool = False
    similarity_detection: bool = True
    claim_verification: bool = True
    twilio_notifications: bool = False
    similarity_threshold: float = 0.80
    judge_phone_numbers: List[str] = Field(default_factory=list)
