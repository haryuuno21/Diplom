from dataclasses import dataclass

@dataclass
class WorldDB:
    world_id: int
    world_name: str
    world_seed: str
    world_creator_id: int
    world_created_at: float
    world_state: dict
    last_modified: float

@dataclass
class UserDB:
    user_id: str
    user_login: str
    user_hashed_password: str