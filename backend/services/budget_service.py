"""
Le réglage des agents et le budget qui limite leurs passages (issue #211).

LE RÉGLAGE
L'administratrice décide depuis la supervision :
    - si la chaîne des services se lance seule à la fin de l'ETL d'une nouvelle ville (services_after_etl) ;
    - l'enveloppe du mois, le plafond du jour, et la part de l'enveloppe gardée pour Vany.
Le réglage est relu en base à chaque décision : un changement vaut tout de suite, sans redémarrer l'application.
Tant que personne n'a rien réglé, DEFAULTS s'applique.

LE BUDGET
Les montants sont en dollars, au prix équivalent API que llm_calls garde pour chaque appel, abonnement compris : en
phase de test, tout passe par l'abonnement, et le budget doit quand même se voir agir. Les euros viendront avec #275.
Un passage d'une chaîne d'agents ne part que si les deux conditions tiennent :
    - ce qui est dépensé depuis le 1er du mois reste sous l'enveloppe, moins la part de Vany ;
    - ce qui est dépensé depuis minuit reste sous le plafond du jour.
Le passage en cours n'est jamais coupé : on peut dépasser d'un passage, soit une ville (2 à 4 $).
Vany elle-même n'est pas bloquée ici : sa réserve la protège des chaînes, son propre plafond viendra avec #198.
"""
from datetime import datetime, timedelta

from services import agent_settings_store

# Les réglages de la phase de test, choisis le 19 novembre 2026 : une enveloppe large en équivalent API (novembre en
# était déjà à 72,59 $), deux à trois villes par jour, et la part que Vany a dépensée en novembre (18 $), arrondie.
DEFAULTS = {"services_after_etl": True, "monthly_budget_usd": 100.0, "daily_budget_usd": 10.0,
            "vany_reserve_usd": 25.0}


def load_settings() -> dict:
    """Le réglage en vigueur, avec qui l'a fait et quand ; les valeurs par défaut si personne n'a encore rien réglé."""
    row = agent_settings_store.load_latest()
    if row is None:
        return {**DEFAULTS, "changed_at": None, "changed_by": None}
    return {"services_after_etl": bool(row["services_after_etl"]),
            "monthly_budget_usd": float(row["monthly_budget_usd"]), "daily_budget_usd": float(row["daily_budget_usd"]),
            "vany_reserve_usd": float(row["vany_reserve_usd"]),
            "changed_at": row["changed_at"], "changed_by": row["changed_by"]}


def check_amounts(settings: dict) -> None:
    """Lève ValueError, avec une phrase qui dit quoi corriger, si les montants ne vont pas ensemble."""
    if settings["daily_budget_usd"] > settings["monthly_budget_usd"]:
        raise ValueError("Le plafond du jour ne peut pas dépasser l'enveloppe du mois.")
    if settings["vany_reserve_usd"] > settings["monthly_budget_usd"]:
        raise ValueError("La part gardée pour Vany ne peut pas dépasser l'enveloppe du mois.")


def save_settings(changes: dict, changed_by: str) -> dict:
    """
    Change le réglage : `changes` ne donne que ce qui change, le reste garde sa valeur. Écrit une nouvelle ligne et
    rend le nouvel état du budget. Lève ValueError si les montants ne vont pas ensemble.
    """
    current = load_settings()
    settings = {key: changes.get(key, current[key]) for key in DEFAULTS}
    check_amounts(settings)
    agent_settings_store.insert(settings, changed_by)
    return budget_state()


def period_starts(now: datetime) -> tuple:
    """Minuit aujourd'hui, et le 1er du mois à minuit : le début du jour et du mois qu'on compte."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day, day.replace(day=1)


def next_month(day: datetime) -> datetime:
    """Le 1er du mois suivant : le jour où l'enveloppe du mois repart."""
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def block_reason(settings: dict, spent_today: float, spent_month: float, now: datetime) -> str | None:
    """
    Pourquoi un passage ne peut pas partir maintenant, en phrase lisible ; None si le budget le permet.
    L'enveloppe du mois est regardée d'abord : si elle est atteinte, attendre demain ne suffit pas.
    """
    usable = settings["monthly_budget_usd"] - settings["vany_reserve_usd"]
    if spent_month >= usable:
        back = next_month(now)
        return (f"enveloppe du mois atteinte : {spent_month:.2f} $ dépensés, {usable:.2f} $ permis aux agents "
                f"({settings['vany_reserve_usd']:.2f} $ gardés pour Vany) ; les passages reprennent le "
                f"{back:%d/%m/%Y}, ou plus tôt si l'enveloppe est relevée")
    if spent_today >= settings["daily_budget_usd"]:
        return (f"plafond du jour atteint : {spent_today:.2f} $ dépensés sur {settings['daily_budget_usd']:.2f} $ ; "
                f"les passages reprennent demain, ou plus tôt si le plafond est relevé")
    return None


def budget_state(now: datetime | None = None) -> dict:
    """
    Ce que la supervision montre du réglage et du budget : les montants réglés, ce qui est dépensé et ce qui reste,
    le jour et le mois, et la raison du blocage si le budget est atteint (None sinon).
    """
    now = now or datetime.now()
    settings = load_settings()
    day_start, month_start = period_starts(now)
    spent_today = agent_settings_store.spent_since(day_start)
    spent_month = agent_settings_store.spent_since(month_start)
    usable = settings["monthly_budget_usd"] - settings["vany_reserve_usd"]
    return {"services_apres_etl": settings["services_after_etl"],
            "enveloppe_du_mois_usd": settings["monthly_budget_usd"],
            "plafond_du_jour_usd": settings["daily_budget_usd"],
            "reserve_vany_usd": settings["vany_reserve_usd"],
            "depense_du_jour_usd": round(spent_today, 2), "depense_du_mois_usd": round(spent_month, 2),
            "reste_du_jour_usd": round(max(0.0, settings["daily_budget_usd"] - spent_today), 2),
            "reste_du_mois_usd": round(max(0.0, usable - spent_month), 2),
            "budget_atteint": block_reason(settings, spent_today, spent_month, now),
            "modifie_le": settings["changed_at"], "modifie_par": settings["changed_by"]}


def budget_block() -> str | None:
    """La raison pour laquelle aucun passage payant ne peut partir maintenant, ou None si le budget le permet."""
    return budget_state()["budget_atteint"]
