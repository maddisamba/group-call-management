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
        self.locks: dict[str,str]={}

    def _lock_for(self, group_id:str, user_id:str):
        self.locks[group_id]=user_id
        return self.locks

    async def acquire_floor(self, group_id:str, user_id:str, priority:bool) -> FloorAcquireResult:
        holder=self.locks.get(group_id)
        if holder is None:
            self._lock_for(group_id,user_id)
            return FloorAcquireResult(FloorAcquireOutCome.OBTAINED)
        if holder == user_id :
            return FloorAcquireResult(FloorAcquireOutCome.ALREADY_HELD_BY_SELF)
        if priority:
            self._lock_for(group_id,user_id)
            return FloorAcquireResult(FloorAcquireOutCome.OBTAINED)
        return FloorAcquireResult(FloorAcquireOutCome.HELD_BY_OTHER,holder=holder)
    
    async def release_floor(self, group_id:str, user_id:str) -> bool:
        if self.locks.get(group_id) == user_id:
            del self.locks[group_id]
            return True
        return False
    
    async def current_floor_holder(self, group_id:str) -> str | None:
        return self.locks.get(group_id)