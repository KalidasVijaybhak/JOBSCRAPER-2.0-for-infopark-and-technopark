from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_title: str = "Kerala IT Park Job Scraper"
    app_description: str = "Scrapes job listings from Technopark (Trivandrum) and Infopark (Kochi)"
    app_version: str = "1.1.0"

    technopark_base: str = "https://technopark.in"
    infopark_base: str = "https://infopark.in"

    http_timeout: float = 20.0
    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
