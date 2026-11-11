"""
Toute la structure de la base MySQL : à relancer sans risque, en « create or alter ».
Une table absente est créée ; une colonne absente d'une table existante est ajoutée, avec sa clé
étrangère si elle en a une, et un index nommé absent est ajouté. Le script n'écrit aucune donnée et ne
supprime ni ne renomme rien.
Une colonne existante n'est pas modifiée : changer son type reste un geste à faire à la main.
"""
import re
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from utils.logger_util import LoggerUtil

import mysql.connector
from utils.db_utils import MySQLUtils
from mysql.connector import Error
from utils.service_utils import ServiceUtil
logger = LoggerUtil.get_logger("db_init")

ServiceUtil.load_env()

# base mysql
DB_HOST = ServiceUtil.get_env("DB_HOST")
DB_ROOT = ServiceUtil.get_env("DB_ROOT")
DB_ROOT_PSWD = ServiceUtil.get_env("DB_ROOT_PSWD")
DB_NAME = ServiceUtil.get_env("DB_NAME")
DB_USER = ServiceUtil.get_env("DB_USER")
DB_PSWD = ServiceUtil.get_env("DB_PSWD")

NOT_A_COLUMN = ("PRIMARY", "UNIQUE", "FOREIGN", "INDEX", "KEY", "CONSTRAINT")


def parse_create_table(statement: str) -> tuple:
    """(table, {colonne: définition}, {colonne: clé étrangère}) d'après un CREATE TABLE IF NOT EXISTS."""
    table = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", statement).group(1)
    columns, foreign_keys = {}, {}
    for line in statement.splitlines()[2:]:
        line = line.strip().rstrip(",")
        if not line or line.startswith(")"):
            continue
        name, definition = line.split(None, 1)
        if name.upper() not in NOT_A_COLUMN:
            columns[name] = definition
        elif name.upper() == "FOREIGN":
            foreign_keys[re.search(r"KEY \((\w+)\)", line).group(1)] = line
    return table, columns, foreign_keys


def add_missing_columns(cursor, database: str, statement: str) -> list:
    """Ajoute à une table existante les colonnes de sa définition qui lui manquent. Renvoie leurs noms."""
    table, columns, foreign_keys = parse_create_table(statement)
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
                   (database, table))
    existing = {row[0] for row in cursor.fetchall()}
    missing = [column for column in columns if column not in existing]
    for column in missing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {columns[column]}")
        if column in foreign_keys:
            cursor.execute(f"ALTER TABLE {table} ADD {foreign_keys[column]}")
        logger.info(f"[MySQL] :→ Colonne ajoutée : {table}.{column}")
    return missing


def add_missing_indexes(cursor, database: str, statement: str) -> list:
    """
    Ajoute à une table existante les index nommés de sa définition qui lui manquent (« INDEX nom (colonnes) »). Renvoie
    leurs noms. Une colonne ajoutée après coup arrive ainsi avec son index : llm_calls.passage_id, le 11 novembre 2026.
    """
    table = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", statement).group(1)
    wanted = dict(re.findall(r"^\s*INDEX (\w+) (\([^)]*\))", statement, re.M))
    cursor.execute("SELECT DISTINCT index_name FROM information_schema.statistics WHERE table_schema = %s AND table_name = %s",
                   (database, table))
    existing = {row[0] for row in cursor.fetchall()}
    missing = [name for name in wanted if name not in existing]
    for name in missing:
        cursor.execute(f"ALTER TABLE {table} ADD INDEX {name} {wanted[name]}")
        logger.info(f"[MySQL] :→ Index ajouté : {table}.{name}")
    return missing


def init_database():
    max_retries = 10
    retry_delay = 2  # secondes
    
    # Attendre que MySQL soit prêt
    for attempt in range(max_retries):
        try:
            test_cnx = mysql.connector.connect(
                host=DB_HOST,
                user=DB_ROOT,
                password=DB_ROOT_PSWD
            )
            test_cnx.close()
            logger.info(f"[MySQL] :✓ MySQL est prêt après {attempt + 1} tentative(s)")
            break
        except Error as err:
            if attempt < max_retries - 1:
                logger.warning(f"[MySQL] : MySQL pas encore prêt (tentative {attempt + 1}/{max_retries}): {err}")
                time.sleep(retry_delay)
            else:
                logger.error(f"[MySQL] : ✗ ERREUR: Impossible de se connecter à MySQL après {max_retries} tentatives")
                sys.exit(1)
    
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
        logger.info(f"[MySQL] : Base '{DB_NAME}' créée.")
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
        logger.info(f"[MySQL] : Utilisateur {DB_USER} créé.")

    # Liste des statements pour la création des tables
        statements = [
            # 1. tables de base sans dépendances
            # 1. table cities
            # name est le lieu que connaît le voyageur (Trézien, Portsall) ; commune et insee, la commune officielle
            # qui le contient (Plouarzel, 29177), d'après geo.api.gouv.fr. Vides si l'API n'a pas répondu.
            """
            CREATE TABLE IF NOT EXISTS cities (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                department VARCHAR(255),
                region VARCHAR(255),
                country VARCHAR(255),
                commune VARCHAR(255),
                insee CHAR(5)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 2. table sources
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 3. table services
            """
            CREATE TABLE IF NOT EXISTS services (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                category VARCHAR(100)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 4. table spots (dépend de sources)
            """
            CREATE TABLE IF NOT EXISTS spots (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                type VARCHAR(100),
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                p4n_id VARCHAR(10),
                rating FLOAT,
                url VARCHAR(512),
                source_id INT,
                verifie BOOL DEFAULT FALSE,
                address VARCHAR(512),
                postal_code VARCHAR(5),
                city_label VARCHAR(120),
                place_label VARCHAR(255),
                description_ia TEXT,
                harmonized_at DATETIME,
                prompt_version INT,
                a_verifier TINYINT(1),
                nuit_interdite TINYINT(1),
                opening_period VARCHAR(255),
                ouverture_statut VARCHAR(12),
                ouverture_debut CHAR(5),
                ouverture_fin CHAR(5),
                ouverture_lue VARCHAR(255),
                price_parking VARCHAR(255),
                price_services VARCHAR(255),
                details_scraped_at DATETIME,
                p4n_removed TINYINT(1) NOT NULL DEFAULT 0,
                duplicate_of_spot_id INT NULL,
                UNIQUE (p4n_id),
                FOREIGN KEY (duplicate_of_spot_id) REFERENCES spots(id),
                INDEX idx_spots_latlon (latitude, longitude),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 5. tables histo scrap par rapport à spots et cities
            """
            CREATE TABLE IF NOT EXISTS histo_scrap (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                spot_id INT NOT NULL,
                city_id INT NOT NULL,
                scraped_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (spot_id, city_id),
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 6. table spot_service (association Spot <-> services)
            """
            CREATE TABLE IF NOT EXISTS spot_service (
                spot_id INT NOT NULL,
                service_id INT NOT NULL,
                source VARCHAR(10) NOT NULL DEFAULT 'p4n',
                PRIMARY KEY (spot_id, service_id),
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 6 bis. commentaires p4n des spots (échantillon, sans auteur)
            """
            CREATE TABLE IF NOT EXISTS spot_reviews (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                spot_id INT NOT NULL,
                p4n_review_id VARCHAR(20) NOT NULL,
                review_date DATE,
                rating TINYINT,
                text TEXT,
                UNIQUE (p4n_review_id),
                FOREIGN KEY (spot_id) REFERENCES spots(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 6 ter. vérifications web des situations temporaires (une ligne par vérification)
            """
            CREATE TABLE IF NOT EXISTS spot_verifications (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                spot_id INT NOT NULL,
                verified_at DATETIME NOT NULL,
                statut VARCHAR(20) NOT NULL,
                resume TEXT,
                sources JSON,
                prompt_version INT,
                model VARCHAR(50),
                a_savoir JSON,
                utilisable VARCHAR(3),
                utilisable_a_partir DATE,
                raison TEXT,
                FOREIGN KEY (spot_id) REFERENCES spots(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 7. hikes (dépend de sources, cities)
            """
            CREATE TABLE IF NOT EXISTS hikes (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                start_latitude FLOAT,
                start_longitude FLOAT,
                distance_km FLOAT,
                estimated_duration_h FLOAT,
                elevation_gain_m FLOAT,
                difficulte VARCHAR(10),
                filename VARCHAR(255),
                mongo_id VARCHAR(24),
                source_id INT,
                city_id INT,
                verifie BOOL DEFAULT FALSE,
                imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                address VARCHAR(512),
                INDEX idx_hikes_latlon (start_latitude, start_longitude),
                FOREIGN KEY (source_id) REFERENCES sources(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 8. poi (dépend de cities, sources)
            # maps_url : le lien Google Maps qu'un admin a saisi dans /supervision, à la place de celui que le code fabrique
            """
            CREATE TABLE IF NOT EXISTS poi (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                description TEXT,
                latitude FLOAT,
                longitude FLOAT,
                image_url VARCHAR(512),
                url VARCHAR(512),
                original_id VARCHAR(255),
                source_id INT,
                verifie BOOL DEFAULT FALSE,
                masque TINYINT(1) NOT NULL DEFAULT 0,
                ferme_moment TINYINT(1) NOT NULL DEFAULT 0,
                statut_saison VARCHAR(10),
                mois_ouverture JSON,
                address VARCHAR(512),
                maps_url VARCHAR(512),
                unique (original_id, source_id),
                INDEX idx_poi_latlon (latitude, longitude),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9.table histo_poi (liaison ville <-> poi, avec date)
            """
            CREATE TABLE IF NOT EXISTS histo_poi (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                poi_id INT NOT NULL,
                city_id INT NOT NULL,
                inserted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (poi_id, city_id),
                FOREIGN KEY (poi_id) REFERENCES poi(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9 bis. vérifications des POI (une ligne par source), dernière réponse brute.
            """
            CREATE TABLE IF NOT EXISTS poi_checks (
                poi_id INT NOT NULL,
                source VARCHAR(20) NOT NULL,
                checked_at DATETIME NOT NULL,
                result JSON,
                PRIMARY KEY (poi_id, source),
                FOREIGN KEY (poi_id) REFERENCES poi(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9 ter. ce que les vérifications signalent sur un POI, à relire avant toute correction
            """
            CREATE TABLE IF NOT EXISTS poi_signals (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                poi_id INT NOT NULL,
                source VARCHAR(20) NOT NULL,
                signal_type VARCHAR(30) NOT NULL,
                detail JSON,
                statut VARCHAR(10) NOT NULL DEFAULT 'a_relire',
                detected_at DATETIME NOT NULL,
                reviewed_at DATETIME,
                UNIQUE (poi_id, source, signal_type),
                FOREIGN KEY (poi_id) REFERENCES poi(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9 quater. spécialisation de poi : un restaurant est un POI avec des attributs en plus
            """
            CREATE TABLE IF NOT EXISTS restaurants (
                poi_id INT NOT NULL PRIMARY KEY,
                genre VARCHAR(100) NOT NULL,
                pourquoi TEXT,
                budget VARCHAR(50),
                jours_fermeture VARCHAR(150),
                distinction VARCHAR(100),
                ancien_nom VARCHAR(255),
                categorie VARCHAR(30),
                registre_depuis DATE,
                prompt_version INT,
                model VARCHAR(50),
                trouve_le DATETIME NOT NULL,
                FOREIGN KEY (poi_id) REFERENCES poi(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9 quater bis. spécialisation de poi : un commerce (boulangerie, épicerie, marché, producteur) trouvé
            # par l'agent find_commerces.py. « jours » : le jour et l'heure d'un marché, lus sur une page acceptée.
            """
            CREATE TABLE IF NOT EXISTS commerces (
                poi_id INT NOT NULL PRIMARY KEY,
                genre VARCHAR(100) NOT NULL,
                pourquoi TEXT,
                jours VARCHAR(150),
                ancien_nom VARCHAR(255),
                categorie VARCHAR(30),
                registre_depuis DATE,
                prompt_version INT,
                model VARCHAR(50),
                trouve_le DATETIME NOT NULL,
                FOREIGN KEY (poi_id) REFERENCES poi(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9 quinquies. les pages qui prouvent qu'un POI existe
            """
            CREATE TABLE IF NOT EXISTS poi_preuves (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                poi_id INT NOT NULL,
                url VARCHAR(512) NOT NULL,
                type_page VARCHAR(20) NOT NULL,
                porte_sur VARCHAR(20),
                citation TEXT,
                citation_trouvee TINYINT(1),
                date_page DATE,
                periode_affichee VARCHAR(255),
                verdict VARCHAR(20) NOT NULL,
                controle_le DATETIME NOT NULL,
                FOREIGN KEY (poi_id) REFERENCES poi(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9 sexies. spécialisation de poi : une station déclarée sur prix-carburants.gouv.fr.
            # Le fichier de l'État prouve que la station existe ; OSM ne donne que la marque, par l'identifiant
            # ref:FR:prix-carburants. Le nom et la position affichés sont dans poi (position OSM : celle de l'État est
            # parfois arrondie). L'adresse, la ville et la position de l'État sont gardées telles quelles.
            """
            CREATE TABLE IF NOT EXISTS stations_carburant (
                poi_id INT NOT NULL PRIMARY KEY,
                pdv_id VARCHAR(10) NOT NULL,
                osm_element VARCHAR(30),
                lien_osm VARCHAR(12) NOT NULL,
                marque VARCHAR(100),
                adresse_etat VARCHAR(255),
                code_postal CHAR(5),
                ville_etat VARCHAR(120),
                latitude_etat DOUBLE,
                longitude_etat DOUBLE,
                route CHAR(1),
                automate_24_24 TINYINT(1),
                horaires JSON,
                services JSON,
                fermeture_type VARCHAR(12),
                fermeture_debut DATETIME,
                fermeture_fin DATETIME,
                lu_le DATETIME NOT NULL,
                UNIQUE (pdv_id),
                FOREIGN KEY (poi_id) REFERENCES poi(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9 septies. le dernier prix connu de chaque carburant d'une station (dépend de stations_carburant).
            # releve_le est la date où la station a déclaré son prix (attribut maj du fichier), pas celle de notre passage.
            # Un carburant en rupture définitive n'est pas vendu : il n'a pas de prix.
            """
            CREATE TABLE IF NOT EXISTS prix_carburants (
                poi_id INT NOT NULL,
                carburant VARCHAR(10) NOT NULL,
                prix DECIMAL(5,3),
                releve_le DATETIME,
                rupture_type VARCHAR(12),
                rupture_debut DATETIME,
                rupture_fin DATETIME,
                PRIMARY KEY (poi_id, carburant),
                FOREIGN KEY (poi_id) REFERENCES stations_carburant(poi_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 10.table poi_service (association POI <-> services)
            """
            CREATE TABLE IF NOT EXISTS poi_service (
                poi_id INT NOT NULL,
                service_id INT NOT NULL,
                PRIMARY KEY (poi_id, service_id),
                FOREIGN KEY (poi_id) REFERENCES poi(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 11. weather (dépend de cities)
            """
            CREATE TABLE IF NOT EXISTS weather (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                date DATE NOT NULL,
                temp_max_c FLOAT,
                temp_min_c FLOAT,
                precipitation_mm FLOAT,
                wind_max_kmh FLOAT,
                weather_code INT,
                solar_energy_sum FLOAT,
                city_id INT NOT NULL,
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 12. trip_plans (dépend de cities)
            """
            CREATE TABLE IF NOT EXISTS trip_plans (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                start_date DATE NOT NULL,
                duration_days INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                city_id INT NOT NULL,
                user_token VARCHAR(64),
                user_id INT,
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 13. trip_days (dépend de trip_plans, hikes, poi)
            """
            CREATE TABLE IF NOT EXISTS trip_days (
                id INT PRIMARY KEY AUTO_INCREMENT,
                trip_plan_id INT NOT NULL,
                day_number INT NOT NULL,
                hike_id INT,
                spot_id INT,
                city_id INT,
                FOREIGN KEY (trip_plan_id) REFERENCES trip_plans(id) ON DELETE CASCADE,
                FOREIGN KEY (hike_id) REFERENCES hikes(id),
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 14. trip_day_pois (dépend de trip_days, poi)
            """
            CREATE TABLE IF NOT EXISTS trip_day_pois (
                trip_day_id INT NOT NULL,
                poi_id INT NOT NULL,
                PRIMARY KEY (trip_day_id, poi_id),
                FOREIGN KEY (trip_day_id) REFERENCES trip_days(id),
                FOREIGN KEY (poi_id) REFERENCES poi(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 15. pepites : les idées trouvées par l'agent
            """
            CREATE TABLE IF NOT EXISTS pepites (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                nom VARCHAR(255) NOT NULL,
                categorie VARCHAR(20) NOT NULL,
                description TEXT,
                commune VARCHAR(100),
                themes JSON,
                lieu VARCHAR(255),
                adresse VARCHAR(255),
                latitude DOUBLE NOT NULL,
                longitude DOUBLE NOT NULL,
                position_source VARCHAR(20),
                position_url VARCHAR(500),
                located_version INT,
                located_at DATETIME,
                date_debut DATE,
                date_fin DATE,
                jours_semaine JSON,
                horaires VARCHAR(100),
                heure_debut FLOAT,
                tarif VARCHAR(50),
                creneau VARCHAR(10) NOT NULL,
                duree_h FLOAT,
                exterieur TINYINT(1) NOT NULL DEFAULT 1,
                permanent TINYINT(1) NOT NULL DEFAULT 0,
                note INT,
                sources JSON,
                found_at DATETIME NOT NULL,
                verified_at DATETIME NOT NULL,
                prompt_version INT,
                model VARCHAR(50)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 16. pepite_recherches : les recherches déjà faites, pour ne pas rappeler l'agent
            """
            CREATE TABLE IF NOT EXISTS pepite_recherches (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                latitude DOUBLE NOT NULL,
                longitude DOUBLE NOT NULL,
                jour DATE NOT NULL,
                jour_fin DATE NOT NULL,
                searched_at DATETIME NOT NULL,
                nb_trouvees INT NOT NULL,
                type VARCHAR(10) NOT NULL DEFAULT 'agenda',
                prompt_version INT NOT NULL,
                trip_day_id INT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 17. trip_day_pepites : les idées proposées pour un jour (dépend de trip_days, pepites)
            """
            CREATE TABLE IF NOT EXISTS trip_day_pepites (
                trip_day_id INT NOT NULL,
                pepite_id INT NOT NULL,
                statut VARCHAR(10) NOT NULL DEFAULT 'proposee',
                pourquoi TEXT,
                moment VARCHAR(15),
                coup_de_coeur TINYINT(1) NOT NULL DEFAULT 0,
                vue TINYINT(1) NOT NULL DEFAULT 0,
                PRIMARY KEY (trip_day_id, pepite_id),
                FOREIGN KEY (trip_day_id) REFERENCES trip_days(id) ON DELETE CASCADE,
                FOREIGN KEY (pepite_id) REFERENCES pepites(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 18. decisions : ce qu'un humain a tranché (qui, quand, quoi, pourquoi)
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                objet_type VARCHAR(20) NOT NULL,
                objet_id INT NOT NULL,
                decision VARCHAR(20) NOT NULL,
                note VARCHAR(255),
                decided_by VARCHAR(100) NOT NULL,
                decided_at DATETIME NOT NULL,
                verification_id INT,
                annulee_at DATETIME,
                a_savoir_corrige TEXT,
                detail JSON,
                INDEX idx_decisions_objet (objet_type, objet_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 19. llm_calls : une ligne par appel d'agent (agents/llm_service.py), réussi ou non.
            # cost_usd est le prix équivalent API ; objet_type vaut commune, spot ou plan, comme objet_id
            # renvoie à cities, spots ou trip_plans (sans clé étrangère : une mesure ne bloque aucune suppression).
            # passage_id : le passage d'une commune par la chaîne des services (agents/find_services.py), le même pour
            # toutes ses catégories et tous ses appels ; etape : la place de l'appel dans le passage (« année 2 »,
            # « zone 3 / 10, analyse », « preuves, lot 2 »).
            """
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                called_at DATETIME NOT NULL,
                agent VARCHAR(50),
                engine VARCHAR(20) NOT NULL,
                model VARCHAR(100) NOT NULL,
                effort VARCHAR(10),
                duration_ms INT,
                input_tokens INT,
                output_tokens INT,
                cache_read_tokens INT,
                cache_write_tokens INT,
                web_searches INT,
                cost_usd DECIMAL(10,4),
                turns INT,
                tools JSON,
                status VARCHAR(10) NOT NULL,
                error VARCHAR(255),
                objet_type VARCHAR(20),
                objet_id INT,
                passage_id CHAR(32),
                etape VARCHAR(80),
                INDEX idx_llm_calls_date (called_at),
                INDEX idx_llm_calls_agent (agent),
                INDEX idx_llm_calls_objet (objet_type, objet_id),
                INDEX idx_llm_calls_passage (passage_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
        ]
        ("- Création des tables :")
        user_cnx = MySQLUtils.connect()
        user_cursor = user_cnx.cursor()
        for stmt in statements:
            try:
                user_cursor.execute(stmt)
                try:
                    user_cursor.fetchall()
                except Exception:
                    pass
                add_missing_columns(user_cursor, DB_NAME, stmt)
                add_missing_indexes(user_cursor, DB_NAME, stmt)
                logger.info(f"[MySQL] :→ OK : {stmt.strip().split()[5]}")
            except Exception as table_err:
                logger.error(f"[MySQL] :✗ [ERREUR SQL] lors de la création: {table_err}\nStatement:\n{stmt}")
                user_cursor.close()
                user_cnx.close()
                sys.exit(1)
        user_cnx.commit()
        user_cursor.close()
        user_cnx.close()
        logger.info("[MySQL] : Initialisation de la base terminée avec succès.")
        return True

    except Error as err:
        logger.error(f"[MySQL] :✗ [ERREUR] {err}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[MySQL] :✗ [ERREUR] {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_database()
