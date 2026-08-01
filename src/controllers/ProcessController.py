import os
from dataclasses import dataclass
from typing import List

from langchain_community.document_loaders import PyMuPDFLoader, TextLoader
from langchain_core.documents import Document  # type: ignore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from models import ProcessingEnum

from .BaseController import BaseController
from .ProjectController import ProjectController


@dataclass
class Document:
    page_content: str
    metadata: dict


class ProcessController(BaseController):

    def __init__(self, project_id: int):
        super().__init__()

        self.project_id = project_id
        self.project_path = ProjectController().get_project_path(project_id=project_id)

    def get_file_extension(self, file_id: str):
        return os.path.splitext(file_id)[-1]

    def get_file_loader(self, file_id: str):
        file_ext = self.get_file_extension(file_id=file_id)
        file_path = os.path.join(self.project_path, file_id)

        if not os.path.exists(file_path):
            return None

        if file_ext == ProcessingEnum.TXT.value:
            return TextLoader(file_path=file_path, encoding="UTF-8")

        elif file_ext == ProcessingEnum.PDF.value:
            return PyMuPDFLoader(file_path=file_path)

        return None

    def get_file_content(self, file_id: str):

        loader = self.get_file_loader(file_id=file_id)

        if loader:
            return loader.load()
        else:
            return None

    def process_file_content(
        self,
        file_content: list[Document],
        file_id: str,
        chunk_size: int = 100,
        overlap_size: int = 20,
    ):

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap_size,
            length_function=len,
        )

        file_content_texts = [rec.page_content for rec in file_content]

        file_content_metaddata = [rec.metadata for rec in file_content]

        # chunks = text_splitter.create_documents(
        #     file_content_texts, metadatas=file_content_metaddata
        # )

        chunks = self.process_simpler_splitter(
            texts=file_content_texts,
            metadatas=file_content_metaddata,
            chunk_size=chunk_size,
        )

        return chunks

    def process_simpler_splitter(
        self,
        texts: List[str],
        metadatas: List[dict],
        chunk_size: int,
        splitter_tag: str = "\n",
    ):

        full_text = " ".join(texts)

        lines = [
            doc.strip() for doc in full_text.split(splitter_tag) if len(doc.strip()) > 1
        ]

        chunks = []

        current_chunk = ""

        for line in lines:
            current_chunk += line + splitter_tag
            if len(current_chunk) >= chunk_size:
                chunks.append(Document(page_content=current_chunk.strip(), metadata={}))

                current_chunk = ""

        if len(current_chunk) >= 0:
            chunks.append(Document(page_content=current_chunk.strip(), metadata={}))

        return chunks
