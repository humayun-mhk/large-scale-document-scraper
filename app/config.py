from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    target_base_url: str
    download_dir: str = "./data"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
