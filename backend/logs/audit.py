import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

AUDIT_DIR = os.path.join(os.path.dirname(__file__), "audit")


class AuditLogger:
    """Per-session JSONL audit trail of agent activity.

    Each record is appended synchronously (open/write/close per record) so the
    trail survives crashes and is never buffered in memory.
    """

    def __init__(self, audit_dir: str = None):
        self.audit_dir = audit_dir or os.environ.get("LEAPP_AUDIT_DIR", AUDIT_DIR)

    def _session_file(self, session_id: str) -> str:
        safe_id = "".join(c for c in str(session_id) if c.isalnum() or c in "-_") or "unknown"
        return os.path.join(self.audit_dir, f"audit_{safe_id}.jsonl")

    def log(self, session_id: str, chat_model: str, event: str, data: dict):
        """Append one audit record for a session"""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "chat_model": chat_model,
            "event": event,
            "data": data
        }
        try:
            os.makedirs(self.audit_dir, exist_ok=True)
            with open(self._session_file(session_id), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError as e:
            logger.error(f"Failed to write audit record: {e}")


# Global instance
audit_logger = AuditLogger()
