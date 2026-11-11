"""
Réglages des agents.

DEUX NIVEAUX DE MODÈLE
Une version exacte dans le .env, jamais un alias : une base traitée en plusieurs passes ne
doit pas mélanger deux modèles. Chaque résultat garde le modèle qui l'a produit.
    - "qualite" : l'agent exerce un jugement que rien ne vérifie derrière ;
    - "rapide"  : le code peut contrôler le résultat (lien qui répond, page qui nomme le lieu).
Passer un agent en "rapide" demande un pilote : comparer sur de vrais cas avant de changer.
"""
from dataclasses import dataclass

from agents.llm_service import ClaudeCodeLLMService, LLMService
from utils.service_utils import ServiceUtil

QUALITE = "qualite"
RAPIDE = "rapide"
MODEL_VARS = {QUALITE: "LLM_MODEL_QUALITE", RAPIDE: "LLM_MODEL_RAPIDE"}

ENGINE_API = "api"
ENGINE_CLAUDE_CODE = "claude-code"

WEB_TOOLS = ["WebSearch", "WebFetch"]


class LLMConfigError(RuntimeError):
    """Réglage absent ou impossible : mieux vaut échouer tout de suite qu'à mi-passage."""


@dataclass(frozen=True)
class AgentConfig:
    niveau: str
    effort: str
    timeout: int
    web: bool = False     # recherche web : seul le moteur claude-code sait la faire aujourd'hui


AGENTS = {
    # Opus : essayé sur 3 villes, Sonnet coûte deux fois moins de quota mais tasse les notes,
    # retient des lieux quelconques et a laissé passer un doublon. La base des lieux sert tous
    # les voyageurs pendant un an : on accepte de relancer le rattrapage si le quota est épuisé.
    "discover_places": AgentConfig(QUALITE, "medium", 600, web=True),
    # step5_pepites.js attend un peu plus longtemps que ce délai (PEPITES_MAX_POLLS).
    "find_pepites": AgentConfig(QUALITE, "medium", 600, web=True),
    # Un choix parmi une dizaine d'idées, sans recherche web : un effort bas garde l'appel court.
    "choose_pepites": AgentConfig(QUALITE, "low", 120),
    "locate_pepites": AgentConfig(QUALITE, "medium", 900, web=True),
    # En "low", l'agent répondait sans vraiment chercher ; il ne traite que les spots marqués.
    "verify_spots": AgentConfig(QUALITE, "high", 400, web=True),
    "find_service_links": AgentConfig(QUALITE, "medium", 900, web=True),
    "find_restaurants": AgentConfig(QUALITE, "medium", 900, web=True),
    "analyze_restaurants": AgentConfig(QUALITE, "medium", 900, web=True),
    # La preuve d'un lot de 5 lieux prend au plus 148 s sur les 134 communes du 6 novembre 2026. Au-delà, l'agent tourne
    # autour d'un lieu introuvable (Ploudalmézeau) : find_proofs relance alors le lot lieu par lieu.
    "prove_restaurants": AgentConfig(QUALITE, "medium", 300, web=True),
    # Commerces en Sonnet depuis le 8 novembre 2026, pour le coût : les 36 premières communes ont été faites
    # en Opus (environ 4,75 $ par commune). Le modèle de chaque fiche reste dans commerces.model.
    "find_commerces": AgentConfig(RAPIDE, "medium", 900, web=True),
    "analyze_commerces": AgentConfig(RAPIDE, "medium", 900, web=True),
    "prove_commerces": AgentConfig(RAPIDE, "medium", 300, web=True),
    # Supermarchés (11 novembre 2026) : les réglages des commerces, à revoir après le pilote. Aucun passage lancé.
    "find_supermarches": AgentConfig(RAPIDE, "medium", 900, web=True),
    "analyze_supermarches": AgentConfig(RAPIDE, "medium", 900, web=True),
    "prove_supermarches": AgentConfig(RAPIDE, "medium", 300, web=True),
    # Opus plutôt que Sonnet : comparaison sur 10 spots (rapport/comparaison_modeles.md).
    "harmonize_spots": AgentConfig(QUALITE, "low", 180),
    "dedupe_spots": AgentConfig(QUALITE, "low", 180),
    "read_openings": AgentConfig(QUALITE, "low", 120),
    # Relit les pages déjà gardées d'un restaurant pour choisir sa catégorie, sans recherche web (8 novembre 2026).
    "classify_restaurants": AgentConfig(QUALITE, "low", 180),
}


def _setting(name: str) -> str:
    ServiceUtil.load_env()
    value = ServiceUtil.get_env(name).strip()
    if not value:
        raise LLMConfigError(f"{name} manque dans le .env (voir .env.example)")
    return value


def engine() -> str:
    """Le moteur choisi dans le .env : l'API, ou le programme `claude` et l'abonnement."""
    value = _setting("LLM_ENGINE")
    if value not in (ENGINE_API, ENGINE_CLAUDE_CODE):
        raise LLMConfigError(f"LLM_ENGINE inconnu : {value}")
    return value


def model_of(agent: str) -> str:
    """La version exacte du modèle de cet agent, selon son niveau."""
    return _setting(MODEL_VARS[AGENTS[agent].niveau])


def make_llm_service(agent: str, chosen_engine: str = None, model: str = None,
                     mcp_servers: dict = None, mcp_tools: list = None):
    """
    Le service Claude d'un agent. `chosen_engine` et `model` forcent un choix à la main
    (options --engine et --model) ; sinon, ceux du .env.
    """
    config = AGENTS[agent]
    chosen_engine = chosen_engine or engine()
    model = model or model_of(agent)
    if chosen_engine == ENGINE_API:
        if config.web or mcp_servers:
            raise LLMConfigError(f"{agent} a besoin d'outils que le moteur api n'a pas encore : utiliser claude-code")
        return LLMService(model=model, agent=agent)
    return ClaudeCodeLLMService(model=model, effort=config.effort, timeout=config.timeout,
                                tools=WEB_TOOLS if config.web else None,
                                mcp_servers=mcp_servers, mcp_tools=mcp_tools, agent=agent)
