"""
Les taux de change du dollar en base : les lire et les écrire (issue #275).

Les taux sont dans la table exchange_rates (déclarée dans db_init) : une ligne par jour où la Banque centrale
européenne a publié un taux. Ce fichier ne contient que les requêtes ; la lecture du site de la BCE et la conversion
sont dans exchange_rate_service.py.
"""
from datetime import date, datetime

from utils.db_utils import MySQLUtils


def rate_on_or_before(day: date) -> dict | None:
    """
    Le dernier taux publié le jour `day` ou avant : {"rate_date", "usd_per_eur"}, ou None si la table n'en a aucun
    d'aussi ancien. Le week-end et les jours fériés, c'est donc le taux du dernier jour ouvré.
    """
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        cursor.execute("""SELECT rate_date, usd_per_eur FROM exchange_rates
                          WHERE rate_date <= %s ORDER BY rate_date DESC LIMIT 1""", (day,))
        row = cursor.fetchone()
    return row


def oldest_rate() -> dict | None:
    """Le plus ancien taux gardé, pour un appel plus vieux que tous les taux connus ; None si la table est vide."""
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        cursor.execute("SELECT rate_date, usd_per_eur FROM exchange_rates ORDER BY rate_date LIMIT 1")
        row = cursor.fetchone()
    return row


def last_fetch() -> datetime | None:
    """Quand les taux ont été lus sur le site de la BCE pour la dernière fois ; None s'ils ne l'ont jamais été."""
    with MySQLUtils.open_cursor() as (connection, cursor):
        cursor.execute("SELECT MAX(fetched_at) FROM exchange_rates")
        fetched_at = cursor.fetchone()[0]
    return fetched_at


def save_rates(rates: dict, fetched_at: datetime) -> None:
    """
    Écrit les taux {jour: dollars pour un euro}. Un jour déjà connu est réécrit : la BCE ne change pas un taux publié,
    mais fetched_at dit ainsi quand on a regardé pour la dernière fois.
    """
    with MySQLUtils.open_cursor() as (connection, cursor):
        cursor.executemany("""INSERT INTO exchange_rates (rate_date, usd_per_eur, fetched_at) VALUES (%s, %s, %s)
                              ON DUPLICATE KEY UPDATE usd_per_eur = VALUES(usd_per_eur), fetched_at = VALUES(fetched_at)""",
                           [(day, rate, fetched_at) for day, rate in rates.items()])
        connection.commit()
