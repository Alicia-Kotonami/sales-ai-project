from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    AI_RUNTIME_HOST: str = "0.0.0.0"
    AI_RUNTIME_PORT: int = 9000
    AI_RUNTIME_PROVIDER: str = "deepseek"  # deepseek | mock
    AI_RUNTIME_TIMEOUT_SECONDS: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
