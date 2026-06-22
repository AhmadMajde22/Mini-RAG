import logging
from typing import List

from qdrant_client import QdrantClient, models

from ..VectorDBEnums import DistanceMethodEnums
from ..VectorDBInterface import VectorDBInterface


class QdrantDBProvider(VectorDBInterface):

    def __init__(self, db_path: str, distance_method: str):

        self.client = None
        self.db_path = db_path
        self.distance_method = None

        if distance_method == DistanceMethodEnums.COSINE.value:
            self.distance_method = models.Distance.COSINE

        elif distance_method == DistanceMethodEnums.DOT.value:
            self.distance_method = models.Distance.DOT

        self.logger = logging.getLogger(__name__)

    def connect(self):
        self.client = QdrantClient(path=self.db_path)

    def disconnect(self):
        self.client = None

    def is_collection_existed(self, collection_name: str) -> bool:
        return self.client.collection_exists(collection_name)

    def list_all_collections(self) -> List:
        return self.client.get_collections()

    def get_collection_info(self, collection_name: str) -> dict:
        return self.client.get_collection(collection_name)

    def delete_collection(self, collection_name: str):  # type: ignore
        if self.is_collection_existed(collection_name=collection_name):
            return self.client.delete_collection(collection_name=collection_name)

    def create_collection(  # type: ignore
        self, collection_name: str, embedding_size: int, do_reset: bool = False
    ):
        if do_reset:
            _ = self.delete_collection(collection_name=collection_name)

        if not self.is_collection_existed(collection_name):

            _ = self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=embedding_size, distance=self.distance_method
                ),
            )

            return True
        return False

    def insert_one(  # type: ignore
        self,
        collection_name: str,
        text: str,
        vector: List,
        metadata: dict = None,
        record_id: str = None,
    ):

        if not self.is_collection_existed(collection_name):
            self.logger.error(
                f"Can't insert new record to non-existed collection {collection_name}"
            )
            return False
        try:
            _ = self.client.upload_points(
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

    def insert_many(  # type: ignore
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
            record_ids = [None] * len(texts)

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
                _ = self.client.upload_points(
                    collection_name=collection_name, points=batch_records
                )
            except Exception as e:
                self.logger.error(f"Error While inserting batch : {e}")
                return False

        return True

    def search_by_vector(self, collection_name: str, vector: List, limit: int = 5):  # type: ignore
        return self.client.query_points(
            collection_name=collection_name, query=vector, limit=limit
        )
