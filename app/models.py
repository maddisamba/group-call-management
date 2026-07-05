from datetime import datetime

from pydantic import BaseModel, field_validator


class UserRequest(BaseModel):
    userId: str

    priority: bool =False

    @field_validator("userId")
    @classmethod
    def user_id_must_not_be_blank(cls, v: str) -> str:
        # Rejects "" and whitespace-only values. A blank userId should not take the floor and be unreleasable in practice.
        if not v or not v.strip():
            raise ValueError("userId must be a non-empty string")
        return v


class AuditRecordResponse(BaseModel):
    """One floor hold: who had the floor on which group, and when.

    releasedAt is null while the hold is still active.
    """

    groupId: str
    userId: str
    priority: bool
    obtainedAt: datetime
    releasedAt: datetime | None
