"""
Sélection des commentaires Park4Night (avis datés et notés des utilisateurs).

Certains spots ont plusieurs centaines de commentaires : on n'en garde qu'un
échantillon représentatif, avec la même fonction à deux endroits :
  - au scraping, ce qu'on stocke en base     (STORED_SELECTION : 10 + 5 + 5)
  - à l'harmonisation, ce qu'on envoie à Claude (PROMPT_SELECTION : 6 + 2 + 2)

Pourquoi un mélange plutôt que les N plus récents ?
  - les plus récents disent si le lieu est TOUJOURS comme décrit ;
  - les plus mauvais signalent les problèmes (bruit, interdiction, saleté) ;
  - les meilleurs disent ce qui fait l'intérêt du lieu.
"""
from datetime import date, datetime

# (nombre de plus récents, nombre de plus mauvais, nombre de meilleurs)
STORED_SELECTION = (10, 5, 5)
PROMPT_SELECTION = (6, 2, 2)


def parse_review_date(text: str):
    """Date d'un commentaire Park4Night ("20/09/2026") en objet date, ou None."""
    try:
        return datetime.strptime(text.strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


def select_reviews(reviews: list, n_recent: int, n_worst: int, n_best: int) -> list:
    """
    Choisit un échantillon de commentaires, sans doublon, du plus récent au plus ancien.

    Chaque commentaire est un dict avec au moins "review_date" (date ou None) et
    "rating" (note sur 5, ou None).
    """
    oldest = date.min  # un commentaire sans date passe en dernier

    def by_date(review):
        return review.get("review_date") or oldest

    rated = [r for r in reviews if r.get("rating") is not None]

    # 1. Les plus récents.
    chosen = sorted(reviews, key=by_date, reverse=True)[:n_recent]

    # 2. Les plus mauvais, puis les meilleurs (à note égale, le plus récent d'abord),
    #    en sautant ceux déjà choisis.
    worst = sorted(rated, key=lambda r: (r["rating"], -by_date(r).toordinal()))
    best = sorted(rated, key=lambda r: (-r["rating"], -by_date(r).toordinal()))
    for candidates, count in ((worst, n_worst), (best, n_best)):
        added = 0
        for review in candidates:
            if added == count:
                break
            if review not in chosen:
                chosen.append(review)
                added += 1

    return sorted(chosen, key=by_date, reverse=True)
