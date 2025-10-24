import os
from dotenv import load_dotenv

class ServiceUtil:
    """Static class for handling useful functions."""

    @staticmethod
    def load_env() -> None:
        """Load environment file and log if missing."""
        from pathlib import Path
        env_path = Path(".env")
        load_dotenv(str(env_path))

    @staticmethod
    def get_env(var: str, default: str = "") -> str:
        """Get environment {var} or {default} value."""
        return os.getenv(var, default)
