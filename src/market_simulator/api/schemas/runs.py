from pydantic import BaseModel
from typing import Optional, Dict


class CreateRunRequest(BaseModel):
    strategy_id: str
    strategy_version_id: Optional[str]
    run_type: str
    executor_type: str
    request_payload: Dict