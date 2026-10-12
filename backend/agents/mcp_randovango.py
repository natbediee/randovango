"""
Serveur MCP de Randovango : des outils de LECTURE de la base, que les agents
Claude peuvent appeler QUAND ILS EN ONT BESOIN.

MCP (Model Context Protocol) est le standard qui permet de brancher ses propres
outils sur Claude. Au lieu d'envoyer d'office toutes les informations à l'agent
(au risque de le noyer sous des données inutiles), on lui donne des outils : il
décide lui-même de s'en servir quand la question le demande.

Ce serveur est lancé par le programme `claude` (option --mcp-config, voir
llm_service.py) et communique avec lui par l'entrée et la sortie standard
("stdio"). Conséquence importante : RIEN ne doit être écrit sur la sortie
standard (pas de print), sinon la communication est corrompue. Les logs, eux,
partent sur la sortie d'erreur.

Outils disponibles :
  - temoignages_commune(spot_id) : ce que disent les voyageurs, sur les AUTRES
    spots de la même commune, à propos des règles de stationnement de nuit.

Lancement manuel pour tester : python /usr/src/app/agents/mcp_randovango.py
"""
import sys
from pathlib import Path

# Le programme `claude` lance ce fichier depuis un autre dossier : on ajoute le
# dossier du backend au chemin de recherche pour pouvoir importer utils.*.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from utils.db_utils import MySQLUtils  # noqa: E402
from utils.service_utils import ServiceUtil  # noqa: E402

server = MCPServer("randovango")

# Nombre maximum de témoignages renvoyés (les plus récents d'abord).
MAX_TESTIMONIES = 15

# Un témoignage n'est retenu que s'il parle À LA FOIS d'une règle...
RULE_WORDS = "interdi|police|verbalis|amende|arrêté|gendarm|panneau|autoris"
# ... et du stationnement de nuit (pour écarter, par exemple, "un panneau
# indique le robinet d'eau propre"). Expressions régulières MySQL.
NIGHT_WORDS = "nuit|nuitée|dormir|stationn|camping.?car|fourgon|bivouac"

# "Même commune" : même nom de commune s'il est connu, sinon à moins de ~3 km
# (0.03° de latitude ≈ 3,3 km ; 0.045° de longitude ≈ 3,3 km en Bretagne).
NEARBY_LAT, NEARBY_LON = 0.03, 0.045


def commune_testimonies(cursor, spot_id: int) -> list:
    """
    Témoignages des AUTRES spots de la commune du spot `spot_id` qui parlent
    de règles de stationnement de nuit. Renvoie une liste de
    (date, nom du spot, texte), du plus récent au plus ancien.
    """
    cursor.execute("SELECT latitude, longitude, city_label FROM spots WHERE id = %s", (spot_id,))
    row = cursor.fetchone()
    if row is None:
        return []
    latitude, longitude, city_label = row

    cursor.execute(
        """
        SELECT r.review_date, s.name, r.text
        FROM spot_reviews r
        JOIN spots s ON s.id = r.spot_id
        WHERE s.id <> %s
          AND (s.city_label = %s
               OR (s.latitude BETWEEN %s AND %s AND s.longitude BETWEEN %s AND %s))
          AND r.text REGEXP %s
          AND r.text REGEXP %s
        ORDER BY r.review_date DESC
        LIMIT %s
        """,
        (
            spot_id, city_label,
            latitude - NEARBY_LAT, latitude + NEARBY_LAT,
            longitude - NEARBY_LON, longitude + NEARBY_LON,
            RULE_WORDS, NIGHT_WORDS, MAX_TESTIMONIES,
        ),
    )
    return cursor.fetchall()


@server.tool()
def temoignages_commune(spot_id: int) -> str:
    """
    Témoignages de voyageurs, sur les AUTRES spots de la même commune, à propos
    des règles de stationnement de nuit (interdictions, contrôles de police,
    panneaux). Utile pour savoir si une interdiction concerne toute la commune
    et si elle est saisonnière (contrôles seulement en été, pas de panneau hors
    saison) ou permanente.
    """
    ServiceUtil.load_env()
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    try:
        rows = commune_testimonies(cursor, spot_id)
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)

    if not rows:
        return "Aucun témoignage sur les règles de stationnement dans la commune."
    lines = []
    for review_date, spot_name, text in rows:
        day = review_date.strftime("%d/%m/%Y") if review_date else "date inconnue"
        lines.append(f'- {day}, {spot_name} : "{" ".join((text or "").split())}"')
    return "\n".join(lines)


if __name__ == "__main__":
    server.run("stdio")
