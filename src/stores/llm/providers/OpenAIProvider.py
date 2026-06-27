import logging
import json
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

from openai import OpenAI, OpenAIError

from ..LLMEnums import OpenAIEnums
from ..LLMInterface import LLMInterface


class OpenAIProvider(LLMInterface):
    MIN_GENERATION_OUTPUT_TOKENS = 2000

    def __init__(
        self,
        api_key: str,
        api_url: str = None,
        default_input_max_characters: int = 1000,
        default_generation_max_output_tokens: int = 1000,
        default_generation_temperature: float = 0.1,
    ):
        self.api_key = api_key
        self.api_url = api_url.strip() if api_url else None

        if self.api_url and not self.api_url.startswith(("http://", "https://")):
            raise ValueError("OPENAI_API_URL must start with 'http://' or 'https://'")

        self.default_input_max_characters = default_input_max_characters
        self.default_generation_max_output_tokens = default_generation_max_output_tokens
        self.default_generation_temperature = default_generation_temperature

        self.generation_model_id = None

        self.embedding_model_id = None
        self.embedding_size = None

        self.enums = OpenAIEnums

        client_options = {"api_key": self.api_key}
        if self.api_url:
            client_options["base_url"] = self.api_url

        self.client = OpenAI(**client_options)

        self.logger = logging.getLogger(__name__)

    def set_generation_model(self, model_id: str):

        self.generation_model_id = model_id

    def set_embedding_model(self, model_id: str, embedding_size: int):
        self.embedding_model_id = model_id
        self.embedding_size = embedding_size

    def process_text(self, text: str):
        return text[: self.default_input_max_characters].strip()

    def is_ollama_endpoint(self):
        return bool(
            self.api_url
            and (
                "11434" in self.api_url
                or "ollama" in self.api_url
                or self.is_ollama_model_id()
            )
        )

    def is_ollama_model_id(self):
        if not self.generation_model_id:
            return False

        model_id = self.generation_model_id.lower()
        ollama_model_names = (
            "qwen",
            "llama",
            "deepseek",
            "gemma",
            "mistral",
            "phi",
        )

        return ":" in model_id and any(name in model_id for name in ollama_model_names)

    def get_ollama_api_url(self):
        parsed_url = urlparse(self.api_url)
        netloc = parsed_url.netloc
        if parsed_url.hostname == "localhost":
            netloc = netloc.replace("localhost", "127.0.0.1", 1)

        return urlunparse(
            (
                parsed_url.scheme,
                netloc,
                "/api/chat",
                "",
                "",
                "",
            )
        )

    def generate_text_with_ollama(
        self,
        messages: list,
        max_output_tokens: int,
        temperature: float,
    ):
        payload = {
            "model": self.generation_model_id,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "num_predict": max_output_tokens,
                "temperature": temperature,
            },
        }

        ollama_api_url = self.get_ollama_api_url()
        request = urllib.request.Request(
            ollama_api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            host = urlparse(ollama_api_url).hostname or ""
            if isinstance(reason, ssl.SSLCertVerificationError) and host.endswith(
                ".ngrok-free.app"
            ):
                self.logger.warning(
                    "Ngrok SSL certificate verification failed; retrying Ollama request without SSL verification for local development."
                )
                unverified_context = ssl._create_unverified_context()
                try:
                    with urllib.request.urlopen(
                        request, timeout=120, context=unverified_context
                    ) as response:
                        response_data = json.loads(response.read().decode("utf-8"))
                except urllib.error.HTTPError as retry_error:
                    error_body = retry_error.read().decode(
                        "utf-8", errors="replace"
                    )
                    self.logger.error(
                        "Ollama request failed: status=%s, body=%s",
                        retry_error.code,
                        error_body,
                    )
                    return None
                except urllib.error.URLError:
                    self.logger.exception("Error while generating text with Ollama")
                    return None
            else:
                self.logger.exception("Error while generating text with Ollama")
                return None
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            self.logger.error(
                "Ollama request failed: status=%s, body=%s",
                e.code,
                error_body,
            )
            return None

        message = response_data.get("message") or {}
        content = message.get("content")
        reasoning = message.get("thinking") or message.get("reasoning")

        self.logger.warning(
            "Ollama response metadata: done=%s, done_reason=%s, has_content=%s, has_reasoning=%s, eval_count=%s",
            response_data.get("done"),
            response_data.get("done_reason"),
            bool(content),
            bool(reasoning),
            response_data.get("eval_count"),
        )

        if not content and reasoning:
            self.logger.error(
                "Ollama returned reasoning-only output even through native /api/chat with think=false."
            )

        return content

    def generate_text(  # type: ignore
        self,
        prompt: str,
        max_output_tokens: int = None,
        chat_history: list = None,
        temperature: float = None,
    ):

        if not self.client:
            self.logger.error("OpenAI client was not set")
            return None

        if not self.generation_model_id:
            self.logger.error("Generation model for OpenAI was not set")

        is_ollama = self.is_ollama_endpoint()
        is_qwen = bool(
            self.generation_model_id and "qwen" in self.generation_model_id.lower()
        )

        max_output_tokens = (
            max_output_tokens
            if max_output_tokens
            else self.default_generation_max_output_tokens
        )
        if is_ollama and is_qwen:
            max_output_tokens = max(
                max_output_tokens, self.MIN_GENERATION_OUTPUT_TOKENS
            )
        temperature = (
            temperature if temperature else self.default_generation_temperature
        )

        messages = list(chat_history or [])
        messages.append(self.construct_prompt(prompt, role=OpenAIEnums.USER.value))
        if is_ollama and is_qwen:
            messages.append({"role": OpenAIEnums.USER.value, "content": "/no_think"})

        if is_ollama:
            return self.generate_text_with_ollama(
                messages=messages,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )

        request_options = {
            "model": self.generation_model_id,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
        }

        try:
            response = self.client.chat.completions.create(**request_options)
        except OpenAIError:
            self.logger.exception("Error while generating text with OpenAI")
            return None

        first_choice = response.choices[0] if response and response.choices else None
        message = first_choice.message if first_choice else None
        self.logger.warning(
            "LLM response metadata: finish_reason=%s, has_content=%s, has_reasoning=%s, usage=%s",
            first_choice.finish_reason if first_choice else None,
            bool(message.content) if message else False,
            bool(getattr(message, "reasoning", None)) if message else False,
            response.usage.model_dump() if response and response.usage else None,
        )

        if (
            not response
            or not response.choices
            or len(response.choices) == 0
            or not response.choices[0].message
        ):
            self.logger.error("Error while generating text with OpenAI")
            return None

        content = response.choices[0].message.content
        reasoning = getattr(response.choices[0].message, "reasoning", None)

        if not content and reasoning:
            self.logger.error(
                "LLM returned reasoning-only output. The selected Ollama model is not producing chat message content; use a non-thinking instruct model or an Ollama model that honors /no_think."
            )
            self.logger.warning(
                "LLM returned reasoning without content; retrying with a direct-answer prompt"
            )
            retry_messages = messages + [
                {
                    "role": OpenAIEnums.USER.value,
                    "content": "Now provide the final answer only. Do not include reasoning or analysis.\n\n/no_think",
                }
            ]
            retry_options = {
                **request_options,
                "messages": retry_messages,
                "max_tokens": max_output_tokens,
            }
            if "extra_body" in retry_options:
                retry_options["extra_body"] = {
                    **retry_options["extra_body"],
                    "options": {"num_predict": max_output_tokens},
                }

            retry_response = self.client.chat.completions.create(**retry_options)
            retry_choice = (
                retry_response.choices[0]
                if retry_response and retry_response.choices
                else None
            )
            retry_message = retry_choice.message if retry_choice else None
            self.logger.warning(
                "LLM retry metadata: finish_reason=%s, has_content=%s, has_reasoning=%s, usage=%s",
                retry_choice.finish_reason if retry_choice else None,
                bool(retry_message.content) if retry_message else False,
                bool(getattr(retry_message, "reasoning", None))
                if retry_message
                else False,
                retry_response.usage.model_dump()
                if retry_response and retry_response.usage
                else None,
            )

            if retry_message and retry_message.content:
                return retry_message.content

        return content

    def embed_text(self, text: str, document_type: str = None):  # type: ignore

        if not self.client:
            self.logger.error("OpenAI client was not set")
            return None

        if not self.embedding_model_id:
            self.logger.error("Embedding model for OpenAI was not set")
            return None

        response = self.client.embeddings.create(
            model=self.embedding_model_id, input=text
        )
        if (
            not response
            or not response.data
            or len(response.data) == 0
            or not response.data[0].embedding
        ):
            self.logger.error("Error while embedding text with OpenAI")
            return None

        return response.data[0].embedding

    def embed_texts(self, texts: list[str], document_type: str = None):  # type: ignore
        if not self.client:
            self.logger.error("OpenAI client was not set")
            return None

        if not self.embedding_model_id:
            self.logger.error("Embedding model for OpenAI was not set")
            return None

        response = self.client.embeddings.create(
            model=self.embedding_model_id,
            input=[self.process_text(text) for text in texts],
        )
        if not response or not response.data or len(response.data) != len(texts):
            self.logger.error("Error while embedding texts with OpenAI")
            return None

        return [item.embedding for item in response.data]

    def construct_prompt(self, prompt: str, role: str):  # type: ignore
        return {"role": role, "content": self.process_text(prompt)}
