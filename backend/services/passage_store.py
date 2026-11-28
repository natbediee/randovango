"""
La trace des passages en base (tables passages et passage_parts, déclarées dans db_init) : l'écrire et la relire.

Un passage est une chaîne d'agents lancée sur une ville (issue #204). Cette trace dit ce qui a été demandé (chaîne, ville,
catégories, origine) et où en est chaque partie. Ce que chaque appel d'agent a coûté reste dans llm_calls, sous le même
passage_id : load_calls le relit. Ce fichier ne contient que les requêtes ; les règles sont dans passage_service.py.
"""
import json
from datetime import datetime

from utils.db_utils import MySQLUtils

# Les états d'un passage, et ceux de chacune de ses parties.
QUEUED = "en_file"          # demandé, pas encore commencé : il partira dès que le verrou et le budget le permettent
WAITING = "en_attente"      # demandé par l'ETL alors que la mise à jour automatique est coupée : attend l'admin (#211)
RUNNING = "en_cours"
DONE = "fini"
FAILED = "echec"
TO_DO = "a_faire"           # une partie que le passage n'a pas encore commencée
RESUMED = "reprise"         # une partie jamais commencée d'un passage repris : sa reprise la fait à sa place (#295)

# Les origines des passages demandés depuis le front avec un compte admin (issue #356) : une demande ou une reprise
# depuis la supervision, une rando envoyée depuis la page d'ajout. Chaque étape de la file les prend avant les envois
# en masse de l'ETL (origine « etl »), qui attendent derrière elles.
PRIORITY_ORIGINS = ("supervision", "ajout")

PASSAGE_COLUMNS = """p.passage_id, p.chain, p.city_id, p.origin, p.status, p.requested_at, p.started_at, p.finished_at,
                     p.error, p.resumed_from, c.name AS city_name, c.commune AS city_commune"""


def _write(sql: str, rows: list) -> None:
    """Exécute une écriture pour chaque ligne de `rows`, puis la valide (commit)."""
    with MySQLUtils.open_cursor() as (connection, cursor):
        for row in rows:
            cursor.execute(sql, row)
        connection.commit()


def _read(sql: str, params: tuple) -> list:
    """Les lignes d'une lecture, chacune en dictionnaire {colonne: valeur}."""
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        cursor.execute(sql, params)
        return cursor.fetchall()


def insert_passage(passage_id: str, chain: str, city_id: int, origin: str, parts: list,
                   resumed_from: str | None = None, status: str = QUEUED) -> None:
    """
    Écrit un passage demandé et ses parties, toutes à faire, dans l'ordre où elles passeront. Le passage est en file,
    ou en attente de l'admin quand la mise à jour automatique est coupée.
    """
    _write("""INSERT INTO passages (passage_id, chain, city_id, origin, status, requested_at, resumed_from)
              VALUES (%s, %s, %s, %s, %s, %s, %s)""",
           [(passage_id, chain, city_id, origin, status, datetime.now(), resumed_from)])
    _write("INSERT INTO passage_parts (passage_id, part, position, status) VALUES (%s, %s, %s, %s)",
           [(passage_id, part, position, TO_DO) for position, part in enumerate(parts, start=1)])


def set_passage_status(passage_id: str, status: str, error: str | None = None) -> None:
    """
    Change l'état d'un passage : son début est noté quand il passe en cours, sa fin quand il finit ou échoue. Un passage
    remis en file (relancé par l'admin) garde sa date de demande : il reprend sa place dans la file.
    """
    if status == QUEUED:
        _write("UPDATE passages SET status = %s WHERE passage_id = %s", [(status, passage_id)])
    elif status == RUNNING:
        _write("UPDATE passages SET status = %s, started_at = %s WHERE passage_id = %s",
               [(status, datetime.now(), passage_id)])
    else:
        _write("UPDATE passages SET status = %s, finished_at = %s, error = %s WHERE passage_id = %s",
               [(status, datetime.now(), error, passage_id)])


def close_resumed_parts() -> int:
    """
    Les parties « à faire » des passages déjà repris passent à « reprise », et rend leur nombre (issue #295).
    Une reprise est un nouveau passage, qui refait les parties pas finies ; l'ancien gardait les siennes « à faire »
    pour toujours, et on lisait qu'il restait du travail sur des villes faites (177 parties le 20 novembre 2026, 1380 le
    28). Les parties en échec gardent leur raison, et un échec pas encore repris garde ses parties « à faire » : il
    attend sa reprise. La requête ne touche que ce qui reste à fermer : la relancer ne change rien de plus.
    """
    with MySQLUtils.open_cursor() as (connection, cursor):
        cursor.execute("""UPDATE passage_parts pp JOIN passages r ON r.resumed_from = pp.passage_id
                          SET pp.status = %s WHERE pp.status = %s""", (RESUMED, TO_DO))
        connection.commit()
        return cursor.rowcount


def set_part(passage_id: str, part: str, status: str, step: str | None = None, summary: dict | None = None,
             error: str | None = None) -> None:
    """Change l'état d'une partie, avec l'étape notée par le code, le bilan de l'enregistrement ou la raison d'un échec."""
    now = datetime.now()
    _write("""UPDATE passage_parts
              SET status = %s, step = %s, summary = %s, error = %s,
                  started_at = COALESCE(started_at, %s),
                  finished_at = CASE WHEN %s IN ('fini', 'echec') THEN %s ELSE NULL END
              WHERE passage_id = %s AND part = %s""",
           [(status, step, json.dumps(summary, ensure_ascii=False) if summary is not None else None, error, now,
             status, now, passage_id, part)])


def load_passage(passage_id: str) -> dict | None:
    """Le passage, avec le nom et la commune de sa ville ; None s'il n'existe pas."""
    rows = _read(f"""SELECT {PASSAGE_COLUMNS} FROM passages p LEFT JOIN cities c ON c.id = p.city_id
                     WHERE p.passage_id = %s""", (passage_id,))
    return rows[0] if rows else None


def load_parts(passage_id: str) -> list:
    """Les parties d'un passage, dans l'ordre où elles passent, avec leur bilan relu depuis le JSON."""
    rows = _read("""SELECT part, position, status, step, started_at, finished_at, summary, error
                    FROM passage_parts WHERE passage_id = %s ORDER BY position""", (passage_id,))
    for row in rows:
        row["summary"] = json.loads(row["summary"]) if row["summary"] else None
    return rows


def load_calls(passage_id: str) -> list:
    """
    Les appels d'agents du passage, lus dans llm_calls, dans l'ordre : agent, étape, statut et coût de chacun, avec
    leur jour et leur moteur pour convertir le coût en euros et dire s'il est réel ou un équivalent API.
    """
    return _read("""SELECT agent, etape, status, cost_usd, called_at, engine FROM llm_calls
                    WHERE passage_id = %s ORDER BY called_at, id""", (passage_id,))


def passage_ids(status: str, limit: int) -> list:
    """Les identifiants des passages dans cet état, du plus récent au plus ancien."""
    rows = _read("SELECT passage_id FROM passages WHERE status = %s ORDER BY requested_at DESC LIMIT %s",
                 (status, limit))
    return [row["passage_id"] for row in rows]


def recent_ids(limit: int) -> list:
    """Les identifiants des derniers passages finis ou en échec, du plus récent au plus ancien."""
    rows = _read("""SELECT passage_id FROM passages WHERE status IN ('fini', 'echec')
                    ORDER BY requested_at DESC LIMIT %s""", (limit,))
    return [row["passage_id"] for row in rows]


def failures_to_resume(chains: tuple, since: datetime) -> list:
    """
    Les passages de l'ETL en échec sur ces chaînes, finis depuis `since`, que personne n'a encore repris : ceux que la
    file peut reprendre seule (issue #316). Du plus ancien échec au plus récent, avec leur fin et le passage qu'ils
    reprenaient eux-mêmes (resumed_from), pour compter les reprises déjà faites.
    """
    placeholders = ",".join(["%s"] * len(chains))
    return _read(f"""SELECT p.passage_id, p.chain, p.city_id, p.resumed_from, p.finished_at FROM passages p
                     WHERE p.status = %s AND p.origin = 'etl' AND p.chain IN ({placeholders}) AND p.finished_at >= %s
                       AND NOT EXISTS (SELECT 1 FROM passages r WHERE r.resumed_from = p.passage_id)
                     ORDER BY p.finished_at""", (FAILED, *chains, since))


def resumed_by(passage_id: str) -> str | None:
    """Le passage qui reprend celui-ci (sa colonne resumed_from le désigne), ou None s'il n'a pas été repris."""
    rows = _read("SELECT passage_id FROM passages WHERE resumed_from = %s", (passage_id,))
    return rows[0]["passage_id"] if rows else None


def active_ids(chain: str, city_id: int) -> list:
    """
    Les passages de cette chaîne sur cette ville qui sont en file, en attente ou en cours : la file ne reprend pas
    seule un échec quand l'un d'eux refera déjà la chaîne (issue #329).
    """
    rows = _read("""SELECT passage_id FROM passages
                    WHERE chain = %s AND city_id = %s AND status IN ('en_file', 'en_attente', 'en_cours')""",
                 (chain, city_id))
    return [row["passage_id"] for row in rows]


def queued_next_parts() -> list:
    """
    Les passages en file, dans l'ordre où la file doit les prendre, chacun avec sa prochaine partie à faire
    (next_part) : c'est elle qui dit quelle étape de la file doit le prendre (services/passage_steps.py, issue #332).
    D'abord les demandes faites depuis le front avec un compte admin (PRIORITY_ORIGINS, #356), puis les envois de
    l'ETL ; dans chacun des deux groupes, du plus ancien au plus récent. Une seule requête pour toute la file : chaque
    étape la relit à chaque tour.
    """
    # « origin NOT IN (...) » vaut 0 pour une demande admin et 1 pour un envoi de l'ETL : le tri croissant les met devant.
    return _read("""SELECT p.passage_id, p.chain, p.city_id,
                           (SELECT pp.part FROM passage_parts pp WHERE pp.passage_id = p.passage_id AND pp.status = %s
                            ORDER BY pp.position LIMIT 1) AS next_part
                    FROM passages p WHERE p.status = %s
                    ORDER BY p.origin NOT IN (%s, %s), p.requested_at, p.passage_id""",
                 (TO_DO, QUEUED, *PRIORITY_ORIGINS))


def running_ids(chain: str) -> list:
    """Les passages en cours d'une chaîne, du plus récent au plus ancien."""
    rows = _read("SELECT passage_id FROM passages WHERE status = %s AND chain = %s ORDER BY requested_at DESC",
                 (RUNNING, chain))
    return [row["passage_id"] for row in rows]


def finished_parts(chain: str, city_ids: list) -> set:
    """
    Les parties déjà finies pour ces villes (les villes d'une même commune), dans n'importe quel passage, même un échec
    (une catégorie finie avant la coupure reste faite).
    La base est commune à toutes les branches, alors que chaque worktree a son propre dossier de fichiers des passages :
    un backend de branche ne voyait pas Combrit et Ergué-Gabéric, cherchées depuis main, et les a payées une seconde
    fois (nuit du 19 au 20 novembre 2026).
    """
    placeholders = ",".join(["%s"] * len(city_ids))
    rows = _read(f"""SELECT DISTINCT pp.part FROM passages p JOIN passage_parts pp ON pp.passage_id = p.passage_id
                     WHERE p.chain = %s AND p.city_id IN ({placeholders}) AND pp.status = 'fini'""",
                 (chain, *city_ids))
    return {row["part"] for row in rows}


def open_parts(chain: str, city_ids: list) -> set:
    """
    Les parties déjà demandées pour ces villes (les villes d'une même commune) dans un passage en file, en attente ou
    en cours, ou dans un échec pas encore repris : l'ETL ne les redemande pas, une seconde rando dans la même commune
    ne fait pas payer deux fois.
    Un échec pas encore repris compte aussi : c'est l'admin qui le reprend, et sa reprise refait ces catégories. Sans
    cela, une seconde rando à Paimpont avait demandé un nouveau passage pendant que le premier attendait sa reprise,
    et reprendre l'échec aurait payé la ville deux fois (19 novembre 2026).
    """
    placeholders = ",".join(["%s"] * len(city_ids))
    rows = _read(f"""SELECT DISTINCT pp.part FROM passages p JOIN passage_parts pp ON pp.passage_id = p.passage_id
                     WHERE p.chain = %s AND p.city_id IN ({placeholders})
                       AND (p.status IN ('en_file', 'en_attente', 'en_cours')
                            OR (p.status = 'echec' AND NOT EXISTS
                                (SELECT 1 FROM passages r WHERE r.resumed_from = p.passage_id)))""",
                 (chain, *city_ids))
    return {row["part"] for row in rows}


def pending_part(chain: str, part: str, city_ids: list, other_than: str) -> bool:
    """
    Cette partie est-elle demandée pour ces villes sans être finie, dans un autre passage que `other_than` : en file,
    en attente, en cours, ou en échec pas encore repris ? Une étape de la file attend alors, pour ces villes seules,
    que cette partie soit faite (services/passage_steps.py, issue #332).
    """
    placeholders = ",".join(["%s"] * len(city_ids))
    rows = _read(f"""SELECT 1 FROM passages p JOIN passage_parts pp ON pp.passage_id = p.passage_id
                     WHERE p.chain = %s AND pp.part = %s AND p.city_id IN ({placeholders}) AND p.passage_id <> %s
                       AND pp.status <> 'fini'
                       AND (p.status IN ('en_file', 'en_attente', 'en_cours')
                            OR (p.status = 'echec' AND NOT EXISTS
                                (SELECT 1 FROM passages r WHERE r.resumed_from = p.passage_id)))
                     LIMIT 1""", (chain, part, *city_ids, other_than))
    return bool(rows)


# --- Le journal de ce que les passages ont ajouté ou modifié (table passage_items, issue #276) ---

ITEM_TYPES = ("service", "spot", "pepite")
ADDED = "ajout"
CHANGED = "modification"

# Le nom de l'objet, lu dans sa table selon son type : poi pour un service, spots, pepites.
ITEM_COLUMNS = """i.passage_id, i.item_type, i.item_id, i.action, i.part, i.written_at,
                  COALESCE(p.name, s.name, pe.nom) AS item_name
                  FROM passage_items i
                  LEFT JOIN poi p ON i.item_type = 'service' AND p.id = i.item_id
                  LEFT JOIN spots s ON i.item_type = 'spot' AND s.id = i.item_id
                  LEFT JOIN pepites pe ON i.item_type = 'pepite' AND pe.id = i.item_id"""


def note_item(cursor, item_type: str, item_id: int | None, action: str, part: str) -> None:
    """
    Note dans le journal qu'un objet vient d'être ajouté ou modifié par le passage en cours. Écrit avec le curseur de
    l'appelant, sans valider : la ligne entre en base avec l'écriture qu'elle raconte, ou pas du tout.
    Sans passage en cours (un appel hors de tout passage, un essai), rien n'est noté.
    """
    # Import ici : agents.llm_service importe des services, qui importent ce module.
    from agents.llm_service import passage_courant
    passage_id = passage_courant()
    if passage_id is None or item_id is None:
        return
    cursor.execute("""INSERT INTO passage_items (passage_id, item_type, item_id, action, part, written_at)
                      VALUES (%s, %s, %s, %s, %s, %s)""",
                   (passage_id, item_type, item_id, action, part, datetime.now()))


def load_items(passage_id: str, item_type: str | None = None, item_id: int | None = None) -> list:
    """
    Ce que le passage a ajouté ou modifié, dans l'ordre où il l'a fait, avec le nom de chaque objet. Avec un objet
    (type et id), seulement ce que le passage a fait sur lui.
    """
    if item_type is None:
        return _read(f"SELECT {ITEM_COLUMNS} WHERE i.passage_id = %s ORDER BY i.id", (passage_id,))
    return _read(f"SELECT {ITEM_COLUMNS} WHERE i.passage_id = %s AND i.item_type = %s AND i.item_id = %s ORDER BY i.id",
                 (passage_id, item_type, item_id))


def count_items(passage_id: str) -> int:
    """Le nombre d'écritures du passage dans le journal : services, spots et pépites ajoutés ou modifiés."""
    return _read("SELECT COUNT(*) AS n FROM passage_items WHERE passage_id = %s", (passage_id,))[0]["n"]


def passages_of_item(item_type: str, item_id: int) -> list:
    """Les passages qui ont ajouté ou modifié cet objet, du plus récent au plus ancien."""
    rows = _read("""SELECT passage_id, MAX(written_at) AS last_written FROM passage_items
                    WHERE item_type = %s AND item_id = %s GROUP BY passage_id ORDER BY last_written DESC""",
                 (item_type, item_id))
    return [row["passage_id"] for row in rows]
