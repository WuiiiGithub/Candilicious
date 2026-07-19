"""
Recovery Module
===

Handles state persistence and recovery when the bot process is interrupted
(power off, crash, deploy, etc.).

Two strategies:
1. Resume: If members are still present (VC occupied or web user recently active),
   restore the session to the SessionManager and restart background tasks.
2. Cleanup: If no members remain (empty VC, stale web session),
   formally close the session, remove orphaned user references, and delete the DB doc.

Collections used:
- recovery.snapshots: periodic state snapshots for crash recovery
- recovery.log: audit trail of all recovery actions
"""
from .manager import RecoveryManager

__all__ = ["RecoveryManager"]
