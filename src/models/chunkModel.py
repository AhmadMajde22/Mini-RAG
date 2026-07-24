from sqlalchemy import delete, func
from sqlalchemy.future import select

from .BaseDataModel import BaseDataModel
from .db_schemas import DataChunk


class ChunkModel(BaseDataModel):
    def __init__(self, db_client: object):
        super().__init__(db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_chunk(self, chunk: DataChunk):
        async with self.db_client() as session:
            session.add(chunk)
            await session.commit()
            await session.refresh(chunk)

        return chunk

    async def get_chunk(self, chunk_id: int):
        async with self.db_client() as session:
            result = await session.execute(
                select(DataChunk).where(DataChunk.chunk_id == chunk_id)
            )

            return result.scalar_one_or_none()

    async def get_project_chunks(
        self, project_id: int, page_number: int = 1, page_size: int = 50
    ):
        if page_number < 1:
            page_number = 1
        if page_size < 1:
            page_size = 50

        async with self.db_client() as session:
            result = await session.execute(
                select(DataChunk)
                .where(DataChunk.chunk_project_id == project_id)
                .order_by(DataChunk.chunk_order)
                .offset((page_number - 1) * page_size)
                .limit(page_size)
            )

            return result.scalars().all()

    async def get_total_chunk_count(self, project_id: int) -> int:
        async with self.db_client() as session:
            count_sql = await session.execute(
                select(func.count(DataChunk.chunk_id)).where(
                    DataChunk.chunk_project_id == project_id
                )
            )

            return count_sql.scalar_one()

    async def insert_many_chunks(self, chunks: list, batch_size: int = 100):
        if batch_size < 1:
            batch_size = 100

        inserted_count = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            async with self.db_client() as session:
                session.add_all(batch)
                await session.commit()

            inserted_count += len(batch)

        return inserted_count

    async def delete_chunks_by_project_id(self, project_id: int):
        async with self.db_client() as session:
            result = await session.execute(
                delete(DataChunk).where(DataChunk.chunk_project_id == project_id)
            )
            await session.commit()

            return result.rowcount
