from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure
from utils.service_utils import ServiceUtil

ServiceUtil.load_env()
DATABASE_NAME = ServiceUtil.get_env("DATABASE_NAME")
class MongoUtils:
    """Utilitaire statique pour MongoDB."""
    client: MongoClient = None

    @staticmethod
    def connect():
        # MongoClient gère déjà un pool de connexions thread-safe : on le crée une
        # seule fois et on le réutilise. Le recréer à chaque appel provoquait une
        # course entre requêtes concurrentes (l'une pouvait fermer la connexion
        # qu'une autre était en train d'utiliser, cf. /hike/{id}/trace en step2).
        if MongoUtils.client is not None:
            return
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
            client = MongoClient(url)
            client.admin.command('ping')
            MongoUtils.client = client
        except ConnectionFailure as e:
            raise RuntimeError("MongoDB connection failed") from e

    @staticmethod
    def disconnect():
        # No-op : le client est partagé entre toutes les requêtes, il ne doit pas
        # être fermé par une requête individuelle (voir connect() ci-dessus).
        pass

    @staticmethod
    def get_database() -> Database:
        return MongoUtils.client.get_database(DATABASE_NAME)

    @staticmethod
    def get_collection(name: str) -> Collection:
        return MongoUtils.get_database().get_collection(name)
