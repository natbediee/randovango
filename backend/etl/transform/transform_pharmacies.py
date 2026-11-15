"""
Des pharmacies du fichier FINESS aux lignes à charger (carte #194). Aucune base, aucun réseau : tout se teste à la main.

FINESS PROUVE QUE LA PHARMACIE EXISTE, ET DONNE SON NOM, SON ADRESSE ET SA POSITION
Décision de l'utilisatrice du 14 novembre 2026 : FINESS est la référence. OSM ne sert qu'à une chose : remplacer un
nom juridique (« SELARL PHARMACIE KERROS ») par le nom que voit le passant (« Pharmacie des Halles »).
Pourquoi FINESS : OSM montrait encore des pharmacies fermées, la Pharmacie de Kérinou à Brest (fermée le 31 octobre 2026)
ou la Pharmacie de La Fontaine à Quimper (fermée le 31 décembre 2025).

UNE PHARMACIE OUVERTE
État « A » (actif) et pas de date de fermeture passée. FINESS annonce parfois une fermeture à l'avance (31 décembre
2026) : la pharmacie reste ouverte jusque-là.

LA POSITION
Le plus souvent en latitude et longitude. Pour 17 % des pharmacies, seulement en Lambert-93 (le système de l'IGN pour
la métropole, en mètres) : on la convertit par le calcul, sans géocodage.

L'APPARIEMENT AVEC OSM, SEULEMENT POUR UN NOM JURIDIQUE
La pharmacie OSM la plus proche à moins de SAME_PLACE_M, sinon une qui partage un mot du nom à moins de SAME_NAME_M :
la position de FINESS est parfois le milieu de la rue ou de la place (Rivoalen-Cousin à Plougonvelin, à 127 m d'OSM).
Sans pharmacie OSM qui convienne, le nom de FINESS est gardé sans la forme juridique.
"""
import math
import re
import unicodedata
from datetime import date

from utils.geo_utils import haversine_distance_km

SAME_PLACE_M = 150
SAME_NAME_M = 1500
ACTIVE = "A"
PHARMACY_WORD = "Pharmacie"
# Les formes juridiques des sociétés de pharmaciens, telles qu'on les lit dans FINESS (les points sont enlevés avant).
COMPANY_FORMS = {"SELARL", "SARL", "SELAS", "SELASU", "SELEURL", "SELAFA", "SEL", "EURL", "SNC", "SAS", "SASU", "SCP",
                 "SPFPL"}
# Les abréviations de FINESS : « SELARL PHIE DALAKUPEIAN BORRELLI ».
ABBREVIATIONS = {"PHIE": "PHARMACIE", "PHCIE": "PHARMACIE"}
# Les petits mots restent en minuscules au milieu d'un nom : « Pharmacie de la Trinité ».
SMALL_WORDS = {"de", "du", "des", "la", "le", "les", "et", "au", "aux", "en", "sur", "d", "l"}
# Les mots qui ne servent pas à reconnaître une pharmacie par son nom.
COMMON_WORDS = {"pharmacie", "pharmacy", "des", "les", "del", "aux", "sur"}


def lambert93_to_wgs84(x: float, y: float) -> tuple:
    """
    (latitude, longitude) d'un point en Lambert-93. Formules de l'IGN (projection conique conforme sur l'ellipsoïde
    GRS80) : la longitude se lit directement, la latitude s'obtient par quelques itérations.
    """
    n, c, xs, ys, e = 0.7256077650532670, 11754255.426096, 700000.0, 12655612.049876, 0.0818191910428158
    radius = math.hypot(x - xs, y - ys)
    gamma = math.atan((x - xs) / (ys - y))
    longitude = math.radians(3) + gamma / n
    isometric = -math.log(radius / c) / n
    latitude = 2 * math.atan(math.exp(isometric)) - math.pi / 2
    for _ in range(10):
        sine = e * math.sin(latitude)
        latitude = 2 * math.atan(((1 + sine) / (1 - sine)) ** (e / 2) * math.exp(isometric)) - math.pi / 2
    return math.degrees(latitude), math.degrees(longitude)


def position(geo: dict | None, insee: str | None) -> tuple:
    """
    (latitude, longitude) d'une adresse FINESS, ou (None, None). Le Lambert-93 ne vaut que pour la métropole : en
    outre-mer (code INSEE 97…), sans latitude, la position reste inconnue.
    """
    geo = geo or {}
    if geo.get("directionLatitude") and geo.get("directionLongitude"):
        return float(geo["directionLatitude"]), float(geo["directionLongitude"])
    if geo.get("coordonneeX") and geo.get("coordonneeY") and not (insee or "").startswith("97"):
        return lambert93_to_wgs84(float(geo["coordonneeX"]), float(geo["coordonneeY"]))
    return None, None


def _day(text: str | None) -> date | None:
    """Les dates de FINESS : « 2026-10-31 », ou rien."""
    return date.fromisoformat(text) if text else None


def full_address(address: dict) -> str | None:
    """
    L'adresse affichée, « numéro et rue, code postal commune » comme celles d'OSM : l'étape 4 y lit le code postal.
    Sans rue (« BREIZH IZEL, Quimper »), seulement le code postal et la commune.
    """
    street = address.get("ligneQuatre") or " ".join(part for part in (address.get("numeroVoie"),
                                                                     address.get("libelleVoie")) if part)
    town = " ".join(part for part in (address.get("codePostal"), readable(address.get("ligneAcheminement") or ""))
                    if part)
    return ", ".join(part for part in (readable(street.strip()), town) if part) or None


def to_pharmacy(ege: dict) -> dict:
    """Une pharmacie du fichier FINESS (structures « ege » de catégorie 620), réduite à ce dont on se sert."""
    info = ege["informationsGeneralesEGE"]
    address = (ege.get("adresse") or [{}])[0]
    latitude, longitude = position(address.get("coordonneesGeographique"), address.get("cogCommune"))
    return {"finess": info["numFinessEge"], "nom_finess": " ".join((info.get("nomEgeLong") or "").split()),
            "address": full_address(address), "code_postal": address.get("codePostal"),
            "latitude": latitude, "longitude": longitude, "etat": ege.get("etatObjet"),
            "fermeture": _day(info.get("dateFermeture"))}


def is_open(pharmacy: dict, today: date) -> bool:
    """Active dans FINESS, et sans fermeture déjà passée."""
    return pharmacy["etat"] == ACTIVE and (pharmacy["fermeture"] is None or pharmacy["fermeture"] > today)


def _tokens(name: str) -> list:
    """Les mots du nom, sans les points des sigles (« S.E.L. » devient « SEL ») et abréviations développées."""
    return [ABBREVIATIONS.get(word.upper(), word) for word in name.replace(".", "").split()]


def has_company_form(name: str) -> bool:
    """Le nom FINESS contient une forme juridique (SELARL, SARL, EURL…) : ce n'est pas le nom que voit le passant."""
    return any(word.upper() in COMPANY_FORMS for word in _tokens(name))


def _capitalize(word: str, first: bool) -> str:
    """
    Un mot en minuscules lisibles. Un petit mot reste en minuscules, sauf en tête du nom ; chaque morceau d'un mot
    composé prend sa majuscule : « RIVOALEN-COUSIN » donne « Rivoalen-Cousin ». Le d' ou l' qui ouvre un mot reste
    en minuscule au milieu d'un nom : « D'ESPERAY » donne « d'Esperay ».
    """
    lower = word.lower()
    if lower in SMALL_WORDS and not first:
        return lower
    if re.match(r"[dl]['’].", lower):
        # « d'esperay » : l'élision, puis le mot avec sa majuscule. Le reste d'un mot breton (« vourc'h ») ne bouge pas.
        elision = lower[:2] if not first else lower[:2].capitalize()
        return elision + lower[2:].capitalize()
    return "-".join(part.capitalize() for part in lower.split("-"))


def readable(text: str) -> str:
    """
    Un texte de FINESS en minuscules lisibles, s'il est tout en capitales : « 16 RUE FRANCHET D'ESPERAY » donne
    « 16 Rue Franchet d'Esperay ». Un texte déjà écrit avec des minuscules (« Pharmacie Bodénès ») est gardé tel quel.
    """
    if not text.isupper():
        return text
    return " ".join(_capitalize(word, index == 0) for index, word in enumerate(text.split()))


def readable_name(name: str) -> str:
    """
    Le nom FINESS à afficher : sans forme juridique, en minuscules lisibles s'il est en capitales.
    « SELARL PHARMACIE DE WESPORT » donne « Pharmacie de Wesport ». Une société au nom du pharmacien seul
    (« SELARL HEMERY ») devient « Pharmacie Hemery ». Un nom sans forme juridique (« CHAMAREL ») garde son sens.
    """
    words = [word for word in _tokens(name) if word.upper() not in COMPANY_FORMS]
    if has_company_form(name) and PHARMACY_WORD.upper() not in (word.upper() for word in words):
        words = [PHARMACY_WORD.upper()] + words
    return readable(" ".join(words))


def name_words(name: str | None) -> set:
    """Les mots qui distinguent une pharmacie, sans accents ni majuscules : « Pharmacie du Léon » donne {« leon »}."""
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z]{3,}", plain)) - COMMON_WORDS - {form.lower() for form in COMPANY_FORMS}


def osm_match(pharmacy: dict, osm_pharmacies: list) -> dict | None:
    """
    La pharmacie OSM qui est cette pharmacie de FINESS : la plus proche à moins de SAME_PLACE_M, sinon la plus proche qui partage
    un mot du nom à moins de SAME_NAME_M. Une pharmacie OSM au nom vide ou seulement « Pharmacie » ne donne aucun nom.
    """
    candidates = []
    for osm in osm_pharmacies:
        if not name_words(osm["name"]):
            continue
        meters = haversine_distance_km(pharmacy["latitude"], pharmacy["longitude"], osm["latitude"],
                                       osm["longitude"]) * 1000
        same_name = bool(name_words(osm["name"]) & name_words(pharmacy["nom_finess"]))
        if meters <= SAME_PLACE_M or (same_name and meters <= SAME_NAME_M):
            candidates.append((meters, osm))
    return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def display_name(pharmacy: dict, osm_pharmacies: list) -> tuple:
    """
    (nom affiché, identifiant de la pharmacie OSM dont il vient ou None). Le nom de FINESS, sauf s'il est juridique et
    qu'une pharmacie OSM correspond : son nom à elle.
    """
    if has_company_form(pharmacy["nom_finess"]):
        osm = osm_match(pharmacy, osm_pharmacies)
        if osm:
            return osm["name"], osm["poi_id"]
    return readable_name(pharmacy["nom_finess"]), None


def pharmacy_row(pharmacy: dict, osm_pharmacies: list) -> dict:
    """
    Ce qu'on charge d'une pharmacie : son numéro FINESS (poi.original_id) et son poi, ce que voit le voyageur.
    nom_finess et osm_poi_id ne sont pas écrits en base : ils servent au compte rendu de l'essai (--essai).
    """
    name, osm_poi_id = display_name(pharmacy, osm_pharmacies)
    return {"finess": pharmacy["finess"], "nom_finess": pharmacy["nom_finess"], "osm_poi_id": osm_poi_id,
            "poi": {"name": name, "latitude": pharmacy["latitude"], "longitude": pharmacy["longitude"],
                    "address": pharmacy["address"]}}


def closures(known: dict, pharmacies: list, today: date) -> dict:
    """
    {numéro FINESS: date de fermeture ou None} des pharmacies déjà en base qui ne sont plus ouvertes : fermées dans
    FINESS, ou sorties du fichier (date inconnue). known : {numéro FINESS: poi_id} des pharmacies en base.
    """
    in_file = {pharmacy["finess"]: pharmacy for pharmacy in pharmacies}
    closed = {}
    for finess in known:
        pharmacy = in_file.get(finess)
        if pharmacy is None:
            closed[finess] = None
        elif not is_open(pharmacy, today):
            closed[finess] = pharmacy["fermeture"]
    return closed
