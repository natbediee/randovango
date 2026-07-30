"""
Client Anthropic partagé : un seul endroit qui sait construire une requête et en
extraire du JSON valide, pour que les modules ETL ne manipulent jamais le SDK
directement.

Deux modes, même schéma de sortie :
  - `complete_json`  : appel unitaire, pour les spots fraîchement scrapés
  - `submit_batch` / `fetch_batch_results` : Batch API, pour un backfill de
    masse (asynchrone, -50 % de coût, sans impact sur le temps de réponse du front)

La sortie est contrainte par `output_config.format` (JSON Schema) : la réponse
est garantie parsable, on n'a pas de post-parsing fragile à écrire.
"""
import json
import os

from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil

logger = LoggerUtil.get_logger("llm_service")

MODEL = "claude-opus-5"

# Effort bas : l'extraction depuis un texte court est une tâche simple, et on la
# répète 1708 fois. On garde en revanche le raisonnement actif (défaut sur Opus 5) :
# le désactiver est le levier le plus coûteux et le plus risqué, alors qu'un effort
# bas donne déjà l'essentiel de l'économie de tokens.
EFFORT = "low"

# Le raisonnement compte dans max_tokens : il faut de la marge au-dessus de la
# taille du JSON attendu (~250 tokens), sinon la réponse est tronquée.
MAX_TOKENS = 4000


class LLMUnavailable(RuntimeError):
    """Le SDK n'est pas installé ou la clé d'API est absente."""


class LLMService:
    """Accès au modèle. Instanciable pour pouvoir être remplacé par un double en test."""

    def __init__(self, api_key: str = None, model: str = MODEL):
        self.model = model
        self._api_key = api_key
        self._client = None

    @property
    def client(self):
        """Client Anthropic, créé à la première utilisation (jamais à l'import)."""
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise LLMUnavailable(
                "Le paquet 'anthropic' n'est pas installé (voir requirements.backend.txt)."
            ) from exc
        ServiceUtil.load_env()
        api_key = self._api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY absente de l'environnement (.env).")
        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    # -- Appel unitaire ------------------------------------------------------

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        """
        Interroge le modèle et retourne le JSON validé contre `schema`.

        `system` porte le marqueur de cache : il est identique d'un spot à l'autre,
        donc facturé au tarif « lecture de cache » à partir du deuxième appel.
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        return self._payload(response)

    @staticmethod
    def _payload(response) -> dict:
        """
        Extrait le JSON d'une réponse. Lève si le modèle a refusé ou a été tronqué :
        mieux vaut ne rien écrire en base qu'y écrire un enrichissement partiel.
        """
        if response.stop_reason == "refusal":
            raise LLMUnavailable(f"Requête refusée par le modèle : {response.stop_reason}")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("Réponse tronquée (max_tokens atteint), JSON inexploitable.")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise LLMUnavailable("Réponse sans bloc texte.")
        return json.loads(text)

    # -- Batch API -----------------------------------------------------------

    def build_batch_request(self, custom_id: str, system: str, user: str, schema: dict):
        """Une entrée de lot, à passer à `submit_batch`."""
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        return Request(
            custom_id=custom_id,
            params=MessageCreateParamsNonStreaming(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                output_config={
                    "effort": EFFORT,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": user}],
            ),
        )

    def submit_batch(self, requests: list) -> str:
        """Envoie un lot et retourne son identifiant (à conserver pour la relecture)."""
        batch = self.client.messages.batches.create(requests=requests)
        logger.info(f"[llm] Lot {batch.id} soumis ({len(requests)} requête(s))")
        return batch.id

    def batch_finished(self, batch_id: str) -> bool:
        """True quand le lot est traité (les résultats sont alors lisibles)."""
        return self.client.messages.batches.retrieve(batch_id).processing_status == "ended"

    def fetch_batch_results(self, batch_id: str) -> dict:
        """
        {custom_id: payload JSON} pour les requêtes réussies.

        Les résultats arrivent dans un ordre quelconque : on indexe par custom_id,
        jamais par position. Les échecs sont journalisés et simplement absents du
        dictionnaire - le spot correspondant reste non enrichi et sera repris au
        prochain passage.
        """
        results = {}
        for result in self.client.messages.batches.results(batch_id):
            if result.result.type != "succeeded":
                logger.warning(f"[llm] {result.custom_id} : {result.result.type}")
                continue
            try:
                results[result.custom_id] = self._payload(result.result.message)
            except (LLMUnavailable, json.JSONDecodeError) as exc:
                logger.warning(f"[llm] {result.custom_id} : réponse inexploitable ({exc})")
        logger.info(f"[llm] Lot {batch_id} : {len(results)} résultat(s) exploitable(s)")
        return results
