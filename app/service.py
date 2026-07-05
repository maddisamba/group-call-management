import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

# How long a user may hold the floor before it is auto-released.
FLOOR_TIMEOUT_SECONDS = 10.0


class FloorAcquireOutCome(Enum):
    OBTAINED = "obtained"
    ALREADY_HELD_BY_SELF="self"
    HELD_BY_OTHER="other"


@dataclass
class FloorAcquireResult:
    result: FloorAcquireOutCome
    holder:str | None = None


@dataclass
class AuditRecord:
    group_id: str
    user_id: str
    priority: bool  # was the hold obtained with priority=true?
    obtained_at: datetime  # wall-clock UTC
    released_at: datetime | None = None  # None while the hold is active


@dataclass
class FloorHolder:
    user_id: str
    expires_at: float  # time.monotonic() deadline for expiry checks
    expires_at_wall: datetime  # same deadline in wall-clock UTC, for audit
    record: AuditRecord  # the open audit entry for this hold


class FloorService:

    def __init__(self) -> None:
        self.floor_holders: dict[str,FloorHolder]={}
        self.floor_locks:dict[str, asyncio.Lock] ={}
        self.audit_log: list[AuditRecord] = []  # ordered by obtained_at
        # Keep references to auto-release tasks so they are not GC'd mid-flight.
        self._release_tasks: set[asyncio.Task] = set()

    def _lock_for(self, group_id:str) -> asyncio.Lock:
        return self.floor_locks.setdefault(group_id,asyncio.Lock())

    def _close_current(self, group_id:str, released_at:datetime) -> None:
        # Ends the current hold: removes the floor entry and stamps the end
        # time on its audit record. Must be called under the group's lock.
        holder = self.floor_holders.pop(group_id, None)
        if holder is not None:
            holder.record.released_at = released_at

    def _active_holder(self, group_id:str) -> str | None:
        # Lazy expiry safety net: an expired entry is treated as free even if
        # the auto-release task has not fired yet. Must be called under the
        # group's lock.
        holder = self.floor_holders.get(group_id)
        if holder is None:
            return None
        if holder.expires_at <= time.monotonic():
            # The hold ended when it expired, not now - use the stored
            # wall-clock deadline for the audit record.
            self._close_current(group_id, holder.expires_at_wall)
            return None
        return holder.user_id

    def _grant(self, group_id:str, user_id:str, priority:bool) -> None:
        # Must be called under the group's lock.
        expires_at = time.monotonic() + FLOOR_TIMEOUT_SECONDS
        obtained_at = datetime.now(timezone.utc)
        expires_at_wall = obtained_at + timedelta(seconds=FLOOR_TIMEOUT_SECONDS)
        record = AuditRecord(group_id, user_id, priority, obtained_at)
        self.audit_log.append(record)
        self.floor_holders[group_id] = FloorHolder(
            user_id, expires_at, expires_at_wall, record
        )
        task = asyncio.create_task(self._auto_release(group_id, expires_at))
        self._release_tasks.add(task)
        task.add_done_callback(self._release_tasks.discard)

    async def _auto_release(self, group_id:str, expires_at:float) -> None:
        await asyncio.sleep(max(0.0, expires_at - time.monotonic()))
        async with self._lock_for(group_id):
            holder = self.floor_holders.get(group_id)
            # Only release the exact grant this task was scheduled for. If the
            # floor was released, re-granted or refreshed meanwhile, expires_at
            # no longer matches and this task does nothing - no cancellation
            # bookkeeping needed.
            if holder is not None and holder.expires_at == expires_at:
                self._close_current(group_id, holder.expires_at_wall)

    async def acquire_floor(self, group_id:str, user_id:str, priority:bool) -> FloorAcquireResult:
        async with self._lock_for(group_id):
            holder=self._active_holder(group_id)
            if holder is None:
                self._grant(group_id, user_id, priority)
                return FloorAcquireResult(FloorAcquireOutCome.OBTAINED)
            if holder == user_id :
                # Re-acquire by the current holder does NOT refresh the
                # timeout: the original expiry keeps counting down.
                return FloorAcquireResult(FloorAcquireOutCome.ALREADY_HELD_BY_SELF)
            if priority:
                # Preemption: close the previous holder's audit record at the
                # moment the floor was taken away.
                self._close_current(group_id, datetime.now(timezone.utc))
                self._grant(group_id, user_id, priority)
                return FloorAcquireResult(FloorAcquireOutCome.OBTAINED)
            return FloorAcquireResult(FloorAcquireOutCome.HELD_BY_OTHER,holder=holder)

    async def release_floor(self, group_id:str, user_id:str) -> bool:
        async with self._lock_for(group_id):
            if self._active_holder(group_id) == user_id:
                self._close_current(group_id, datetime.now(timezone.utc))
                return True
            return False

    async def current_floor_holder(self, group_id:str) -> str | None:
        async with self._lock_for(group_id):
            return self._active_holder(group_id)

    async def aclose(self) -> None:
        # Cancel auto-release timers still sleeping so the event loop can
        # shut down cleanly (called from the app lifespan / test teardown).
        for task in list(self._release_tasks):
            task.cancel()
        await asyncio.gather(*self._release_tasks, return_exceptions=True)
        self._release_tasks.clear()
