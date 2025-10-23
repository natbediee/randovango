from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure

from backend.utils.service_util import ServiceUtil

DATABASE_NAME = "randovango"

class ServiceMongo:
    """Static class for handling MongoDB."""

    client: MongoClient = None

    @classmethod
    def connect(cls) -> None:
        """Create MongoClient using env variables via ServiceUtil."""
        ServiceUtil.load_env()
        username = ServiceUtil.get_env("MONGO_INITDB_ROOT_USERNAME", "")
        password = ServiceUtil.get_env("MONGO_INITDB_ROOT_PASSWORD", "")
        host = ServiceUtil.get_env("MONGO_HOST", "localhost")
        port = ServiceUtil.get_env("MONGO_PORT", "27017")
        
        # Si username et password sont fournis ET non vides, utiliser l'authentification
        if username and password and username.strip() and password.strip():
            url = f"mongodb://{username.strip()}:{password.strip()}@{host}:{port}"
        else:
            # Sinon, connexion sans authentification
            url = f"mongodb://{host}:{port}"
        
        try:
            cls.client = MongoClient(url)
            # Test de la connexion
            cls.client.admin.command('ping')
        except ConnectionFailure as e:
            raise RuntimeError("MongoDB connection failed") from e

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
