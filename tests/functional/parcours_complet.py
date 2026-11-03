"""
Parcours de bout en bout du planificateur RandoVanGo (filet de sécurité).

Lancé MANUELLEMENT (pas par pytest - pas de préfixe test_) :
    .venv/bin/python tests/functional/parcours_complet.py
    .venv/bin/python tests/functional/parcours_complet.py --changer-de-ville

Déroule le parcours complet d'un utilisateur invité dans un Chrome headless
piloté par Selenium (le même outil que le scraping P4N) :
    /duration (2 jours) → /step1 (recherche d'une ville) → /step2 (choix rando)
    → /step3 (choix spot) → /step4 (choix service) → /results (jour 1)
    → "Rester dans la même ville" → step2..step4 → /results (jour 2, fin de séjour)

Avec --changer-de-ville, le jour 2 se planifie dans une AUTRE ville : au
récapitulatif du jour 1, on clique "Changer de ville" au lieu de "Rester",
ce qui repasse par /step1 en mode changement de ville mi-séjour
(changingCityForNextDay, la zone la plus délicate du parcours).

Échoue (exit code 1) si :
  - un élément attendu n'apparaît pas (TimeoutException),
  - une alerte JavaScript s'ouvre : le front n'en affiche qu'en cas d'erreur
    (UnexpectedAlertPresentException, avec le texte de l'alerte),
  - une erreur est écrite dans la console du navigateur.

Prérequis : les conteneurs Docker du projet doivent tourner (frontend sur
http://localhost, backend sur http://localhost:8000). Chrome et chromedriver
sont trouvés (ou téléchargés) par Selenium Manager ; CHROMEDRIVER_PATH, s'il
est défini, impose un chromedriver précis (comme dans l'image backend).
"""

import os
import sys
import tempfile
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

FRONT = "http://localhost"

# Erreurs console préexistantes tolérées (bugs connus AVANT la refonte).
# À retirer au fur et à mesure des corrections - la liste doit finir vide.
ERREURS_CONNUES = []

erreurs_console = []


def est_erreur_connue(message):
    return any(connue in message for connue in ERREURS_CONNUES)


def log(msg):
    print(f"  ✓ {msg}")


def creer_driver(dossier_telechargement):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,900")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Le carnet PDF de fin de séjour est récupéré en blob puis téléchargé par le
    # navigateur (cf. downloadPdfBooklet dans results.js) : on l'envoie dans un
    # dossier temporaire, sans fenêtre de confirmation.
    options.add_experimental_option("prefs", {
        "download.default_directory": str(dossier_telechargement),
        "download.prompt_for_download": False,
    })
    # Garde les messages de la console du navigateur, lus par relever_erreurs_console
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    return webdriver.Chrome(service=Service(os.getenv("CHROMEDRIVER_PATH")), options=options)


def relever_erreurs_console(driver):
    """Ajoute à erreurs_console les erreurs apparues depuis le dernier relevé.

    Chrome classe en SEVERE les console.error, les exceptions JavaScript non
    rattrapées et les ressources qui n'ont pas pu être chargées.
    """
    for entree in driver.get_log("browser"):
        if entree["level"] == "SEVERE":
            erreurs_console.append(entree["message"])


def attendre(driver, condition, timeout):
    """Attend une condition Selenium (EC....) et renvoie son résultat."""
    return WebDriverWait(driver, timeout).until(condition)


def attendre_js(driver, script, timeout):
    """Attend qu'une expression JavaScript devienne vraie."""
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script(f"return {script}"))


def premier_cliquable(selecteur):
    """Condition d'attente : le premier élément du sélecteur visible et actif.

    Le premier élément du DOM ne suffit pas : à l'étape 4, les boutons de toutes
    les catégories sont dans la page, mais seuls ceux de la catégorie ouverte
    sont affichés.
    """
    def condition(driver):
        for element in driver.find_elements(By.CSS_SELECTOR, selecteur):
            if element.is_displayed() and element.is_enabled():
                return element
        return False
    return condition


def cliquer(driver, selecteur, timeout=5):
    """Clique sur le premier élément visible du sélecteur CSS, une fois cliquable."""
    element = attendre(driver, premier_cliquable(selecteur), timeout)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    element.click()


def selectionner_jour(driver, etape, jour):
    """Vérifie le badge 'Jour X/N' affiché en haut du stepper."""
    badge = driver.find_element(By.ID, "dayBadge").text
    attendu = f"Jour {jour}/2"
    assert attendu in badge, f"{etape}: badge attendu '{attendu}', obtenu '{badge}'"
    log(f"{etape}: badge '{badge}'")


def derouler_une_journee(driver, jour):
    """Enchaîne step2 → step3 → step4 → step5 → results pour le jour donné."""
    # --- Étape 2 : choisir la première randonnée de la liste ---
    attendre(driver, EC.presence_of_element_located((By.CSS_SELECTOR, ".hiking-card")), 15)
    selectionner_jour(driver, "step2", jour)
    cliquer(driver, "[id^=select-hike-btn-]")
    cliquer(driver, "#nextStepBtn")
    log(f"step2 jour {jour}: randonnée choisie")

    # --- Étape 3 : choisir le premier spot ---
    cliquer(driver, "[id^=select-spot-btn-]", timeout=15)
    selectionner_jour(driver, "step3", jour)
    cliquer(driver, "#nextStepBtn")
    log(f"step3 jour {jour}: spot choisi")

    # --- Étape 4 : ouvrir la première catégorie, choisir son premier service ---
    # Les services sont regroupés en tuiles de catégories (vue 1) ; les boutons
    # "Ajouter" n'apparaissent qu'une fois une catégorie ouverte (vue 2).
    cliquer(driver, ".category-tile", timeout=15)
    selectionner_jour(driver, "step4", jour)
    sous_titre = driver.find_element(By.ID, "step4Subtitle").text
    assert sous_titre.strip(), "step4: sous-titre vide"
    cliquer(driver, "[id^=btn-poi-]")
    cliquer(driver, "#nextStepBtn")
    log(f"step4 jour {jour}: service choisi ('{sous_titre}')")

    # --- Étape 5 : les pépites de Vany sont facultatives, on continue sans ---
    cliquer(driver, "#skipBtn", timeout=15)
    log(f"step5 jour {jour}: pépites passées")

    # --- Récapitulatif : vérifier la ligne du jour dans le tableau ---
    # Le tableau contient une ligne "Chargement..." tant que le JS n'a pas
    # remplacé son contenu : on attend le nombre de lignes final.
    attendre_js(
        driver,
        f"document.querySelectorAll('#days-table-body tr').length === {jour}"
        " && !document.getElementById('days-table-body').textContent"
        ".includes('Chargement')",
        15,
    )
    lignes = driver.find_elements(By.CSS_SELECTOR, "#days-table-body tr")
    cellules = lignes[jour - 1].find_elements(By.TAG_NAME, "td")
    for i, cellule in enumerate(cellules):
        assert cellule.text.strip(), f"results: cellule {i} vide"
    log(f"results jour {jour}: tableau OK ({len(lignes)} ligne(s))")
    relever_erreurs_console(driver)


def selectionner_ville(driver, nom_a_eviter=None):
    """Sur /step1, choisit une ville via la recherche et renvoie son nom.

    Par défaut la première ville de la liste ; si `nom_a_eviter` est donné
    (scénario changement de ville), prend la première ville différente.
    """
    attendre(driver, EC.presence_of_element_located((By.ID, "citySearch")), 10)
    # Attendre que le JS de la page ait rempli le <select> caché avec les
    # villes de l'API (la recherche ne trouve rien tant qu'il est vide).
    attendre_js(driver, "document.getElementById('citySelect').options.length > 0", 20)
    ville = driver.execute_script(
        """return Array.from(document.getElementById('citySelect').options)
                .map(o => o.dataset.name)
                .find(name => name !== arguments[0])""",
        nom_a_eviter,
    )
    recherche = driver.find_element(By.ID, "citySearch")
    recherche.clear()
    recherche.send_keys(ville[:6])
    cliquer(driver, ".city-suggestion-item", timeout=10)
    attendre(driver, EC.presence_of_element_located((By.CSS_SELECTOR, "#weatherGrid .weather-day")), 15)
    log(f"step1: ville '{ville}' sélectionnée, météo affichée")
    cliquer(driver, "#planButton")
    relever_erreurs_console(driver)
    return ville


def attendre_pdf(dossier, timeout):
    """Attend qu'un PDF complet apparaisse dans le dossier et renvoie son nom.

    Pendant le téléchargement, Chrome écrit dans un fichier .crdownload :
    le .pdf n'apparaît qu'une fois le fichier terminé.
    """
    pdfs = WebDriverWait(None, timeout, poll_frequency=1).until(
        lambda _: list(Path(dossier).glob("*.pdf"))
    )
    return pdfs[0].name


def main():
    changer_de_ville = "--changer-de-ville" in sys.argv

    with tempfile.TemporaryDirectory(prefix="randovango-e2e-") as dossier_telechargement:
        driver = creer_driver(dossier_telechargement)
        try:
            # --- /duration : choisir un séjour de 2 jours ---
            driver.get(f"{FRONT}/duration")
            cliquer(driver, ".duration-card[data-days='2']", timeout=10)
            cliquer(driver, "#nextButton:not([disabled])")
            log("duration: 2 jours choisis")

            # --- /step1 : rechercher une ville et lancer le plan ---
            # On prend la première ville de la liste (peu importe laquelle,
            # le parcours doit marcher pour toutes).
            ville = selectionner_ville(driver)

            # --- Jour 1 complet ---
            derouler_une_journee(driver, jour=1)

            # --- Jour 2 : rester dans la même ville, ou en changer ---
            attendre(driver, EC.visibility_of_element_located((By.ID, "nextDaySection")), 5)
            if changer_de_ville:
                # Repasse par /step1 en mode changement de ville mi-séjour
                cliquer(driver, "button[onclick='changeCityForNextDay()']")
                nouvelle_ville = selectionner_ville(driver, nom_a_eviter=ville)
                assert nouvelle_ville != ville, "le scénario doit changer de ville"
                log(f"jour 2: changement de ville '{ville}' → '{nouvelle_ville}'")
            else:
                cliquer(driver, "#stayButton")
            derouler_une_journee(driver, jour=2)

            # --- Fin de séjour : section de fin + téléchargement du carnet ---
            # Le carnet n'est plus un lien mais un bouton : il récupère le PDF en
            # arrière-plan pour garder l'utilisateur sur le récapitulatif. On vérifie
            # le téléchargement lui-même plutôt qu'une URL.
            attendre(driver, EC.visibility_of_element_located((By.ID, "tripEndSection")), 5)
            cliquer(driver, "#downloadPdfBtn")
            nom_fichier = attendre_pdf(dossier_telechargement, timeout=180)
            log(f"fin de séjour: carnet téléchargé ({nom_fichier})")
            relever_erreurs_console(driver)
        finally:
            driver.quit()

    inattendues = [e for e in erreurs_console if not est_erreur_connue(e)]
    if inattendues:
        print("\n✗ ERREURS JAVASCRIPT DÉTECTÉES :")
        for e in inattendues:
            print(f"  - {e}")
        sys.exit(1)

    tolerees = len(erreurs_console) - len(inattendues)
    if tolerees:
        print(f"\n⚠ {tolerees} erreur(s) connue(s) tolérée(s) (voir ERREURS_CONNUES)")
    print("\n✓ Parcours complet réussi, aucune erreur JavaScript inattendue.")


if __name__ == "__main__":
    main()
