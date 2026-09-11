import os
from pathlib import Path
from dotenv import load_dotenv

# プロジェクトルートの.envを読み込み
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

# Streamlit Cloud (st.secrets) サポート
try:
    import streamlit as st
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if k not in os.environ and isinstance(v, str):
                os.environ[k] = v
except Exception:
    pass


# Notion API設定
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

# Gemini API設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# 個別DB設定（指定があれば優先、無ければ共通NOTION_DATABASE_ID）
NOTION_ARTICLES_DB_ID = os.getenv("NOTION_ARTICLES_DB_ID", "").strip() or NOTION_DATABASE_ID
NOTION_SEARCH_DB_ID = os.getenv("NOTION_SEARCH_DB_ID", "").strip() or NOTION_DATABASE_ID
NOTION_QUOTES_DB_ID = os.getenv("NOTION_QUOTES_DB_ID", "").strip() or NOTION_DATABASE_ID

# クロール・スクレイピング設定
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "3"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.0"))


def validate_notion_config(db_type: str = "default") -> tuple[bool, str]:
    """Notion設定が有効かチェックする"""
    if not NOTION_API_KEY or NOTION_API_KEY.startswith("ntn_your_") or NOTION_API_KEY.startswith("secret_your_"):
        return False, "Notion APIキー (NOTION_API_KEY) が設定されていないか、サンプルのままです。.envファイルを確認してください。"
    
    target_db = NOTION_DATABASE_ID
    if db_type == "articles" and NOTION_ARTICLES_DB_ID:
        target_db = NOTION_ARTICLES_DB_ID
    elif db_type == "search" and NOTION_SEARCH_DB_ID:
        target_db = NOTION_SEARCH_DB_ID
    elif db_type == "quotes" and NOTION_QUOTES_DB_ID:
        target_db = NOTION_QUOTES_DB_ID

    if not target_db or target_db.startswith("your_"):
        return False, f"Notion データベースID ({db_type}) が設定されていません。.envファイルを確認してください。"
        
    return True, ""
