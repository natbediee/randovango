"""
Le bilan des appels d'agents, lu dans llm_calls (écrite par agents/llm_service.py).

Source du futur tableau de monitorage et du calcul du modèle économique. Chaque bilan
donne, par groupe : le nombre d'appels, les échecs, le coût en dollars, la durée et
les tokens. Un appel raté compte aussi : il a consommé du quota.

Le coût en euros (#275) : calls_cost et run_cost_text convertissent les dollars en euros TTC estimés, au taux de la
BCE, et disent ce que vaut le coût (dépense réelle par l'API, ou équivalent API pour l'abonnement).

Un passage de la chaîne des services (agents/find_services.py) se relit de deux façons : le bilan « passage », une
ligne par passage, et passage_calls, tous ses appels dans l'ordre.

Un appel est rattaché à une commune de trois façons, selon son objet :
    - commune : objet_id est cities.id ;
    - spot    : la commune du spot dans histo_scrap (la plus petite s'il y en a plusieurs) ;
    - plan    : la commune de départ du voyage, trip_plans.city_id.
"""
from datetime import datetime, time

from services import exchange_rate_service
from services.exchange_rate_service import RateUnavailable
from utils.db_utils import MySQLUtils
from utils.paris_time import paris_today

# Ce que vaut le coût d'un appel, selon son moteur (llm_calls.engine) : l'API facture vraiment ce prix ; le programme
# `claude` passe par l'abonnement, et son coût n'est que ce qu'aurait coûté l'appel par l'API.
NATURES = {"api": "dépense réelle", "api-batch": "dépense réelle", "claude-code": "équivalent API, abonnement"}

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
    # Par heure UTC : cost_report range ensuite chaque heure dans son jour de Paris (paris_days, #299).
    "jour": f"""
        SELECT DATE(l.called_at) AS jour_utc, HOUR(l.called_at) AS heure_utc, {TOTALS}
        FROM llm_calls l
        GROUP BY DATE(l.called_at), HOUR(l.called_at)
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


def paris_days(hours: list) -> list:
    """
    Le bilan « jour » à partir du bilan heure UTC par heure UTC : chaque heure va dans son jour de Paris, ses totaux
    s'additionnent, et les jours vont du plus récent au plus ancien. Paris est toujours à un nombre entier d'heures de
    l'UTC : une heure UTC tombe entière dans un seul jour de Paris.
    """
    days = {}
    for row in hours:
        day = paris_today(datetime.combine(row["jour_utc"], time(row["heure_utc"])))
        totals = days.setdefault(day, {"jour": day})
        for name, value in row.items():
            if name not in ("jour_utc", "heure_utc"):
                totals[name] = totals.get(name, 0) + (value or 0)
    return [days[day] for day in sorted(days, reverse=True)]


def cost_report(cursor, by: str) -> list:
    """
    [{groupe..., appels, echecs, cout_usd, ...}] ; `by` vaut agent, jour, voyage, commune ou passage. Le jour est
    celui de Paris (#299).
    """
    if by not in QUERIES:
        raise ValueError(f"Bilan inconnu : {by} (attendu : {', '.join(QUERIES)})")
    cursor.execute(QUERIES[by])
    rows = _dicts(cursor)
    return paris_days(rows) if by == "jour" else rows


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


# --- Le coût en euros (#275) ---

def cost_nature(engines) -> str | None:
    """
    Ce que vaut un coût, d'après les moteurs des appels qu'il additionne : « dépense réelle », « équivalent API,
    abonnement », ou « en partie réelle, en partie équivalent API » quand les deux se mêlent. None sans aucun appel :
    un passage d'une chaîne gratuite (OSM, FINESS, carburants) n'appelle aucun agent, son coût n'est ni l'un ni l'autre.
    """
    natures = {NATURES.get(engine, "équivalent API, abonnement") for engine in engines}
    if len(natures) > 1:
        return "en partie réelle, en partie équivalent API"
    return natures.pop() if natures else None


def calls_cost(calls: list) -> dict:
    """
    Le coût d'une liste d'appels de llm_calls (avec called_at, engine et cost_usd) : en dollars, en euros TTC estimés,
    chaque appel au taux de la BCE de son jour, le taux du dernier jour en clair, et ce que vaut le coût (cost_nature).
    Sans aucun taux connu, cout_eur vaut None et taux dit pourquoi.
    """
    usd_by_day = {}
    for call in calls:
        day = paris_today(call["called_at"])     # le jour de Paris de l'appel, pour son taux (#299)
        usd_by_day[day] = usd_by_day.get(day, 0.0) + float(call["cost_usd"] or 0)
    cost = {"cout_usd": round(sum(usd_by_day.values()), 4), "cout_eur": None, "taux": None,
            "nature_du_cout": cost_nature({call["engine"] for call in calls})}
    if not usd_by_day:
        cost["cout_eur"] = 0.0
        return cost
    try:
        rates = {day: exchange_rate_service.rate_for(day) for day in usd_by_day}
    except RateUnavailable as error:
        cost["taux"] = f"euros inconnus : {error}"
        return cost
    cost["cout_eur"] = round(sum(exchange_rate_service.usd_to_eur(usd, rates[day]) for day, usd in usd_by_day.items()), 2)
    cost["taux"] = exchange_rate_service.rate_label(rates[max(rates)])
    return cost


def run_cost_text(run: dict) -> str:
    """
    La fin d'une ligne du journal d'un agent : durée et coût d'un appel qui vient de finir (last_run du service), en
    dollars et en euros TTC estimés au taux du jour, avec ce que vaut ce coût. « 42 s, 0.53 $ ≈ 0.58 € TTC (équivalent
    API, abonnement ; taux BCE du 19/11/2026 : 1 € = 1.0992 $ (dernier connu)) ».
    """
    nature = NATURES.get(run.get("engine"), NATURES["claude-code"])
    usd = run.get("cost_usd") or 0
    seconds = (run.get("duration_ms") or 0) / 1000
    try:
        rate = exchange_rate_service.rate_for(paris_today())
    except RateUnavailable:
        return f"{seconds:.0f} s, {usd:.2f} $ ({nature} ; euros inconnus, aucun taux de la BCE)"
    eur = exchange_rate_service.usd_to_eur(usd, rate)
    return f"{seconds:.0f} s, {usd:.2f} $ ≈ {eur:.2f} € TTC ({nature} ; {exchange_rate_service.rate_label(rate)})"
