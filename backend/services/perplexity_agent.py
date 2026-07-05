import requests
import os

PERPLEXITY_API_URL = "https://api.perplexity.ai/v1/chat/completions"  # À adapter selon la doc Perplexity
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")


def get_perplexity_plan(prompt: str, model: str = "pplx-70b-online", max_tokens: int = 1024) -> list:
    """
    Envoie un prompt à Perplexity et retourne la réponse JSON parsée (liste d'étapes de planning).
    """
    if not PERPLEXITY_API_KEY:
        raise RuntimeError("Clé API Perplexity manquante (variable d'environnement PERPLEXITY_API_KEY)")

    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    response = requests.post(PERPLEXITY_API_URL, headers=headers, json=data, timeout=30)
    response.raise_for_status()
    # On suppose que la réponse est dans response.json()['choices'][0]['message']['content']
    content = response.json()['choices'][0]['message']['content']
    # On attend une réponse JSON, on parse
    import json
    try:
        plan = json.loads(content)
    except Exception:
        # Si la réponse n'est pas un JSON valide, retourne le texte brut
        plan = content
    return plan

# Exemple d'utilisation :
# prompt = "Pour la ville de Brest le 13 décembre 2025... (voir prompt détaillé)"
# plan = get_perplexity_plan(prompt)
# print(plan)
