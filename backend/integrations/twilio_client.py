"""
backend/integrations/twilio_client.py
Wraps Twilio REST client. Skips silently when toggle is off or creds missing.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from backend.config import settings

logger = logging.getLogger(__name__)


class TwilioClient:
    def __init__(self):
        self._available = settings.twilio_available
        self._client = None
        if self._available:
            try:
                from twilio.rest import Client
                self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
                logger.info("TwilioClient: initialized")
            except Exception as exc:
                logger.warning("TwilioClient: init failed — %s", exc)
                self._available = False

    def send_notification(
        self,
        to: str,
        body: str,
        enabled: bool = True,
    ) -> Optional[str]:
        """
        Send an SMS to `to`.  Returns Twilio SID on success, None otherwise.
        No exception is raised on failure — notification is best-effort.
        """
        if not enabled or not self._available or not self._client:
            logger.info("TwilioClient: notification skipped (enabled=%s, available=%s)", enabled, self._available)
            return None
        try:
            msg = self._client.messages.create(
                body=body,
                from_=settings.twilio_phone_number,
                to=to,
            )
            logger.info("TwilioClient: sent to %s — SID %s", to, msg.sid)
            return msg.sid
        except Exception as exc:
            logger.warning("TwilioClient: send failed to %s — %s", to, exc)
            return None

    def notify_all_judges(
        self,
        judge_phones: List[str],
        team_name: str,
        final_score: float,
        recommendation: str,
        team_id: str,
        enabled: bool = True,
    ) -> List[Optional[str]]:
        """Send completion notification to every judge phone number."""
        body = (
            f"EvalAI: {team_name} evaluation complete. "
            f"Score: {final_score:.1f}/100. "
            f"Verdict: {recommendation}. "
            f"View: {settings.frontend_url}/scorecard/{team_id}"
        )
        results = []
        for phone in judge_phones:
            sid = self.send_notification(to=phone, body=body, enabled=enabled)
            results.append(sid)
        return results
