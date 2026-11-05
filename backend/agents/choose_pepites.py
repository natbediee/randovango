"""
Choix des pépites d'une journée : parmi les idées possibles ce jour-là, Vany choisit
celles qui rendront CETTE journée meilleure, désigne son coup de cœur et dit en une
phrase pourquoi chacune tombe bien.

LE CODE DÉCIDE DE CE QUI EST POSSIBLE, L'IA DE CE QUI EST LE MIEUX
Le code a déjà écarté ce qui ne peut pas se faire ce jour-là (fermé, trop loin, pas
le temps après la rando, dehors sous la pluie : pepite_service.evaluate). Reste un
choix de jugement, que des règles font mal : le point de vue au coucher du soleil
juste après une rando courte, une sortie à l'abri un jour gris, une soirée plutôt
qu'une balade après 5 h de marche...
Les garde-fous :
    - Vany ne choisit que parmi les idées qu'on lui donne, désignées par leur numéro :
      il ne peut ni inventer un lieu, ni ramener une idée écartée par le code ;
    - s'il ne répond pas, ou mal, le code classe seul (les plus proches d'abord) ;
    - pas de recherche web : un appel court, qui ne lit que le message.

UN AGENT APPELÉ À LA DEMANDE, à la préparation d'une journée (choix du spot).
C'est services/pepite_service.py qui l'appelle (_top_up) et applique son choix.
"""
from agents import llm_config
from services.pepite_service import DAY_START_H
from utils.display_utils import FR_WEEKDAYS, PEPITE_MOMENTS, pepite_display
from utils.logger_util import LoggerUtil
from utils.meteo_utils import PICTO_LABELS

logger = LoggerUtil.get_logger("agent_pepites")

# Version des consignes. À AUGMENTER À CHAQUE MODIFICATION DU PROMPT.
#   1 : version initiale
#   2 : un conseil pratique (réserver, horaires de marée) seulement si la fiche le dit
#       (au pilote, Vany conseillait de réserver un concert sans que rien ne l'indique)
#   3 : le programme des autres jours du séjour, pour ne pas renvoyer le voyageur sur un
#       site qu'il a déjà au programme (la pointe Saint-Mathieu le lundi, à 74 m du
#       mémorial visité le dimanche)
#   4 : le moment de la journée de chaque idée (matin, après-midi, coucher du soleil...),
#       qui range les pépites d'un jour dans le carnet
CHOOSE_PROMPT_VERSION = 4

SYSTEM_PROMPT = """Tu es Vany, le compagnon de voyage de Randovango, une application de randonnée en
van. Pour une journée de voyage, tu choisis parmi des idées déjà vérifiées celles qui rendront la
journée meilleure, et tu dis au voyageur, en une phrase, pourquoi elles tombent bien ce jour-là.

## Comment choisir
- Pense à la journée entière : la rando du jour, le temps libre qui reste, la météo prévue, la
  saison, l'heure du coucher du soleil, le jour de la semaine.
- Varie : pas trois sorties dehors un jour gris ; après une longue rando, plutôt quelque chose de
  tranquille ou une soirée.
- Un point de vue ou une plage au coucher du soleil, quand l'heure tombe après la rando, est
  souvent le plus beau moment de la journée.
- Le séjour a déjà un programme les autres jours : ne renvoie pas le voyageur sur un site qu'il
  y a déjà, ni vers une sortie trop semblable, sauf si l'idée apporte vraiment autre chose.
- Le coup de cœur : l'idée qui fera le plus plaisir CE jour-là, pas forcément la mieux notée.

## Ce que tu sais et ce que tu ne sais pas
- Les idées sont déjà vérifiées (dates, horaires, distance) : ne les remets pas en cause.
- N'invente aucun fait absent du message (prix, horaires, météo, distance).
- Pas de conseil pratique (réserver, prévoir de la monnaie, arriver tôt...) que la fiche de l'idée
  ne mentionne pas.
- Tu ne connais pas les horaires des marées : pour une idée qui en dépend, dis seulement de les
  vérifier, sans inventer d'heure.

## Le moment
Pour chaque idée choisie, dis à quel moment de la journée la faire : matin, midi, apres_midi,
coucher_soleil ou soiree. Tiens compte de l'heure de départ et de la durée de la rando, des
horaires de l'idée et de l'heure du coucher du soleil. Ta phrase parle du même moment.

## La phrase
Tu tutoies le voyageur. Une phrase chaleureuse et concrète, qui relie l'idée à cette journée
(météo, heure, rando, jour de la semaine) ; pas une description du lieu, elle est déjà affichée.
Pas plus de 30 mots.

Réponds en français."""


def choose_schema(candidate_ids: list, count: int) -> dict:
    """Le choix attendu : `count` idées au plus, désignées par leur numéro, et le coup de cœur."""
    return {
        "type": "object",
        "properties": {
            "choix": {
                "type": "array",
                "minItems": 1,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "enum": candidate_ids},
                        "pourquoi": {"type": "string"},
                        "moment": {"type": "string", "enum": list(PEPITE_MOMENTS)},
                    },
                    "required": ["id", "pourquoi", "moment"],
                    "additionalProperties": False,
                },
            },
            "coup_de_coeur": {"type": "integer", "enum": candidate_ids},
        },
        "required": ["choix", "coup_de_coeur"],
        "additionalProperties": False,
    }


def weather_line(weather: dict | None) -> str:
    """La météo prévue en une ligne, ou ce qu'on en sait quand il n'y a pas de prévision."""
    if not weather:
        return "MÉTÉO PRÉVUE : pas encore de prévision (journée à plus de 7 jours)"
    parts = [PICTO_LABELS.get(weather["picto"], "temps incertain"),
             f"{weather['temp_min_c']:.0f} à {weather['temp_max_c']:.0f} °C"]
    if weather.get("wind_max_kmh"):
        parts.append(f"vent jusqu'à {weather['wind_max_kmh']:.0f} km/h")
    if weather.get("precipitation_mm"):
        parts.append(f"{weather['precipitation_mm']:.0f} mm de pluie")
    return "MÉTÉO PRÉVUE : " + ", ".join(parts)


def build_user_message(day: dict, candidates: list, count: int, already: list, program: list = ()) -> str:
    """
    La journée (rando, temps libre, météo, coucher du soleil), le programme des autres
    jours (pepite_service.program_elsewhere) et les idées possibles, numérotées.
    """
    hike = (f"{day['hike_name']}, {day['hike_duration_h']:g} h de marche (départ prévu à {DAY_START_H} h)"
            if day.get("hike_name") else "pas de rando ce jour-là")
    lines = [
        f"JOUR : {FR_WEEKDAYS[day['day_date'].weekday()].lower()} {day['day_date'].strftime('%d/%m/%Y')}",
        f"COMMUNE : {day.get('city_name') or 'inconnue'}",
        f"RANDO DU JOUR : {hike}",
        f"TEMPS LIBRE EN JOURNÉE : environ {day['free_time_h']:g} h",
        weather_line(day.get("weather")),
        f"COUCHER DU SOLEIL : {day['sunset'].strftime('%H h %M')}",
    ]
    if already:
        lines.append("DÉJÀ PROPOSÉES CE JOUR (pour varier) : " + ", ".join(already))
    if program:
        lines.append("DÉJÀ AU PROGRAMME DU SÉJOUR, LES AUTRES JOURS : " + ", ".join(
            f"{p['nom']} ({FR_WEEKDAYS[p['day_date'].weekday()].lower()}, à {p['distance_km']:.1f} km)"
            for p in program))
    lines.append(f"CHOISIS {count} IDÉE(S) PARMI :")
    for candidate in candidates:
        shown = pepite_display(candidate)
        themes = ", ".join(candidate.get("themes") or []) or "?"
        lines.append(f"[{candidate['id']}] {candidate['nom']} - {shown['type_label']} · {shown['meta_label']}"
                     f" · thèmes : {themes} · note {candidate.get('note') or '?'}/10")
        lines.append(f"    {shown['description']}")
    return "\n".join(lines)


def clean_choice(answer: dict, candidate_ids: list, count: int) -> dict | None:
    """
    Garde du choix ce qui est utilisable : des idées de la liste, sans doublon, au
    plus `count`, chacune avec sa phrase. Le coup de cœur doit être parmi elles.
    Le moment de la journée est gardé s'il est connu, sinon l'idée est rangée d'après
    sa fiche (pepite_service.day_order).
    Renvoie {"ids": [...], "why": {id: phrase}, "moment": {id: moment}, "favorite": id ou None}, ou None.
    """
    ids, why, moment = [], {}, {}
    for item in answer.get("choix") or []:
        sentence = " ".join((item.get("pourquoi") or "").split())
        if item.get("id") in candidate_ids and item["id"] not in why and sentence:
            ids.append(item["id"])
            why[item["id"]] = sentence
            if item.get("moment") in PEPITE_MOMENTS:
                moment[item["id"]] = item["moment"]
    ids = ids[:count]
    if not ids:
        return None
    favorite = answer.get("coup_de_coeur")
    return {"ids": ids, "why": {i: why[i] for i in ids}, "moment": {i: moment[i] for i in ids if i in moment},
            "favorite": favorite if favorite in ids else None}


def make_llm_service():
    """Le seul endroit qui choisit comment appeler le modèle (et donc le fournisseur)."""
    return llm_config.make_llm_service("choose_pepites")


def choose_pepites(day: dict, candidates: list, count: int, already: list = (), program: list = ()) -> dict | None:
    """
    Fait choisir à Vany `count` idées parmi `candidates` pour la journée `day`.
    Renvoie le choix nettoyé (voir clean_choice), ou None si Vany n'a pas pu répondre :
    l'appelant classe alors seul. Ne lève jamais d'exception.
    """
    candidate_ids = [c["id"] for c in candidates]
    service = make_llm_service()
    try:
        message = build_user_message(day, candidates, count, list(already), list(program))
        answer = service.complete_json(SYSTEM_PROMPT, message, choose_schema(candidate_ids, count))
    except Exception as error:   # le choix est un plus : son échec ne doit rien bloquer
        logger.warning(f"[pépites] choix du {day['day_date']} impossible, classement par le code : {error}")
        return None
    choice = clean_choice(answer, candidate_ids, count)
    logger.info(f"[pépites] choix du {day['day_date']} ({(service.last_run.get('duration_ms') or 0) / 1000:.0f} s) :"
                f" {choice['ids'] if choice else 'inutilisable'} parmi {candidate_ids}")
    return choice
