"""schemas/stats.py — Response schema for GET /stats."""

from pydantic import BaseModel


class StatsResponse(BaseModel):
    """
    GET /stats response.
    """
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int
