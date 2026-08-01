import json
import logging
import re
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import text as sql_text

from models.db_schemas import RetrivedDocument

from ..VectorDBEnums import (
    DistanceMethodEnums,
    PgVectorDistanceMethodEnums,
    PgVectorIndexTypeEnums,
    PgVectorTableSchemeEnums,
)
from ..VectorDBInterface import VectorDBInterface


class PGVectorProvider(VectorDBInterface):

    def __init__(
        self,
        db_client: async_sessionmaker[AsyncSession],
        default_vector_size: int = 1024,
        distance_method: str = None,
        index_threshold: int = 100,
    ):
        self.db_client: async_sessionmaker[AsyncSession] = db_client
        self.default_vector_size = default_vector_size
        self.distance_method = distance_method
        self.pgvector_table_prefix = PgVectorTableSchemeEnums._PREFIX.value  # type: ignore

        self.logger = logging.getLogger("uvicorn")
        self.default_index_name = (
            lambda collection_name: f"{collection_name}_vector_idx"
        )

        self.index_threshold = index_threshold

    async def connect(self):  # type: ignore
        async with self.db_client() as session:
            await session.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()

    async def disconnect(self):  # type: ignore
        pass

    async def is_collection_existed(self, collection_name: str) -> bool:  # type: ignore
        async with self.db_client() as session:
            list_tbl = sql_text(
                "SELECT * FROM pg_tables WHERE tablename = :collection_name"
            )
            results = await session.execute(
                list_tbl, {"collection_name": collection_name}
            )
            record = results.scalar_one_or_none()

            if record is None:
                return False

            return True

    async def list_all_collections(self) -> List:  # type: ignore
        async with self.db_client() as session:
            list_tbl = sql_text(
                "SELECT tablename FROM pg_tables WHERE tablename LIKE :prefix"
            )
            results = await session.execute(
                list_tbl, {"prefix": self.pgvector_table_prefix}
            )
            records = results.scalars().all()
        return records

    async def get_collection_info(self, collection_name: str) -> dict:
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        async with self.db_client() as session:
            table_info_sql = sql_text(
                """SELECT schemaname, tablename, tableowner, tablespace, hasindexes
                FROM pg_tables
                WHERE tablename = :collection_name"""
            )

            count_sql = sql_text(f'SELECT COUNT(*) FROM "{collection_name}"')

            table_info = await session.execute(
                table_info_sql, {"collection_name": collection_name}
            )

            record_count = (await session.execute(count_sql)).scalar_one()
            table_data = table_info.mappings().one_or_none()

            if not table_data:
                return None

            return {"table_info": dict(table_data), "record_count": record_count}

    async def delete_collection(self, collection_name: str): # type: ignore
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        async with self.db_client() as session:
            self.logger.info(f"Deleting collection: {collection_name}")
            delete_sql = sql_text(f'DROP TABLE IF EXISTS "{collection_name}"')
            await session.execute(delete_sql)
            await session.commit()

        return True

    async def create_collection( # type: ignore
        self, collection_name: str, embedding_size: int, do_reset: bool = False
    ):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        if embedding_size <= 0:
            raise ValueError("Embedding size must be positive")

        if do_reset:
            await self.delete_collection(collection_name=collection_name)

        is_collection_existed = await self.is_collection_existed(
            collection_name=collection_name
        )
        if not is_collection_existed:
            self.logger.info(f"Creating collection {collection_name}")
            async with self.db_client() as session:
                create_sql = sql_text(f"""CREATE TABLE "{collection_name}" (
                        {PgVectorTableSchemeEnums.ID.value} BIGSERIAL PRIMARY KEY,
                        {PgVectorTableSchemeEnums.TEXT.value} TEXT NOT NULL,
                        {PgVectorTableSchemeEnums.VECTOR.value} VECTOR({embedding_size}) NOT NULL,
                        {PgVectorTableSchemeEnums.METADATA.value} JSONB DEFAULT '{{}}',
                        {PgVectorTableSchemeEnums.CHUNK_ID.value} INTEGER,
                        FOREIGN KEY ({PgVectorTableSchemeEnums.CHUNK_ID.value})
                            REFERENCES chunks(chunk_id)
                    )""")
                await session.execute(create_sql)
                await session.commit()
            return True
        return False

    async def is_index_existed(self, collection_name: str) -> bool:
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        index_name = self.default_index_name(collection_name)

        async with self.db_client() as session:
            check_sql = sql_text("""SELECT 1 FROM pg_indexes
                WHERE tablename = :collection_name AND indexname = :index_name""")

            results = await session.execute(
                check_sql,
                {"collection_name": collection_name, "index_name": index_name},
            )
            return results.scalar_one_or_none() is not None

    async def create_vector_index(
        self, collection_name: str, index_type: str = PgVectorIndexTypeEnums.HNSW.value
    ):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        allowed_index_types = {item.value for item in PgVectorIndexTypeEnums}
        if index_type not in allowed_index_types:
            self.logger.error(f"Unsupported vector index type: {index_type}")
            return False

        try:
            distance_method = DistanceMethodEnums(self.distance_method)
            distance_operator_class = PgVectorDistanceMethodEnums[
                distance_method.name
            ].value
        except (ValueError, KeyError):
            self.logger.error(f"Unsupported distance method: {self.distance_method}")
            return False

        if not await self.is_collection_existed(collection_name=collection_name):
            self.logger.error(f"Collection does not exist: {collection_name}")
            return False

        is_index_existed = await self.is_index_existed(collection_name=collection_name)

        if is_index_existed:
            return False

        async with self.db_client() as session:
            count_sql = sql_text(f'SELECT COUNT(*) FROM "{collection_name}"')
            result = await session.execute(count_sql)

            records_count = result.scalar_one()

            if records_count < self.index_threshold:
                return False

            self.logger.info(
                f"START Creating vector index for collection : {collection_name}"
            )

            index_name = self.default_index_name(collection_name)
            create_idx_sql = sql_text(f"""CREATE INDEX IF NOT EXISTS "{index_name}"
                ON "{collection_name}"
                USING {index_type} (
                    {PgVectorTableSchemeEnums.VECTOR.value} {distance_operator_class}
                )""")

            try:
                await session.execute(create_idx_sql)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                self.logger.error(f"Error while creating vector index: {exc}")
                return False

            self.logger.info(
                f"END Creating vector index for collection : {collection_name}"
            )
            return True

    async def reset_vector_index(
        self,
        collection_name: str,
        index_type: str = PgVectorIndexTypeEnums.HNSW.value,
    ) -> bool:
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        allowed_index_types = {item.value for item in PgVectorIndexTypeEnums}
        if index_type not in allowed_index_types:
            self.logger.error(f"Unsupported vector index type: {index_type}")
            return False

        try:
            distance_method = DistanceMethodEnums(self.distance_method)
            distance_operator_class = PgVectorDistanceMethodEnums[
                distance_method.name
            ].value
        except (ValueError, KeyError):
            self.logger.error(f"Unsupported distance method: {self.distance_method}")
            return False

        if not await self.is_collection_existed(collection_name=collection_name):
            self.logger.error(f"Collection does not exist: {collection_name}")
            return False

        index_name = self.default_index_name(collection_name)

        async with self.db_client() as session:
            count_sql = sql_text(f'SELECT COUNT(*) FROM "{collection_name}"')
            records_count = (await session.execute(count_sql)).scalar_one()

            if records_count < self.index_threshold:
                self.logger.info(
                    f"Collection {collection_name} has fewer than "
                    f"{self.index_threshold} records; index was not reset"
                )
                return False

            drop_index_sql = sql_text(f'DROP INDEX IF EXISTS "{index_name}"')
            create_index_sql = sql_text(
                f'''CREATE INDEX "{index_name}"
                ON "{collection_name}"
                USING {index_type} (
                    {PgVectorTableSchemeEnums.VECTOR.value} {distance_operator_class}
                )'''
            )

            try:
                self.logger.info(
                    f"START Resetting vector index for collection: {collection_name}"
                )
                await session.execute(drop_index_sql)
                await session.execute(create_index_sql)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                self.logger.error(f"Error while resetting vector index: {exc}")
                return False

        self.logger.info(
            f"END Resetting vector index for collection: {collection_name}"
        )
        return True

    async def insert_one( # type: ignore
        self,
        collection_name: str,
        text: str,
        vector: list,
        metadate: dict = None,
        record_id: str = None,
    ):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        if not text:
            raise ValueError("Text cannot be empty")

        if not vector:
            raise ValueError("Vector cannot be empty")

        if not record_id:
            self.logger.error("Record ID is required")
            return False

        try:
            chunk_id = int(record_id)
        except (TypeError, ValueError):
            self.logger.error("Record ID must be a positive integer chunk ID")
            return False

        if chunk_id <= 0 or isinstance(record_id, bool):
            self.logger.error("Record ID must be a positive integer chunk ID")
            return False

        if not await self.is_collection_existed(collection_name=collection_name):
            self.logger.error(f"Collection does not exist: {collection_name}")
            return False

        insert_sql = sql_text(f"""INSERT INTO "{collection_name}" (
                {PgVectorTableSchemeEnums.TEXT.value},
                {PgVectorTableSchemeEnums.VECTOR.value},
                {PgVectorTableSchemeEnums.METADATA.value},
                {PgVectorTableSchemeEnums.CHUNK_ID.value}
            ) VALUES (
                :text,
                CAST(:vector AS vector),
                CAST(:metadata AS jsonb),
                :chunk_id
            )""")

        values = {
            "text": text,
            "vector": "[" + ",".join(str(value) for value in vector) + "]",
            "metadata": json.dumps(metadate or {}),
            "chunk_id": chunk_id,
        }

        async with self.db_client() as session:
            try:
                await session.execute(insert_sql, values)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                self.logger.error(f"Error while inserting record: {exc}")
                return False

        return True

    async def insert_many( # type: ignore
        self,
        collection_name: str,
        texts: list,
        vectors: list,
        metadata: list = None,
        record_ids: list = None,
        batch_size: int = 50,
    ):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        if not texts:
            self.logger.error("No texts were provided for insertion")
            return False

        if batch_size <= 0:
            self.logger.error("Batch size must be a positive integer")
            return False

        if not metadata:
            metadata = [None] * len(texts)

        if record_ids is None:
            self.logger.error("Record IDs are required")
            return False

        expected_count = len(texts)
        if not (
            len(vectors) == expected_count
            and len(metadata) == expected_count
            and len(record_ids) == expected_count
        ):
            self.logger.error(
                "Texts, vectors, metadata, and record IDs must have equal lengths"
            )
            return False

        if not await self.is_collection_existed(collection_name=collection_name):
            self.logger.error(f"Collection does not exist: {collection_name}")
            return False

        insert_sql = sql_text(f"""INSERT INTO "{collection_name}" (
                {PgVectorTableSchemeEnums.TEXT.value},
                {PgVectorTableSchemeEnums.VECTOR.value},
                {PgVectorTableSchemeEnums.METADATA.value},
                {PgVectorTableSchemeEnums.CHUNK_ID.value}
            ) VALUES (
                :text,
                CAST(:vector AS vector),
                CAST(:metadata AS jsonb),
                :chunk_id
            )""")

        async with self.db_client() as session:
            try:
                for i in range(0, len(texts), batch_size):
                    batch_end = i + batch_size
                    batch_texts = texts[i:batch_end]
                    batch_vectors = vectors[i:batch_end]
                    batch_metadata = metadata[i:batch_end]
                    batch_record_ids = record_ids[i:batch_end]

                    batch_records = []
                    for text, vector, item_metadata, record_id in zip(
                        batch_texts,
                        batch_vectors,
                        batch_metadata,
                        batch_record_ids,
                    ):
                        if not text or not vector:
                            self.logger.error(
                                "Texts and vectors cannot contain empty values"
                            )
                            await session.rollback()
                            return False

                        if not record_id or isinstance(record_id, bool):
                            self.logger.error(
                                "Every record ID must be a positive integer chunk ID"
                            )
                            await session.rollback()
                            return False

                        try:
                            chunk_id = int(record_id)
                        except (TypeError, ValueError):
                            self.logger.error(
                                "Every record ID must be a positive integer chunk ID"
                            )
                            await session.rollback()
                            return False

                        if chunk_id <= 0:
                            self.logger.error(
                                "Every record ID must be a positive integer chunk ID"
                            )
                            await session.rollback()
                            return False

                        batch_records.append(
                            {
                                "text": text,
                                "vector": "["
                                + ",".join(str(value) for value in vector)
                                + "]",
                                "metadata": json.dumps(item_metadata or {}),
                                "chunk_id": chunk_id,
                            }
                        )

                    await session.execute(insert_sql, batch_records)

                await session.commit()
            except Exception as exc:
                await session.rollback()
                self.logger.error(f"Error while inserting records: {exc}")
                return False

        return True

    async def search_by_vector( # type: ignore
        self, collection_name: str, vector: list, limit: int = 5
    ):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", collection_name):
            raise ValueError("Invalid collection name")

        if not vector:
            self.logger.error("Search vector cannot be empty")
            return False

        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            self.logger.error("Search limit must be a positive integer")
            return False

        is_collection_existed = await self.is_collection_existed(
            collection_name=collection_name
        )
        if not is_collection_existed:
            self.logger.error(
                f"Can't search records in non-existent collection: {collection_name}"
            )
            return False

        query_vector = "[" + ",".join(str(value) for value in vector) + "]"

        search_sql = sql_text(f"""SELECT
                {PgVectorTableSchemeEnums.TEXT.value} AS text,
                1 - (
                    {PgVectorTableSchemeEnums.VECTOR.value}
                    <=> CAST(:query_vector AS vector)
                ) AS score
            FROM "{collection_name}"
            ORDER BY
                {PgVectorTableSchemeEnums.VECTOR.value}
                <=> CAST(:query_vector AS vector)
            LIMIT :limit""")

        async with self.db_client() as session:
            try:
                results = await session.execute(
                    search_sql,
                    {"query_vector": query_vector, "limit": limit},
                )
                records = results.mappings().all()
            except Exception as exc:
                self.logger.error(f"Error while searching records: {exc}")
                return False

        if not records:
            return None

        return [
            RetrivedDocument(text=record["text"], score=float(record["score"]))
            for record in records
        ]
