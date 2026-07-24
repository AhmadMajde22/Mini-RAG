import logging
from typing import List

from qdrant_client import AsyncQdrantClient, models

from models.db_schemas import RetrivedDocument

from ..VectorDBEnums import DistanceMethodEnums
from ..VectorDBInterface import VectorDBInterface


class QdrantDBProvider(VectorDBInterface):

    def __init__(
        self,
        db_client: str,
        default_vector_size: int = 1024,
        distance_method: str = DistanceMethodEnums.COSINE.value,
    ):
        if not db_client:
            raise ValueError("Qdrant database path is required")

        if default_vector_size <= 0:
            raise ValueError("Default vector size must be positive")

        try:
            distance_method_enum = DistanceMethodEnums(distance_method)
            qdrant_distance_method = models.Distance[distance_method_enum.name]
        except (ValueError, KeyError):
            raise ValueError(f"Unsupported distance method: {distance_method}")

        self.client: AsyncQdrantClient | None = None
        self.db_client = db_client
        self.default_vector_size = default_vector_size
        self.distance_method = qdrant_distance_method

        self.logger = logging.getLogger("uvicorn")

    async def connect(self):
        self.client = AsyncQdrantClient(path=self.db_client)

    async def disconnect(self):
        if self.client is not None:
            await self.client.close()
        self.client = None

    async def is_collection_existed(self, collection_name: str) -> bool:
        return await self.client.collection_exists(collection_name)

    async def list_all_collections(self) -> List:
        return await self.client.get_collections()

    async def get_collection_info(self, collection_name: str) -> dict:
        return await self.client.get_collection(collection_name)

    async def delete_collection(self, collection_name: str):  # type: ignore
        if await self.is_collection_existed(collection_name=collection_name):
            return await self.client.delete_collection(collection_name=collection_name)

    async def create_collection(  # type: ignore
        self, collection_name: str, embedding_size: int, do_reset: bool = False
    ):
        if do_reset:
            await self.delete_collection(collection_name=collection_name)

        if not await self.is_collection_existed(collection_name):

            self.logger(f"Creating new Qdrant collection : {collection_name}")

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=embedding_size, distance=self.distance_method
                ),
            )

            return True
        return False

    async def insert_one(  # type: ignore
        self,
        collection_name: str,
        text: str,
        vector: List,
        metadata: dict = None,
        record_id: str = None,
    ):

        if not await self.is_collection_existed(collection_name):
            self.logger.error(
                f"Can't insert new record to non-existed collection {collection_name}"
            )
            return False
        try:
            await self.client.upload_points(
                collection_name=collection_name,
                points=[
                    models.PointStruct(
                        id=record_id,
                        vector=vector,
                        payload={"text": text, "metadate": metadata},
                    )
                ],
            )
        except Exception as e:
            self.logger.error(f"Error While inserting  : {e}")
            return False
        return True

    async def insert_many(  # type: ignore
        self,
        collection_name: str,
        texts: List,
        vectors: List,
        metadata: List = None,
        record_ids: List = None,
        batch_size: int = 50,
    ):
        if not metadata:
            metadata = [None] * len(texts)

        if not record_ids:
            self.logger.error("No record ids were provided for vector db insertion")
            return False

        if len(record_ids) != len(texts):
            self.logger.error("Record ids count does not match texts count")
            return False

        if any(record_id is None for record_id in record_ids):
            self.logger.error("Record ids contain empty values")
            return False

        for i in range(0, len(texts), batch_size):

            batch_end = i + batch_size

            batch_texts = texts[i:batch_end]
            batch_vectors = vectors[i:batch_end]

            batch_metadata = metadata[i:batch_end]
            batch_records = record_ids[i:batch_end]

            batch_records = [
                models.PointStruct(
                    id=batch_records[x],
                    vector=batch_vectors[x],
                    payload={"text": batch_texts[x], "metadata": batch_metadata[x]},
                )
                for x in range(len(batch_texts))
            ]
            try:
                await self.client.upload_points(
                    collection_name=collection_name, points=batch_records
                )
            except Exception as e:
                self.logger.error(f"Error While inserting batch : {e}")
                return False

        return True

    async def search_by_vector(  # type: ignore
        self, collection_name: str, vector: List, limit: int = 5
    ):
        results = await self.client.query_points(
            collection_name=collection_name, query=vector, limit=limit
        )

        points = getattr(results, "points", results)

        if not points:
            return None

        return [
            RetrivedDocument(**{"score": result.score, "text": result.payload["text"]})
            for result in points
        ]
