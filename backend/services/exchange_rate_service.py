"""
Le coût des agents en euros (issue #275) : le taux de la Banque centrale européenne, et la conversion.

POURQUOI UNE CONVERSION
Le fournisseur des agents facture en dollars : llm_calls garde le coût de chaque appel en dollars (cost_usd). Pour
la France, la banque convertit puis la TVA à 20 % s'ajoute. L'administratrice raisonne en euros : on convertit au
moment d'afficher ou de comparer au budget, jamais dans llm_calls. Le résultat est une estimation, en euros TTC :
le taux réel de la banque et ses frais ne sont connus que sur le relevé.

LE TAUX
Le taux de référence de la BCE, publié chaque jour ouvré vers 16 h, sur un fichier public et sans clé. On lit le
fichier des 90 derniers jours, une fois par jour au plus, et on garde les taux du dollar dans exchange_rates.
Un appel est converti au taux de son jour. Un jour sans taux (week-end, jour férié, ou taux du jour pas encore
publié ou pas encore lu), on prend le dernier taux connu avant ce jour, et on le dit.
"""
import xml.etree.ElementTree as ElementTree
from datetime import date, datetime

import requests

from services import exchange_rate_store
from utils.logger_util import LoggerUtil
from utils.paris_time import paris_today

logger = LoggerUtil.get_logger("exchange_rates")

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
VAT = 1.20  # la TVA française, ajoutée à la facture du fournisseur

# Le jour du dernier essai raté de lecture de la BCE : on ne réessaie pas à chaque conversion, seulement le lendemain
# (ou au redémarrage de l'application). Rien n'est perdu entre-temps : le dernier taux connu sert.
_failed_on = None


class RateUnavailable(RuntimeError):
    """Aucun taux connu du tout : la BCE n'a jamais pu être lue. On ne peut pas estimer un coût en euros."""


def parse_usd_rates(xml_text: str) -> dict:
    """
    Les taux du dollar d'un fichier de la BCE : {jour: dollars pour un euro}.
    Le fichier range un bloc par jour, <Cube time="2026-11-20">, et dedans une ligne par monnaie,
    <Cube currency="USD" rate="1.0812"/>.
    """
    rates = {}
    for day_block in ElementTree.fromstring(xml_text).iter():
        if day_block.get("time") is None:
            continue
        for line in day_block:
            if line.get("currency") == "USD":
                rates[date.fromisoformat(day_block.get("time"))] = float(line.get("rate"))
    return rates


def refresh_rates(today: date | None = None) -> None:
    """
    Lit les taux sur le site de la BCE s'ils n'ont pas encore été lus aujourd'hui, et les garde en base.
    Une BCE injoignable n'arrête rien : on le note dans le journal, et le dernier taux connu continue de servir.
    """
    global _failed_on
    today = today or paris_today()
    last_fetch = exchange_rate_store.last_fetch()
    if (last_fetch is not None and last_fetch.date() >= today) or _failed_on == today:
        return
    try:
        response = requests.get(ECB_URL, timeout=10)
        response.raise_for_status()
        exchange_rate_store.save_rates(parse_usd_rates(response.text), datetime.now())
    except (requests.RequestException, ElementTree.ParseError, ValueError) as error:
        _failed_on = today
        logger.warning(f"Taux de la BCE illisible aujourd'hui, le dernier taux connu sert : {error}")


def rate_for(day: date) -> dict:
    """
    Le taux qui convertit les appels du jour `day` : {"usd_per_eur", "rate_date", "same_day"}.
    same_day est faux quand le taux est celui d'un autre jour (le dernier connu avant, ou, pour un appel plus ancien
    que tous les taux gardés, le plus ancien). Lève RateUnavailable si aucun taux n'est connu.
    """
    refresh_rates()
    row = exchange_rate_store.rate_on_or_before(day) or exchange_rate_store.oldest_rate()
    if row is None:
        raise RateUnavailable("aucun taux de la BCE connu : le site de la BCE n'a pas encore pu être lu")
    return {"usd_per_eur": float(row["usd_per_eur"]), "rate_date": row["rate_date"],
            "same_day": row["rate_date"] == day}


def usd_to_eur(usd: float, rate: dict) -> float:
    """Un montant en dollars en euros TTC estimés, au taux donné, arrondi au centime."""
    return round(usd / rate["usd_per_eur"] * VAT, 2)


def eur_to_usd(eur: float, rate: dict) -> float:
    """Le chemin inverse : un montant en euros TTC en dollars, au taux donné, arrondi au centime."""
    return round(eur / VAT * rate["usd_per_eur"], 2)


def rate_label(rate: dict) -> str:
    """Le taux en clair, à mettre à côté d'un montant : « taux BCE du 19/11/2026 : 1 € = 1.0812 $ (dernier connu) »."""
    label = f"taux BCE du {rate['rate_date']:%d/%m/%Y} : 1 € = {rate['usd_per_eur']:.4f} $"
    return label if rate["same_day"] else f"{label} (dernier connu)"
