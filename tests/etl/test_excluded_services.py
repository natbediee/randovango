from utils.service_utils import EXCLUDED_SERVICES, SERVICE_CATEGORY_MAP, is_excluded_service


def test_moto_is_excluded() -> None:
    assert is_excluded_service("Belle balade à moto")
    assert not is_excluded_service("Eau potable")


def test_excluded_services_are_not_mapped_to_a_category() -> None:
    # Un service exclu n'a rien à faire dans le mapping : il n'entre jamais en base.
    assert not EXCLUDED_SERVICES & SERVICE_CATEGORY_MAP.keys()

