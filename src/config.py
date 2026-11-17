from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    max_upload_mb: int = int(os.getenv("BUGTRACE_MAX_UPLOAD_MB", "2"))
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

settings = Settings()
