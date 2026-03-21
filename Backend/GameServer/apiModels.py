from typing import List, Optional
from pydantic import BaseModel, Field

class CreateWorldRequest(BaseModel):
    world_name: str = Field(None,min_length=3, max_length=50)
    world_seed: Optional[str] = Field(None, max_length=100)

class User(BaseModel):
    user_id: str = Field(None)
    user_name: str = Field(None, min_length=3, max_length=50)

class WorldInfo(BaseModel):
    world_id: int = Field(...)
    world_name: str = Field(..., min_length=3, max_length=50)
    world_created_at: float = Field(...)
    world_last_modified: float = Field(...)

class WorldListResponse(BaseModel):
    worlds: List[WorldInfo]

class CreateServerRequest(BaseModel):
    world_id: int = Field(..., gt=0, description="ID мира для создания сервера")
