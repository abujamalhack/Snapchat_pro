import os
import yaml
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

@dataclass
class BotConfig:
    token: str
    admin_ids: List[int]
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    concurrent_downloads: int = 5
    request_timeout: int = 30
    temp_dir: str = "./temp"
    log_level: str = "INFO"
    
@dataclass
class SnapConfig:
    user_agents: List[str] = None
    api_endpoints: dict = None
    retry_attempts: int = 3
    cache_ttl: int = 300
    
class ConfigManager:
    def __init__(self):
        self.bot = self._load_bot_config()
        self.snap = self._load_snap_config()
        
    def _load_bot_config(self) -> BotConfig:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        admin_ids = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
        
        return BotConfig(
            token=token,
            admin_ids=admin_ids,
            max_file_size=int(os.getenv("MAX_FILE_SIZE", "104857600")),
            concurrent_downloads=int(os.getenv("CONCURRENT_DOWNLOADS", "5")),
            temp_dir=os.getenv("TEMP_DIR", "./temp_downloads")
        )
    
    def _load_snap_config(self) -> SnapConfig:
        return SnapConfig(
            user_agents=[
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15",
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
            ],
            api_endpoints={
                "story": "https://story.snapchat.com/s/{}",
                "spotlight": "https://www.snapchat.com/spotlight/{}",
                "public_api": "https://snapchat.com/api/{}"
            },
            retry_attempts=3
        )
    
config = ConfigManager()