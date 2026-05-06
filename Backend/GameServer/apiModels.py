from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserRegisterRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9_]+$",
        description="Login containing latin letters, digits, or underscore.",
    )
    password: str = Field(..., min_length=6, max_length=128)


class UserLoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)


class SessionUser(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: int
    username: str


class UpdateProfileRequest(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class AuthResponse(BaseModel):
    message: str
    user: UserResponse


class MessageResponse(BaseModel):
    message: str


class CreateWorldRequest(BaseModel):
    world_name: str = Field(..., min_length=3, max_length=50)
    world_seed: Optional[str] = Field(default=None, max_length=100)


class WorldInfo(BaseModel):
    world_id: int
    world_name: str
    world_seed: str
    world_created_at: float
    world_last_modified: float


class WorldListResponse(BaseModel):
    worlds: list[WorldInfo]


class CreateServerRequest(BaseModel):
    world_id: int = Field(..., gt=0)


class GameServerResponse(BaseModel):
    server_id: str
    server_code: str
    world_id: int
    world_name: str
    host_id: int
    status: Literal["waiting", "active", "stopped"]
    created_at: float
    player_count: int
    max_players: int
