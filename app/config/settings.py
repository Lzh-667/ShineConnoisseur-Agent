from pathlib import Path
from urllib.parse import quote_plus

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
    # 计费（元/百万 token，按 DeepSeek 官网当前价格填写）
    deepseek_input_price: float = 0.0
    deepseek_output_price: float = 0.0

    # Embedding (SiliconFlow BGE-M3)
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # MySQL
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""

    # Redis
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # Elasticsearch
    es_url: str = ""

    # 后端 REST API
    backend_url: str = "http://localhost:8080"

    # Agent 服务
    agent_host: str = "0.0.0.0"
    agent_port: int = 8001
    agent_checkpoint: str = "sqlite"  # sqlite | memory
    chat_rate_limit: int = 10  # 每分钟聊天次数
    agent_cookie_secure: bool = False  # HTTPS 部署时设为 true
    admin_tool_invoke_enabled: bool = False

    def validate_runtime_config(self) -> None:
        """在服务启动时拒绝缺失的生产依赖，避免悄悄连到错误环境。"""
        required = {
            "MYSQL_HOST": self.mysql_host,
            "MYSQL_USER": self.mysql_user,
            "MYSQL_PASSWORD": self.mysql_password,
            "MYSQL_DATABASE": self.mysql_database,
            "REDIS_HOST": self.redis_host,
            "ES_URL": self.es_url,
            "DEEPSEEK_API_KEY": self.deepseek_api_key,
            "SILICONFLOW_API_KEY": self.siliconflow_api_key,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"缺少必要运行配置：{', '.join(missing)}")

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def checkpoint_db_path(self) -> str:
        return str(BASE_DIR / "data" / "agent_checkpoints.db")


settings = Settings()
