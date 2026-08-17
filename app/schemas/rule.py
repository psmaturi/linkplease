"""schemas/rule.py — Request/response schemas for the /rules endpoint."""


from pydantic import BaseModel, Field


class RuleCreate(BaseModel):
    """POST /rules request body."""
    keyword: str = Field(..., min_length=1, max_length=255)
    dm_message: str = Field(..., min_length=1)


class RuleResponse(BaseModel):
    """POST /rules response (HTTP 201)."""
    rule_id: str
    keyword: str
    dm_message: str

    model_config = {"from_attributes": True}
