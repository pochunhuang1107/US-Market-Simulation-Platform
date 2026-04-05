from pydantic import BaseModel
from typing import Optional, Dict


class CreateStrategyRequest(BaseModel):
    name: str
    description: Optional[str]
    strategy_type: str
    config: Dict


class CreateStrategyVersionRequest(BaseModel):
    config: Dict
    change_note: Optional[str] = None