from typing import Optional
from pydantic import BaseModel, Field

class CreateWorldRequest(BaseModel):
    world_name: str = Field(...,min_length=3,max_length=50)
    world_seed: Optional[str] = Field(None, max_length=100)