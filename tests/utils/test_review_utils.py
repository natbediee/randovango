from datetime import date

from utils.review_utils import parse_review_date, select_reviews


def review(day, rating, review_id):
    return {"p4n_review_id": str(review_id), "review_date": date(2026, 1, day), "rating": rating}


REVIEWS = [review(d, r, i) for i, (d, r) in enumerate(
    [(20, 5), (19, 4), (18, 1), (17, 5), (16, 2), (15, 3), (2, 1), (1, 5)]
)]


def test_parse_review_date() -> None:
    assert parse_review_date("20/09/2026") == date(2026, 9, 20)
    assert parse_review_date("pas une date") is None


def test_selection_mixes_recent_worst_and_best_without_duplicates() -> None:
    chosen = select_reviews(REVIEWS, 2, 2, 1)
    days = [r["review_date"].day for r in chosen]
    # 2 plus récents (20, 19), 2 plus mauvais (18 et 2 : notes 1), 1 meilleur pas déjà pris (17 : note 5)
    assert days == [20, 19, 18, 17, 2]
    assert len({r["p4n_review_id"] for r in chosen}) == len(chosen)


def test_selection_keeps_everything_when_there_are_few_reviews() -> None:
    assert len(select_reviews(REVIEWS[:3], 10, 5, 5)) == 3


def test_review_without_date_comes_last() -> None:
    reviews = [{"review_date": None, "rating": 5}, {"review_date": date(2026, 1, 1), "rating": 4}]
    assert select_reviews(reviews, 2, 0, 0)[-1]["review_date"] is None
