"""
backend/pipeline/similarity.py
Cross-team plagiarism detection via cosine similarity on mean submission embeddings.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

import numpy as np

from backend.models.schemas import SimilarityAlert

logger = logging.getLogger(__name__)


class SimilarityEngine:
    def __init__(self):
        from backend.pipeline.rag import rag_pipeline
        self._rag = rag_pipeline

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def cross_similarity_check(
        self,
        teams: List[dict],  # list of { team_id, team_name }
        threshold: float = 0.80,
    ) -> List[SimilarityAlert]:
        """
        Compute pairwise cosine similarity between mean embeddings of all teams.
        Returns SimilarityAlert list for pairs exceeding threshold.
        """
        # Build embedding map
        emb_map: dict[str, Optional[np.ndarray]] = {}
        for team in teams:
            tid = team["team_id"]
            emb_map[tid] = self._rag.get_mean_embedding(tid)

        alerts: List[SimilarityAlert] = []
        team_ids = [t["team_id"] for t in teams]
        team_names = {t["team_id"]: t["team_name"] for t in teams}

        for i in range(len(team_ids)):
            for j in range(i + 1, len(team_ids)):
                tid_a, tid_b = team_ids[i], team_ids[j]
                emb_a = emb_map.get(tid_a)
                emb_b = emb_map.get(tid_b)
                if emb_a is None or emb_b is None:
                    continue

                score = self._cosine_similarity(emb_a, emb_b)
                logger.info(
                    "Similarity %s <-> %s: %.4f (threshold=%.2f)",
                    tid_a, tid_b, score, threshold
                )

                if score >= threshold:
                    alert = SimilarityAlert(
                        alert_id=str(uuid.uuid4()),
                        team_a_id=tid_a,
                        team_a_name=team_names.get(tid_a, tid_a),
                        team_b_id=tid_b,
                        team_b_name=team_names.get(tid_b, tid_b),
                        similarity_score=round(score, 4),
                        flagged=True,
                        created_at=datetime.utcnow(),
                    )
                    alerts.append(alert)
                    logger.warning(
                        "SIMILARITY ALERT: %s <-> %s score=%.4f",
                        team_names.get(tid_a), team_names.get(tid_b), score
                    )

        return alerts


# Module-level singleton
similarity_engine = SimilarityEngine()
