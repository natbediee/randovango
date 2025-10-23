import os
from dotenv import load_dotenv

class ServiceUtil:
    """Static class for handling useful functions."""

    @staticmethod
    def load_env() -> None:
        """Load environment file."""
        load_dotenv(".env")

    @staticmethod
    def get_env(var: str, default: str = "") -> str:
        """Get environment {var} or {default} value."""
        return os.getenv(var, default)
