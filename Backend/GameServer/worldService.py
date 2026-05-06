from apiModels import CreateWorldRequest, SessionUser, WorldInfo
from gameDBService import GameDBService
from worldGenerator import WorldGenerator


class WorldService:
    def __init__(self, db_service: GameDBService, generator: WorldGenerator):
        self.db_service = db_service
        self.generator = generator

    async def create_world(self, world_info: CreateWorldRequest, user: SessionUser) -> WorldInfo:
        seed = world_info.world_seed or self.generator.generate_seed()
        world_state = self.generator.generate_world(seed)
        return await self.db_service.create_world(world_info.world_name, seed, user, world_state)

    async def delete_world(self, world_id: int, user: SessionUser) -> bool:
        return await self.db_service.delete_world(world_id, user.id)
