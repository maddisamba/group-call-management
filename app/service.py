import asyncio
from dataclasses import dataclass



class FloorAcquireOutCome(enumerate):
    OBTAINED = "obtained"
    ALREADY_HELD_BY_SELF="self"
    HELD_BY_OTHER="other"


@dataclass
class FloorAcquireResult:
    result: FloorAcquireOutCome
    holder:str | None = None


class FloorService:

    def __init__(self) -> None:
        self.floor_holders: dict[str,str]={}
        self.floor_locks:dict[str, asyncio.Lock] ={}

    def _lock_for(self, group_id:str) -> asyncio.Lock:        
        return self.floor_locks.setdefault(group_id,asyncio.Lock())

    async def acquire_floor(self, group_id:str, user_id:str, priority:bool) -> FloorAcquireResult:
        async with self._lock_for(group_id):
            holder=self.floor_holders.get(group_id)
            if holder is None:
                self.floor_holders[group_id]=user_id
                return FloorAcquireResult(FloorAcquireOutCome.OBTAINED)
            if holder == user_id :
                return FloorAcquireResult(FloorAcquireOutCome.ALREADY_HELD_BY_SELF)
            if priority:
                self.floor_holders[group_id]=user_id
                return FloorAcquireResult(FloorAcquireOutCome.OBTAINED)
            return FloorAcquireResult(FloorAcquireOutCome.HELD_BY_OTHER,holder=holder)
    
    async def release_floor(self, group_id:str, user_id:str) -> bool:
        async with self._lock_for(group_id):
            if self.floor_holders.get(group_id) == user_id:
                del self.floor_holders[group_id]
                return True
            return False
    
    async def current_floor_holder(self, group_id:str) -> str | None:
        return self.floor_holders.get(group_id)