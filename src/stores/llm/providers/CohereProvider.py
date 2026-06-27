import logging

import cohere

from ..LLMEnums import CoHereEnums, DocumentTypeEnum
from ..LLMInterface import LLMInterface


class CoHereProvider(LLMInterface):
    def __init__(
        self,
        api_key: str,
        default_input_max_characters: int = 1000,
        default_generation_max_output_tokens: int = 1000,
        default_generation_temperature: float = 0.1,
    ):
        self.api_key = api_key

        self.default_input_max_characters = default_input_max_characters
        self.default_generation_max_output_tokens = default_generation_max_output_tokens
        self.default_generation_temperature = default_generation_temperature

        self.generation_model_id = None

        self.embedding_model_id = None
        self.embedding_size = None

        self.enums = CoHereEnums

        self.client = cohere.ClientV2(api_key=self.api_key)

        self.logger = logging.getLogger(__name__)

    def set_generation_model(self, model_id: str):
        self.generation_model_id = model_id

    def set_embedding_model(self, model_id: str, embedding_size: int):
        self.embedding_model_id = model_id
        self.embedding_size = embedding_size

    def process_text(self, text: str):
        return text[: self.default_input_max_characters].strip()

    def generate_text(  # type: ignore
        self,
        prompt: str,
        max_output_tokens: int = None,
        chat_history: list = None,
        temperature: float = None,
    ):

        if not self.client:
            self.logger.error("CoHere client was not set")
            return None

        if not self.generation_model_id:
            self.logger.error("Generation model for CoHere was not set")

        max_output_tokens = (
            max_output_tokens
            if max_output_tokens
            else self.default_generation_max_output_tokens
        )
        temperature = (
            temperature if temperature else self.default_generation_temperature
        )

        chat_history = chat_history or []
        chat_history.append(self.construct_prompt(prompt, role=CoHereEnums.USER.value))

        response = self.client.chat(
            model=self.generation_model_id,
            messages=chat_history,
            temperature=temperature,
            max_tokens=max_output_tokens,
        )

        if not response or not response.message.content[0].text:
            self.logger.error("Error while generating text with CoHere")
            return None

        return response.message.content[0].text

    def embed_text(self, text: str, document_type: str = None):  # type: ignore
        if not self.client:
            self.logger.error("CoHere client was not set")
            return None

        if not self.embedding_model_id:
            self.logger.error("Embedding model for CoHere was not set")
            return None

        input_type = CoHereEnums.DOCUMENT.value

        if document_type == DocumentTypeEnum.QUERY.value:
            input_type = CoHereEnums.QUERY.value

        try:
            response = self.client.embed(
                model=self.embedding_model_id,
                texts=[self.process_text(text)],
                input_type=input_type,
                output_dimension=self.embedding_size,
                embedding_types=["float"],
            )
        except Exception as e:
            self.logger.error(f"Error While embeddding text with CoHere: {e}")
            return None

        if not response or not response.embeddings or not response.embeddings.float_:
            self.logger.error("Error While embeddding text with CoHere")
            return None
        return response.embeddings.float_[0]

    def embed_texts(self, texts: list[str], document_type: str = None):  # type: ignore
        if not self.client:
            self.logger.error("CoHere client was not set")
            return None

        if not self.embedding_model_id:
            self.logger.error("Embedding model for CoHere was not set")
            return None

        input_type = CoHereEnums.DOCUMENT.value

        if document_type == DocumentTypeEnum.QUERY.value:
            input_type = CoHereEnums.QUERY.value

        try:
            response = self.client.embed(
                model=self.embedding_model_id,
                texts=[self.process_text(text) for text in texts],
                input_type=input_type,
                output_dimension=self.embedding_size,
                embedding_types=["float"],
            )
        except Exception as e:
            self.logger.error(f"Error While embeddding texts with CoHere: {e}")
            return None

        if (
            not response
            or not response.embeddings
            or not response.embeddings.float_
            or len(response.embeddings.float_) != len(texts)
        ):
            self.logger.error("Error While embeddding texts with CoHere")
            return None

        return response.embeddings.float_

    def construct_prompt(self, prompt: str, role: str):  # type: ignore
        return {"role": role, "content": self.process_text(prompt)}
