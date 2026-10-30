from agents import dedupe_spots


CAMPING = {
    "id": 10, "name": "(29550) Camping Menez Bichen", "type": "CAMPING",
    "rating": 4.5, "description": "Camping familial en bord de dunes.", "services": ["Douches (accès possible)"],
}
PARKING_RICHE = {
    "id": 11, "name": "(29550) Saint-Nic - 353 Chemin des Dunes", "type": "PARKING JOUR ET NUIT",
    "rating": 4.0, "description": "Grand parking gravillonné face aux dunes, calme la nuit.",
    "services": ["Eau potable", "Toilettes"],
}
PARKING_PAUVRE = {
    "id": 12, "name": "(29550) Saint-Nic - Chemin des Dunes", "type": "PARKING JOUR ET NUIT",
    "rating": None, "description": "Parking.", "services": [],
}


class FakeLLM:
    """Double du service : renvoie les verdicts fournis, dans l'ordre des appels."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append(user)
        return self.verdicts.pop(0)


def verdict(same_place=True, confidence="elevee", reason="Même rue décrite deux fois."):
    return {"same_place": same_place, "confidence": confidence, "reason": reason}


def test_rank_key_prefers_the_rated_spot() -> None:
    winner, loser = sorted((PARKING_PAUVRE, PARKING_RICHE), key=dedupe_spots.rank_key, reverse=True)
    assert winner["id"] == PARKING_RICHE["id"]
    assert loser["id"] == PARKING_PAUVRE["id"]


def test_rank_key_falls_back_to_services_then_description() -> None:
    # Notes égales : c'est le nombre de services qui départage, puis la description.
    riche = {**PARKING_RICHE, "rating": 3.0}
    pauvre = {**PARKING_PAUVRE, "rating": 3.0}
    assert dedupe_spots.rank_key(riche) > dedupe_spots.rank_key(pauvre)

    meme_services = {**pauvre, "services": riche["services"], "description": "Court."}
    assert dedupe_spots.rank_key(riche) > dedupe_spots.rank_key(meme_services)


def test_rank_key_treats_a_missing_rating_as_zero() -> None:
    assert dedupe_spots.rank_key(PARKING_PAUVRE)[0] == 0.0


def test_arbitrate_confirms_a_duplicate_and_designates_the_winner() -> None:
    service = FakeLLM([verdict()])
    confirmed = dedupe_spots.arbitrate(service, [(66.0, PARKING_PAUVRE, PARKING_RICHE)])

    assert len(confirmed) == 1
    winner, loser, distance, _ = confirmed[0]
    assert (winner["id"], loser["id"]) == (PARKING_RICHE["id"], PARKING_PAUVRE["id"])
    assert distance == 66.0


def test_arbitrate_keeps_distinct_places() -> None:
    service = FakeLLM([verdict(same_place=False, reason="Contraintes contradictoires.")])
    assert dedupe_spots.arbitrate(service, [(66.0, PARKING_PAUVRE, PARKING_RICHE)]) == []


def test_arbitrate_ignores_a_low_confidence_duplicate() -> None:
    # Ne pas fusionner un doublon ne perd rien ; fusionner deux vrais lieux, si.
    service = FakeLLM([verdict(confidence="faible")])
    assert dedupe_spots.arbitrate(service, [(66.0, PARKING_PAUVRE, PARKING_RICHE)]) == []


def test_arbitrate_skips_a_pair_the_model_could_not_judge() -> None:
    class Failing:
        def complete_json(self, system, user, schema):
            raise dedupe_spots.LLMUnavailable("clé absente")

    assert dedupe_spots.arbitrate(Failing(), [(66.0, PARKING_PAUVRE, PARKING_RICHE)]) == []


def test_build_user_prompt_carries_both_descriptions_and_the_distance() -> None:
    prompt = dedupe_spots.build_user_prompt(PARKING_RICHE, PARKING_PAUVRE, 66.4)
    assert PARKING_RICHE["description"] in prompt
    assert PARKING_PAUVRE["description"] in prompt
    assert "66 mètres" in prompt


def test_apply_merges_marks_the_loser_and_never_deletes() -> None:
    executed = []

    class Cursor:
        def execute(self, query, params=None):
            executed.append((" ".join(query.split()), params))

    count = dedupe_spots.apply_merges(Cursor(), [(PARKING_RICHE, PARKING_PAUVRE, 66.0, verdict())])

    assert count == 1
    statements = [query for query, _ in executed]
    assert any("DELETE" in query.upper() for query in statements) is False
    # Les services du perdant sont recopiés sur le gagnant avant le marquage.
    assert "INSERT IGNORE INTO spot_service" in statements[0]
    assert "UPDATE spots SET duplicate_of_spot_id" in statements[1]
    assert executed[1][1] == (PARKING_RICHE["id"], PARKING_PAUVRE["id"])
    # La source ('p4n' ou 'ia') suit le service recopié.
    assert "SELECT %s, service_id, source FROM spot_service" in statements[0]


def test_candidate_pairs_drops_pairs_of_different_types(monkeypatch) -> None:
    # 38 des 55 paires détectées opposent un camping et le parking voisin :
    # elles doivent disparaître sans consommer un appel au modèle.
    pairs = [
        (55.0, CAMPING["id"], CAMPING["name"], CAMPING["type"],
         PARKING_RICHE["id"], PARKING_RICHE["name"], PARKING_RICHE["type"]),
        (66.0, PARKING_RICHE["id"], PARKING_RICHE["name"], PARKING_RICHE["type"],
         PARKING_PAUVRE["id"], PARKING_PAUVRE["name"], PARKING_PAUVRE["type"]),
    ]
    monkeypatch.setattr(dedupe_spots, "find_close_pairs", lambda cursor: pairs)
    monkeypatch.setattr(
        dedupe_spots, "load_spot_details",
        lambda cursor, ids: {s["id"]: s for s in (CAMPING, PARKING_RICHE, PARKING_PAUVRE)},
    )

    candidates = dedupe_spots.candidate_pairs(cursor=None)

    assert len(candidates) == 1
    assert {candidates[0][1]["id"], candidates[0][2]["id"]} == {PARKING_RICHE["id"], PARKING_PAUVRE["id"]}



def test_each_decision_is_logged_on_a_self_sufficient_line(caplog) -> None:
    # La ligne de log doit suffire pour décider : les deux fiches, la distance,
    # la décision et sa raison.
    service = FakeLLM([verdict()])
    with caplog.at_level("INFO", logger="etl_dedupe_spots"):
        dedupe_spots.arbitrate(service, [(66.0, PARKING_PAUVRE, PARKING_RICHE)])
    line = next(r.getMessage() for r in caplog.records if "DOUBLON" in r.getMessage())
    assert PARKING_PAUVRE["name"] in line and PARKING_RICHE["name"] in line
    assert "66 m" in line
    assert f"on garde #{PARKING_RICHE['id']}" in line
    assert "Même rue décrite deux fois." in line
