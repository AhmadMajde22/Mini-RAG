from typing import Optional

from pydantic_settings import BaseSettings, SecretsSettingsSource


class Settings(BaseSettings):

    APP_NAME: str
    APP_VERSION: str

    FILE_ALLOOWED_TYPES: list
    FILE_MAX_SIZE: int
    FILE_DEFAULT_CHUNK_SIZE: int

    POSTGRES_USERNAME: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_MAIN_DATABASE: str

    # MONGODB_URL: str
    # MONGODB_DATABASE: str

    GENERATION_BACKEND: str
    EMBEDDING_BACKEND: str

    OPENAI_API_KEY: str
    OPENAI_API_URL: Optional[str] = None
    COHERE_API_KEY: str

    GENERATION_MODEL_ID: str
    EMBEDDING_MODEL_ID: str
    EMBEDDING_MODEL_SIZE: int

    INPUT_DEFAULT_MAX_CHARACTERS: int
    GENERATION_DEFAULT_MAX_TOKENS: int
    GENERATION_DEFAULT_TEMPERATURE: float

    VECTOR_DB_BACKEND: str
    VECTOR_DB_PATH: str
    VECTOR_DB_DISTANCE_METHOD: str

    DEFAULT_LANG: str
    PRIMARY_LANG: str

    class Config:
        env_file = ".env"


def get_settings():
    return Settings()
