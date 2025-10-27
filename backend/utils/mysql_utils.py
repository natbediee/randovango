import mysql.connector
from dotenv import load_dotenv
from pathlib import Path
from utils.service_utils import ServiceUtil

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT/".env")


class MySQLUtils:
    """Utilitaire statique pour MySQL."""
    @staticmethod
    def connect():
        ServiceUtil.load_env()
        return mysql.connector.connect(
            host=ServiceUtil.get_env('DB_HOST'),
            user=ServiceUtil.get_env('DB_USER'),
            password=ServiceUtil.get_env('DB_PSWD'),
            database=ServiceUtil.get_env('DB_NAME'),
            charset='utf8mb4'
        )

    @staticmethod
    def get_cursor(conn):
        return conn.cursor()

    @staticmethod
    def disconnect(conn):
        if conn:
            conn.close()
