"""
Les réglages des agents et leurs dépenses en base : les lire et les écrire (issues #211 et #275).

Les réglages sont dans la table agent_settings (déclarée dans db_init) : une ligne par changement, la plus récente est
celle qui vaut. Les montants y sont en euros (_eur) et, pour les branches qui les lisent encore, en dollars (_usd).
Les dépenses sont lues dans llm_calls, qui garde le prix de chaque appel d'agent en dollars.
Ce fichier ne contient que les requêtes ; les règles du budget sont dans budget_service.py.
"""
from datetime import datetime, time

from utils.db_utils import MySQLUtils
from utils.paris_time import paris_today


def load_latest() -> dict | None:
    """Le réglage en vigueur : la ligne la plus récente de agent_settings, ou None si personne n'a encore rien réglé."""
    # L'id plutôt que la date : deux changements dans la même seconde auraient la même date.
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        cursor.execute("""SELECT services_after_etl, monthly_budget_usd, daily_budget_usd, vany_reserve_usd,
                                 monthly_budget_eur, daily_budget_eur, vany_reserve_eur, changed_at, changed_by, reason
                          FROM agent_settings ORDER BY id DESC LIMIT 1""")
        row = cursor.fetchone()
    return row


def insert(settings: dict, changed_by: str, reason: str | None = None) -> None:
    """
    Écrit un nouveau réglage complet ; l'ancien reste en base, comme trace de qui a changé quoi, quand et pourquoi
    (reason, facultatif). `settings` donne les montants en euros et en dollars.
    """
    with MySQLUtils.open_cursor() as (connection, cursor):
        cursor.execute("""INSERT INTO agent_settings (services_after_etl, monthly_budget_usd, daily_budget_usd,
                                                      vany_reserve_usd, monthly_budget_eur, daily_budget_eur,
                                                      vany_reserve_eur, changed_at, changed_by, reason)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                       (settings["services_after_etl"], settings["monthly_budget_usd"], settings["daily_budget_usd"],
                        settings["vany_reserve_usd"], settings["monthly_budget_eur"], settings["daily_budget_eur"],
                        settings["vany_reserve_eur"], datetime.now(), changed_by, reason))
        connection.commit()


def spent_by_day(start: datetime) -> dict:
    """
    Ce qu'ont coûté les appels d'agents depuis `start`, jour par jour, en dollars : {jour: dollars}. Le prix est celui
    de llm_calls (réel pour l'API, équivalent API pour l'abonnement). Jour par jour, parce que chaque jour se convertit
    en euros à son propre taux. Tous les agents comptent (services, spots, pépites, Vany) : l'enveloppe est une seule.
    Le jour est celui de Paris (#299) : un appel fait à 0 h 30 à Paris compte le jour qui commence, au taux de ce jour.
    """
    # La base est en UTC. On additionne heure UTC par heure UTC, puis on range chaque heure dans son jour de Paris :
    # Paris est toujours à un nombre entier d'heures de l'UTC, une heure UTC tombe donc entière dans un seul jour de
    # Paris. Lire les appels un par un ferait des dizaines de milliers de lignes par mois.
    with MySQLUtils.open_cursor() as (connection, cursor):
        cursor.execute("""SELECT DATE(called_at), HOUR(called_at), SUM(cost_usd) FROM llm_calls
                          WHERE called_at >= %s AND cost_usd IS NOT NULL
                          GROUP BY DATE(called_at), HOUR(called_at)""", (start,))
        rows = cursor.fetchall()
    by_day = {}
    for day, hour, total in rows:
        paris_day = paris_today(datetime.combine(day, time(hour)))
        by_day[paris_day] = by_day.get(paris_day, 0.0) + float(total)
    return by_day
