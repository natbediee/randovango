"""
Service d'accès à Claude (le modèle d'IA d'Anthropic).

Les agents (harmonize_spots.py, verify_spots.py, dedupe_spots.py) ne parlent jamais à
Claude directement : ils passent par ce fichier. Ainsi, si on change la façon
d'appeler Claude, il n'y a qu'un seul endroit à modifier.

Ce fichier propose DEUX façons d'appeler Claude. Elles ont la même méthode
`complete_json(system, user, schema)` et renvoient le même résultat :

  1. LLMService           -> passe par l'API Anthropic (clé ANTHROPIC_API_KEY,
                             payée à l'usage). Permet aussi les "lots" (Batch API).
  2. ClaudeCodeLLMService -> passe par le programme `claude` installé sur la
                             machine (abonnement Claude, jeton CLAUDE_CODE_OAUTH_TOKEN).

Dans les deux cas, on donne à Claude un "schéma JSON" : la description exacte
du JSON qu'on attend en retour. Claude est obligé de le respecter, donc on
reçoit toujours un JSON propre, directement utilisable.
"""
import json
import os
import shutil
import subprocess
import tempfile

from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil

logger = LoggerUtil.get_logger("llm_service")


# --- Réglages ----------------------------------------------------------------

# Modèle utilisé avec l'API.
MODEL = "claude-opus-5"

# Niveau de réflexion du modèle. "low" suffit : extraire quelques infos d'un
# texte court est simple, et on le fait pour environ 1700 spots, donc on économise.
EFFORT = "low"

# Nombre maximum de "tokens" (morceaux de mots) que Claude peut écrire.
# Sa réflexion compte dedans : on prend une bonne marge au-dessus des ~250
# tokens du JSON attendu, sinon la réponse serait coupée.
MAX_TOKENS = 4000


class LLMUnavailable(RuntimeError):
    """Erreur levée quand on ne peut pas obtenir de réponse exploitable de Claude."""


# --- 1. Appel via l'API Anthropic ---------------------------------------------

class LLMService:
    """Appelle Claude via l'API Anthropic (clé ANTHROPIC_API_KEY dans le .env)."""

    def __init__(self, api_key: str = None, model: str = MODEL):
        self.model = model
        self.api_key = api_key
        self.client = None  # créé seulement au premier appel (voir _get_client)

    def _get_client(self):
        """
        Crée le client Anthropic la première fois, puis réutilise le même.

        On ne le crée pas dès le début : ainsi, le reste de l'application peut
        démarrer même si la clé d'API n'est pas configurée.
        """
        if self.client is not None:
            return self.client

        try:
            import anthropic
        except ImportError:
            raise LLMUnavailable("Le paquet 'anthropic' n'est pas installé (requirements.backend.txt).")

        # Charge le fichier .env dans les variables d'environnement.
        ServiceUtil.load_env()
        api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY absente du fichier .env.")

        self.client = anthropic.Anthropic(api_key=api_key)
        return self.client

    def _build_params(self, system: str, user: str, schema: dict) -> dict:
        """
        Prépare les paramètres d'une requête à Claude.

        - system : les consignes générales (identiques pour tous les spots)
        - user   : le texte propre à un spot
        - schema : la forme du JSON attendu en réponse
        """
        return {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            # "cache_control" : les consignes sont les mêmes à chaque appel, donc
            # Anthropic les garde en cache et les facture moins cher dès le 2e appel.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "output_config": {
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": schema},
            },
            "messages": [{"role": "user", "content": user}],
        }

    @staticmethod
    def _read_json(response) -> dict:
        """
        Récupère le JSON contenu dans la réponse de Claude.

        Si Claude a refusé ou si sa réponse a été coupée, on lève une erreur :
        mieux vaut ne rien écrire en base qu'écrire un résultat incomplet.
        """
        if response.stop_reason == "refusal":
            raise LLMUnavailable("Claude a refusé de répondre.")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("Réponse coupée (MAX_TOKENS atteint).")

        # La réponse est une liste de blocs ; on prend le premier bloc de texte.
        for block in response.content:
            if block.type == "text":
                return json.loads(block.text)
        raise LLMUnavailable("Réponse sans texte.")

    # Appel simple : une question, une réponse

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        """Envoie une requête à Claude et renvoie sa réponse sous forme de dict Python."""
        client = self._get_client()
        response = client.messages.create(**self._build_params(system, user, schema))
        return self._read_json(response)

    # Appels groupés (Batch API)
    # On envoie toutes les requêtes d'un coup, Anthropic les traite en arrière-plan
    # (jusqu'à quelques heures) et c'est 50 % moins cher. Fonctionnement en 3 temps :
    #   1. submit_batch()        -> envoie le lot, renvoie son identifiant
    #   2. batch_finished()      -> demande si le lot est terminé
    #   3. fetch_batch_results() -> récupère les réponses

    def build_batch_request(self, custom_id: str, system: str, user: str, schema: dict) -> dict:
        """
        Prépare UNE requête du lot.

        `custom_id` est une étiquette (ex : "spot-42") : les réponses reviennent
        dans le désordre, cette étiquette permet de savoir à quel spot chacune correspond.
        """
        return {"custom_id": custom_id, "params": self._build_params(system, user, schema)}

    def submit_batch(self, requests: list) -> str:
        """Envoie le lot de requêtes et renvoie son identifiant (à noter pour la suite)."""
        batch = self._get_client().messages.batches.create(requests=requests)
        logger.info(f"[llm] Lot {batch.id} envoyé ({len(requests)} requête(s))")
        return batch.id

    def batch_finished(self, batch_id: str) -> bool:
        """Renvoie True si Anthropic a fini de traiter le lot."""
        batch = self._get_client().messages.batches.retrieve(batch_id)
        return batch.processing_status == "ended"

    def fetch_batch_results(self, batch_id: str) -> dict:
        """
        Récupère les réponses d'un lot terminé.

        Renvoie un dict {custom_id: JSON de la réponse}. Les requêtes en échec
        sont seulement signalées dans les logs : le spot concerné n'est pas
        traité et sera retenté au prochain passage.
        """
        results = {}
        for item in self._get_client().messages.batches.results(batch_id):
            if item.result.type != "succeeded":
                logger.warning(f"[llm] {item.custom_id} : échec ({item.result.type})")
                continue
            try:
                results[item.custom_id] = self._read_json(item.result.message)
            except (LLMUnavailable, json.JSONDecodeError) as error:
                logger.warning(f"[llm] {item.custom_id} : réponse inutilisable ({error})")

        logger.info(f"[llm] Lot {batch_id} : {len(results)} réponse(s) exploitable(s)")
        return results


# --- 2. Appel via le programme `claude` (abonnement) -------------------------

class ClaudeCodeLLMService:
    """
    Appelle Claude en lançant le programme `claude` en ligne de commande,
    comme si on tapait dans un terminal :  claude -p "question"

    C'est l'abonnement Claude (Pro/Max) qui est utilisé, pas une clé d'API.
    Dans Docker, le programme s'authentifie avec la variable
    CLAUDE_CODE_OAUTH_TOKEN du .env (jeton créé avec `claude setup-token`).

    Limites :
      - pas d'envoi par lot : les spots sont traités un par un (plus lent) ;
      - on consomme le quota de l'abonnement.
    À réserver aux mises à jour lancées à la main.
    """

    # Version exacte du modèle, et non un alias comme "opus" : l'alias suit les
    # nouvelles versions, et une base harmonisée en plusieurs paquets pourrait alors
    # l'être avec deux modèles différents.
    # Opus plutôt que Sonnet : comparaison sur 10 spots (rapport/comparaison_modeles.md),
    # Opus suit l'intention même quand la consigne est floue, pour un quota environ x2.
    DEFAULT_MODEL = "claude-opus-5-5"

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = EFFORT, timeout: int = 180,
                 tools: list = None, mcp_servers: dict = None, mcp_tools: list = None):
        self.model = model
        self.effort = effort
        self.timeout = timeout  # temps maximum d'attente d'une réponse, en secondes
        # Outils intégrés à Claude Code autorisés, par exemple ["WebSearch", "WebFetch"]
        # pour l'agent de vérification. Par défaut : aucun outil, Claude ne fait que
        # lire le texte reçu.
        self.tools = tools or []
        # Serveurs MCP à brancher (nos propres outils), au format attendu par la CLI :
        # {"randovango": {"command": "python", "args": [...]}}, et les noms des outils
        # MCP autorisés, par exemple ["mcp__randovango__temoignages_commune"].
        self.mcp_servers = mcp_servers or {}
        self.mcp_tools = mcp_tools or []
        # Mesures du dernier appel (modèle, durée, coût, outils appelés).
        self.last_run = {}

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        """Lance `claude -p` et renvoie sa réponse sous forme de dict Python."""
        # 1. Vérifier que le programme `claude` est bien installé.
        if shutil.which("claude") is None:
            raise LLMUnavailable("Programme 'claude' introuvable (voir Dockerfile.backend).")

        # 2. Charger le .env : le jeton CLAUDE_CODE_OAUTH_TOKEN devient une variable
        #    d'environnement, que le programme `claude` lancé juste après pourra lire.
        ServiceUtil.load_env()

        # 3. Construire la commande, un élément de la liste par mot.
        command = [
            "claude",
            "-p", user,                          # -p : pose la question, affiche la réponse, quitte
            "--system-prompt", system,           # les consignes générales
            "--json-schema", json.dumps(schema), # la forme du JSON attendu
            # stream-json : une ligne JSON par étape (réflexion, appel d'outil...) puis
            # le résultat final. Permet de savoir quels outils l'agent a utilisés.
            # --verbose est obligatoire avec ce format.
            "--output-format", "stream-json", "--verbose",
            "--model", self.model,
            "--effort", self.effort,
            # Options qui isolent l'appel : pas de fichiers, pas de réglages du
            # projet, et seulement les outils explicitement autorisés.
            "--tools", ",".join(self.tools),     # "" = aucun outil
            "--setting-sources", "",             # ignore les réglages et CLAUDE.md du projet
            "--strict-mcp-config",               # seulement les serveurs MCP donnés ci-dessous
            "--no-session-persistence",          # n'enregistre pas la conversation sur le disque
        ]
        if self.mcp_servers:
            command += ["--mcp-config", json.dumps({"mcpServers": self.mcp_servers})]
        allowed = self.tools + self.mcp_tools
        if allowed:
            # Sans cette autorisation, la CLI demanderait une confirmation à chaque
            # appel d'outil, impossible en mode non interactif.
            command += ["--allowedTools", ",".join(allowed)]

        # 4. Lancer la commande et attendre la fin. On la lance depuis le dossier
        #    temporaire pour qu'elle ne voie pas les fichiers du projet.
        try:
            process = subprocess.run(
                command,
                capture_output=True,  # récupère ce que le programme affiche
                text=True,            # ... sous forme de texte (str) et non d'octets
                timeout=self.timeout,
                cwd=tempfile.gettempdir(),
            )
        except subprocess.TimeoutExpired:
            raise LLMUnavailable(f"claude -p n'a pas répondu en {self.timeout} secondes.")

        # 5. Lire la réponse : une ligne JSON par étape. On note les outils appelés
        #    (StructuredOutput est l'étape interne qui produit le JSON final, on
        #    l'ignore), et la dernière ligne, de type "result", contient la réponse :
        #    {"type": "result", "is_error": false, "structured_output": {...}, ...}
        answer, tools_used = None, []
        for line in process.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") != "StructuredOutput":
                        tools_used.append(block.get("name"))
            elif event.get("type") == "result":
                answer = event
        if answer is None:
            message = (process.stderr or process.stdout).strip()[:300]
            raise LLMUnavailable(f"claude -p a échoué (code {process.returncode}) : {message}")

        if answer.get("is_error") or answer.get("structured_output") is None:
            raise LLMUnavailable(f"claude -p : réponse inutilisable ({str(answer.get('result'))[:300]})")

        # 6. Garder quelques mesures de l'appel. "total_cost_usd" est le prix
        #    qu'aurait coûté l'appel via l'API : avec l'abonnement, rien n'est facturé.
        self.last_run = {
            "models": list(answer.get("modelUsage", {}).keys()),
            "duration_ms": answer.get("duration_ms"),
            "cost_usd": answer.get("total_cost_usd"),
            "turns": answer.get("num_turns"),
            "tools": tools_used,
        }
        return answer["structured_output"]
