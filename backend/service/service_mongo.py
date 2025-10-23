"""Service for handling connection to MongoDB for Randovango."""

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure

from services.util import ServiceUtil

DATABASE_NAME = "randovango"

class ServiceMongo:
    """Static class for handling MongoDB."""

    client: MongoClient = None

    @classmethod
    def connect(cls) -> None:
        """Create MongoClient."""
        ServiceUtil.load_env()
        username = ServiceUtil.get_env("MONGO_INITDB_ROOT_USERNAME")
        password = ServiceUtil.get_env("MONGO_INITDB_ROOT_PASSWORD")
        url = f"mongodb://{username}:{password}@mongo:27017"
        try:
            cls.client = MongoClient(url)
        except ConnectionFailure as e:
            raise RuntimeError from e

    @classmethod
    def disconnect(cls) -> None:
        """Close MongoClient."""
        if cls.client:
            cls.client.close()

    @classmethod
    def get_collection(cls, name: str) -> Collection:
        """Get MongoDB collection by {name}."""
        database = cls.get_database()
        return database.get_collection(name=name)

    @classmethod
    def get_database(cls) -> Database:
        """Get MongoDB database."""
        return cls.client.get_database(DATABASE_NAME)
