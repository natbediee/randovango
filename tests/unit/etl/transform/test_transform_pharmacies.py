"""Les pharmacies de FINESS : ouvertes ou fermées, position, nom affiché, appariement avec les pharmacies d'OSM."""
from datetime import date

from etl.transform.transform_pharmacies import (closures, display_name, full_address, has_company_form, is_open,
                                                lambert93_to_wgs84, osm_match, pharmacy_row, position,
                                                readable_name, to_pharmacy)

TODAY = date(2026, 11, 14)

# La Pharmacie Rivoalen-Cousin de Plougonvelin, telle que le fichier FINESS du 14 novembre 2026 la décrit.
RIVOALEN_EGE = {
    "categorieentiteGeographiqueExercice": "620",
    "etatObjet": "A",
    "informationsGeneralesEGE": {"numFinessEge": "290011048", "nomEgeLong": "PHARMACIE RIVOALEN-COUSIN",
                                 "dateOuverture": "2022-03-18", "dateFermeture": None},
    "adresse": [{"ligneQuatre": "Place du General de Gaulle", "codePostal": "29217",
                 "ligneAcheminement": "Plougonvelin", "cogCommune": "29190",
                 "coordonneesGeographique": {"directionLatitude": "48.341576", "directionLongitude": "-4.719367"}}],
}
# La pharmacie OSM en face, rue Saint-Yves : 127 m plus loin que la position de FINESS (milieu de la place).
OSM_RIVOALEN = {"poi_id": 79, "name": "Pharmacie Rivoalen", "latitude": 48.3419, "longitude": -4.71772}


def _pharmacy(**changes):
    return {**to_pharmacy(RIVOALEN_EGE), **changes}


def test_a_pharmacy_keeps_its_finess_name_address_and_position():
    """FINESS est la référence : le nom, l'adresse (avec le code postal lu par l'étape 4) et la position viennent de lui."""
    pharmacy = to_pharmacy(RIVOALEN_EGE)
    assert pharmacy["finess"] == "290011048"
    assert pharmacy["address"] == "Place du General de Gaulle, 29217 Plougonvelin"
    assert (pharmacy["latitude"], pharmacy["longitude"]) == (48.341576, -4.719367)
    row = pharmacy_row(pharmacy, [OSM_RIVOALEN])
    assert row["poi"]["name"] == "Pharmacie Rivoalen-Cousin"
    assert row["poi"]["latitude"] == 48.341576
    assert row["osm_poi_id"] is None


def test_a_closed_pharmacy_is_not_open():
    """La Pharmacie Fresneau de Kérinou, à Brest, fermée le 31 octobre 2026 : elle n'est plus ouverte."""
    assert not is_open(_pharmacy(etat="I", fermeture=date(2026, 10, 31)), TODAY)


def test_a_closure_announced_in_advance_waits_for_its_date():
    """FINESS annonce parfois une fermeture d'avance (31 décembre 2026) : la pharmacie reste ouverte jusque-là."""
    assert is_open(_pharmacy(fermeture=date(2026, 12, 31)), TODAY)
    assert not is_open(_pharmacy(fermeture=date(2026, 11, 14)), TODAY)


def test_lambert93_is_converted_to_latitude_and_longitude():
    """Une pharmacie sans latitude dans FINESS : son point Lambert-93 donne la même position, au mètre près."""
    latitude, longitude = lambert93_to_wgs84(882630.01, 6542638.96)
    assert round(latitude, 5) == 45.95892 and round(longitude, 5) == 5.35837


def test_an_overseas_pharmacy_without_latitude_has_no_position():
    """En outre-mer, le Lambert-93 ne vaut pas : sans latitude, la position reste inconnue."""
    assert position({"coordonneeX": "1", "coordonneeY": "2"}, "97411") == (None, None)


def test_an_address_without_street_keeps_its_town():
    """« BREIZH IZEL » à Quimper n'a pas de rue dans FINESS : l'adresse garde le code postal et la commune."""
    assert full_address({"codePostal": "29000", "ligneAcheminement": "QUIMPER"}) == "29000 Quimper"


def test_a_street_in_capitals_is_made_readable():
    """« 16 RUE FRANCHET D'ESPERAY » à Brest s'affiche « 16 Rue Franchet d'Esperay »."""
    address = {"ligneQuatre": "16 RUE FRANCHET D'ESPERAY", "codePostal": "29200", "ligneAcheminement": "BREST"}
    assert full_address(address) == "16 Rue Franchet d'Esperay, 29200 Brest"


def test_company_forms_are_recognised():
    """SELARL, S.E.L., SNC… sont des noms de société, pas des noms que voit le passant."""
    assert has_company_form("SELARL PHARMACIE KERROS")
    assert has_company_form("S.E.L. PHARMACIE DE CHATEAUNEUF")
    assert not has_company_form("PHARMACIE FRESNEAU")


def test_a_company_name_is_made_readable():
    """Sans pharmacie OSM en face, le nom de FINESS perd sa forme juridique et ses capitales."""
    assert readable_name("SELARL PHARMACIE DE WESPORT") == "Pharmacie de Wesport"
    assert readable_name("SELARL HEMERY") == "Pharmacie Hemery"
    assert readable_name("PHARMACIE  DES HAUTS DE PENFELD") == "Pharmacie des Hauts de Penfeld"
    assert readable_name("Pharmacie Bodénès") == "Pharmacie Bodénès"
    assert readable_name("PHARMACIE VOURC'H") == "Pharmacie Vourc'h"


def test_a_company_name_takes_the_osm_name_of_the_same_place():
    """« SELARL PHARMACIE KERROS », rue Danton à Brest, est la « Pharmacie des Halles » d'OSM, à 2 m."""
    kerros = _pharmacy(nom_finess="SELARL PHARMACIE KERROS", latitude=48.39621, longitude=-4.48100)
    halles = {"poi_id": 330, "name": "Pharmacie des Halles", "latitude": 48.39622, "longitude": -4.48102}
    assert display_name(kerros, [halles]) == ("Pharmacie des Halles", 330)


def test_a_true_name_is_kept_even_with_an_osm_pharmacy_nearby():
    """Le nom de FINESS est la règle : OSM ne remplace qu'un nom juridique."""
    assert display_name(_pharmacy(), [OSM_RIVOALEN]) == ("Pharmacie Rivoalen-Cousin", None)


def test_the_same_name_matches_further_than_the_same_place():
    """Rivoalen-Cousin et Rivoalen, à 127 m : au-delà de 150 m, le nom commun suffit jusqu'à 1,5 km."""
    far = {**OSM_RIVOALEN, "latitude": 48.3480}
    assert osm_match(_pharmacy(), [far]) == far
    other = {**far, "name": "Pharmacie du Port"}
    assert osm_match(_pharmacy(), [other]) is None


def test_a_generic_osm_name_gives_no_name():
    """Une pharmacie OSM nommée seulement « Pharmacie » (rue Marcellin Duval à Brest) n'apporte aucun nom."""
    generic = {**OSM_RIVOALEN, "name": "Pharmacie"}
    assert osm_match(_pharmacy(), [generic]) is None


def test_closures_of_known_pharmacies():
    """Une pharmacie en base fermée dans FINESS, ou sortie du fichier, est à masquer ; une ouverte ne l'est pas."""
    known = {"290011048": 1, "290013226": 2, "290099999": 3}
    pharmacies = [_pharmacy(), _pharmacy(finess="290013226", etat="I", fermeture=date(2026, 10, 31))]
    assert closures(known, pharmacies, TODAY) == {"290013226": date(2026, 10, 31), "290099999": None}
