from dataclasses import dataclass
from typing import Literal, Tuple

Coordinates = Tuple[int, int, int]
Direction = Literal["N", "W", "S", "E"]

@dataclass
class User:
    login: str

@dataclass
class Player:
    user: User
    position: Coordinates = (0, 0, 0)
    rotation: Direction = "N"
    health: int = 100

@dataclass
class Block:
    position: Coordinates = (0, 0, 0)
    id: int = 0