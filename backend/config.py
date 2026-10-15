from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/db/prepress.db"
    REDIS_URL: str = "redis://redis:6379"
    GROQ_API_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    UPLOAD_DIR: str = "./data/uploads"
    OUTPUT_DIR: str = "./data/outputs"
    # Zprávy pro zákazníky (services/outbox.py). Absolutní cesta: kontejnery mají cwd /app/backend,
    # takže relativní ./data by skončilo v repu místo v bind mountu ./data -> /app/data.
    OUTBOX_DIR: str = "/app/data/outbox"
    # Strata přes ollama-gate na ai-core; strata-batch = nižší priorita než chat/fakturace
    AI_CORE_OLLAMA_URL: str = "http://192.168.0.174:11434"
    CUSTOMER_MSG_MODEL: str = "strata-batch"
    CUSTOMER_MSG_TIMEOUT_S: float = 90.0
    MAX_UPLOAD_SIZE_MB: int = 500
    GHOSTSCRIPT_PATH: str = "/usr/bin/gs"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
