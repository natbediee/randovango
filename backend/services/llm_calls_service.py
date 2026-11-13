"""
Le bilan des appels d'agents, lu dans llm_calls (écrite par agents/llm_service.py).

Source du futur tableau de monitorage et du calcul du modèle économique. Chaque bilan
donne, par groupe : le nombre d'appels, les échecs, le coût équivalent API, la durée et
les tokens. Un appel raté compte aussi : il a consommé du quota.

Un passage de la chaîne des services (agents/find_services.py) se relit de deux façons : le bilan « passage », une
ligne par passage, et passage_calls, tous ses appels dans l'ordre.

Un appel est rattaché à une commune de trois façons, selon son objet :
    - commune : objet_id est cities.id ;
    - spot    : la commune du spot dans histo_scrap (la plus petite s'il y en a plusieurs) ;
    - plan    : la commune de départ du voyage, trip_plans.city_id.
"""
from utils.db_utils import MySQLUtils

TOTALS = """
    COUNT(*) AS appels,
    SUM(l.status <> 'reussi') AS echecs,
    COALESCE(SUM(l.cost_usd), 0) AS cout_usd,
    COALESCE(SUM(l.duration_ms), 0) AS duree_ms,
    COALESCE(SUM(l.input_tokens), 0) AS tokens_entree,
    COALESCE(SUM(l.output_tokens), 0) AS tokens_sortie
"""

QUERIES = {
    "agent": f"""
        SELECT l.agent AS agent, {TOTALS}
        FROM llm_calls l
        GROUP BY l.agent
        ORDER BY cout_usd DESC
    """,
    "jour": f"""
        SELECT DATE(l.called_at) AS jour, {TOTALS}
        FROM llm_calls l
        GROUP BY DATE(l.called_at)
        ORDER BY jour DESC
    """,
    "voyage": f"""
        SELECT l.objet_id AS plan_id, {TOTALS}
        FROM llm_calls l
        WHERE l.objet_type = 'plan'
        GROUP BY l.objet_id
        ORDER BY cout_usd DESC
    """,
    "commune": f"""
        SELECT c.id AS city_id, c.name AS commune, {TOTALS}
        FROM llm_calls l
        LEFT JOIN (SELECT spot_id, MIN(city_id) AS city_id FROM histo_scrap GROUP BY spot_id) hs
               ON l.objet_type = 'spot' AND hs.spot_id = l.objet_id
        LEFT JOIN trip_plans tp ON l.objet_type = 'plan' AND tp.id = l.objet_id
        JOIN cities c ON c.id = CASE l.objet_type
                                    WHEN 'commune' THEN l.objet_id
                                    WHEN 'spot' THEN hs.city_id
                                    WHEN 'plan' THEN tp.city_id
                                END
        GROUP BY c.id, c.name
        ORDER BY cout_usd DESC
    """,
    "passage": f"""
        SELECT l.passage_id AS passage_id, MIN(l.called_at) AS debut, MIN(c.name) AS commune, {TOTALS}
        FROM llm_calls l
        LEFT JOIN cities c ON l.objet_type = 'commune' AND c.id = l.objet_id
        WHERE l.passage_id IS NOT NULL
        GROUP BY l.passage_id
        ORDER BY debut DESC
    """,
}

PASSAGE_CALLS = """
    SELECT l.called_at, l.agent, l.etape, l.status, l.duration_ms, l.cost_usd, l.web_searches, l.turns, l.error
    FROM llm_calls l
    WHERE l.passage_id = %s
    ORDER BY l.called_at, l.id
"""


def _dicts(cursor) -> list:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def passage_calls(cursor, passage_id: str) -> list:
    """
    Tous les appels d'un passage, dans l'ordre : quel agent, à quelle étape (« zone 3 / 10, année 2 », « analyse »,
    « preuves, lot 2 »), avec son statut, sa durée, son coût et ses recherches web. On y lit ce qui a été refait
    (« preuves, lot 1, lieu par lieu ») et ce qui a échoué.
    """
    cursor.execute(PASSAGE_CALLS, (passage_id,))
    return _dicts(cursor)


def cost_report(cursor, by: str) -> list:
    """[{groupe..., appels, echecs, cout_usd, ...}] ; `by` vaut agent, jour, voyage, commune ou passage."""
    if by not in QUERIES:
        raise ValueError(f"Bilan inconnu : {by} (attendu : {', '.join(QUERIES)})")
    cursor.execute(QUERIES[by])
    return _dicts(cursor)


def load_cost_report(by: str) -> list:
    """Le même bilan, lu directement dans la base."""
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        rows = cost_report(cursor, by)
        cursor.close()
        return rows
    finally:
        MySQLUtils.disconnect(connection)
