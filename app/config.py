from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: SecretStr
    WEBHOOK_SECRET: SecretStr
    PROVIDER_TIMEOUT: int = 60
    ALPHA_URL: str = "http://localhost:8001"
    BETA_URL: str = "http://localhost:8002"
    SERVICE_URL: str = "http://localhost:8000"
    SEND_TIMEOUT: float = 5
    WATCHDOG_INTERVAL: float = 2

settings = Settings()
