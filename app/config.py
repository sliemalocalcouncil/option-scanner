from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    POLYGON_API_KEY: str = ""
    DATABASE_URL: str = "sqlite:///./local.db"
    POLYGON_BASE: str = "https://api.polygon.io"

    # Options Starter 플랜은 15분 지연. 신호/스캐너 모두 지연 기준으로 계산.
    DELAY_MINUTES: int = 15

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
