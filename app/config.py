"""运行时配置:从 .env 读取,集中管理。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent          # app/
PROJECT_DIR = BASE_DIR.parent                        # 仓库根目录
WEB_DIR = PROJECT_DIR / "web"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
DATA_DIR = BASE_DIR / "data"

load_dotenv(PROJECT_DIR / ".env", encoding="utf-8-sig")


class Settings:
    """集中式配置;读取一次后缓存。"""

    def __init__(self) -> None:
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.chat_model: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash").strip()
        self.embed_model: str = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001").strip()
        self.embed_dim: int = int(os.getenv("EMBED_DIM", "768"))
        self.port: int = int(os.getenv("PORT", "8000"))
        # Gemini 原生协议的 API 根地址。中转站若兼容 Gemini REST 接口，
        # 可在 .env 中覆盖，例如 https://relay.example.com/v1beta。
        self.api_base: str = os.getenv(
            "GEMINI_API_BASE",
            "https://generativelanguage.googleapis.com/v1beta",
        ).strip().rstrip("/")
        # 教师管理端口令(轻量身份)
        self.teacher_passcode: str = os.getenv("TEACHER_PASSCODE", "888888").strip()
        self.database_backend = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
        if self.database_backend not in {"sqlite", "mysql"}:
            raise ValueError("DATABASE_BACKEND must be sqlite or mysql")
        self.mysql_host = os.getenv("MYSQL_HOST", "127.0.0.1")
        self.mysql_port = int(os.getenv("MYSQL_PORT", "13306"))
        self.mysql_database = os.getenv("MYSQL_DATABASE", "zhixue")
        self.mysql_user = os.getenv("MYSQL_USER", "zhixue")
        self.mysql_password = os.getenv("MYSQL_PASSWORD", "")
        self.vector_backend = os.getenv("VECTOR_BACKEND", "json").strip().lower()
        if self.vector_backend not in {"json", "pgvector"}:
            raise ValueError("VECTOR_BACKEND must be json or pgvector")
        self.pg_host = os.getenv("PGVECTOR_HOST", "127.0.0.1")
        self.pg_port = int(os.getenv("PGVECTOR_PORT", "15432"))
        self.pg_database = os.getenv("PGVECTOR_DATABASE", "zhixue_vectors")
        self.pg_user = os.getenv("PGVECTOR_USER", "zhixue")
        self.pg_password = os.getenv("PGVECTOR_PASSWORD", "")
        self.chat_provider = os.getenv("CHAT_PROVIDER", "gemini").strip().lower()
        self.chat_api_key = os.getenv("CHAT_API_KEY", self.gemini_api_key).strip()
        self.chat_api_base = os.getenv("CHAT_API_BASE", self.api_base).strip().rstrip("/")
        self.chat_model = os.getenv("CHAT_MODEL", self.chat_model).strip()
        self.embed_provider = os.getenv("EMBED_PROVIDER", "gemini").strip().lower()
        self.embed_api_key = os.getenv("EMBED_API_KEY", self.gemini_api_key).strip()
        self.embed_api_base = os.getenv("EMBED_API_BASE", self.api_base).strip().rstrip("/")
        self.embed_model = os.getenv("EMBED_MODEL", self.embed_model).strip()
        if self.chat_provider not in {"gemini", "openai"} or self.embed_provider not in {"gemini", "openai", "local"}:
            raise ValueError("CHAT_PROVIDER must be gemini/openai; EMBED_PROVIDER must be gemini/openai/local")

        # RAG 参数
        self.retrieve_top_k: int = 5
        self.chunk_max_chars: int = 900       # 单个知识块上限
        self.chunk_overlap: int = 120

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path: Path = DATA_DIR / "tutor.db"
        self.index_path: Path = DATA_DIR / "kb_index.json"
        self.document_dir: Path = DATA_DIR / "documents"
        self.document_max_bytes = int(os.getenv("DOCUMENT_MAX_MB", "20")) * 1024 * 1024
        self.document_max_pages = int(os.getenv("DOCUMENT_MAX_PAGES", "300"))

    @property
    def configured(self) -> bool:
        return bool(self.chat_api_key if self.chat_provider == "openai" else
                    (self.chat_api_key or self.gemini_api_key))

    @property
    def embedding_configured(self) -> bool:
        if self.embed_provider == "local":
            return True
        return bool(self.embed_api_key if self.embed_provider == "openai" else
                    (self.embed_api_key or self.gemini_api_key))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
