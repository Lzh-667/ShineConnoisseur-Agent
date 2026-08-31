from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM (DeepSeek)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_reasoner_model: str = "deepseek-v4-flash"

    # Embedding (SiliconFlow BGE-M3)
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # MySQL
    mysql_host: str = "192.168.100.129"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "shineconnoisseur"

    # Redis
    redis_host: str = "192.168.100.129"
    redis_port: int = 6379
    redis_password: str = "123456"
    redis_db: int = 0

    # Elasticsearch
    es_url: str = "http://192.168.100.129:9200"

    # 后端 REST API
    backend_url: str = "http://localhost:8080"

    # Agent 服务
    agent_host: str = "0.0.0.0"
    agent_port: int = 8001
    agent_checkpoint: str = "sqlite"  # sqlite | memory
    chat_rate_limit: int = 10  # 每分钟聊天次数

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def checkpoint_db_path(self) -> str:
        return str(BASE_DIR / "data" / "agent_checkpoints.db")


settings = Settings()
