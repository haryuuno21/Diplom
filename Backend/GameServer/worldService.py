from apiModels import CreateWorldRequest, User
from gameDBService import GameDBService
from worldGenerator import WorldGenerator

class WorldService:
    def __init__(self, db_service: GameDBService, generator: WorldGenerator):
        self.db_service = db_service
        self.generator = generator

    async def createWorld(self, world_info: CreateWorldRequest, user: User) -> int:
        if not world_info.world_seed:
            world_info.world_seed = self.generator.generateSeed()

        world_state = self.generator.generateWorld(world_info.world_seed)

        world_id = await self.db_service.createWorld(world_info, user, world_state)

        return world_id