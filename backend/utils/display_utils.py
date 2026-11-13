"""
Préparation des textes prêts à afficher pour le frontend.

Toute la logique de présentation (libellés français, pluriels, badges,
catégories, formatage des nombres et des dates) vit ICI, en Python.
Le JavaScript ne fait plus que recevoir ces champs et les insérer dans la page.

Conventions de nommage des champs ajoutés aux réponses API :
  - *_label : texte prêt à afficher ("350 m", "⭐ 4.2/5", "Lundi 7 juil")
  - *_css   : nom de classe CSS à appliquer ("good-weather", "facile")
  - badge   : dictionnaire {"text": "Vérifié", "css": "verified"}

Les fonctions sont pures (pas d'accès base de données) : elles sont testées
dans tests/unit/utils/test_display_utils.py.
"""

import math
import re
from datetime import date, datetime
from html import escape

# ---------------------------------------------------------------------------
# Petits utilitaires de formatage "à la JavaScript"
# ---------------------------------------------------------------------------
# Le frontend historique insérait les nombres bruts dans les textes : en JS,
# 13.0 s'affiche "13" et 13.5 s'affiche "13.5". On reproduit ce comportement
# pour que les textes générés en Python soient identiques à l'ancien affichage.


def js_num(value) -> str:
    """Formate un nombre comme le ferait JavaScript (13.0 → "13", 13.5 → "13.5")."""
    if value is None:
        return ""
    return f"{float(value):g}"


def js_round(value) -> int:
    """Arrondi à la JavaScript : Math.round arrondit toujours 0.5 vers le haut,
    alors que le round() de Python arrondit 0.5 vers le pair le plus proche."""
    return math.floor(float(value) + 0.5)


# UN DOUTE EN ATTENTE = « NON VÉRIFIÉ » (11 novembre 2026). Un service dont un signal attend une relecture dans la
# supervision (un lien d'OSM à valider, un renommage, un doublon possible) s'affiche « non vérifié » jusqu'à la décision :
# 78 services s'affichaient « Vérifié » avec un doute en attente. Le badge en base n'est pas touché : il revient tout seul
# quand le doute est tranché. À mettre dans le SELECT d'une requête sur « poi p », puis à donner à shown_verified.
PENDING_DOUBT_SQL = "EXISTS (SELECT 1 FROM poi_signals doute WHERE doute.poi_id = p.id AND doute.statut = 'a_relire')"


def shown_verified(verified, pending_doubt) -> bool:
    """Le badge montré : celui de la base, sauf si un doute attend une relecture (PENDING_DOUBT_SQL)."""
    return bool(verified) and not pending_doubt


def verified_badge(verifie) -> dict:
    """Badge de vérification affiché sur les cartes randonnée/spot/service."""
    if verifie:
        return {"text": "Vérifié", "css": "verified"}
    return {"text": "Non vérifié", "css": "pending"}


# ---------------------------------------------------------------------------
# Météo (étape 1)
# ---------------------------------------------------------------------------

# Jours et mois en français pour les entêtes des cartes météo.
FR_WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
FR_MONTHS_SHORT = ["janv", "févr", "mars", "avr", "mai", "juin",
                   "juil", "août", "sept", "oct", "nov", "déc"]

# Conseil de randonnée associé à chaque pictogramme météo
# (icône Font Awesome + phrase affichée sous la carte météo).
WEATHER_ADVICE = {
    "sun":           {"icon": "fa-check-circle",         "text": "Parfait pour randonner"},
    "partly_cloudy": {"icon": "fa-check-circle",         "text": "Parfait pour randonner"},
    "storm":         {"icon": "fa-exclamation-triangle", "text": "Éviter les randos"},
    "rain":          {"icon": "fa-info-circle",          "text": "Équipements conseillés"},
    "snow":          {"icon": "fa-info-circle",          "text": "Équipements conseillés"},
    "fog":           {"icon": "fa-eye-slash",            "text": "Avec prudence"},
    "cloud":         {"icon": "fa-cloud",                "text": "Conditions correctes"},
    "indisponible":  {"icon": "fa-question-circle",      "text": "Météo indisponible"},
}

# Par beau temps, on remplace le conseil par un avertissement chaleur
# dès que la température maximale atteint ce seuil.
HEAT_ADVICE_THRESHOLD_C = 25
GOOD_WEATHER_PICTOS = ("sun", "partly_cloudy", "cloud")


def weather_css(weather_code) -> str:
    """Classe CSS de la carte météo selon le code météo Open-Meteo :
    beau temps (fond vert), acceptable (orange), mauvais (rouge)."""
    if weather_code is None:
        return "good-weather"
    if 45 <= weather_code <= 65:
        return "acceptable-weather"
    if weather_code > 65:
        return "bad-weather"
    return "good-weather"


def weather_advice(picto, temp_max) -> dict:
    """Conseil de randonnée du jour : celui du pictogramme, sauf par beau temps
    chaud où l'on conseille plutôt de partir tôt."""
    if picto in GOOD_WEATHER_PICTOS and temp_max is not None \
            and temp_max >= HEAT_ADVICE_THRESHOLD_C:
        return {"icon": "fa-sun", "text": "Partez de bonne heure"}
    return WEATHER_ADVICE.get(picto, WEATHER_ADVICE["indisponible"])


def meteo_day_label(forecast_date, index) -> str:
    """Entête de la carte météo : "Aujourd'hui" pour la première prévision,
    sinon "Lundi 7 juil". (La première prévision est toujours celle du jour :
    on se fie à sa position, pas à la date système.)"""
    if index == 0:
        return "Aujourd'hui"
    if isinstance(forecast_date, str):
        forecast_date = datetime.strptime(forecast_date, "%Y-%m-%d").date()
    return (f"{FR_WEEKDAYS[forecast_date.weekday()]} "
            f"{forecast_date.day} {FR_MONTHS_SHORT[forecast_date.month - 1]}")


def enrich_meteo_forecasts(forecasts) -> list:
    """Ajoute à chaque prévision météo ses champs prêts à afficher :
    day_label, css, advice, températures/pluie/vent formatés."""
    for index, f in enumerate(forecasts):
        f["day_label"] = meteo_day_label(f.get("date"), index)
        f["css"] = weather_css(f.get("weather_code"))
        f["advice"] = weather_advice(f.get("picto"), f.get("temp_max"))
        f["temp_max_label"] = f"{js_round(f['temp_max'])}°" if f.get("temp_max") is not None else "?"
        f["temp_min_label"] = f"{js_round(f['temp_min'])}°" if f.get("temp_min") is not None else "?"
        # Pluie et vent : affichés seulement s'ils sont non nuls (None sinon).
        precipitation = f.get("precipitation_sum") or 0
        f["precipitation_label"] = f"{float(precipitation):.1f} mm" if precipitation > 0 else None
        wind = f.get("wind_speed_max") or 0
        f["wind_label"] = f"{js_round(wind)} km/h" if wind > 0 else None
    return forecasts


def city_stats_labels(stats) -> dict:
    """Libellés de la fiche ville : "12 randonnées", "50 spots nuit", ..."""
    return {
        "hikes": f"{stats.get('hikes', 0)} randonnées",
        "spots": f"{stats.get('spots', 0)} spots nuit",
        "poi": f"{stats.get('poi', 0)} points d'intérêt",
    }


# ---------------------------------------------------------------------------
# Randonnées (étape 2)
# ---------------------------------------------------------------------------

def duration_category(duration_h) -> str:
    """Catégorie de durée utilisée par le filtre "Durée" de l'étape 2."""
    if duration_h is None:
        return "long"
    if duration_h < 2:
        return "court"
    if duration_h <= 4:
        return "moyen"
    return "long"


def hike_trace_color(index, total) -> str:
    """Teinte de teal propre à chaque randonnée (dégradé clair → foncé), assortie
    à l'identité Vany, pour distinguer les tracés GPX qui se chevauchent sur la
    carte. Stable car les randonnées sont triées par nom dans la requête SQL."""
    lightness = 50 - (index / (total - 1)) * 20 if total > 1 else 40
    return f"hsl(187, 55%, {js_num(lightness)}%)"


# Heure de départ supposée de la rando du jour. Tout le calcul de la journée en
# découle (temps libre, sorties possibles après la rando : pepite_service.DAY_START_H)
# et Vany s'y réfère (« ta rando finit vers 11 h ») : elle est donc affichée au
# voyageur (hike_schedule_label), à l'étape 2, dans le carnet et dans le PDF.
HIKE_START_H = 9


def hour_label(hour: float) -> str:
    """Heure lisible au quart d'heure près : 11 -> "11 h", 11.5 -> "11 h 30"."""
    minutes = round(hour * 4) * 15
    h, m = divmod(minutes, 60)
    return f"{h} h" if m == 0 else f"{h} h {m:02d}"


def hike_schedule_label(duration_h) -> str:
    """ "Départ conseillé vers 9 h, retour vers 11 h 30" pour une rando de 2 h 30. """
    if duration_h is None:
        return ""
    return f"Départ conseillé vers {hour_label(HIKE_START_H)}, retour vers {hour_label(HIKE_START_H + float(duration_h))}"


def enrich_hike(hike, index, total) -> dict:
    """Ajoute à une randonnée ses champs prêts à afficher."""
    difficulte = hike.get("difficulte")
    hike["difficulty_css"] = difficulte.lower() if difficulte else "facile"
    hike["difficulty_label"] = difficulte or "N/A"
    hike["duration_category"] = duration_category(hike.get("duration"))
    hike["badge"] = verified_badge(hike.get("verifie"))
    hike["description_label"] = hike.get("description") or "Randonnée sans description"
    # Résumé affiché dans les popups de la carte ("13 km - 4h").
    hike["summary_label"] = f"{js_num(hike.get('distance_km'))} km - {js_num(hike.get('duration'))}h"
    hike["schedule_label"] = hike_schedule_label(hike.get("duration"))
    hike["color"] = hike_trace_color(index, total)
    return hike


# ---------------------------------------------------------------------------
# Spots nuit (étape 3)
# ---------------------------------------------------------------------------

# Types de spots (colonne spots.type) classés gratuit/payant pour le filtre
# "Prix" de l'étape 3. Tout type absent de ces listes est classé "autres".
SPOT_TYPES_GRATUIT = (
    "AIRE CC STAT. GRATUIT",
    "PARKING CC SANS SERVICES",
    "PARKING JOUR ET NUIT",
    "AIRE DE REPOS",
)
SPOT_TYPES_PAYANT = (
    "AIRE CC STAT. PAYANT",
    "CAMPING",
    "AIRE CC PRIVÉE",
    "ACCUEIL ENTRE PARTICULIERS",
    "A LA FERME (FERME, VIGNOBLE ...)",
)

# Icône affichée devant chaque service d'un spot (recherche par inclusion,
# insensible à la casse : "eau potable" → 💧). "✓" par défaut.
SPOT_SERVICE_ICONS = {
    "Eau": "💧",
    "WC": "🚽",
    "Douche": "🚿",
    "Électricité": "⚡",
    "WiFi": "📶",
    "Restaurant": "🍽️",
    "Supermarché": "🛒",
    "Boulangerie": "🥐",
    "Parking": "🅿️",
    "Plage": "🏖️",
    "Vue mer": "🌅",
    "Lavage": "🧽",
}


# Types de spots jamais affichés à l'étape 3 (points de services sans
# stationnement) : utilisé par l'API (step3) ET par l'harmonisation IA, qui
# n'a pas à traiter des spots que personne ne verra.
# Types de spots qui n'intéressent pas Randovango : on ne peut pas y dormir.
# Un nouveau spot de ce type n'est pas chargé en base (etl/load/load_p4n.py).
EXCLUDED_SPOT_TYPES = ("PARKING JOUR UNIQUEMENT",)

HIDDEN_SPOT_TYPES = (
    "AIRE DE SERVICES SANS STAT.",
    "SERVICES D'APPOINT",
    # Un spot déjà en base peut devenir "jour uniquement" sur p4n : il
    # reste en base (un carnet de voyage peut y faire référence) mais est masqué.
    *EXCLUDED_SPOT_TYPES,
)

# Nom commun de chaque type de spot p4n, utilisé pour construire un nom
# de secours quand la description ne nomme pas le lieu ("Parking · Saint-Cava").
SPOT_TYPE_NOUNS = {
    "PARKING JOUR ET NUIT": "Parking",
    "PARKING CC SANS SERVICES": "Parking camping-car",
    "CAMPING": "Camping",
    "AIRE CC STAT. GRATUIT": "Aire camping-car",
    "AIRE CC STAT. PAYANT": "Aire camping-car",
    "AIRE CC PRIVÉE": "Aire camping-car",
    "AIRE DE SERVICES SANS STAT.": "Aire de services",
    "AIRE DE REPOS": "Aire de repos",
    "SERVICES D'APPOINT": "Services",
    "PARKING JOUR UNIQUEMENT": "Parking de jour",
    "ACCUEIL ENTRE PARTICULIERS": "Chez l'habitant",
    "A LA FERME (FERME, VIGNOBLE ...)": "À la ferme",
}

# Numéro de rue en tête d'une adresse : "139", "54B", "33-35", "9001F".
HOUSE_NUMBER_RE = re.compile(r"^\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?\s+")


def spot_name_label(place_label, city_label, name, spot_type):
    """
    Nom affiché d'un spot, construit SANS IA à partir des données p4n.

    1. Le type du spot + le lieu, sans numéro de rue :
         "139 Mechou Kamm Doun" (PARKING JOUR ET NUIT) -> "Parking · Mechou Kamm Doun"
         "Camping Kermaléro"    (CAMPING)              -> "Camping Kermaléro" (inchangé)
    2. À défaut de lieu, la commune ; en dernier recours, le nom p4n brut.
    Renvoie None si le spot n'existe pas (tout est vide).
    """
    noun = SPOT_TYPE_NOUNS.get((spot_type or "").upper().strip(), "Spot")

    # Le lieu : le libellé sans son numéro de rue, ou à défaut la commune.
    place = HOUSE_NUMBER_RE.sub("", place_label).strip() if place_label else ""
    place = place or city_label
    if not place:
        return name

    # Pas de "Camping · Camping Kermaléro" : si le libellé commence déjà par le
    # premier mot du type, il se suffit à lui-même.
    first_word = noun.split()[0].lower()
    if place.lower().startswith(first_word):
        return place
    return f"{noun} · {place}"


def spot_description_label(description_ia, description, prompt_version) -> str:
    """
    Description affichée d'un spot.
    - Harmonisée par l'IA : on l'affiche.
    - Harmonisée mais vide (l'IA n'a rien trouvé d'utile) : on n'affiche rien,
      le titre et les badges suffisent.
    - Pas encore harmonisée : le texte d'origine du contributeur.
    """
    if description_ia:
        return description_ia
    if prompt_version is not None:
        return ""
    return description or "Aucune description disponible"


def a_savoir_on(items: list, on_date) -> list:
    """
    Phrases de l'« À savoir » retravaillé (verify_spots) valables à cette date. Les périodes
    reviennent chaque année (MM-JJ) et peuvent passer le 31 décembre (du 16/09 au 14/06). Sans
    début, la phrase vaut jusqu'à sa date de fin ; sans fin, à partir de son début.
    """
    day = on_date.strftime("%m-%d")

    def applies(item):
        start, end = item.get("debut"), item.get("fin")
        if start and end and start > end:
            return day >= start or day <= end
        return (not start or day >= start) and (not end or day <= end)
    return [item["texte"] for item in items if applies(item)]


def with_a_savoir(description, sentences: list) -> str:
    """La description avec son paragraphe « À savoir » remplacé ; retiré s'il ne reste aucune phrase."""
    presentation = (description or "").split("À savoir :", 1)[0].strip()
    if not sentences:
        return presentation
    a_savoir = "À savoir : " + " ".join(sentences)
    return f"{presentation}\n\n{a_savoir}" if presentation else a_savoir


def spot_description_html(description) -> str:
    """
    Description d'un spot prête à insérer en HTML (fiche de l'étape 3). Le texte est
    échappé, puis le paragraphe des mises en garde de la description harmonisée
    (« À savoir : l'aire est en pente... ») est signalé par son libellé en gras.
    """
    text = escape(description or "")
    return re.sub(r"^À savoir :", '<strong class="spot-warning">À savoir :</strong>', text, flags=re.M)


def spot_category(spot_type) -> str:
    """Catégorie prix d'un spot : "gratuit", "payant" ou "autres"."""
    if not spot_type:
        return "autres"
    t = spot_type.upper().strip()
    if t in SPOT_TYPES_GRATUIT:
        return "gratuit"
    if t in SPOT_TYPES_PAYANT:
        return "payant"
    return "autres"


# Un badge par CATÉGORIE de service (et non par service p4n) : les
# services équivalents sont ainsi fusionnés ("Coins de pêche" + "Pêche à pied"
# -> "Pêche"). Clé = code de catégorie en base (services.category, cf.
# SERVICE_CATEGORY_MAP), valeur = (icône, libellé français affiché).
# L'ordre du dictionnaire est l'ordre d'affichage : équipements, puis activités.
SPOT_SERVICE_CATEGORIES = {
    # Équipements
    "drinking_water":        ("💧", "Eau potable"),
    "sanitary_dump_station": ("💧", "Vidange"),          # Eaux usées + Eaux noires
    "toilets":               ("✓", "Toilettes"),
    "shower":                ("🚿", "Douches"),
    "power_supply":          ("⚡", "Électricité"),
    "internet_access":       ("📶", "Internet"),         # WiFi + 3G/4G
    "waste_disposal":        ("✓", "Poubelle"),
    "laundry":               ("✓", "Laverie"),
    "pets":                  ("✓", "Animaux autorisés"),
    "fuel":                  ("✓", "Gaz / GPL"),         # Station GPL + Dépannage en gaz
    "car_wash":              ("🧽", "Lavage camping-car"),
    "bakery":                ("🥐", "Boulangerie"),
    "shop":                  ("🥐", "Boulangerie"),
    "butcher":               ("✓", "Boucherie, poissonnerie, fromagerie"),
    "wine":                  ("✓", "Cave"),
    "confectionery":         ("✓", "Gourmandises"),
    "caravan_site":          ("✓", "Caravaneige"),
    # Activités
    "hiking":                ("✓", "Randonnée"),
    "viewpoint":             ("✓", "Point de vue"),
    "swimming":              ("✓", "Baignade"),
    "swimming_pool":         ("✓", "Piscine"),
    "fishing":               ("✓", "Pêche"),             # Coins de pêche + Pêche à pied
    "bicycle":               ("✓", "VTT"),
    "canoe":                 ("✓", "Canoë / kayak"),
    "watersport":            ("✓", "Windsurf / kitesurf"),
    "climbing":              ("✓", "Escalade"),
    "tourism":               ("✓", "Monuments"),
    "playground":            ("✓", "Aire de jeux"),
}


def spot_services_display(services) -> list:
    """
    Badges des services d'un spot : un badge par catégorie, avec son libellé
    français, dans l'ordre de SPOT_SERVICE_CATEGORIES.

    `services` est une liste de {"name": ..., "category": ...}. Un service dont
    la catégorie est inconnue garde son nom p4n (repli de
    spot_service_display), pour ne jamais faire disparaître une information.
    """
    categories = {s.get("category") for s in services}

    badges = []
    for category, (icon, label) in SPOT_SERVICE_CATEGORIES.items():
        if category in categories:
            badges.append({"icon": icon, "name": label})

    # Services sans catégorie connue : affichés tels quels, sans doublon.
    unknown_names = []
    for service in services:
        if service.get("category") not in SPOT_SERVICE_CATEGORIES and service["name"] not in unknown_names:
            unknown_names.append(service["name"])
    for name in unknown_names:
        badges.append(spot_service_display(name))

    return badges


def spot_service_display(service_name) -> dict:
    """Icône + nom d'un service de spot, prêt à afficher."""
    lower = service_name.lower()
    for key, icon in SPOT_SERVICE_ICONS.items():
        if key.lower() in lower:
            return {"icon": icon, "name": service_name}
    return {"icon": "✓", "name": service_name}


def enrich_spot(spot) -> dict:
    """
    Ajoute à un spot ses champs prêts à afficher.

    Le nom p4n est un gabarit "(29200) Brest - 172 Rue de Quimper" : on
    affiche un nom lisible construit par spot_name_label. La description
    harmonisée par l'IA (`description_ia`) prime sur le texte contributeur brut
    quand elle existe. La source reste disponible dans `name` / `description`.
    """
    spot["category"] = spot_category(spot.get("type"))
    spot["type_label"] = spot.get("type") or "Bivouac"
    spot["badge"] = verified_badge(spot.get("verifie"))
    spot["name_label"] = spot_name_label(
        spot.get("place_label"), spot.get("city_label"), spot.get("name"), spot.get("type"),
    )
    spot["description_label"] = spot_description_label(
        spot.get("description_ia"), spot.get("description"), spot.get("prompt_version"),
    )
    # L'« À savoir » retravaillé par verify_spots remplace celui de la fiche harmonisée.
    if spot.get("a_savoir") is not None:
        spot["description_label"] = with_a_savoir(spot["description_label"], spot["a_savoir"])
    spot["description_html"] = spot_description_html(spot["description_label"])
    rating = spot.get("rating")
    spot["rating_label"] = f"⭐ {js_num(rating)}/5" if rating else None
    spot["services_display"] = spot_services_display(spot.get("services", []))
    # Distance à la rando du jour (étape 3), quand une rando est choisie.
    hike_km = spot.get("hike_distance_km")
    spot["on_hike"] = hike_km is not None and hike_km <= SPOT_ON_HIKE_KM
    spot["hike_distance_label"] = hike_distance_label(hike_km)
    return spot


# ---------------------------------------------------------------------------
# Services / POI (étape 4)
# ---------------------------------------------------------------------------

# Libellés français de chaque catégorie de services, avec le genre pour
# accorder la phrase "Aucun/Aucune ... disponible".
POI_CATEGORY_LABELS = {
    "tout":         {"singular": "service",             "plural": "services",             "gender": "m"},
    "eau":          {"singular": "point d'eau",         "plural": "points d'eau",         "gender": "m"},
    "vidange":      {"singular": "station de vidange",  "plural": "stations de vidange",  "gender": "f"},
    "gasoil":       {"singular": "point carburant",     "plural": "points carburant",     "gender": "m"},
    "supermarche":  {"singular": "supermarché",         "plural": "supermarchés",         "gender": "m"},
    "commerce":     {"singular": "commerce",            "plural": "commerces",            "gender": "m"},
    "restauration": {"singular": "restaurant",          "plural": "restaurants",          "gender": "m"},
    "cafe":         {"singular": "café ou bar",         "plural": "cafés et bars",        "gender": "m"},
    "toilettes":    {"singular": "point toilettes",     "plural": "points toilettes",     "gender": "m"},
    "hygiene":      {"singular": "point hygiène",       "plural": "points hygiène",       "gender": "m"},
    "laverie":      {"singular": "laverie",             "plural": "laveries",             "gender": "f"},
    "culture":      {"singular": "site culturel",       "plural": "sites culturels",      "gender": "m"},
    "urgence":      {"singular": "service d'urgence",   "plural": "services d'urgence",   "gender": "m"},
}


# Icône Font Awesome de chaque catégorie de services, alignée sur CATEGORY_META
# (frontend/static/js/step4_services.js) : sert au récapitulatif pour qu'on
# reconnaisse d'un coup d'œil le type d'un service (restaurant, plage, eau...) et
# pas seulement son nom.
POI_CATEGORY_ICONS = {
    "eau":          "fa-tint",
    "vidange":      "fa-recycle",
    "gasoil":       "fa-gas-pump",
    "supermarche":  "fa-cart-arrow-down",
    "commerce":     "fa-shopping-basket",
    "restauration": "fa-utensils",
    "cafe":         "fa-mug-hot",
    "toilettes":    "fa-toilet",
    "hygiene":      "fa-shower",
    "laverie":      "fa-shirt",
    "culture":      "fa-camera",
    "urgence":      "fa-first-aid",
}


def poi_category_icon(category) -> str:
    """Classe d'icône Font Awesome d'une catégorie (repli : marqueur générique)."""
    return POI_CATEGORY_ICONS.get(category, "fa-map-marker-alt")


def poi_category_label(category) -> str:
    """Libellé court d'une catégorie de service (ex. "restaurant", "site culturel")."""
    labels = POI_CATEGORY_LABELS.get(category)
    return labels["singular"] if labels else "service"


def distance_label(distance_km) -> str:
    """Distance lisible : "350 m" en dessous d'un kilomètre, sinon "1.2 km"."""
    if distance_km is None:
        return ""
    if distance_km < 1:
        return f"{js_round(distance_km * 1000)} m"
    return f"{js_num(distance_km)} km"


# Un spot à moins de 500 m du tracé de la rando du jour est « sur ta rando » : on
# gare le van et on part à pied. Un peu plus large que les lieux « En chemin »
# (400 m, pepite_service.TRAIL_KM) : marcher jusqu'au sentier reste raisonnable.
SPOT_ON_HIKE_KM = 0.5


def hike_distance_label(distance_km) -> str:
    """Distance d'un spot à la rando du jour : "Sur ta rando · 150 m du tracé" ou "À 1.8 km de ta rando"."""
    if distance_km is None:
        return ""
    # Arrondi à 10 m sous le kilomètre, à 100 m au-delà : la distance est mesurée au
    # point du tracé le plus proche, une précision plus fine serait trompeuse.
    rounded = round(distance_km, 2) if distance_km < 1 else round(distance_km, 1)
    if distance_km <= SPOT_ON_HIKE_KM:
        return f"Sur ta rando · {distance_label(rounded)} du tracé"
    return f"À {distance_label(rounded)} de ta rando"


def enrich_poi(poi) -> dict:
    """Ajoute à un POI (service) ses champs prêts à afficher."""
    poi["service_type_label"] = poi.get("service_type") or "Service"
    poi["distance_label"] = distance_label(poi.get("distance_km"))
    # La distance dit d'où elle se mesure, comme sur la fiche spot ("À 3.8 km de ton spot").
    # Sous SPOT_ON_HIKE_KM, le lieu est à pied du spot : même mise en avant qu'un spot sur la rando.
    poi["near_spot"] = bool(poi.get("from_spot")) and poi.get("distance_km") is not None and poi["distance_km"] <= SPOT_ON_HIKE_KM
    # Arrondi comme hike_distance_label : 10 m sous le kilomètre, 100 m au-delà.
    km = poi.get("distance_km")
    rounded = None if km is None else round(km, 2) if km < 1 else round(km, 1)
    # À pied du spot, un texte court suffit : le cadre de la carte le dit déjà.
    poi["reference_distance_label"] = ("Proche de ton spot" if poi["near_spot"]
                                       else f"À {distance_label(rounded)} {'de ton spot' if poi.get('from_spot') else 'du centre'}"
                                       if rounded is not None else "")
    # Nom du site affiché en clair sur la fiche, comme la source d'une pépite. OSM donne
    # parfois l'adresse sans protocole (20 POI) : le lien renverrait vers notre propre site.
    url = (poi.get("url") or "").strip()
    poi["url"] = url if not url or url.startswith(("http://", "https://")) else f"https://{url}"
    poi["url_label"] = source_label(poi["url"])
    poi["badge"] = verified_badge(poi.get("verifie"))
    return poi


def poi_subtitle(category, count) -> str:
    """Phrase "X services disponibles pour cette journée" de l'étape 4,
    accordée en genre et en nombre selon la catégorie."""
    labels = POI_CATEGORY_LABELS.get(category, POI_CATEGORY_LABELS["tout"])
    if count == 0:
        aucun = "Aucune" if labels["gender"] == "f" else "Aucun"
        return f"{aucun} {labels['singular']} disponible pour cette journée"
    noun = labels["plural"] if count > 1 else labels["singular"]
    s = "s" if count > 1 else ""
    return f"{count} {noun} disponible{s} pour cette journée"


# ---------------------------------------------------------------------------
# Les pépites de Vany (étape 5, tableau récap, PDF)
# ---------------------------------------------------------------------------

PEPITE_CATEGORY_LABELS = {
    "lieu": "Lieu à ne pas rater",
    "point_de_vue": "Point de vue",
    "activite": "Activité",
    "evenement": "Événement",
    "marche": "Marché",
    "producteur": "Producteur local",
}


def duration_label(duration_h) -> str:
    """Durée lisible : "45 min" en dessous d'une heure, sinon "1.5 h"."""
    if not duration_h:
        return ""
    if duration_h < 1:
        return f"{js_round(duration_h * 60)} min"
    return f"{js_num(duration_h)} h"


def source_label(url) -> str:
    """Nom de site d'une source, sans "www." (ex. "ouest-france.fr")."""
    host = re.sub(r"^https?://", "", url or "").split("/")[0]
    return host.removeprefix("www.")


# Moment de la journée où faire une pépite, donné par Vany (agents/choose_pepites.py),
# dans l'ordre de la journée : il range les pépites d'un jour (marché le matin, plage
# l'après-midi, point de vue au coucher du soleil).
PEPITE_MOMENTS = {
    "matin": "Le matin",
    "midi": "À midi",
    "apres_midi": "L'après-midi",
    "coucher_soleil": "Au coucher du soleil",
    "soiree": "En soirée",
}


# Deux familles d'idées, proposées dans deux sections de l'étape 5 : les lieux en accès
# libre, déjà en base, et ce qui dépend des dates (événement, marché, cinéma, musée à
# horaires...), que la recherche de l'agenda met plusieurs minutes à trouver.
def pepite_section(pepite) -> str:
    """ "saison" pour une idée intemporelle, "sejour" pour une idée liée aux dates du séjour. """
    return "saison" if pepite.get("permanent") else "sejour"


def pepite_news_text(count, day_date, with_favorite) -> str:
    """Rappel de la barre du bas : "Vany a trouvé 2 idées pour ton lundi, dont un coup de cœur"."""
    ideas = "1 idée" if count == 1 else f"{count} idées"
    favorite = ", dont un coup de cœur" if with_favorite and count > 1 else ""
    return f"Vany a trouvé {ideas} pour ton {FR_WEEKDAYS[day_date.weekday()].lower()}{favorite}"


def pepite_display(pepite, top=False) -> dict:
    """Champs prêts à afficher d'une idée (étape « Les pépites de Vany »)."""
    meta = [
        PEPITE_MOMENTS.get(pepite.get("moment"), ""),
        pepite.get("horaires") or "",
        pepite.get("tarif") or "",
        f"à {distance_label(pepite.get('distance_km'))}" if pepite.get("distance_km") is not None else "",
        f"{duration_label(pepite.get('duree_h'))} sur place" if pepite.get("duree_h") else "",
        "" if pepite.get("exterieur") else "en intérieur",
    ]
    # Seuls les vrais liens web sont gardés (une source vient du web, via l'agent).
    sources = [url for url in pepite.get("sources") or [] if url.startswith(("https://", "http://"))]
    return {
        "id": pepite["id"],
        "nom": pepite["nom"],
        "type_label": PEPITE_CATEGORY_LABELS.get(pepite.get("categorie"), "Idée"),
        "description": pepite.get("description") or "",
        "meta_label": " · ".join(part for part in meta if part),
        "meteo_a_verifier": bool(pepite.get("meteo_a_verifier")),
        "source_url": sources[0] if sources else None,
        "source_label": source_label(sources[0]) if sources else "",
        "top": top,
        "section": pepite_section(pepite),
        # Pourquoi Vany l'a choisie pour cette journée (agents/choose_pepites.py) ;
        # vide si le code a classé seul.
        "why": pepite.get("pourquoi") or "",
        "added": pepite.get("statut") == "choisie",
        "latitude": pepite["latitude"],
        "longitude": pepite["longitude"],
        # Position estimée par l'agent, que le code n'a retrouvée ni dans la base ETL
        # ni par l'adresse (pepite_service.locate) : le marqueur est indicatif.
        "position_approx": pepite.get("position_source") not in ("base", "adresse", "source"),
    }


def trail_tip_display(tip) -> dict:
    """Champs d'un lieu à voir en chemin sur la rando (liste et carte de l'étape)."""
    return {"nom": tip["nom"], "description": tip.get("description") or "",
            "latitude": tip["latitude"], "longitude": tip["longitude"]}


def pepite_day_texts(day_date, hike_duration_h, free_time_h) -> dict:
    """Titre et phrase d'introduction de l'étape « Les pépites de Vany »."""
    weekday = FR_WEEKDAYS[day_date.weekday()].lower()
    if hike_duration_h:
        intro = f"Après tes {js_num(hike_duration_h)} h de rando, il te reste environ {js_num(free_time_h)} h en journée."
    else:
        intro = "Journée sans rando : tu as tout ton temps."
    return {"title": f"Les pépites de Vany pour ton {weekday}",
            "intro": intro + " Ajoute ce qui te tente, ou continue sans."}


def pepite_nothing_texts(day_date) -> dict:
    """Encadré quand la recherche n'a rien donné d'exceptionnel pour ce jour."""
    weekday = FR_WEEKDAYS[day_date.weekday()].lower()
    return {"title": f"Pas de pépite pour ton {weekday}",
            "intro": "Vany a cherché autour de ton spot et de ta rando sans trouver de bonne idée en plus."
                     " Plutôt rien qu'une idée moyenne : profite simplement de ta journée !"}


def pepite_line_html(pepite) -> str:
    """Ligne de l'idée retenue dans la colonne Services du tableau récap.
    Le nom vient du web (agent) : il est échappé avant d'être inséré en HTML."""
    return f'<span class="pepite-line"><i class="pepite-icon" aria-hidden="true"></i> {escape(pepite["nom"])}</span>'


def trail_tips_html(tips) -> str:
    """
    Ligne « En chemin » sous la rando du tableau récap, signée du chapeau de Vany
    qui recommande ces lieux dès l'étape 2 (noms venus du web, échappés).
    """
    if not tips:
        return ""
    names = " · ".join(escape(tip["nom"]) for tip in tips)
    return f'<br><span class="trail-tips"><i class="pepite-icon" aria-hidden="true"></i> En chemin : {names}</span>'


# ---------------------------------------------------------------------------
# Récapitulatif (page results)
# ---------------------------------------------------------------------------

def result_day_display(day) -> dict:
    """Contenu prêt à afficher des cellules du tableau récapitulatif.

    Les champs *_html peuvent contenir du HTML simple (<br>, <small>) inséré
    tel quel par le JS (innerHTML) - même comportement que l'ancien affichage,
    les données venant de nos propres bases.
    """
    if day.get("hike_id"):
        distance = js_num(day["distance_km"]) if day.get("distance_km") is not None else "?"
        activity = f"{day.get('hike_name')} ({distance} km, {day.get('difficulte') or ''})"
        # Adresse du point de départ de la rando (géocodée depuis start_latitude/longitude,
        # cf. le script ponctuel oneshot/backfill_addresses.py) : affichée quand elle est connue, comme le spot.
        if day.get("hike_address"):
            activity += f"<br><small>📍 {day['hike_address']}</small>"
        if day.get("hike_duration_h") is not None:
            activity += f"<br><small>🕘 {hike_schedule_label(day['hike_duration_h'])}</small>"
        activity += trail_tips_html(day.get("trail_tips"))
    else:
        activity = "Pas de randonnée - Détente"

    if day.get("spot_id"):
        accommodation = day.get("spot_name") or ""
        if day.get("spot_address"):
            accommodation += f"<br><small>📍 {day['spot_address']}</small>"
    else:
        accommodation = "Aucun spot sélectionné"

    pois = day.get("pois") or []
    if pois:
        # Icône de catégorie + nom + type, pour reconnaître le service (un nom comme
        # « Glenn » ou « Plage de Trémazan » ne dit pas s'il s'agit d'un restaurant,
        # d'un site culturel, d'un point d'eau...).
        def _service_line(p):
            icon = poi_category_icon(p.get("category"))
            name = p.get("name") or ""
            # Type précis ("Restaurant") s'il n'est pas une simple répétition du nom,
            # sinon le libellé de catégorie ("site culturel").
            raw_type = (p.get("service_type") or "").strip()
            kind = raw_type if raw_type and raw_type.lower() != name.lower() \
                else poi_category_label(p.get("category"))
            line = f'<i class="fas {icon}"></i> {name}'
            if kind:
                line += f' <small class="muted">· {kind}</small>'
            if p.get("address"):
                line += f"<br><small>📍 {p['address']}</small>"
            return line
        services = "<br>".join(_service_line(p) for p in pois)
    else:
        services = "Aucun service"
    for pepite in day.get("pepites") or []:
        services += "<br>" + pepite_line_html(pepite)

    return {
        "day_title": f"Jour {day.get('day_number')}",
        "activity_html": activity,
        "accommodation_html": accommodation,
        "services_html": services,
    }
