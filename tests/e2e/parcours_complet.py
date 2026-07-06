"""
Parcours de bout en bout du planificateur RandoVanGo (filet de sécurité).

Lancé MANUELLEMENT (pas par pytest — pas de préfixe test_) :
    .venv/bin/python tests/e2e/parcours_complet.py

Déroule le parcours complet d'un utilisateur invité dans un navigateur headless :
    /duration (2 jours) → /step1 (recherche d'une ville) → /step2 (choix rando)
    → /step3 (choix spot) → /step4 (choix service) → /results (jour 1)
    → "Rester dans la même ville" → step2..step4 → /results (jour 2, fin de séjour)

Échoue (exit code 1) si :
  - un élément attendu n'apparaît pas,
  - une erreur JavaScript est levée dans la console du navigateur.

Prérequis : les conteneurs Docker du projet doivent tourner (frontend sur
http://localhost, backend sur http://localhost:8000).
"""

import sys

from playwright.sync_api import sync_playwright

FRONT = "http://localhost"

# Erreurs console préexistantes tolérées (bugs connus AVANT la refonte).
# À retirer au fur et à mesure des corrections — la liste doit finir vide.
ERREURS_CONNUES = [
    # step4 goToNextDayOrResults : la sauvegarde est lancée puis la page navigue
    # aussitôt, ce qui avorte la requête. Sans conséquence (chaque clic sauvegarde
    # déjà au fil de l'eau) ; corrigé lors de la réécriture de step4_services.js.
    "Erreur sauvegarde services: TypeError: Failed to fetch",
]

console_errors = []
js_page_errors = []


def est_erreur_connue(message):
    return any(connue in message for connue in ERREURS_CONNUES)


def log(msg):
    print(f"  ✓ {msg}")


def selectionner_jour(page, etape, jour):
    """Vérifie le badge 'Jour X/N' affiché en haut du stepper."""
    badge = page.locator("#dayBadge").inner_text()
    attendu = f"Jour {jour}/2"
    assert attendu in badge, f"{etape}: badge attendu '{attendu}', obtenu '{badge}'"
    log(f"{etape}: badge '{badge}'")


def derouler_une_journee(page, jour):
    """Enchaîne step2 → step3 → step4 → results pour le jour donné."""
    # --- Étape 2 : choisir la première randonnée de la liste ---
    page.wait_for_selector(".hiking-card", timeout=15000)
    selectionner_jour(page, "step2", jour)
    page.locator("[id^=select-hike-btn-]").first.click()
    page.wait_for_selector("#nextStepBtn", state="visible", timeout=5000)
    page.locator("#nextStepBtn").click()
    log(f"step2 jour {jour}: randonnée choisie")

    # --- Étape 3 : choisir le premier spot ---
    page.wait_for_selector("[id^=select-spot-btn-]", timeout=15000)
    selectionner_jour(page, "step3", jour)
    page.locator("[id^=select-spot-btn-]").first.click()
    page.wait_for_selector("#nextStepBtn", state="visible", timeout=5000)
    page.locator("#nextStepBtn").click()
    log(f"step3 jour {jour}: spot choisi")

    # --- Étape 4 : choisir le premier service (POI) ---
    page.wait_for_selector("[id^=btn-poi-]", timeout=15000)
    selectionner_jour(page, "step4", jour)
    sous_titre = page.locator("#step4Subtitle").inner_text()
    assert sous_titre.strip(), "step4: sous-titre vide"
    page.locator("[id^=btn-poi-]").first.click()
    page.wait_for_selector("#nextStepBtn", state="visible", timeout=5000)
    page.locator("#nextStepBtn").click()
    log(f"step4 jour {jour}: service choisi ('{sous_titre}')")

    # --- Récapitulatif : vérifier la ligne du jour dans le tableau ---
    # Le tableau contient une ligne "Chargement..." tant que le JS n'a pas
    # remplacé son contenu : on attend le nombre de lignes final.
    page.wait_for_function(
        f"document.querySelectorAll('#days-table-body tr').length === {jour}"
        " && !document.getElementById('days-table-body').textContent"
        ".includes('Chargement')",
        timeout=15000,
    )
    lignes = page.locator("#days-table-body tr").count()
    cellules = page.locator("#days-table-body tr").nth(jour - 1).locator("td")
    for i in range(cellules.count()):
        assert cellules.nth(i).inner_text().strip(), f"results: cellule {i} vide"
    log(f"results jour {jour}: tableau OK ({lignes} ligne(s))")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("dialog", lambda d: d.accept())
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: js_page_errors.append(str(e)))

        # --- /duration : choisir un séjour de 2 jours ---
        page.goto(f"{FRONT}/duration")
        page.wait_for_selector(".duration-card[data-days='2']", timeout=10000)
        page.locator(".duration-card[data-days='2']").click()
        page.wait_for_selector("#nextButton:not([disabled])", timeout=5000)
        page.locator("#nextButton").click()
        log("duration: 2 jours choisis")

        # --- /step1 : rechercher une ville et lancer le plan ---
        page.wait_for_selector("#citySearch", timeout=10000)
        # Attendre que le JS de la page ait rempli le <select> caché avec les
        # villes de l'API (la recherche ne trouve rien tant qu'il est vide).
        page.wait_for_function(
            "document.getElementById('citySelect').options.length > 0",
            timeout=20000,
        )
        # On prend la première ville de la liste (peu importe laquelle,
        # le parcours doit marcher pour toutes).
        ville = page.evaluate(
            "document.getElementById('citySelect').options[0].dataset.name"
        )
        page.locator("#citySearch").fill(ville[:6])
        page.wait_for_selector(".city-suggestion-item", timeout=10000)
        page.locator(".city-suggestion-item").first.click()
        page.wait_for_selector("#weatherGrid .weather-day", timeout=15000)
        log(f"step1: ville '{ville}' sélectionnée, météo affichée")
        page.wait_for_selector("#planButton", state="visible", timeout=5000)
        page.locator("#planButton").click()

        # --- Jour 1 complet ---
        derouler_une_journee(page, jour=1)

        # --- Jour 2 : rester dans la même ville ---
        page.wait_for_selector("#nextDaySection", state="visible", timeout=5000)
        page.locator("#stayButton").click()
        derouler_une_journee(page, jour=2)

        # --- Fin de séjour : section de fin + lien PDF ---
        page.wait_for_selector("#tripEndSection", state="visible", timeout=5000)
        pdf_href = page.locator("#downloadPdfBtn").get_attribute("href")
        assert pdf_href and "plan_id=" in pdf_href, f"lien PDF invalide: {pdf_href}"
        log(f"fin de séjour: lien PDF OK ({pdf_href})")

        browser.close()

    inattendues = [
        e for e in console_errors + js_page_errors if not est_erreur_connue(e)
    ]
    if inattendues:
        print("\n✗ ERREURS JAVASCRIPT DÉTECTÉES :")
        for e in inattendues:
            print(f"  - {e}")
        sys.exit(1)

    tolerees = len(console_errors) + len(js_page_errors) - len(inattendues)
    if tolerees:
        print(f"\n⚠ {tolerees} erreur(s) connue(s) tolérée(s) (voir ERREURS_CONNUES)")
    print("\n✓ Parcours complet réussi, aucune erreur JavaScript inattendue.")


if __name__ == "__main__":
    main()
