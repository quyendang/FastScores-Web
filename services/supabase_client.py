import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client | None = None
_bot_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment")
        _client = create_client(url, key)
    return _client


def get_bot_supabase() -> Client:
    global _bot_client
    if _bot_client is None:
        url = os.environ.get("BOT_SUPABASE_URL", "")
        key = os.environ.get("BOT_SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError("BOT_SUPABASE_URL and BOT_SUPABASE_SERVICE_KEY must be set in environment")
        _bot_client = create_client(url, key)
    return _bot_client
