import mysql.connector
import os
from mysql.connector import Error
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT/".env")

# base mysql
DB_HOST = os.getenv("DB_HOST")
DB_ROOT = os.getenv("DB_ROOT")
DB_ROOT_PSWD = os.getenv("DB_ROOT_PSWD")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PSWD = os.getenv("DB_PSWD")

MYSQL_CONF = {
    'host':     os.getenv('DB_HOST'),
    'user':     os.getenv('DB_USER'),
    'password': os.getenv('DB_PSWD'),
    'database': os.getenv('DB_NAME'),
}

def init_database():
    try:
        # 1. Connexion admin pour créer la base et l'utilisateur
        admin_cnx = mysql.connector.connect(
            host=DB_HOST,
            user=DB_ROOT,
            password=DB_ROOT_PSWD
        )
        admin_cursor = admin_cnx.cursor()
        admin_cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        print(f"Base '{DB_NAME}' créée.")
        admin_cursor.execute(
            f"CREATE USER IF NOT EXISTS '{DB_USER}'@'%' "
            f"IDENTIFIED BY '{DB_PSWD}'"
        )
        admin_cursor.execute(
            f"GRANT ALL PRIVILEGES ON `{DB_NAME}`.* "
            f"TO '{DB_USER}'@'%'"
        )
        admin_cursor.execute("FLUSH PRIVILEGES")
        admin_cnx.commit()
        admin_cursor.close()
        admin_cnx.close()
        print(f"Utilisateur {DB_USER} créé.")

    except Error as err:
        print(f"[Erreur admin] {err}")
        return

    try:
        # 2. Connexion utilisateur pour créer la table randonnée
        user_cnx = mysql.connector.connect(**MYSQL_CONF)
        user_cursor = user_cnx.cursor()

        statements = [
            # table cities
            """
            CREATE TABLE IF NOT EXISTS cities (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table hikes
            """
            CREATE TABLE IF NOT EXISTS hikes (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                start_latitude FLOAT,
                start_longitude FLOAT,
                distance_km FLOAT,
                estimated_duration_h FLOAT,
                elevation_gain_m FLOAT,
                description TEXT,
                city_id INT,
                mongo_id VARCHAR(24),
                source_id INT,
                FOREIGN KEY (city_id) REFERENCES cities(id),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table spots
            """
            CREATE TABLE IF NOT EXISTS spots (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                type VARCHAR(100),
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                address VARCHAR(255),
                rating FLOAT,
                url VARCHAR(512),
                city_id INT,
                source_id INT,
                FOREIGN KEY (city_id) REFERENCES cities(id),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table services
            """
            CREATE TABLE IF NOT EXISTS services (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                service_type VARCHAR(100)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table spot_service
            """
            CREATE TABLE IF NOT EXISTS spot_service (
                spot_id INT NOT NULL,
                service_id INT NOT NULL,
                PRIMARY KEY (spot_id, service_id),
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table sources
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table poi
            """
            CREATE TABLE IF NOT EXISTS poi (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                description TEXT,
                type VARCHAR(100),
                subtype VARCHAR(100),
                latitude FLOAT,
                longitude FLOAT,
                image_url VARCHAR(512),
                url VARCHAR(512),
                mongo_id VARCHAR(24),
                city_id INT,
                source_id INT,
                FOREIGN KEY (city_id) REFERENCES cities(id),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table weather
            """
            CREATE TABLE IF NOT EXISTS weather (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                city_id INT NOT NULL,
                date DATE NOT NULL,
                temp_max_c FLOAT,
                temp_min_c FLOAT,
                precipitation_mm FLOAT,
                wind_max_kmh FLOAT,
                weather_code INT,
                solar_energy_sum FLOAT,
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            # table trip_plans
            """
            CREATE TABLE IF NOT EXISTS trip_plans (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                session_token VARCHAR(64) UNIQUE NOT NULL,
                city_id INT NOT NULL,
                start_date DATE NOT NULL,
                duration_days INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            # table trip_days
            """
            CREATE TABLE trip_days (
                id INT PRIMARY KEY AUTO_INCREMENT,
                trip_plan_id INT NOT NULL,
                day_number INT NOT NULL,
                hike_id INT,
                spot_id INT,
                FOREIGN KEY (trip_plan_id) REFERENCES trip_plans(id) ON DELETE CASCADE,
                FOREIGN KEY (hike_id) REFERENCES hikes(id),
                FOREIGN KEY (spot_id) REFERENCES pois(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            # table trip_day_services
            """
            CREATE TABLE poi (
                trip_day_id INT NOT NULL,
                poi_id INT NOT NULL,
                PRIMARY KEY (trip_day_id, poi_id),
                FOREIGN KEY (trip_day_id) REFERENCES trip_days(id),
                FOREIGN KEY (poi_id) REFERENCES pois(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
        ]
        print("- Création des tables :")
        for stmt in statements:
            user_cursor.execute(stmt)
            print("→ OK :", stmt.strip().split()[5])

        user_cnx.commit()
        user_cursor.close()
        user_cnx.close()
        print("Initialisation de la base terminée avec succès.\n")

    except Error as err:
        print(f"[Erreur user] {err}")

if __name__ == "__main__":
    init_database()
