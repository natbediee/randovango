"""
Le réglage des agents et le budget qui limite leurs passages (issues #211 et #275).

LE RÉGLAGE
L'administratrice décide depuis la supervision :
    - si la chaîne des services se lance seule à la fin de l'ETL d'une nouvelle ville (services_after_etl) ;
    - l'enveloppe du mois, le plafond du jour, et la part de l'enveloppe gardée pour Vany.
Le réglage est relu en base à chaque décision : un changement vaut tout de suite, sans redémarrer l'application.
Tant que personne n'a rien réglé, DEFAULTS s'applique.

LE BUDGET, EN EUROS
L'admin règle les montants en euros TTC. Le fournisseur facture en dollars : llm_calls garde le prix de chaque appel en
dollars (réel pour l'API, équivalent API pour l'abonnement), et la dépense est convertie en euros TTC jour par jour, au
taux de la BCE de chaque jour (exchange_rate_service.py). Le plafond ne bouge donc pas quand le dollar varie.
Les colonnes en dollars d'agent_settings restent remplies, converties au taux du jour du réglage, pour les branches
qui les lisent encore. Une ligne d'avant les euros n'a que des dollars : on la convertit au taux du jour où elle a été
écrite.
Un passage d'une chaîne d'agents ne part que si les deux conditions tiennent :
    - ce qui est dépensé depuis le 1er du mois reste sous l'enveloppe, moins la part de Vany ;
    - ce qui est dépensé depuis minuit reste sous le plafond du jour.
Le jour et le mois sont ceux de Paris (#299) : le plafond du jour repart à minuit à Paris, l'enveloppe le 1er du mois
à minuit à Paris, été comme hiver. Les heures de llm_calls sont en UTC (utils/paris_time.py) : on compare donc à
l'heure UTC de ce minuit-là.
Le passage en cours n'est jamais coupé : on peut dépasser d'un passage, soit une ville (2 à 4 €).
Sans aucun taux connu (site de la BCE jamais lu), la dépense ne peut pas se compter en euros : les passages attendent.
Vany elle-même n'est pas bloquée ici : sa réserve la protège des chaînes, son propre plafond viendra avec #198.

LE BUDGET COUPÉ, SUR LE POSTE DE DÉVELOPPEMENT (issue #324)
En local, les agents passent par l'abonnement : la dépense comptée n'est qu'un équivalent API, pas une facture.
AGENT_BUDGET_ENABLED=0 dans le .env coupe alors le plafond du jour et l'enveloppe du mois : la file ne retient plus
aucun passage à cause du budget. Les dépenses restent comptées et affichées, et budget_actif le dit à la supervision.
Sans ce réglage, le budget est actif (préprod, prod), comme les plafonds de RATE_LIMIT_ENABLED.
"""
import os
from datetime import date, datetime, timedelta

from services import agent_settings_store, exchange_rate_service
from services.exchange_rate_service import RateUnavailable
from utils import paris_time

# Les montants réglables, sans leur monnaie : chacun a une colonne _eur et une colonne _usd dans agent_settings.
AMOUNTS = ("monthly_budget", "daily_budget", "vany_reserve")

# Les réglages de la phase de test, en euros TTC, quand personne n'a encore rien réglé : une enveloppe large, deux à
# trois villes par jour, et à peu près la part que Vany a dépensée en novembre 2026.
DEFAULTS = {"services_after_etl": True, "monthly_budget_eur": 100.0, "daily_budget_eur": 10.0,
            "vany_reserve_eur": 25.0}


def amounts_in_euros(row: dict) -> dict:
    """
    Les montants d'une ligne d'agent_settings en euros. Une ligne d'avant les euros n'a que des dollars : ils sont
    convertis au taux du jour où l'admin les a réglés. Lève RateUnavailable si aucun taux n'est connu.
    """
    amounts = {}
    for name in AMOUNTS:
        if row[f"{name}_eur"] is not None:
            amounts[f"{name}_eur"] = float(row[f"{name}_eur"])
        else:
            rate = exchange_rate_service.rate_for(row["changed_at"].date())
            amounts[f"{name}_eur"] = exchange_rate_service.usd_to_eur(float(row[f"{name}_usd"]), rate)
    return amounts


def budget_enabled() -> bool:
    """
    Le budget retient-il les passages ? Oui par défaut (préprod, prod) ; AGENT_BUDGET_ENABLED=0 le coupe sur le poste
    de développement. Relu à chaque décision, mais une valeur changée dans le .env n'arrive dans l'API qu'au
    redémarrage de son conteneur : on la règle avant un gros envoi, pas pendant un passage.
    """
    return os.getenv("AGENT_BUDGET_ENABLED", "1") != "0"


def load_settings() -> dict:
    """
    Le réglage en vigueur, avec qui l'a fait et quand ; les valeurs par défaut si personne n'a encore rien réglé.
    Si une ligne en dollars ne peut pas être convertie (aucun taux connu), ses montants en euros valent None :
    services_after_etl reste lisible, pour que la fin de l'ETL ne casse pas.
    """
    row = agent_settings_store.load_latest()
    if row is None:
        return {**DEFAULTS, "changed_at": None, "changed_by": None, "reason": None}
    try:
        amounts = amounts_in_euros(row)
    except RateUnavailable:
        amounts = {f"{name}_eur": None for name in AMOUNTS}
    return {"services_after_etl": bool(row["services_after_etl"]), **amounts,
            "changed_at": row["changed_at"], "changed_by": row["changed_by"], "reason": row["reason"]}


def check_amounts(settings: dict) -> None:
    """Lève ValueError, avec une phrase qui dit quoi corriger, si les montants ne vont pas ensemble."""
    if settings["daily_budget_eur"] > settings["monthly_budget_eur"]:
        raise ValueError("Le plafond du jour ne peut pas dépasser l'enveloppe du mois.")
    if settings["vany_reserve_eur"] > settings["monthly_budget_eur"]:
        raise ValueError("La part gardée pour Vany ne peut pas dépasser l'enveloppe du mois.")


def save_settings(changes: dict, changed_by: str, reason: str | None = None) -> dict:
    """
    Change le réglage : `changes` ne donne que ce qui change (montants en euros), le reste garde sa valeur. Écrit une
    nouvelle ligne, avec la raison du changement si l'admin en donne une, et rend le nouvel état du budget.
    Les montants sont aussi écrits en dollars, au taux du jour. Lève ValueError si les montants ne vont pas ensemble,
    RateUnavailable si aucun taux n'est connu.
    """
    current = load_settings()
    settings = {key: changes.get(key, current[key]) for key in DEFAULTS}
    check_amounts(settings)
    rate = exchange_rate_service.rate_for(paris_time.paris_today())
    for name in AMOUNTS:
        settings[f"{name}_usd"] = exchange_rate_service.eur_to_usd(settings[f"{name}_eur"], rate)
    agent_settings_store.insert(settings, changed_by, reason)
    return budget_state()


def period_starts(now: datetime) -> tuple:
    """
    Le début du jour et du mois qu'on compte : minuit à Paris aujourd'hui, et le 1er du mois à minuit à Paris, en heure
    UTC de la base. `now` est une heure de la base (UTC, sans fuseau).
    """
    today = paris_time.paris_today(now)
    return paris_time.paris_midnight(today), paris_time.paris_midnight(today.replace(day=1))


def next_month(day: date) -> date:
    """Le 1er du mois suivant : le jour où l'enveloppe du mois repart. `day` est un jour de Paris."""
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def spent_since(start: datetime) -> dict:
    """
    Ce qu'ont coûté les appels d'agents depuis `start` : {"eur": euros TTC, "usd": dollars}. Chaque jour est converti
    à son propre taux. Lève RateUnavailable si aucun taux n'est connu.
    """
    by_day = agent_settings_store.spent_by_day(start)
    euros = sum(exchange_rate_service.usd_to_eur(usd, exchange_rate_service.rate_for(day)) for day, usd in by_day.items())
    return {"eur": round(euros, 2), "usd": round(sum(by_day.values()), 2)}


def block_reason(settings: dict, spent_today: float, spent_month: float, now: datetime) -> str | None:
    """
    Pourquoi un passage ne peut pas partir maintenant, en phrase lisible ; None si le budget le permet.
    Les montants sont en euros. L'enveloppe du mois est regardée d'abord : si elle est atteinte, attendre demain ne
    suffit pas. `now` est une heure de la base (UTC, sans fuseau) : le jour de reprise dit est celui de Paris.
    """
    usable = settings["monthly_budget_eur"] - settings["vany_reserve_eur"]
    if spent_month >= usable:
        back = next_month(paris_time.paris_today(now))
        return (f"enveloppe du mois atteinte : {spent_month:.2f} € dépensés, {usable:.2f} € permis aux agents "
                f"({settings['vany_reserve_eur']:.2f} € gardés pour Vany) ; les passages reprennent le "
                f"{back:%d/%m/%Y}, ou plus tôt si l'enveloppe est relevée")
    if spent_today >= settings["daily_budget_eur"]:
        return (f"plafond du jour atteint : {spent_today:.2f} € dépensés sur {settings['daily_budget_eur']:.2f} € ; "
                f"les passages reprennent demain, ou plus tôt si le plafond est relevé")
    return None


def budget_state(now: datetime | None = None) -> dict:
    """
    Ce que la supervision montre du réglage et du budget : les montants réglés en euros, ce qui est dépensé (en euros
    TTC estimés et en dollars) et ce qui reste, le jour et le mois, le taux de la BCE utilisé pour aujourd'hui, et la
    raison du blocage si le budget est atteint (None sinon).
    Sans aucun taux connu, les montants en euros valent None et la raison du blocage le dit.
    Budget coupé (AGENT_BUDGET_ENABLED=0) : budget_actif vaut False, les dépenses sont comptées comme d'habitude, et la
    raison du blocage vaut toujours None, puisque rien ne retient la file.
    `now` est une heure de la base (UTC, sans fuseau) ; l'heure du changement de réglage (modifie_le) est rendue à
    l'heure de Paris.
    """
    now = now or datetime.now()
    settings = load_settings()
    active = budget_enabled()
    state = {"budget_actif": active, "services_apres_etl": settings["services_after_etl"],
             "enveloppe_du_mois_eur": settings["monthly_budget_eur"],
             "plafond_du_jour_eur": settings["daily_budget_eur"],
             "reserve_vany_eur": settings["vany_reserve_eur"],
             "depense_du_jour_eur": None, "depense_du_mois_eur": None,
             "depense_du_jour_usd": None, "depense_du_mois_usd": None,
             "reste_du_jour_eur": None, "reste_du_mois_eur": None, "taux": None,
             "modifie_le": paris_time.to_paris(settings["changed_at"]), "modifie_par": settings["changed_by"],
             "raison_du_changement": settings["reason"]}
    try:
        if settings["daily_budget_eur"] is None:
            raise RateUnavailable("le réglage en dollars ne peut pas être converti")
        day_start, month_start = period_starts(now)
        today, month = spent_since(day_start), spent_since(month_start)
        state["taux"] = exchange_rate_service.rate_label(exchange_rate_service.rate_for(paris_time.paris_today(now)))
    except RateUnavailable as error:
        state["budget_atteint"] = None
        if active:
            state["budget_atteint"] = (f"taux du dollar inconnu ({error}) ; "
                                       f"les passages attendent que le site de la BCE réponde")
        return state
    # Dépensé et restant se calculent sur les montants arrondis au centime : sinon 10 − 2,725 donnerait « 2,73 dépensés »
    # et « 7,28 restants » (essai du 19 novembre 2026).
    usable = settings["monthly_budget_eur"] - settings["vany_reserve_eur"]
    state.update({"depense_du_jour_eur": today["eur"], "depense_du_mois_eur": month["eur"],
                  "depense_du_jour_usd": today["usd"], "depense_du_mois_usd": month["usd"],
                  "reste_du_jour_eur": round(max(0.0, settings["daily_budget_eur"] - today["eur"]), 2),
                  "reste_du_mois_eur": round(max(0.0, usable - month["eur"]), 2),
                  "budget_atteint": block_reason(settings, today["eur"], month["eur"], now) if active else None})
    return state


def budget_block() -> str | None:
    """La raison pour laquelle aucun passage payant ne peut partir maintenant, ou None si le budget le permet."""
    return budget_state()["budget_atteint"]
