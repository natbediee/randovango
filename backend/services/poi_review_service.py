"""
Supervision des services : les vérifications proposent (etl_poi_check.py, find_service_links.py),
un humain tranche, le code applique. C'est le SEUL endroit qui modifie la table poi à partir d'un signal.

QUATRE FILES, parce que les décisions ne se prennent pas pareil :
    liens      : ajouter un lien. Ceux que le code a contrôlés se valident par lot ;
    fermetures : renommer, retirer, garder. Toujours au cas par cas : c'est là qu'une erreur coûte le
                 plus. Les sources sont montrées ensemble, car elles se contredisent souvent ;
    saison     : valider les mois d'ouverture, ou « saisonnier probable » sans mois ;
    morts      : retirer un lien qui ne répond plus.

UNE DÉCISION SE DÉFAIT : elle garde les valeurs d'avant (decisions.detail) et les remet si on l'annule.
Elle reste tracée dans la table `decisions`, avec celles des spots (objet_type = 'poi').

CE QUE VOIT LE VOYAGEUR : un lieu masqué (poi.masque) n'est plus proposé à l'étape 4 : retiré ici, ou
masqué par poi_triage_service.py dès qu'une fermeture est signalée. Garder ou renommer le remet. La saison
et la fermeture du moment sont enregistrées ici, leur affichage sur les fiches reste à faire.
"""
import json

from utils.db_utils import MySQLUtils

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
}
SIGNAL_TAB = {signal: tab for tab, signals in TAB_SIGNALS.items() for signal in signals}
SOURCE_LABELS = {"osm": "OSM", "agent": "Agent", "liens": "Contrôle"}
SIGNAL_LABELS = {
    "lien_agent": "Lien trouvé par l'agent", "lien_osm": "Lien indiqué dans OSM",
    "fermeture_agent": "Fermeture signalée", "renommage_osm": "Renommé dans OSM", "fermeture_osm": "Marqué fermé dans OSM",
    "absent_osm": "Absent d'OSM", "saison_agent": "Saison", "saison_osm": "Saison dans OSM", "lien_mort": "Lien mort",
}
# Les décisions possibles et le sort des signaux relus. Le code n'accepte rien d'autre.
ACTIONS = {
    "valider_lien": "valide", "valider_lien_nom": "valide", "refuser_lien": "rejete",
    "renommer": "valide", "retirer": "valide", "fermer_moment": "valide", "garder": "rejete",
    "valider_saison": "valide", "pas_saisonnier": "rejete",
    "retirer_lien": "valide", "garder_lien": "rejete",
}
ACTION_LABELS = {
    "valider_lien": "lien ajouté", "valider_lien_nom": "lien ajouté et nom corrigé", "refuser_lien": "lien refusé",
    "renommer": "renommé", "retirer": "retiré", "fermer_moment": "fermé pour le moment", "garder": "gardé",
    "valider_saison": "saison validée", "pas_saisonnier": "pas saisonnier",
    "retirer_lien": "lien retiré", "garder_lien": "lien gardé",
}
ACTION_BUTTONS = {
    "valider_lien": ("Valider le lien", "main"), "valider_lien_nom": ("Valider le lien et le nom", "main"),
    "refuser_lien": ("Refuser", "line"), "renommer": ("Renommer", "main"), "retirer": ("Retirer le lieu", "remove"),
    "fermer_moment": ("Fermé pour le moment", "main"), "garder": ("Garder tel quel", "line"),
    "valider_saison": ("Valider la saison", "main"), "pas_saisonnier": ("Pas saisonnier", "line"),
    "retirer_lien": ("Retirer le lien", "main"), "garder_lien": ("Garder le lien", "line"),
}
# Les seules colonnes qu'une décision peut changer, et donc remettre.
APPLIED_COLUMNS = ("url", "name", "masque", "ferme_moment", "statut_saison", "mois_ouverture")
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


CARD_BUILDERS = {"liens": _links_card, "fermetures": _closure_card, "saison": _season_card, "morts": _dead_link_card}


def build_card(tab: str, poi: dict, signals: list) -> dict:
    """La fiche de relecture d'un lieu : tous ses signaux d'une file, ensemble."""
    card = CARD_BUILDERS[tab](signals)
    ordered = sorted(signals, key=lambda signal: TAB_SIGNALS[tab].index(signal["signal_type"]))
    return {
        **card, "tab": tab, "poi_id": poi["id"], "nom": poi["name"], "adresse": poi.get("address") or "",
        "service": poi.get("service") or "", "url_actuelle": poi.get("url"),
        "signal_ids": [signal["id"] for signal in ordered],
        "signal": SIGNAL_LABELS[ordered[0]["signal_type"]],
        "gravite": "red" if ordered[0]["signal_type"] in ("lien_mort", "fermeture_agent")
                   else ("teal" if tab == "saison" and card.get("statut") == "confirmee" else "warn"),
        "preuves": [{"source": SOURCE_LABELS.get(signal["source"], signal["source"]), "texte": proof_text(signal)}
                    for signal in ordered],
        "boutons": [{"action": action, "label": ACTION_BUTTONS[action][0], "style": ACTION_BUTTONS[action][1]}
                    for action in card["actions"]],
    }


def applied_fields(action: str, card: dict, months: list | None) -> dict:
    """Ce qu'une décision change sur le lieu. Le lien et le nom viennent du signal, jamais du navigateur."""
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
    return {}


def _pending(cursor, service: str | None, city: str | None, statut: str = "a_relire") -> tuple:
    """{(file, poi_id): signaux dans cet état} et les lieux concernés, à travers les filtres."""
    filters, params = ["sg.statut = %s"], [statut]
    if city:
        filters.append("EXISTS (SELECT 1 FROM histo_poi h JOIN cities c ON c.id = h.city_id"
                       " WHERE h.poi_id = p.id AND c.name = %s)")
        params.append(city)
    if service:
        filters.append("EXISTS (SELECT 1 FROM poi_service ps JOIN services s ON s.id = ps.service_id"
                       " WHERE ps.poi_id = p.id AND s.name = %s)")
        params.append(service)
    cursor.execute(f"""
        SELECT sg.id, sg.poi_id, sg.source, sg.signal_type, sg.detail, p.id AS p_id, p.name, p.address, p.url,
               (SELECT MIN(s.name) FROM poi_service ps JOIN services s ON s.id = ps.service_id
                WHERE ps.poi_id = p.id) AS service
        FROM poi_signals sg JOIN poi p ON p.id = sg.poi_id
        WHERE {' AND '.join(filters)}
    """, tuple(params))
    groups, pois = {}, {}
    for row in cursor.fetchall():
        tab = SIGNAL_TAB.get(row["signal_type"])
        if not tab:
            continue
        groups.setdefault((tab, row["poi_id"]), []).append(row)
        pois[row["poi_id"]] = {"id": row["p_id"], "name": row["name"], "address": row["address"],
                               "url": row["url"], "service": row["service"]}
    return groups, pois


def get_reviews(tab: str = "liens", service: str | None = None, city: str | None = None) -> dict:
    """Une file de relecture, ses compteurs, les filtres et les dernières décisions."""
    if tab not in TAB_SIGNALS:
        raise ValueError(f"File inconnue : {tab}")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        groups, pois = _pending(cursor, service, city)
        counts = {name: 0 for name in TAB_SIGNALS}
        for name, _ in groups:
            counts[name] += 1
        cards = [build_card(tab, pois[poi_id], signals) for (name, poi_id), signals in groups.items() if name == tab]
        # Un lieu à fermeture signalée n'entre pas dans le lot : son lien attend qu'on tranche la fermeture.
        masked = _masked_ids(cursor, [card["poi_id"] for card in cards]) if tab == "liens" else set()
        for card in cards:
            if card["poi_id"] in masked:
                card["auto"] = False
                card["proposal"] = "ce lieu est masqué pour une fermeture signalée : à trancher d'abord."
        cards.sort(key=lambda card: (card["nom"] or "").lower())

        cursor.execute("""
            SELECT DISTINCT c.name FROM poi_signals sg JOIN histo_poi h ON h.poi_id = sg.poi_id
            JOIN cities c ON c.id = h.city_id WHERE sg.statut = 'a_relire' ORDER BY c.name
        """)
        cities = [row["name"] for row in cursor.fetchall()]
        cursor.execute("""
            SELECT d.id, d.decision, d.note, d.decided_by, d.decided_at, p.name FROM decisions d
            JOIN poi p ON p.id = d.objet_id
            WHERE d.objet_type = %s AND d.annulee_at IS NULL ORDER BY d.id DESC LIMIT %s
        """, (POI, RECENT_DECISIONS))
        recent = [{"id": row["id"], "nom": row["name"], "action": ACTION_LABELS.get(row["decision"], row["decision"]),
                   "note": row["note"] or "", "par": row["decided_by"], "le": row["decided_at"].strftime("%d/%m/%Y")}
                  for row in cursor.fetchall()]
        audit = _audit_sample(cursor)
        cursor.close()
        return {"tab": tab, "counts": counts, "total": len(cards), "cards": cards[:PAGE_SIZE],
                "cities": cities, "recent": recent, "audit": audit}
    finally:
        MySQLUtils.disconnect(connection)


def _masked_ids(cursor, poi_ids: list) -> set:
    if not poi_ids:
        return set()
    marks = ",".join(["%s"] * len(poi_ids))
    cursor.execute(f"SELECT id FROM poi WHERE masque = 1 AND id IN ({marks})", tuple(poi_ids))
    return {row["id"] for row in cursor.fetchall()}


def _audit_sample(cursor) -> list:
    """Quelques décisions de la règle, tirées au sort : si elles sont fausses, on resserre la règle."""
    cursor.execute("""
        SELECT d.id, d.decision, d.detail, p.name, p.address, p.url FROM decisions d JOIN poi p ON p.id = d.objet_id
        WHERE d.objet_type = %s AND d.decided_by = %s AND d.annulee_at IS NULL AND d.note IS NULL
        ORDER BY RAND() LIMIT %s
    """, (POI, RULE_AUTHOR, AUDIT_SIZE))
    sample = []
    for row in cursor.fetchall():
        detail = json.loads(row["detail"]) if isinstance(row["detail"], str) else (row["detail"] or {})
        sample.append({"id": row["id"], "nom": row["name"], "adresse": row["address"] or "",
                       "action": ACTION_LABELS.get(row["decision"], row["decision"]),
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


def decide_one(cursor, tab: str, poi_id: int, action: str, note: str, decided_by: str, months: list | None) -> None:
    cursor.execute("""
        SELECT sg.id, sg.poi_id, sg.source, sg.signal_type, sg.detail FROM poi_signals sg
        WHERE sg.poi_id = %s AND sg.statut = 'a_relire'
    """, (poi_id,))
    signals = [row for row in cursor.fetchall() if SIGNAL_TAB.get(row["signal_type"]) == tab]
    if not signals:
        raise ValueError("Ce lieu n'a plus rien à relire dans cette file")
    card = build_card(tab, {"id": poi_id, "name": ""}, signals)
    if action not in card["actions"]:
        raise ValueError(f"Décision impossible ici : {action}")
    fields = applied_fields(action, card, months)
    cursor.execute(f"SELECT {', '.join(APPLIED_COLUMNS)} FROM poi WHERE id = %s", (poi_id,))
    before = cursor.fetchone()
    if fields:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*fields.values(), poi_id))
    signal_ids = [signal["id"] for signal in signals]
    marks = ",".join(["%s"] * len(signal_ids))
    cursor.execute(f"UPDATE poi_signals SET statut = %s, reviewed_at = NOW() WHERE id IN ({marks})",
                   (ACTIONS[action], *signal_ids))
    detail = {"file": tab, "signal_ids": signal_ids, "avant": {column: before[column] for column in fields}}
    cursor.execute("""
        INSERT INTO decisions (objet_type, objet_id, decision, note, decided_by, decided_at, detail)
        VALUES (%s, %s, %s, %s, %s, NOW(), %s)
    """, (POI, poi_id, action, (note or "").strip()[:255] or None, decided_by, json.dumps(detail, ensure_ascii=False)))


def decide(tab: str, poi_ids: list, action: str, note: str, decided_by: str, months: list | None = None) -> None:
    """Enregistre et applique une décision, sur un lieu ou sur un lot de liens contrôlés, en une transaction."""
    if tab not in TAB_SIGNALS or action not in ACTIONS:
        raise ValueError("Décision inconnue")
    if len(poi_ids) > 1 and (tab != "liens" or action != "valider_lien"):
        raise ValueError("Seuls les liens se valident par lot")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        for poi_id in poi_ids:
            decide_one(cursor, tab, poi_id, action, note, decided_by, months)
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
        signal_ids = detail["signal_ids"]
        marks = ",".join(["%s"] * len(signal_ids))
        cursor.execute(f"UPDATE poi_signals SET statut = 'a_relire', reviewed_at = NULL WHERE id IN ({marks})", tuple(signal_ids))
        cursor.execute("UPDATE decisions SET annulee_at = NOW() WHERE id = %s", (decision_id,))
        connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)
