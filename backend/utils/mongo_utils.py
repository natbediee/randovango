from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure
from backend.utils.service_utils import ServiceUtil

ServiceUtil.load_env()
DATABASE_NAME = ServiceUtil.get_env("DATABASE_NAME")
class MongoUtils:
    """Utilitaire statique pour MongoDB."""
    client: MongoClient = None

    @staticmethod
    def connect():
        ServiceUtil.load_env()
        username = ServiceUtil.get_env("MONGO_INITDB_ROOT_USERNAME", "")
        password = ServiceUtil.get_env("MONGO_INITDB_ROOT_PASSWORD", "")
        host = ServiceUtil.get_env("MONGO_HOST", "localhost")
        port = ServiceUtil.get_env("MONGO_PORT", "27017")
        if username and password and username.strip() and password.strip():
            url = f"mongodb://{username.strip()}:{password.strip()}@{host}:{port}"
        else:
            url = f"mongodb://{host}:{port}"
        try:
            MongoUtils.client = MongoClient(url)
            MongoUtils.client.admin.command('ping')
        except ConnectionFailure as e:
            raise RuntimeError("MongoDB connection failed") from e

    @staticmethod
    def disconnect():
        if MongoUtils.client:
            MongoUtils.client.close()

    @staticmethod
    def get_database() -> Database:
        return MongoUtils.client.get_database(DATABASE_NAME)

    @staticmethod
    def get_collection(name: str) -> Collection:
        return MongoUtils.get_database().get_collection(name)
