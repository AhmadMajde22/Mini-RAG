import json
from typing import List
from uuid import NAMESPACE_URL, uuid5

from models.db_schemas import DataChunk, Project
from stores.llm.LLMEnums import DocumentTypeEnum
from stores.llm.LLMInterface import LLMInterface
from stores.llm.templates.template_parser import TemplateParser
from stores.vectordb.VectorDBInterface import VectorDBInterface

from .BaseController import BaseController


class NLPController(BaseController):

    def __init__(
        self,
        vectordb_client: VectorDBInterface,
        generation_client: LLMInterface,
        embedding_client: LLMInterface,
        template_parser: TemplateParser,
    ):
        super().__init__()

        self.vectodb_client = vectordb_client
        self.generation_client = generation_client
        self.embedding_client = embedding_client
        self.template_parser = template_parser

    def create_collection_name(self, project_id: str):
        return f"collection_{project_id}".strip()

    def reset_vector_db_collection(self, project: Project):

        collection_name = self.create_collection_name(project.project_id)
        return self.vectodb_client.delete_collection(collection_name=collection_name)

    def get_vector_db_collection_info(self, project: Project):
        collection_name = self.create_collection_name(project_id=project.project_id)
        collection_info = self.vectodb_client.get_collection_info(
            collection_name=collection_name
        )

        return json.loads(json.dumps(collection_info, default=lambda x: x.__dict__))

    def index_into_vector_db(
        self, project: Project, chunks: List[DataChunk], do_reset: bool = False
    ):

        collection_name = self.create_collection_name(project_id=project.project_id)

        texts = [c.chunk_text for c in chunks]

        metadata = [c.chunk_metadata for c in chunks]
        record_ids = [str(uuid5(NAMESPACE_URL, str(c.chunk_id))) for c in chunks]

        vectors = self.embedding_client.embed_texts(
            texts=texts, document_type=DocumentTypeEnum.DOCUMENT.value
        )

        if not vectors:
            return False

        if len(vectors) != len(texts):
            return False

        _ = self.vectodb_client.create_collection(
            collection_name=collection_name,
            do_reset=do_reset,
            embedding_size=self.embedding_client.embedding_size,
        )

        is_inserted = self.vectodb_client.insert_many(
            collection_name=collection_name,
            texts=texts,
            metadata=metadata,
            vectors=vectors,
            record_ids=record_ids,
        )

        return is_inserted

    def search_vectordb_collection(self, project: Project, text: str, limit: int = 10):
        collection_name = self.create_collection_name(project_id=project.project_id)

        vector = self.embedding_client.embed_text(
            text=text, document_type=DocumentTypeEnum.QUERY.value
        )

        if not vector or len(vector) == 0:
            return False

        results = self.vectodb_client.search_by_vector(
            collection_name=collection_name, vector=vector, limit=limit
        )

        if not results:
            return False

        return results

    def answer_rag_question(self, project: Project, query: str, limit: int = 10):
        retrieved_documents = self.search_vectordb_collection(
            project=project, text=query, limit=limit
        )
        if not retrieved_documents:
            return None

        system_prompt = self.template_parser.get("rag", "system_prompt")

        document_prompts = "\n".join(
            [
                self.template_parser.get(
                    "rag",
                    "document_prompt",
                    {
                        "doc_num": idx,
                        "chunk_text": self.generation_client.process_text(doc.text),
                    },
                )
                for idx, doc in enumerate(retrieved_documents, start=1)
            ]
        )

        footer_prompt = self.template_parser.get(
            "rag", "footer_prompt", {"query": query}
        )

        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt, role=self.generation_client.enums.SYSTEM.value
            )
        ]

        full_prompt = "\n\n".join([document_prompts, footer_prompt])

        answer = self.generation_client.generate_text(
            prompt=full_prompt, chat_history=chat_history
        )

        return answer, full_prompt, chat_history
