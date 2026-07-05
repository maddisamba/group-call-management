from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models import AuditRecordResponse, UserRequest
from app.service import FloorAcquireOutCome


router = APIRouter(tags=["Floor Control"])



@router.post(
    "/groups/{groupId}/floor",
    description="Obtain the floor for a group. The floor is auto-released "
                "after 10 seconds unless released manually; a re-request by "
                "the current holder does not reset the timer - the original "
                "expiry still applies.",
)
async def obtain_floor(groupId:str, body: UserRequest, request:Request):
    service = request.app.state.floor_service
    result = await service.acquire_floor(groupId, body.userId, body.priority)

    if result.result == FloorAcquireOutCome.HELD_BY_OTHER:
        return JSONResponse(
            status_code=409,
            content={
                "message": f"Floor is currently held by {result.holder} "
                           f"for group {groupId}"
            },
        )

    # OBTAINED and ALREADY_HELD_BY_SELF both return 200.
    # Rationale: the spec's 409 is defined as "held by ANOTHER user",
    # so a re-acquire by the current holder cannot be a 409. Treating
    # it as an idempotent success is the least surprising behaviour.
    return JSONResponse(
        status_code=200,
        content={"message": f"Floor obtained by {body.userId} for group {groupId}"},
    )



@router.delete("/groups/{groupId}/floor/{userId}")
async def release_floor(groupId: str, userId: str, request: Request):
    service = request.app.state.floor_service
    released = await service.release_floor(groupId, userId)

    if not released:
        return JSONResponse(
            status_code=403,
            content={
                "message": f"User {userId} does not hold the floor "
                           f"for group {groupId}"
            },
        )

    # Note: the OpenAPI spec has a typo here ('mesage'); we deliberately
    # use the correct 'message' key, consistent with every other response.
    return JSONResponse(
        status_code=200,
        content={"message": f"Floor released by {userId} for group {groupId}"},
    )


@router.get("/floor/holder/{groupId}")
async def get_floor_holder(groupId: str, request: Request):
    service = request.app.state.floor_service
    userId = await service.current_floor_holder(groupId)

    if not userId:
        return JSONResponse(
            status_code=200,
            content={
                "message": f"No User hold the floor "
                           f"for group {groupId}"
            },
        )

    # Note: the OpenAPI spec has a typo here ('mesage'); we deliberately
    # use the correct 'message' key, consistent with every other response.
    return JSONResponse(
        status_code=200,
        content={"message": f"Floor Holded by {userId} for group {groupId}"},
    )


@router.get(
    "/audit",
    response_model=list[AuditRecordResponse],
    description="Historical data of who had the floor when on what group, "
                "across all groups, ordered by when each hold was obtained. "
                "releasedAt is null for a hold that is still active.",
)
async def get_audit_log(request: Request):
    service = request.app.state.floor_service
    return [
        AuditRecordResponse(
            groupId=r.group_id,
            userId=r.user_id,
            priority=r.priority,
            obtainedAt=r.obtained_at,
            releasedAt=r.released_at,
        )
        for r in service.audit_log
    ]