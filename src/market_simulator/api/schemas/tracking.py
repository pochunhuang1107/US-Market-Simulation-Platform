from pydantic import BaseModel
from typing import Optional


class CreateTrackedStrategyRequest(BaseModel):
    strategy_id: str
    strategy_version_id: Optional[str]
    tracking_mode: str