"""
Les réglages des agents et leurs dépenses en base : les lire et les écrire (issue #211).

Les réglages sont dans la table agent_settings (déclarée dans db_init) : une ligne par changement, la plus récente est
celle qui vaut. Les dépenses sont lues dans llm_calls, qui garde le prix de chaque appel d'agent.
Ce fichier ne contient que les requêtes ; les règles du budget sont dans budget_service.py.
"""
from datetime import datetime

from utils.db_utils import MySQLUtils


def load_latest() -> dict | None:
    """Le réglage en vigueur : la ligne la plus récente de agent_settings, ou None si personne n'a encore rien réglé."""
    # L'id plutôt que la date : deux changements dans la même seconde auraient la même date.
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        cursor.execute("""SELECT services_after_etl, monthly_budget_usd, daily_budget_usd, vany_reserve_usd,
                                 changed_at, changed_by, reason
                          FROM agent_settings ORDER BY id DESC LIMIT 1""")
        row = cursor.fetchone()
    return row


def insert(settings: dict, changed_by: str, reason: str | None = None) -> None:
    """
    Écrit un nouveau réglage complet ; l'ancien reste en base, comme trace de qui a changé quoi, quand et pourquoi
    (reason, facultatif).
    """
    with MySQLUtils.open_cursor() as (connection, cursor):
        cursor.execute("""INSERT INTO agent_settings (services_after_etl, monthly_budget_usd, daily_budget_usd,
                                                      vany_reserve_usd, changed_at, changed_by, reason)
                          VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                       (settings["services_after_etl"], settings["monthly_budget_usd"], settings["daily_budget_usd"],
                        settings["vany_reserve_usd"], datetime.now(), changed_by, reason))
        connection.commit()


def spent_since(start: datetime) -> float:
    """
    Ce qu'ont coûté tous les appels d'agents depuis `start`, en dollars : le prix équivalent API de llm_calls,
    abonnement compris. Tous les agents comptent (services, spots, pépites, Vany) : l'enveloppe est une seule.
    """
    with MySQLUtils.open_cursor() as (connection, cursor):
        cursor.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE called_at >= %s", (start,))
        total = cursor.fetchone()[0]
    return float(total)
