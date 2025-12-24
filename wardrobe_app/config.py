from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str = "8582666055:AAEH0QVbIAsmAfHV4EUN92333ojX_CPB0ck"
    DATABASE_URL: str = "sqlite+aiosqlite:///wardrobe_bot.db"
    WEATHERAPI_KEY: str = "f5ae1146d4c8afc02f9344e3a1f84edf"
    HUGGINGFACE_API_KEY: str = "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"

    class Config:
        env_file = "../.env"


settings = Settings()