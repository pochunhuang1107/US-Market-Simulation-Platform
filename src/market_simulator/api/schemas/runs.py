from typing import Dict, Optional

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    strategy_id: str
    strategy_version_id: Optional[str]
    run_type: str
    executor_type: str
    request_payload: Dict
    max_attempts: int = Field(default=3, ge=1, le=10)