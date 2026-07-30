"""
Nettoyage déterministe de la table `spots`, à passer avant tout enrichissement
IA : tout ce qui est calculable sans modèle l'est ici, pour que l'agent n'ait
plus à traiter que ce qui relève vraiment du texte libre.

Rejouable et non destructif :
  1. catégorise les services P4N encore à NULL (mapping service_utils)
  2. ajoute les colonnes postal_code / city_label / place_label si absentes
  3. éclate `name` ("(29200) Brest - 172 Rue de Quimper") dans ces colonnes
  4. répare les mojibake résiduels (double encodage UTF-8 lu en latin-1)
  5. RAPPORTE les paires de spots quasi confondus - sans rien supprimer :
     à 80 m, deux parkings distincts existent, la fusion demande un arbitrage.

Usage (depuis /usr/src/app dans le conteneur backend) : python -m etl.clean_spots
"""
from math import asin, cos, radians, sin, sqrt

from etl.transform.transform_p4n import parse_spot_name
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil
from utils.service_utils import SERVICE_CATEGORY_MAP

logger = LoggerUtil.get_logger("etl_clean_spots")

# Colonnes issues du parsing de `name`, ajoutées si le schéma est antérieur.
NEW_SPOT_COLUMNS = {
    "postal_code": "VARCHAR(5)",
    "city_label": "VARCHAR(120)",
    "place_label": "VARCHAR(255)",
}

# Deux spots plus proches que ce seuil sont signalés comme doublon potentiel.
DUPLICATE_RADIUS_M = 80


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distance orthodromique en mètres entre deux points."""
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 6371000 * 2 * asin(sqrt(a))


def categorize_services(cursor) -> int:
    """Renseigne services.category pour les services P4N encore sans catégorie."""
    cursor.execute("SELECT id, name FROM services WHERE category IS NULL OR category = ''")
    rows = cursor.fetchall()
    updated = 0
    for service_id, name in rows:
        category = SERVICE_CATEGORY_MAP.get(name)
        if not category:
            logger.warning(f"[clean] Service sans catégorie et absent du mapping : '{name}' (id={service_id})")
            continue
        cursor.execute("UPDATE services SET category = %s WHERE id = %s", (category, service_id))
        logger.info(f"[clean] Service '{name}' → catégorie '{category}'")
        updated += 1
    logger.info(f"[clean] {updated}/{len(rows)} service(s) sans catégorie corrigé(s)")
    return updated


def add_missing_columns(cursor, database: str) -> None:
    """Ajoute les colonnes de parsing absentes du schéma (idempotent)."""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'spots'",
        (database,),
    )
    existing = {row[0] for row in cursor.fetchall()}
    for column, sql_type in NEW_SPOT_COLUMNS.items():
        if column in existing:
            continue
        cursor.execute(f"ALTER TABLE spots ADD COLUMN {column} {sql_type}")
        logger.info(f"[clean] Colonne spots.{column} ajoutée ({sql_type})")


def parse_names(cursor) -> int:
    """Éclate `name` en postal_code / city_label / place_label sur tous les spots."""
    cursor.execute("SELECT id, name FROM spots WHERE name IS NOT NULL")
    rows = cursor.fetchall()
    updated, without_place = 0, 0
    for spot_id, name in rows:
        postal_code, city, place = parse_spot_name(name)
        if not place:
            without_place += 1
        cursor.execute(
            "UPDATE spots SET postal_code = %s, city_label = %s, place_label = %s WHERE id = %s",
            (postal_code, city, place, spot_id),
        )
        updated += 1
    logger.info(f"[clean] {updated} spot(s) parsé(s), dont {without_place} sans libellé de lieu exploitable")
    return updated


# Séquences produites par un UTF-8 relu en latin-1 ("é" → "Ã©", "'" → "â€™").
# Exigées en plus du test de ré-encodage : celui-ci réussit aussi sur du texte
# sain purement latin-1, qu'il ne faut évidemment pas toucher.
MOJIBAKE_MARKERS = ("Ã", "â€", "Â")


def _decode_mojibake(text):
    """
    Retourne le texte re-décodé, ou tel quel si ce n'est pas du double encodage.

    La détection se fait en Python et non en SQL : la collation utf8mb4_unicode_ci
    est insensible aux accents, un LIKE '%Ã%' remonterait tous les 'a' accentués
    de la base.
    """
    if not text or not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def fix_mojibake(cursor) -> int:
    """Répare les textes doublement encodés (UTF-8 relu en latin-1 : "Ã©" pour "é")."""
    cursor.execute("SELECT id, name, description FROM spots")
    rows = cursor.fetchall()
    fixed = 0
    for spot_id, name, description in rows:
        fixed_name = _decode_mojibake(name)
        fixed_description = _decode_mojibake(description)
        if fixed_name == name and fixed_description == description:
            continue
        cursor.execute(
            "UPDATE spots SET name = %s, description = %s WHERE id = %s",
            (fixed_name, fixed_description, spot_id),
        )
        logger.info(f"[clean] Mojibake corrigé sur le spot {spot_id} : {name!r} → {fixed_name!r}")
        fixed += 1
    logger.info(f"[clean] {fixed} spot(s) au texte doublement encodé corrigé(s)")
    return fixed


def report_geographic_duplicates(cursor) -> list:
    """
    Liste les paires de spots distants de moins de DUPLICATE_RADIUS_M.

    Volontairement en lecture seule : deux emplacements à 80 m peuvent être un
    seul lieu saisi deux fois sur Park4Night comme deux parkings bien distincts.
    Le tri se fait sur un pré-filtre par boîte englobante pour éviter le produit
    cartésien complet.
    """
    cursor.execute(
        "SELECT id, name, type, latitude, longitude FROM spots"
        " WHERE id > 0 AND latitude IS NOT NULL AND longitude IS NOT NULL"
        " ORDER BY latitude"
    )
    spots = cursor.fetchall()
    # ~0.001° de latitude ≈ 111 m : au-delà de cet écart en latitude, deux spots
    # triés par latitude ne peuvent plus être à moins de 80 m.
    lat_window = 0.001
    pairs = []
    for i, (spot_id, name, spot_type, lat, lon) in enumerate(spots):
        for other in spots[i + 1:]:
            other_id, other_name, other_type, other_lat, other_lon = other
            if other_lat - lat > lat_window:
                break
            distance = _haversine_m(lat, lon, other_lat, other_lon)
            if distance < DUPLICATE_RADIUS_M:
                pairs.append((distance, spot_id, name, spot_type, other_id, other_name, other_type))

    pairs.sort()
    logger.info(f"[clean] {len(pairs)} paire(s) de spots à moins de {DUPLICATE_RADIUS_M} m (aucune suppression)")
    for distance, spot_id, name, spot_type, other_id, other_name, other_type in pairs:
        logger.info(
            f"[clean:doublon] {distance:5.1f} m | #{spot_id} {name} [{spot_type}]"
            f"  ~  #{other_id} {other_name} [{other_type}]"
        )
    return pairs


def main():
    from utils.service_utils import ServiceUtil

    ServiceUtil.load_env()
    database = ServiceUtil.get_env("DB_NAME")

    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()

    categorize_services(cursor)
    add_missing_columns(cursor, database)
    parse_names(cursor)
    fix_mojibake(cursor)
    cnx.commit()

    report_geographic_duplicates(cursor)

    cursor.close()
    MySQLUtils.disconnect(cnx)
    logger.info("[clean] Nettoyage déterministe terminé")


if __name__ == "__main__":
    main()
