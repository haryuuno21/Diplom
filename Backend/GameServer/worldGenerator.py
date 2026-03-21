from gameClasses import WorldState
from gameDBService import GameDBService


class WorldGenerator:
    def __init__(self, game_db_service: GameDBService):
        self.game_db_service = game_db_service
    
    def generateWorld(seed: str) -> WorldState:
        pass

    def generateSeed() -> str:
        pass