"""
Supervision des services : les vérifications proposent (etl_poi_check.py, find_service_links.py),
un humain tranche, le code applique. C'est le SEUL endroit qui modifie la table poi à partir d'un signal.

QUATRE FILES, parce que les décisions ne se prennent pas pareil :
    liens      : ajouter un lien. Ceux que le code a contrôlés se valident par lot ;
    fermetures : renommer, retirer, garder. Toujours au cas par cas : c'est là qu'une erreur coûte le
                 plus. Les sources sont montrées ensemble, car elles se contredisent souvent ;
    saison     : valider les mois d'ouverture, ou « saisonnier probable » sans mois ;
    morts      : retirer un lien qui ne répond plus ;
    confirmer  : un restaurant ou un commerce que son agent n'a pas pu trancher (service_store.py,
                 signal a_confirmer). Valider
                 écrit la fiche qu'il avait préparée et l'affiche ; retirer le laisse masqué.
                 Aussi une station-service douteuse (etl/transform/transform_carburants.py), masquée en attendant :
                 « Garder tel quel » la réaffiche, retirer la laisse masquée ;
    doublons   : deux restaurants proches que la règle n'a pas su trancher (restaurant_duplicates_service.py), ou deux
                 lieux de même nom, quel que soit le service (poi_duplicates_service.py, signal doublon_service).
                 On choisit le lieu qu'on garde (« Garder ce lieu » sous chacun des deux, 13 novembre 2026) : l'autre est
                 masqué, et la décision « fusionner » est enregistrée sur lui ; rien n'est effacé. Rarement, aucun des
                 deux n'est à garder : « Aucun des deux » les retire tous les deux (remove_both_places). Une station figée près d'une station
                 active (doublon_station) est déjà masquée : « Deux lieux » la réaffiche (poi_triage_service.hide_doubtful_stations l'avait masquée).
                 Un lieu mixte, qui vend et sert à la fois (une boulangerie qui fait snack, des viviers avec dégustation),
                 a une fiche restaurant d'un côté et une fiche commerce de l'autre : « Lieu mixte » donne la fiche de
                 celui-ci à l'autre, qui garde ainsi les deux et s'affiche dans les deux onglets (join_mixed_place).

PARTOUT, « Retirer le lieu » : un lieu qui n'a rien à faire là se voit dans n'importe quelle file. Il est masqué
et sort de toutes les files.

UNE DÉCISION SE DÉFAIT : elle garde les valeurs d'avant (decisions.detail) et les remet si on l'annule.
Elle reste tracée dans la table `decisions`, avec celles des spots (objet_type = 'poi').

CE QUE VOIT LE VOYAGEUR : un lieu masqué (poi.masque) n'est plus proposé à l'étape 4 : retiré ici, ou
masqué par poi_triage_service.py dès qu'une fermeture est signalée. Garder ou renommer le remet. La saison
et la fermeture du moment sont enregistrées ici, leur affichage sur les fiches reste à faire.
"""
import json
from collections import Counter
import re

from agents import find_services
from agents.find_restaurants import RESTAURANTS
from services import service_store
from services.supervision import rating
from services.supervision.decisions import record_decision
from services.commerce_selection_service import SHOP_CATEGORY_LABELS
from services.restaurant_selection_service import TABLE_CATEGORY_LABELS
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP
from utils.db_utils import MySQLUtils
from utils.geo_utils import address_town, town_choices, town_key

POI = "poi"
PAGE_SIZE = 50
RECENT_DECISIONS = 10
AUDIT_SIZE = 20
AUDIT_DONE = "contrôlé"
RULE_AUTHOR = "règle automatique"

TAB_SIGNALS = {
    "liens": ("lien_agent", "lien_osm"),
    "fermetures": ("fermeture_agent", "renommage_osm", "fermeture_osm", "absent_osm"),
    "saison": ("saison_agent", "saison_osm"),
    "morts": ("lien_mort",),
    "doublons": ("doublon_restaurant", "doublon_commerce", "doublon_service", "doublon_station"),
    "confirmer": ("a_confirmer", "station_douteuse", "station_muette", "station_absente"),
}
# Les stations-service douteuses (etl/transform/transform_carburants.py), masquées en attendant (poi_triage_service.py).
STATION_SIGNALS = ("station_douteuse", "station_muette", "station_absente")
SIGNAL_TAB = {signal: tab for tab, signals in TAB_SIGNALS.items() for signal in signals}
SOURCE_LABELS = {"osm": "OSM", "agent": "Agent", "liens": "Contrôle", "carburants_osm": "OSM", "carburants_etat": "État"}
SIGNAL_LABELS = {
    "lien_agent": "Lien trouvé par l'agent", "lien_osm": "Lien indiqué dans OSM",
    "fermeture_agent": "Fermeture signalée", "renommage_osm": "Renommé dans OSM", "fermeture_osm": "Marqué fermé dans OSM",
    "absent_osm": "Absent d'OSM", "saison_agent": "Saison", "saison_osm": "Saison dans OSM", "lien_mort": "Lien mort",
    "doublon_restaurant": "Doublon possible",
    "doublon_commerce": "Doublon possible",
    "doublon_service": "Doublon possible",
    "doublon_station": "Station déclarée deux fois",
    "a_confirmer": "À confirmer",
    "station_douteuse": "Station douteuse",
    "station_muette": "Station muette",
    "station_absente": "Absente du fichier de l'État",
}
# Les décisions possibles et le sort des signaux relus. Le code n'accepte rien d'autre.
ACTIONS = {
    "valider_lien": "valide", "valider_lien_nom": "valide", "refuser_lien": "rejete",
    "renommer": "valide", "retirer": "valide", "fermer_moment": "valide", "garder": "rejete",
    "valider_saison": "valide", "pas_saisonnier": "rejete",
    "retirer_lien": "valide", "garder_lien": "rejete",
    "fusionner": "valide", "deux_lieux": "rejete", "lieu_mixte": "valide", "garder_celui_ci": "valide",
    "retirer_les_deux": "valide",
    "valider_pepite": "valide",
    "sans_suite": "rejete",
    "autre_lien": "rejete",
    "autre_nom": "valide",
    "autre_maps": "valide",
}
ACTION_LABELS = {
    "valider_lien": "lien ajouté", "valider_lien_nom": "lien ajouté et nom corrigé", "refuser_lien": "lien refusé",
    "renommer": "renommé", "retirer": "retiré", "fermer_moment": "fermé pour le moment", "garder": "gardé",
    "valider_saison": "saison validée", "pas_saisonnier": "pas saisonnier",
    "retirer_lien": "lien retiré", "garder_lien": "lien gardé",
    "fusionner": "fusionné", "deux_lieux": "deux lieux", "lieu_mixte": "lieu mixte : une fiche, deux onglets",
    # Jamais enregistré sous ce nom : la décision est « fusionner », sur l'autre lieu (keep_this_place).
    "garder_celui_ci": "gardé, l'autre lieu masqué",
    # Jamais enregistré sous ce nom non plus : une décision « retirer » sur chacun des deux lieux (remove_both_places).
    "retirer_les_deux": "les deux lieux retirés",
    "valider_pepite": "lieu confirmé",
    "sans_suite": "classé sans suite",
    "autre_lien": "lien saisi à la main",
    "autre_nom": "renommé à la main",
    "autre_maps": "lien Google Maps saisi à la main",
    "modifier_fiche": "fiche modifiée",
}
ACTION_BUTTONS = {
    "valider_lien": ("Valider le lien", "main"), "valider_lien_nom": ("Valider le lien et le nom", "main"),
    "refuser_lien": ("Refuser", "line"), "renommer": ("Renommer", "main"), "retirer": ("Retirer le lieu", "remove"),
    "fermer_moment": ("Fermé pour le moment", "main"), "garder": ("Garder tel quel", "line"),
    "valider_saison": ("Valider la saison", "main"), "pas_saisonnier": ("Pas saisonnier", "line"),
    "retirer_lien": ("Retirer le lien", "main"), "garder_lien": ("Garder le lien", "line"),
    "fusionner": ("Même lieu : garder l'autre", "remove"), "deux_lieux": ("Deux lieux", "line"),
    "garder_celui_ci": ("Même lieu : garder celui-ci", "remove"),
    "retirer_les_deux": ("Aucun des deux : retirer les deux lieux", "remove"),
    "lieu_mixte": ("Lieu mixte : un seul lieu, deux fiches", "main"),
    "valider_pepite": ("Confirmer et afficher le lieu", "main"),
    "autre_lien": ("Mettre ce lien", "line"),
    "autre_nom": ("Renommer ainsi", "line"),
    "autre_maps": ("Mettre ce lien Google Maps", "line"),
}
# Les cases de toutes les fiches : un nom ou un lien trouvé à la main. Elles ne tranchent que le problème de leur file
# (le nom, le lien) ; ailleurs, elles corrigent le lieu et le problème reste à trancher.
SIDE_ACTIONS = {"autre_nom": "fermetures", "autre_lien": "liens",
                # Le lien Google Maps corrige la carte du voyageur (step4.py) sans trancher aucune file.
                "autre_maps": None}
ALL_TABS = "tous"
# Les files que la page et le bilan ne proposent pas : la règle tranche tous les liens morts (poi_triage_service.py).
# Une décision annulée en ramène un : il apparaît alors dans « Tous » (7 novembre 2026).
HIDDEN_TABS = ("morts",)
# Les décisions que seule la règle prend (poi_triage_service.py) : aucun bouton, mais annulables comme les autres.
RULE_ACTIONS = ("sans_suite",)
# La décision des lieux mixtes : proposée seulement dans la file « Doublons », quand l'un a une fiche restaurant et
# l'autre une fiche commerce (mixed_sheet_table).
MIXED = "lieu_mixte"
# « Garder ce lieu » sous le lieu de la carte, dans la file « Doublons » : c'est l'autre lieu qui est masqué
# (keep_this_place). « fusionner » reste le geste inverse : il masque le lieu de la carte et garde l'autre.
KEEP_THIS = "garder_celui_ci"
# « Aucun des deux » : les deux lieux d'un doublon sont retirés, chacun avec sa décision « retirer » (remove_both_places).
REMOVE_BOTH = "retirer_les_deux"
SHEET_TABLES = ("restaurants", "commerces")
# Le filtre « Type de lieu » reprend les onglets de l'étape 4 (utils/service_utils.POI_FRONTEND_CATEGORY_MAP), puis le
# type précis : la catégorie de la fiche de l'agent quand il y en a une (« Crêperie », « Marché »), sinon le service
# (« Café »). Un service sans onglet (le voyageur ne le voit jamais) est rangé à part.
NO_TAB = "hors_etape4"
SHEET_LABELS = {**TABLE_CATEGORY_LABELS, **SHOP_CATEGORY_LABELS}


def step4_tab(raw_category: str | None) -> str:
    return POI_FRONTEND_CATEGORY_MAP.get((raw_category or "").lower(), NO_TAB)


def tab_categories(service: str) -> tuple:
    """Les services OSM d'un onglet de l'étape 4."""
    return tuple(category for category, tab in POI_FRONTEND_CATEGORY_MAP.items() if tab == service)


# Valider un lieu à confirmer écrit la fiche que son agent avait préparée, dans la table de sa catégorie : celle de la
# source du signal (« agent_restaurants », « agent_commerces »).
CATEGORIES = {category.source: category for category in find_services.CATEGORIES}
# Les seules colonnes qu'une décision peut changer, et donc remettre.
APPLIED_COLUMNS = ("url", "name", "masque", "ferme_moment", "statut_saison", "mois_ouverture", "maps_url", "latitude", "longitude",
                   "address", "description")
# Les champs de fiche qu'une fiche corrigée à la main (services_edit.decide_sheet) peut changer, table par table.
SHEET_COLUMNS = {"restaurants": ("genre", "pourquoi", "categorie", "distinction"),
                 "commerces": ("genre", "pourquoi", "categorie", "jours")}
OSM_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

def signal_detail(signal: dict) -> dict:
    value = signal.get("detail")
    return json.loads(value) if isinstance(value, str) else (value or {})


_detail = signal_detail


def proof_text(signal: dict) -> str:
    """Ce que dit une source, en une phrase, avec ses preuves. Le texte de l'agent est cité tel quel."""
    kind, detail = signal["signal_type"], _detail(signal)
    if kind == "lien_agent":
        checks = {"ok": "la page nomme le lieu et sa commune", "ok_telephone": "le téléphone et la commune sont sur la page",
                  "ok_rebond": "page citée par une page contrôlée", "a_valider_nom": "la page porte un autre nom",
                  "a_valider_social": "réseau social, illisible par le code"}
        return f"{checks.get(detail.get('verdict'), 'à vérifier')}."
    if kind == "lien_osm":
        checks = {"ok": "indiqué par un contributeur, la page nomme le lieu et sa commune",
                  "a_valider_social": "indiqué par un contributeur, réseau social illisible par le code",
                  "nom_absent": "indiqué par un contributeur, mais la page ne nomme pas le lieu",
                  "commune_absente": "indiqué par un contributeur, mais la page ne cite pas la commune",
                  "lien_mort": "indiqué par un contributeur, mais la page n'existe plus",
                  "page_illisible": "indiqué par un contributeur, page illisible par le code"}
        return f"{checks.get(detail.get('controle'), 'indiqué par un contributeur, sans contrôle de la page')}."
    if kind == "fermeture_osm":
        return "l'objet est marqué fermé" + (f" (nom : {detail['nom_osm']})." if detail.get("nom_osm") else ".")
    if kind == "renommage_osm":
        return f"l'objet s'appelle maintenant « {detail.get('nom_osm')} »."
    if kind == "absent_osm":
        return "l'objet n'existe plus."
    if kind == "fermeture_agent":
        date_text = f" (page du {detail['date_page']})" if detail.get("date_page") else ""
        return f"{detail.get('type')} : « {detail.get('citation') or 'sans citation'} »{date_text}."
    if kind == "saison_agent":
        return f"{detail.get('statut')} : « {detail.get('citation') or 'sans citation'} »."
    if kind == "saison_osm":
        return f"horaires « {detail.get('opening_hours') or detail.get('seasonal')} »."
    if kind == "lien_mort":
        return f"{detail.get('url')} : {detail.get('raison')} (vérifié deux fois)."
    if kind == "a_confirmer":
        return f"{detail.get('raison')}" + (f" : « {detail['indice']} »." if detail.get("indice") else ".")
    if kind in STATION_SIGNALS:
        osm = f" (« {detail['nom_osm']} », {detail['osm_element']})" if detail.get("nom_osm") else ""
        return f"{detail.get('raison')}{osm}."
    if kind in ("doublon_restaurant", "doublon_commerce", "doublon_service", "doublon_station"):
        distance = f"à {detail['distance_m']} m de" if detail.get("distance_m") is not None else "même lieu que"
        return f"{detail.get('raison')}, {distance} « {detail.get('autre_nom')} » ({detail.get('autre_adresse') or 'sans adresse'})."
    return ""


def new_name_of(signals: list) -> str | None:
    """Le nouveau nom : celui de la page lue par l'agent, sinon celui d'OSM."""
    by_type = {signal["signal_type"]: _detail(signal) for signal in signals}
    agent = by_type.get("fermeture_agent", {})
    if agent.get("type") == "reprise" and agent.get("autre_nom"):
        return agent["autre_nom"]
    return by_type.get("renommage_osm", {}).get("nom_osm")


def _links_card(signals: list) -> dict:
    agent = next((s for s in signals if s["signal_type"] == "lien_agent"), None)
    osm = next((s for s in signals if s["signal_type"] == "lien_osm"), None)
    # Le lien de l'agent a été contrôlé par le code, pas celui d'OSM.
    chosen = _detail(agent) if agent else _detail(osm)
    auto = chosen.get("controle") in (None, "ok") if not agent else chosen.get("niveau") == "auto"
    other_name = chosen.get("autre_nom") if chosen.get("verdict") == "a_valider_nom" else None
    actions = ["valider_lien_nom", "valider_lien", "refuser_lien"] if other_name else ["valider_lien", "refuser_lien"]
    proposal = f"ajouter ce lien et corriger le nom en « {other_name} »." if other_name else "ajouter ce lien."
    return {"auto": auto, "url": chosen.get("url"), "type_page": chosen.get("type_page") or "osm", "autre_nom": other_name,
            "link": chosen.get("url"), "proposal": proposal, "actions": actions}


def _closure_card(signals: list) -> dict:
    agent = next((_detail(s) for s in signals if s["signal_type"] == "fermeture_agent"), {})
    new_name = new_name_of(signals)
    actions = (["renommer"] if new_name else []) + (["fermer_moment"] if agent.get("type") == "momentanee" else [])
    actions += ["retirer", "garder"]
    if new_name:
        proposal = f"renommer en « {new_name} »."
    elif agent.get("type") == "momentanee":
        proposal = "signaler une fermeture du moment."
    else:
        proposal = "vérifier avant de retirer."
    return {"new_name": new_name, "link": agent.get("page"), "proposal": proposal, "actions": actions}


def _season_card(signals: list) -> dict:
    by_type = {signal["signal_type"]: _detail(signal) for signal in signals}
    osm = by_type.get("saison_osm", {})
    agent = by_type.get("saison_agent", {})
    months = [OSM_MONTHS.index(month) for month in osm.get("mois") or []]
    confirmed = bool(months) or agent.get("statut") == "confirmee"
    period = agent.get("mois") or ""
    proposal = "saisonnier" + (f" : {period}." if period else ", mois à préciser. Sans mois, la fiche dira « à vérifier ».")
    return {"months": months, "statut": "confirmee" if confirmed else "probable", "link": agent.get("page"),
            "proposal": proposal, "actions": ["valider_saison", "pas_saisonnier"]}


def _dead_link_card(signals: list) -> dict:
    detail = _detail(signals[0])
    return {"link": detail.get("url"), "proposal": "retirer le lien de la fiche.", "actions": ["retirer_lien", "garder_lien"]}


def _duplicate_card(signals: list) -> dict:
    detail = _detail(signals[0])
    # Une station figée est masquée dès qu'elle est repérée : « Deux lieux » doit donc la réafficher.
    hidden = signals[0]["signal_type"] == "doublon_station"
    # Sans le numéro de l'autre lieu, on ne peut pas le masquer : on ne propose alors que de masquer celui-ci.
    if detail.get("autre_id"):
        actions = [KEEP_THIS, "fusionner", "deux_lieux", REMOVE_BOTH]
    else:
        actions = ["fusionner", "deux_lieux"]
    return {"link": None, "autre_id": detail.get("autre_id"), "reafficher": hidden,
            "proposal": f"même lieu que « {detail.get('autre_nom')} » ? Coche le lieu à garder, les deux si ce sont "
                        "deux lieux différents ; rien n'est effacé." + (" En attendant, celui-ci est masqué." if hidden else ""),
            "actions": actions}


def _to_confirm_card(signals: list) -> dict:
    detail = _detail(signals[0])
    if signals[0]["signal_type"] in STATION_SIGNALS:
        return {"link": None, "proposal": "cette station existe-t-elle encore ? Masquée en attendant ; la garder la "
                                          "réaffiche avec ses prix et leur date.", "actions": ["garder", "retirer"]}
    sheet = detail.get("fiche") or {}
    genre = f" ({sheet['genre']})" if sheet.get("genre") else ""
    # « valider_pepite » est un nom interne gardé pour les décisions déjà prises : ce sont des services, pas des pépites.
    return {"link": detail.get("page"), "proposal": f"ce lieu{genre} existe-t-il ? Le confirmer l'affiche au voyageur, avec sa fiche.",
            "actions": ["valider_pepite", "retirer"] if sheet.get("genre") else ["retirer"]}


CARD_BUILDERS = {"liens": _links_card, "fermetures": _closure_card, "saison": _season_card, "morts": _dead_link_card,
                 "doublons": _duplicate_card, "confirmer": _to_confirm_card}


def build_card(tab: str, poi: dict, signals: list) -> dict:
    """
    La fiche de relecture d'un lieu : tous ses signaux d'une file, ensemble. Toutes les fiches ont la même forme et
    les mêmes cases « autre nom » et « autre lien » (7 novembre 2026) : seules les décisions propres au problème changent.
    """
    card = CARD_BUILDERS[tab](signals)
    # « Retirer le lieu » sur toutes les fiches : un lieu qui n'a rien à faire là (une bijouterie classée supérette)
    # se voit dans n'importe quelle file (7 novembre 2026).
    card["actions"] = card["actions"] + [action for action in ("retirer", *SIDE_ACTIONS) if action not in card["actions"]]
    ordered = sorted(signals, key=lambda signal: TAB_SIGNALS[tab].index(signal["signal_type"]))
    return {
        **card, "tab": tab, "poi_id": poi["id"], "nom": poi["name"], "adresse": poi.get("address") or "",
        "service": poi.get("service") or "", "url_actuelle": poi.get("url"), "maps_actuel": poi.get("maps_url"),
        # Sans adresse (Gortozenn, un objet OSM), la commune et la position disent quand même où est le lieu.
        "commune": poi.get("commune") or "",
        "position": [float(poi["latitude"]), float(poi["longitude"])] if poi.get("latitude") is not None else None,
        "signal_ids": [signal["id"] for signal in ordered],
        "signal": SIGNAL_LABELS[ordered[0]["signal_type"]],
        "gravite": "red" if ordered[0]["signal_type"] in ("lien_mort", "fermeture_agent")
                   else ("teal" if tab == "saison" and card.get("statut") == "confirmee" else "warn"),
        "preuves": [{"source": SOURCE_LABELS.get(signal["source"], signal["source"]), "texte": proof_text(signal)}
                    for signal in ordered],
        "boutons": [{"action": action, "label": ACTION_BUTTONS[action][0], "style": ACTION_BUTTONS[action][1]}
                    for action in card["actions"]],
    }


def offer_mixed_place(card: dict) -> None:
    """Ajoute « Lieu mixte » en tête des décisions d'un doublon entre une fiche restaurant et une fiche commerce."""
    card["actions"] = [MIXED, *card["actions"]]
    card["boutons"] = [{"action": MIXED, "label": ACTION_BUTTONS[MIXED][0], "style": ACTION_BUTTONS[MIXED][1]}, *card["boutons"]]
    card["proposal"] += (" S'il vend et sert à la fois (une boulangerie qui fait snack), « Lieu mixte » garde un seul lieu"
                         " avec ses deux fiches, dans les deux onglets.")


def typed_link(url: str | None) -> str:
    """
    Le lien qu'un admin a trouvé lui-même : une adresse web complète, et rien d'autre. Une apostrophe ou un guillemet sont
    encodés comme le fait un navigateur : le lien Google Maps de « A Fleur d'Eau » contient « d'Eau » (8 novembre 2026).
    Encodés, ils ne peuvent plus sortir d'un attribut href. Une espace reste refusée : ce n'est pas une adresse.
    """
    url = (url or "").strip().replace("'", "%27").replace('"', "%22")
    if not re.fullmatch(r"https?://[^\s\"'<>]{4,490}", url):
        raise ValueError("Lien invalide : colle une adresse complète, qui commence par https://")
    return url


def typed_name(name: str | None) -> str:
    """Le nom qu'un admin a trouvé lui-même : du texte court, sans balise."""
    name = " ".join((name or "").split())
    if not 2 <= len(name) <= 150 or re.search(r"[<>]", name):
        raise ValueError("Nom invalide : entre 2 et 150 caractères, sans < ni >")
    return name


GOOGLE_MAPS_HOSTS = re.compile(r"^(www\.)?google\.[a-z.]{2,6}/maps|^maps\.google\.[a-z.]{2,6}/|^maps\.app\.goo\.gl/|^goo\.gl/maps/")
# La position d'un lien Google Maps : l'épingle du lieu (!3d…!4d…), sinon le centre de la carte (@lat,lon) ou la recherche.
MAPS_POSITIONS = (re.compile(r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)"), re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),
                  re.compile(r"[?&](?:query|q)=(-?\d{1,2}\.\d+)(?:,|%2C)(-?\d{1,3}\.\d+)"))


def typed_maps_link(url: str | None) -> dict:
    """
    Le lien Google Maps qu'un admin a trouvé lui-même (7 novembre 2026), quand la recherche fabriquée par le code tombe
    sur un autre lieu. Seulement une adresse de Google Maps. Sa position, si le lien en porte une, corrige aussi celle
    du lieu : 18 lieux des agents n'en avaient pas. Le code n'ouvre jamais ce lien (Google est un site exclu).
    """
    url = typed_link(url)
    if not GOOGLE_MAPS_HOSTS.search(re.sub(r"^https?://", "", url)):
        raise ValueError("Lien Google Maps invalide : colle l'adresse d'une page de Google Maps")
    fields = {"maps_url": url}
    for pattern in MAPS_POSITIONS:
        match = pattern.search(url)
        if match:
            latitude, longitude = float(match.group(1)), float(match.group(2))
            if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                fields |= {"latitude": latitude, "longitude": longitude}
            break
    return fields


def applied_fields(action: str, card: dict, months: list | None, url: str | None = None, name: str | None = None) -> dict:
    """
    Ce qu'une décision change sur le lieu. Le lien et le nom viennent du signal, jamais du navigateur, sauf un lien
    ou d'un nom que l'admin a trouvé lui-même (« Mettre ce lien », « Renommer ainsi ») : contrôlés par typed_link et typed_name.
    """
    if action == "autre_lien":
        return {"url": typed_link(url)}
    if action == "autre_maps":
        return typed_maps_link(url)
    # Renommer à la main dit aussi que le lieu existe, comme « Renommer », mais seulement là où l'existence était en doute.
    if action == "autre_nom":
        return {"name": typed_name(name), "masque": 0} if card.get("tab") == "fermetures" else {"name": typed_name(name)}
    if action == "valider_lien":
        return {"url": card["url"]}
    if action == "valider_lien_nom":
        return {"url": card["url"], "name": card["autre_nom"]}
    # Renommer ou garder décide que le lieu existe : il est de nouveau affiché s'il était masqué.
    if action == "renommer":
        return {"name": card["new_name"], "masque": 0}
    if action == "retirer":
        return {"masque": 1}
    if action == "garder":
        return {"masque": 0}
    if action == "fermer_moment":
        return {"ferme_moment": 1, "masque": 0}
    if action == "valider_saison":
        chosen = sorted({month for month in (months or []) if isinstance(month, int) and 0 <= month <= 11})
        return {"statut_saison": "confirmee" if chosen else "probable", "mois_ouverture": json.dumps(chosen)}
    if action == "pas_saisonnier":
        return {"statut_saison": None, "mois_ouverture": None}
    if action == "retirer_lien":
        return {"url": None}
    if action in ("fusionner", MIXED):
        return {"masque": 1}
    if action == "deux_lieux" and card.get("reafficher"):
        return {"masque": 0}
    if action == "valider_pepite":
        return {"masque": 0}
    return {}


def _pending(cursor, service: str | None, city: str | None, statut: str = "a_relire", kind: str | None = None,
             town: str | None = None) -> tuple:
    """
    {(file, poi_id): signaux dans cet état} et les lieux concernés, à travers les filtres. service est un onglet de
    l'étape 4 (« commerce »), kind le type précis dans cet onglet (« Boulangerie »), town une commune d'adresse qui
    n'est pas une ville de l'appli (« Guilvinec », comme dans l'onglet « Modifier »).
    """
    filters, params = ["sg.statut = %s"], [statut]
    if city:
        filters.append("EXISTS (SELECT 1 FROM histo_poi h JOIN cities c ON c.id = h.city_id"
                       " WHERE h.poi_id = p.id AND c.name = %s)")
        params.append(city)
    cursor.execute(f"""
        SELECT sg.id, sg.poi_id, sg.source, sg.signal_type, sg.detail, p.id AS p_id, p.name, p.address, p.url,
               p.latitude, p.longitude, p.maps_url,
               (SELECT MIN(s.name) FROM poi_service ps JOIN services s ON s.id = ps.service_id
                WHERE ps.poi_id = p.id) AS service_name,
               (SELECT MIN(s.category) FROM poi_service ps JOIN services s ON s.id = ps.service_id
                WHERE ps.poi_id = p.id) AS service_category,
               (SELECT r.categorie FROM restaurants r WHERE r.poi_id = p.id) AS table_categorie,
               (SELECT c.categorie FROM commerces c WHERE c.poi_id = p.id) AS shop_categorie,
               (SELECT MIN(c.name) FROM histo_poi h JOIN cities c ON c.id = h.city_id WHERE h.poi_id = p.id) AS commune
        FROM poi_signals sg JOIN poi p ON p.id = sg.poi_id
        WHERE {' AND '.join(filters)}
    """, tuple(params))
    groups, pois = {}, {}
    for row in cursor.fetchall():
        tab = SIGNAL_TAB.get(row["signal_type"])
        if not tab:
            continue
        # Le type précis : la catégorie de la fiche de l'agent (« Crêperie », « Marché »), sinon le nom du service.
        precise = SHEET_LABELS.get(row.get("table_categorie") or row.get("shop_categorie")) or row.get("service_name")
        onglet = step4_tab(row.get("service_category"))
        if (service and onglet != service) or (kind and precise != kind):
            continue
        if town and town_key(address_town(row["address"])) != town_key(town):
            continue
        groups.setdefault((tab, row["poi_id"]), []).append(row)
        pois[row["poi_id"]] = {"id": row["p_id"], "name": row["name"], "address": row["address"],
                               "url": row["url"], "maps_url": row.get("maps_url"), "service": precise, "onglet": onglet,
                               "commune": row["commune"],
                               "latitude": row["latitude"], "longitude": row["longitude"]}
    return groups, pois


def get_reviews(tab: str = "liens", service: str | None = None, city: str | None = None, kind: str | None = None,
                town: str | None = None) -> dict:
    """
    Une file de relecture, ou toutes (ALL_TABS), ses compteurs, les filtres et les dernières décisions. service est un
    onglet de l'étape 4, kind un type précis dans cet onglet (le sous-filtre, quand l'onglet en a plusieurs).
    """
    if tab not in TAB_SIGNALS and tab != ALL_TABS:
        raise ValueError(f"File inconnue : {tab}")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        groups, pois = _pending(cursor, service, city, kind=kind, town=town)
        counts = {name: 0 for name in TAB_SIGNALS}
        for name, _ in groups:
            counts[name] += 1
        counts[ALL_TABS] = sum(counts.values())
        # Le nombre de lieux par onglet, puis par type dans l'onglet choisi, dans la file et la ville choisies.
        all_groups, all_pois = _pending(cursor, None, city, town=town) if service or kind else (groups, pois)
        in_tab = [poi_id for name, poi_id in all_groups if tab in (name, ALL_TABS)]
        service_counts = Counter(all_pois[poi_id]["onglet"] for poi_id in in_tab)
        type_counts = Counter(all_pois[poi_id]["service"] or "" for poi_id in in_tab
                              if service and all_pois[poi_id]["onglet"] == service)
        cards = [build_card(name, pois[poi_id], signals) for (name, poi_id), signals in groups.items() if tab in (name, ALL_TABS)]
        # Un lieu à fermeture signalée : son lien attend qu'on tranche la fermeture.
        masked = _masked_ids(cursor, [card["poi_id"] for card in cards if card["tab"] == "liens"])
        for card in cards:
            if card["tab"] == "liens" and card["poi_id"] in masked:
                card["auto"] = False
                card["proposal"] = "ce lieu est masqué pour une fermeture signalée : à trancher d'abord."
        for card in cards:
            if card["tab"] == "doublons" and mixed_sheet_table(cursor, card["poi_id"], card.get("autre_id")):
                offer_mixed_place(card)
        cards.sort(key=lambda card: (card["nom"] or "").lower())

        cursor.execute("""
            SELECT DISTINCT c.name, c.commune FROM poi_signals sg JOIN histo_poi h ON h.poi_id = sg.poi_id
            JOIN cities c ON c.id = h.city_id WHERE sg.statut = 'a_relire' ORDER BY c.name
        """)
        city_rows = [{"id": row["name"], "name": row["name"], "commune": row["commune"]} for row in cursor.fetchall()]
        # La recherche de ville, comme dans « Modifier » : les villes qui ont des lieux à relire, et les communes des
        # adresses de ces lieux, avec leurs codes postaux.
        cursor.execute("""
            SELECT DISTINCT p.address FROM poi_signals sg JOIN poi p ON p.id = sg.poi_id
            WHERE sg.statut = 'a_relire' AND p.address IS NOT NULL
        """)
        city_codes, towns = town_choices([row["address"] for row in cursor.fetchall()], city_rows)
        cities = [{"name": row["name"], "codes": city_codes.get(row["name"], [])} for row in city_rows]
        cursor.execute("""
            SELECT d.id, d.decision, d.note, d.decided_by, d.decided_at, p.name FROM decisions d
            JOIN poi p ON p.id = d.objet_id
            WHERE d.objet_type = %s AND d.annulee_at IS NULL ORDER BY d.id DESC LIMIT %s
        """, (POI, RECENT_DECISIONS))
        recent = [{"id": row["id"], "nom": row["name"], "action": ACTION_LABELS.get(row["decision"], row["decision"]),
                   "note": row["note"] or "", "par": row["decided_by"], "le": row["decided_at"].strftime("%d/%m/%Y")}
                  for row in cursor.fetchall()]
        audit = _audit_sample(cursor, tab, service, city)
        cursor.close()
        return {"tab": tab, "counts": counts, "notation": rating.labels(), "service_counts": dict(service_counts), "type_counts": dict(type_counts),
                "total": len(cards), "cards": cards[:PAGE_SIZE],
                "cities": cities, "towns": towns, "recent": recent, "audit": audit}
    finally:
        MySQLUtils.disconnect(connection)


def _masked_ids(cursor, poi_ids: list) -> set:
    if not poi_ids:
        return set()
    marks = ",".join(["%s"] * len(poi_ids))
    cursor.execute(f"SELECT id FROM poi WHERE masque = 1 AND id IN ({marks})", tuple(poi_ids))
    return {row["id"] for row in cursor.fetchall()}


def _audit_sample(cursor, tab: str, service: str | None = None, city: str | None = None) -> list:
    """
    Quelques décisions de la règle, tirées au sort dans la file et les filtres affichés : si elles sont fausses, on
    resserre la règle. Chacune dit ce que la règle a lu (le signal) : le lien du lieu seul faisait croire qu'elle
    avait jugé le lien (Steak 'n Shake, un renommage OSM classé sans suite, 7 novembre 2026).
    """
    filters, params = ["d.objet_type = %s", "d.decided_by = %s", "d.annulee_at IS NULL", "d.note IS NULL"], [POI, RULE_AUTHOR]
    if tab != ALL_TABS:
        filters.append("JSON_UNQUOTE(JSON_EXTRACT(d.detail, '$.file')) = %s")
        params.append(tab)
    if city:
        filters.append("EXISTS (SELECT 1 FROM histo_poi h JOIN cities c ON c.id = h.city_id"
                       " WHERE h.poi_id = p.id AND c.name = %s)")
        params.append(city)
    if service and service != NO_TAB:
        categories = tab_categories(service) or ("",)
        filters.append("EXISTS (SELECT 1 FROM poi_service ps JOIN services s ON s.id = ps.service_id"
                       f" WHERE ps.poi_id = p.id AND s.category IN ({', '.join(['%s'] * len(categories))}))")
        params.extend(categories)
    cursor.execute(f"""
        SELECT d.id, d.decision, d.detail, p.name, p.address, p.url FROM decisions d JOIN poi p ON p.id = d.objet_id
        WHERE {' AND '.join(filters)} ORDER BY RAND() LIMIT %s
    """, (*params, AUDIT_SIZE))
    rows = cursor.fetchall()
    signal_ids = [signal_id for row in rows for signal_id in _detail(row).get("signal_ids", [])]
    signals = {}
    if signal_ids:
        marks = ",".join(["%s"] * len(signal_ids))
        cursor.execute(f"SELECT id, source, signal_type, detail FROM poi_signals WHERE id IN ({marks})", tuple(signal_ids))
        signals = {signal["id"]: signal for signal in cursor.fetchall()}
    sample = []
    for row in rows:
        detail = _detail(row)
        read = [signals[signal_id] for signal_id in detail.get("signal_ids", []) if signal_id in signals]
        sample.append({"id": row["id"], "nom": row["name"], "adresse": row["address"] or "",
                       "action": ACTION_LABELS.get(row["decision"], row["decision"]),
                       "signal": "; ".join(f"{SIGNAL_LABELS.get(signal['signal_type'], signal['signal_type'])} : {proof_text(signal)}"
                                           for signal in read),
                       "url": row["url"] or detail.get("avant", {}).get("url")})
    return sample


def confirm_audit(decision_id: int) -> None:
    """Une décision de la règle vue et jugée bonne : elle ne sera plus tirée au sort."""
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE decisions SET note = %s WHERE id = %s AND objet_type = %s AND decided_by = %s",
                       (AUDIT_DONE, decision_id, POI, RULE_AUTHOR))
        connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)


def mixed_sheet_table(cursor, poi_id: int, other_id: int | None) -> str | None:
    """
    La table de la fiche que poi_id peut donner à other_id pour en faire un lieu mixte : l'un a une fiche restaurant,
    l'autre une fiche commerce. None sinon (deux fiches de la même table, ou un lieu sans fiche).
    """
    if not other_id:
        return None
    tables = {poi_id: set(), other_id: set()}
    for table in SHEET_TABLES:
        cursor.execute(f"SELECT poi_id FROM {table} WHERE poi_id IN (%s, %s)", (poi_id, other_id))
        for row in cursor.fetchall():
            tables[row["poi_id"]].add(table)
    mine, theirs = tables[poi_id], tables[other_id]
    return next(iter(mine)) if len(mine) == 1 and len(theirs) == 1 and mine != theirs else None


def join_mixed_place(cursor, poi_id: int, other_id: int, table: str) -> list:
    """
    Fait de other_id un lieu mixte : il reçoit la fiche de poi_id (dans sa table) et ses services, pour s'afficher dans
    les deux onglets de l'étape 4. poi_id, lui, est masqué par la décision. Rend les services ajoutés, pour l'annulation.
    """
    cursor.execute(f"UPDATE {table} SET poi_id = %s WHERE poi_id = %s", (other_id, poi_id))
    cursor.execute("""SELECT service_id FROM poi_service WHERE poi_id = %s
                      AND service_id NOT IN (SELECT service_id FROM poi_service WHERE poi_id = %s)""", (poi_id, other_id))
    added = [row["service_id"] for row in cursor.fetchall()]
    for service_id in added:
        cursor.execute("INSERT INTO poi_service (poi_id, service_id) VALUES (%s, %s)", (other_id, service_id))
    return added


def split_mixed_place(cursor, poi_id: int, mixed: dict) -> None:
    """Défait un lieu mixte (annulation) : la fiche revient à poi_id, l'autre perd les services qu'il avait reçus."""
    cursor.execute(f"UPDATE {mixed['table']} SET poi_id = %s WHERE poi_id = %s", (poi_id, mixed["vers"]))
    for service_id in mixed["services"]:
        cursor.execute("DELETE FROM poi_service WHERE poi_id = %s AND service_id = %s", (mixed["vers"], service_id))


def decide_one(cursor, tab: str, poi_id: int, action: str, note: str, decided_by: str, months: list | None,
               url: str | None = None, name: str | None = None, pertinence: str | None = None,
               raison: str | None = None) -> None:
    """
    Applique et enregistre la décision sur un lieu d'une file. pertinence et raison : la note facultative de l'humain
    sur la proposition de l'agent (rating, #201) ; None quand elle n'est pas notée, comme pour les règles.
    """
    cursor.execute("""
        SELECT sg.id, sg.poi_id, sg.source, sg.signal_type, sg.detail FROM poi_signals sg
        WHERE sg.poi_id = %s AND sg.statut = 'a_relire'
    """, (poi_id,))
    signals = [row for row in cursor.fetchall() if SIGNAL_TAB.get(row["signal_type"]) == tab]
    if not signals:
        raise ValueError("Ce lieu n'a plus rien à relire dans cette file")
    card = build_card(tab, {"id": poi_id, "name": ""}, signals)
    mixed_table = mixed_sheet_table(cursor, poi_id, card.get("autre_id")) if action == MIXED and tab == "doublons" else None
    if action == MIXED and not mixed_table:
        raise ValueError("Lieu mixte : il faut une fiche restaurant d'un côté et une fiche commerce de l'autre")
    if action not in card["actions"] and action not in RULE_ACTIONS and action != MIXED:
        raise ValueError(f"Décision impossible ici : {action}")
    if action == KEEP_THIS:
        keep_this_place(cursor, poi_id, card, signals, note, decided_by, pertinence, raison)
        return
    if action == REMOVE_BOTH:
        remove_both_places(cursor, poi_id, card, note, decided_by, pertinence, raison)
        return
    fields = applied_fields(action, card, months, url, name)
    cursor.execute(f"SELECT {', '.join(APPLIED_COLUMNS)} FROM poi WHERE id = %s", (poi_id,))
    before = cursor.fetchone()
    if fields:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*fields.values(), poi_id))
    if action == "valider_pepite":
        # La fiche reste si la décision est annulée : le lieu redevient masqué, l'étape 4 ne le montre plus.
        # La fiche va dans la table de l'agent qui l'a préparée : restaurants ou commerces.
        category = CATEGORIES.get(signals[0].get("source"), RESTAURANTS)
        service_store.save_validated_sheet(category, cursor, poi_id, _detail(signals[0]).get("fiche"))
    mixed = None
    if mixed_table:
        added = join_mixed_place(cursor, poi_id, card["autre_id"], mixed_table)
        mixed = {"vers": card["autre_id"], "table": mixed_table, "services": added}
    # Ajouter un lien depuis une autre file ne tranche pas ce qu'elle demande (le nom, la fermeture) : le signal reste.
    signal_ids = [] if SIDE_ACTIONS.get(action, tab) != tab else [signal["id"] for signal in signals]
    if action == "retirer":
        # Un lieu retiré n'a plus rien à relire : ses signaux des autres files sont tranchés avec lui (et rouverts si
        # la décision est annulée).
        cursor.execute("SELECT id FROM poi_signals WHERE poi_id = %s AND statut = 'a_relire'", (poi_id,))
        signal_ids = [row["id"] for row in cursor.fetchall()]
    if signal_ids:
        marks = ",".join(["%s"] * len(signal_ids))
        cursor.execute(f"UPDATE poi_signals SET statut = %s, reviewed_at = NOW() WHERE id IN ({marks})",
                       (ACTIONS[action], *signal_ids))
    detail = {"file": tab, "signal_ids": signal_ids, "avant": {column: before[column] for column in fields}}
    if mixed:
        detail["lieu_mixte"] = mixed
    record_decision(cursor, POI, poi_id, action, note, decided_by, detail,
                    pertinence=pertinence, raison=raison)
    if action == "autre_maps":
        confirm_located(cursor, poi_id, fields, decided_by)


def keep_this_place(cursor, poi_id: int, card: dict, signals: list, note: str, decided_by: str,
                    pertinence: str | None = None, raison: str | None = None) -> None:
    """
    « Garder ce lieu » sous le lieu de la carte : l'autre lieu (autre_id) est masqué, celui-ci reste. La décision est
    enregistrée sur le lieu masqué, sous le nom « fusionner » : c'est elle que lisent les règles, les agents et les
    carburants (poi_triage_service, load_carburants) pour ne jamais le réafficher. Une décision « fusionner » veut donc
    toujours dire « ce lieu est masqué comme doublon d'un autre », quel que soit le bouton cliqué.
    Une station figée (doublon_station) était masquée en attendant : la garder la réaffiche. detail.garde retient le
    lieu gardé et son état d'avant, pour que l'annulation remette les deux lieux comme avant (cancel_decision).
    La note de la proposition (pertinence, raison) va sur cette unique décision : une carte, une note.
    """
    other_id = card["autre_id"]
    cursor.execute("SELECT id, masque FROM poi WHERE id IN (%s, %s)", (poi_id, other_id))
    masked_before = {row["id"]: row["masque"] for row in cursor.fetchall()}
    if other_id not in masked_before:
        raise ValueError("L'autre lieu n'existe plus : impossible de le masquer")
    cursor.execute("UPDATE poi SET masque = %s WHERE id = %s", (1, other_id))
    kept = {"poi_id": poi_id, "avant": {}}
    if card.get("reafficher"):
        cursor.execute("UPDATE poi SET masque = %s WHERE id = %s", (0, poi_id))
        kept["avant"] = {"masque": masked_before.get(poi_id)}
    # Les signaux tranchés sont ceux de la carte : c'est ce lieu-ci qui portait le doute.
    signal_ids = [signal["id"] for signal in signals]
    marks = ",".join(["%s"] * len(signal_ids))
    cursor.execute(f"UPDATE poi_signals SET statut = %s, reviewed_at = NOW() WHERE id IN ({marks})",
                   (ACTIONS[KEEP_THIS], *signal_ids))
    detail = {"file": "doublons", "signal_ids": signal_ids, "avant": {"masque": masked_before[other_id]}, "garde": kept}
    record_decision(cursor, POI, other_id, "fusionner", note, decided_by, detail,
                    pertinence=pertinence, raison=raison)


def remove_both_places(cursor, poi_id: int, card: dict, note: str, decided_by: str,
                       pertinence: str | None = None, raison: str | None = None) -> None:
    """
    « Aucun des deux » : ni ce lieu ni l'autre ne sont à garder (rare : deux lignes d'un restaurant qui a fermé).
    Ce lieu est retiré comme avec « Retirer le lieu », puis l'autre de la même façon. Chacun reçoit sa propre décision
    « retirer » : les agents et les carburants la lisent déjà pour ne pas le réafficher, et chaque retrait s'annule à part.
    La note de la proposition ne va que sur la décision de ce lieu-ci, celui de la carte : une carte, une note
    (la noter deux fois compterait double dans le bilan).
    """
    decide_one(cursor, "doublons", poi_id, "retirer", note, decided_by, None, pertinence=pertinence, raison=raison)
    remove_other_place(cursor, card["autre_id"], note, decided_by)


def remove_other_place(cursor, other_id: int, note: str, decided_by: str) -> None:
    """
    Retire l'autre lieu d'un doublon, qui n'a pas de carte à lui : il est masqué, ses signaux à relire sont tranchés
    (un lieu retiré n'a plus rien à relire), et la décision « retirer » garde son état d'avant pour l'annulation.
    """
    cursor.execute("SELECT masque FROM poi WHERE id = %s", (other_id,))
    before = cursor.fetchone()
    if not before:
        raise ValueError("L'autre lieu n'existe plus : impossible de le retirer")
    cursor.execute("UPDATE poi SET masque = %s WHERE id = %s", (1, other_id))
    cursor.execute("SELECT id FROM poi_signals WHERE poi_id = %s AND statut = 'a_relire'", (other_id,))
    signal_ids = [row["id"] for row in cursor.fetchall()]
    if signal_ids:
        marks = ",".join(["%s"] * len(signal_ids))
        cursor.execute(f"UPDATE poi_signals SET statut = %s, reviewed_at = NOW() WHERE id IN ({marks})",
                       (ACTIONS["retirer"], *signal_ids))
    detail = {"file": "doublons", "signal_ids": signal_ids, "avant": {"masque": before["masque"]}}
    record_decision(cursor, POI, other_id, "retirer", note, decided_by, detail)


def confirm_located(cursor, poi_id: int, fields: dict, decided_by: str) -> bool:
    """
    Un humain vient de donner au lieu un lien Google Maps qui porte sa position (fields). Si le lieu n'attendait une
    relecture que pour sa « position introuvable », il est confirmé du même geste, sous le nom de cet humain : la position
    était le seul doute, et pour l'utilisatrice le lien Google Maps est la référence qu'un lieu existe (11 novembre 2026 :
    4 lieux avaient reçu leur lien et attendaient encore un second clic). Annulable comme toute décision.
    """
    if "latitude" not in fields:
        return False
    cursor.execute("""SELECT id, detail FROM poi_signals WHERE poi_id = %s AND signal_type = 'a_confirmer'
                      AND statut = 'a_relire'""", (poi_id,))
    signals = list(cursor.fetchall())
    if not signals or any(_detail(signal).get("raison") != service_store.NO_POSITION
                          or not (_detail(signal).get("fiche") or {}).get("genre") for signal in signals):
        return False
    decide_one(cursor, "confirmer", poi_id, "valider_pepite", "position donnée par le lien Google Maps", decided_by, None)
    return True


def decide(tab: str, poi_ids: list, action: str, note: str, decided_by: str, months: list | None = None,
           url: str | None = None, name: str | None = None, pertinence: str | None = None,
           raison: str | None = None) -> None:
    """
    Enregistre et applique une décision, sur un lieu ou sur un lot de liens contrôlés, en une transaction.
    pertinence et raison : la note facultative de la proposition, pour un seul lieu (un lot n'est pas noté, #201).
    """
    if tab not in TAB_SIGNALS or action not in ACTIONS or action in RULE_ACTIONS:
        raise ValueError("Décision inconnue")
    if len(poi_ids) > 1 and (tab != "liens" or action != "valider_lien"):
        raise ValueError("Seuls les liens se valident par lot")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        for poi_id in poi_ids:
            decide_one(cursor, tab, poi_id, action, note, decided_by, months, url, name, pertinence, raison)
        connection.commit()
        cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        MySQLUtils.disconnect(connection)


def cancel_decision(decision_id: int) -> None:
    """Annule une décision : le lieu reprend ses valeurs d'avant et revient à la relecture. Elle reste tracée."""
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT objet_id, detail FROM decisions WHERE id = %s AND objet_type = %s AND annulee_at IS NULL",
                       (decision_id, POI))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Décision introuvable")
        detail = json.loads(row["detail"]) if isinstance(row["detail"], str) else row["detail"]
        before = {column: value for column, value in detail["avant"].items() if column in APPLIED_COLUMNS}
        if before:
            assignments = ", ".join(f"{column} = %s" for column in before)
            cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*before.values(), row["objet_id"]))
        if detail.get("avant_fiche"):
            restore_sheet(cursor, row["objet_id"], detail["avant_fiche"])
        if detail.get("lieu_mixte"):
            split_mixed_place(cursor, row["objet_id"], detail["lieu_mixte"])
        if detail.get("garde"):
            restore_kept_place(cursor, detail["garde"])
        signal_ids = detail["signal_ids"]
        if signal_ids:
            marks = ",".join(["%s"] * len(signal_ids))
            cursor.execute(f"UPDATE poi_signals SET statut = 'a_relire', reviewed_at = NULL WHERE id IN ({marks})", tuple(signal_ids))
        cursor.execute("UPDATE decisions SET annulee_at = NOW() WHERE id = %s", (decision_id,))
        connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)


def restore_kept_place(cursor, kept: dict) -> None:
    """Annulation de « Garder ce lieu » : le lieu gardé reprend son état d'avant (une station figée redevient masquée)."""
    before = {column: value for column, value in (kept.get("avant") or {}).items() if column in APPLIED_COLUMNS}
    if before:
        assignments = ", ".join(f"{column} = %s" for column in before)
        cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*before.values(), kept["poi_id"]))


def restore_sheet(cursor, poi_id: int, before: dict) -> None:
    """
    Remet la fiche d'avant une fiche corrigée à la main : dans sa table (restaurants, commerces), ou dans le signal d'un
    lieu à confirmer, dont la fiche préparée par l'agent n'est pas encore en table.
    """
    columns = SHEET_COLUMNS.get(before.get("table"), ())
    values = {column: value for column, value in (before.get("values") or {}).items() if column in columns}
    if not values:
        return
    if before.get("origine") == "table":
        assignments = ", ".join(f"{column} = %s" for column in values)
        cursor.execute(f"UPDATE {before['table']} SET {assignments} WHERE poi_id = %s", (*values.values(), poi_id))
    elif before.get("origine") == "signal":
        cursor.execute("SELECT detail FROM poi_signals WHERE id = %s", (before["signal_id"],))
        signal = cursor.fetchone()
        if signal:
            detail = _detail(signal)
            detail["fiche"] = {**(detail.get("fiche") or {}), **values}
            cursor.execute("UPDATE poi_signals SET detail = %s WHERE id = %s",
                           (json.dumps(detail, ensure_ascii=False, default=str), before["signal_id"]))
