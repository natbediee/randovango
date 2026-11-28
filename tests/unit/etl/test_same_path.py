"""
La recherche, en base, d'une rando qui suit déjà le même chemin qu'un tracé lu (issue #271) : la plus recouverte est
nommée, avec l'écart entre les départs ; une rando voisine n'est pas retenue.

Ni base ni MongoDB : les randos de la zone et leurs tracés sont donnés par le test.
"""
from etl.extract import same_path

# Une ligne droite de 1 km, d'ouest en est, à Préfailles, avec un point tous les 100 m.
LINE = [{"lat": 47.13, "lon": -2.22 + k * 0.00132} for k in range(11)]
# La même ligne, décalée vers le nord de 30 m : un autre enregistrement du même chemin.
LINE_30_M_NORTH = [{"lat": p["lat"] + 0.00027, "lon": p["lon"]} for p in LINE]
# Une ligne parallèle à 300 m au nord : une autre rando, toute proche.
LINE_300_M_NORTH = [{"lat": p["lat"] + 0.0027, "lon": p["lon"]} for p in LINE]


def hike(hike_id, name, points) -> dict:
    """Une rando de la zone telle que la lit candidate_hikes, partie du premier point de son tracé."""
    return {"id": hike_id, "name": name, "mongo_id": f"trace-{hike_id}", "city": "Préfailles",
            "start_latitude": points[0]["lat"], "start_longitude": points[0]["lon"]}


def in_base(monkeypatch, hikes_and_points) -> None:
    """Remplace la base : ces randos sont dans la zone, avec ces tracés."""
    monkeypatch.setattr(same_path, "candidate_hikes", lambda points: [h for h, _ in hikes_and_points])
    traces = {h["mongo_id"]: points for h, points in hikes_and_points}
    monkeypatch.setattr(same_path, "trace_points", lambda mongo_id: traces[mongo_id])


def test_the_hike_on_the_same_path_is_found_with_its_start_gap(monkeypatch) -> None:
    """La rando qui suit le même chemin est trouvée, avec son recouvrement et l'écart de 30 m entre les départs."""
    in_base(monkeypatch, [(hike(325, "Pointe Saint-Gildas", LINE_30_M_NORTH), LINE_30_M_NORTH)])

    found = same_path.find_same_path_hike(LINE)

    assert (found["id"], found["name"], found["share"]) == (325, "Pointe Saint-Gildas", 1.0)
    assert 25 <= found["start_gap_m"] <= 35
    assert found["identical"] is True


def test_only_the_same_path_from_the_same_start_is_identical() -> None:
    """Seul le même chemin parti du même endroit est identique ; à 512 m de départ (Saint-Rambert-en-Bugey) ou à 95 %, l'admin garde le choix."""
    assert same_path.is_identical(1.0, 12)
    assert not same_path.is_identical(1.0, 512)
    assert not same_path.is_identical(0.95, 0)


def test_a_neighbour_hike_is_not_taken_for_the_same_path(monkeypatch) -> None:
    """Une rando parallèle, à 300 m, n'est pas prise pour le même chemin : rien n'est trouvé."""
    in_base(monkeypatch, [(hike(40, "La vallée des Seigneurs", LINE_300_M_NORTH), LINE_300_M_NORTH)])

    assert same_path.find_same_path_hike(LINE) is None


def test_the_most_covered_hike_is_named_when_several_match(monkeypatch) -> None:
    """Si deux randos suivent le chemin, c'est la plus recouverte qui est nommée."""
    partly = LINE[:10]   # 90 % du chemin seulement
    in_base(monkeypatch, [(hike(1, "En partie", partly), partly), (hike(2, "En entier", LINE_30_M_NORTH), LINE_30_M_NORTH)])

    assert same_path.find_same_path_hike(LINE)["name"] == "En entier"


def test_a_hike_without_trace_is_skipped(monkeypatch) -> None:
    """Une rando de la zone dont le tracé manque dans MongoDB est passée, sans erreur."""
    in_base(monkeypatch, [(hike(9, "Sans tracé", LINE), [])])

    assert same_path.find_same_path_hike(LINE) is None


def test_the_search_box_surrounds_the_trace_with_5_km() -> None:
    """La zone de recherche des départs entoure le tracé de 5 km de chaque côté."""
    min_lat, min_lon, max_lat, max_lon = same_path.search_box(LINE)

    assert round((LINE[0]["lat"] - min_lat) * 111.32, 1) == 5.0
    assert min_lon < LINE[0]["lon"] and max_lon > LINE[-1]["lon"]
    assert round((max_lat - LINE[0]["lat"]) * 111.32, 1) == 5.0


def test_the_refusal_names_the_hike_and_says_where_it_starts() -> None:
    """Le motif nomme la rando et sa ville, et dit où elle part : même endroit, en mètres, ou en kilomètres à la française (cas de Préfailles, 2,6 km)."""
    found = {"name": "Pointe Saint-Gildas", "city": "Préfailles", "share": 0.868, "start_gap_m": 2600}

    assert same_path.same_path_reason(found) == ("ce tracé recouvre à 86 % la rando « Pointe Saint-Gildas » (Préfailles),"
                                                 " dont le départ est à 2,6 km de celui-ci")
    assert same_path.start_gap_text(60) == "dont le départ est à 60 m de celui-ci"
    assert same_path.start_gap_text(12) == "qui part du même endroit"


def test_the_refusal_of_an_identical_trace_says_it_is_the_same_hike() -> None:
    """Le motif d'un tracé identique dit qu'il est identique à la rando en base, sans pourcentage (cas du Gouet Nord)."""
    found = {"name": "Tour de la retenue du Gouet Nord", "city": "Ploufragan", "share": 1.0, "start_gap_m": 0,
             "identical": True}

    assert same_path.same_path_reason(found) == ("ce tracé est identique à la rando « Tour de la retenue du Gouet Nord »"
                                                 " (Ploufragan), qui part du même endroit")
