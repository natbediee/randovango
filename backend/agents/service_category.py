"""
Le réglage d'une catégorie de services (restaurants, commerces) : tout ce qui la distingue des autres dans la chaîne
commune. Les agents (service_chain.py) et l'enregistrement (services/service_store.py) sont écrits une fois, et lisent
ici ce qui change d'une catégorie à l'autre.

AJOUTER UNE CATÉGORIE
Écrire son fichier de réglage, comme find_restaurants.py : ses consignes, ses règles de preuve, et un ServiceCategory.
Puis déclarer ses trois agents dans llm_config.AGENTS, sous les noms find_<key>, analyze_<key> et prove_<key>.
"""
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from utils.logger_util import LoggerUtil


def no_review(row: dict, register: dict | None, commune: str) -> str | None:
    """Aucune relecture demandée : la valeur par défaut des deux règles de relecture d'une catégorie."""
    return None


@dataclass(frozen=True)
class ServiceCategory:
    # --- Qui elle est ---
    key: str                    # « restaurants » : la liste dans les réponses, et le nom des trois agents
    source: str                 # « agent_restaurants » : la source des lieux créés, des signaux, du journal et des fichiers
    prompt_version: int         # à augmenter à chaque modification des consignes

    # --- Les recherches ---
    searches: tuple             # ((nom de la recherche, consignes), ...), toutes lancées en même temps
    categories: list            # la grille fixe où l'agent range chaque lieu
    register_activities: tuple  # les codes d'activité lus au registre
    place_key: Callable         # (nom) -> la clé qui reconnaît un même lieu sous deux noms, d'une recherche à l'autre

    # --- L'analyse et la preuve ---
    analysis_prompt: str        # les consignes de l'analyste : fermeture, doublon, lieu inutile au voyageur, détails
    proof_prompt: str           # les consignes de la recherche de preuve
    not_for_travellers: str     # le champ de l'analyste qui retire un lieu inutile au voyageur (« pas_un_restaurant »)
    not_for_travellers_log: str  # son nom dans le journal (« sans table »)
    detail_fields: tuple        # les détails pratiques cherchés (« saison », « distinction »)
    accepts: Callable           # (page, lieu, commune) -> cette page prouve-t-elle ce lieu ?
    register_proves: Callable   # (lieu, registre) -> le registre suffit-il à le prouver, sans chercher de page ?
    register_facts: Callable    # (lieu, registre) -> {"registre_depuis", "au_registre"}, lus une fois les preuves cherchées

    # --- La fiche et l'enregistrement ---
    sheet_table: str            # la table de la fiche
    sheet_fields: tuple         # les champs gardés dans un signal à confirmer, pour écrire la fiche si un humain valide
    human_sheet_fields: tuple   # ceux qu'un humain peut corriger : un nouveau passage les laisse tels quels
    detail_column: tuple        # (champ propre à cette fiche, longueur en base)
    known_services: tuple       # les services où chercher la ligne d'un lieu déjà en base
    new_service: Callable       # (lieu) -> le service donné à un lieu créé
    find_known: Callable        # (lieu, position, ville, lieux connus) -> la ligne du lieu déjà en base, ou None
    is_verified: Callable       # (lieu, pages acceptées) -> a-t-il le badge « Vérifié » ?

    # --- Ce que seules certaines catégories font ---
    zone_activity: str = ""                     # dans une zone, l'agent ne lit que les lignes du registre à ce code
    sends_category: bool = False                # la catégorie du lieu est-elle donnée à l'analyste ?
    detail_only_for: dict = field(default_factory=dict)     # {détail : seule catégorie qui le garde}
    refused_duplicate_to_review: bool = False   # un doublon que le code refuse part-il en relecture ?
    review_before_proof: Callable = no_review   # (lieu, registre, commune) -> raison d'une relecture sans chercher de preuve
    review_after_proof: Callable = no_review    # (lieu, registre, commune) -> raison d'une relecture, les preuves cherchées
    review_keeps_sheet: bool = False            # un lieu à relire qui a déjà une fiche la garde-t-il, sans signal ?
    shown_elsewhere: dict = field(default_factory=dict)     # {catégorie : (table d'une autre chaîne, compteur du bilan, raison)}
    duplicate_signal: str | None = None         # le signal des doublons vus par l'analyste et refusés par le code

    @property
    def find_agent(self) -> str:
        """Les trois agents de la catégorie, sous ces noms dans llm_config.AGENTS : celui qui cherche..."""
        return f"find_{self.key}"

    @property
    def analyze_agent(self) -> str:
        """... celui qui relit tous les lieux..."""
        return f"analyze_{self.key}"

    @property
    def prove_agent(self) -> str:
        """... et celui qui cherche une preuve."""
        return f"prove_{self.key}"

    @property
    def logger(self):
        """Le journal de la catégorie : logs/agent_restaurants.log."""
        return LoggerUtil.get_logger(self.source)

    @property
    def trace_dir(self) -> Path:
        """Le dossier des fichiers JSON de chaque passage : logs/agent_restaurants/."""
        return Path(os.getenv("RANDOVANGO_LOG_DIR", "/usr/src/logs")) / self.source
