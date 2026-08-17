"""
schemas/webhook.py — Pydantic models for webhook event payloads.
"""

from pydantic import BaseModel


class CommentData(BaseModel):
    """The nested comment object inside a webhook event."""

    comment_id: str
    post_id: str
    user_id: str
    username: str | None = None
    text: str | None = None

    model_config = {"extra": "allow"}


class WebhookPayload(BaseModel):
    """Top-level webhook event envelope."""

    event_id: str
    event_type: str  # "comment.created" or "comment.deleted"
    comment: CommentData

    model_config = {"extra": "allow"}
