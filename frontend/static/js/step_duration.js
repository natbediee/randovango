    document.addEventListener('DOMContentLoaded', function () {
        // /duration n'est atteint qu'au tout début d'une nouvelle planification (le
        // changement de ville mi-séjour, lui, va directement à /step1). On efface donc
        // ici tout l'état d'un séjour précédent, y compris s'il a été abandonné en
        // cours de route (ex. changingCityForNextDay resté bloqué à '1' après un
        // "Changer de ville" jamais finalisé) — sinon l'utilisateur reste coincé sur
        // l'ancienne ville/plan à sa prochaine visite.
        localStorage.removeItem('changingCityForNextDay');
        localStorage.removeItem('planId');
        localStorage.removeItem('currentDay');
        localStorage.removeItem('selectedCityId');
        localStorage.removeItem('selectedHiking');
        localStorage.removeItem('selectedSpot');
        localStorage.removeItem('selectedServices');
        // Idem pour la ville mémorisée en sessionStorage par step1_city.html afin de
        // restaurer la sélection lors d'un retour arrière depuis step2 : utile dans ce
        // cas précis, mais pas pour un vrai nouveau départ.
        sessionStorage.removeItem('step1_cityId');

        // ========================================
        // GESTION DE L'AUTHENTIFICATION JWT ET DE L'UPLOAD GPX
        // ========================================

        // Récupération des éléments DOM pour l'authentification
        const loginForm = document.getElementById('loginForm');
        const userMenu = document.getElementById('userMenu');
        const stepperLoginForm = document.getElementById('stepperLoginForm');
        const stepperLoginError = document.getElementById('stepperLoginError');
        const logoutBtn = document.getElementById('logoutBtn');

        // Récupération des éléments DOM pour l'upload GPX
        const gpxUploadForm = document.getElementById('gpxUploadForm');
        const gpxFileInput = document.getElementById('gpxFileInput');
        const fileName = document.getElementById('fileName');
        const uploadBtn = document.getElementById('uploadBtn');
        const gpxUploadError = document.getElementById('gpxUploadError');
        const gpxUploadSuccess = document.getElementById('gpxUploadSuccess');

        /**
         * Vérifie si un token JWT est expiré
         * Décode le payload base64 et compare le timestamp d'expiration
         * @param {string} token - Le token JWT à vérifier
         * @returns {boolean} - true si expiré ou invalide, false sinon
         */
        function isJwtExpired(token) {
            if (!token) return true;
            try {
                const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
                if (!payload.exp) return true;
                // exp est en secondes depuis epoch
                const now = Math.floor(Date.now() / 1000);
                return payload.exp < now;
            } catch (e) {
                return true;
            }
        }

        // Récupération du token et username depuis sessionStorage
        let token = sessionStorage.getItem('jwtToken');
        const username = sessionStorage.getItem('username');

        // Nettoyage automatique si le token est expiré
        if (token && isJwtExpired(token)) {
            sessionStorage.removeItem('jwtToken');
            sessionStorage.removeItem('username');
            token = null;
        }

        // Affichage conditionnel : menu utilisateur OU formulaire de connexion
        if (token && username) {
            // Utilisateur connecté : afficher le menu utilisateur avec upload GPX
            loginForm.style.display = 'none';
            userMenu.style.display = 'block';
            document.getElementById('userName').textContent = username;
        } else {
            // Utilisateur non connecté : afficher le formulaire de connexion
            loginForm.style.display = 'block';
            userMenu.style.display = 'none';
        }

        // ========================================
        // GESTION DU FORMULAIRE DE CONNEXION
        // ========================================

        if (stepperLoginForm) {
            stepperLoginForm.addEventListener('submit', async function(e) {
                e.preventDefault();
                stepperLoginError.style.display = 'none';
                const login = document.getElementById('stepperLogin').value;
                const password = document.getElementById('stepperLoginPassword').value;

                try {
                    // Appel direct à l'API FastAPI (plus de relais Flask)
                    const response = await fetch(`${window.API_BASE}/api/auth/login`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username: login, password: password })
                    });

                    const data = await response.json();

                    if (response.ok && data.success) {
                        // Succès : stocker le token JWT et le username en sessionStorage
                        sessionStorage.setItem('jwtToken', data.token);
                        sessionStorage.setItem('username', data.user.username);
                        // Recharger la page pour afficher le menu utilisateur et les données filtrées par rôle
                        location.reload();
                    } else {
                        // Échec : afficher le message d'erreur
                        stepperLoginError.textContent = data.message || 'Erreur de connexion';
                        stepperLoginError.style.display = 'block';
                    }
                } catch (err) {
                    console.error('Erreur connexion:', err);
                    stepperLoginError.textContent = 'Erreur réseau ou serveur';
                    stepperLoginError.style.display = 'block';
                }
            });
        }

        // ========================================
        // GESTION DE LA DÉCONNEXION
        // ========================================

        if (logoutBtn) {
            logoutBtn.addEventListener('click', function() {
                // Supprimer le token et le username du sessionStorage
                sessionStorage.removeItem('jwtToken');
                sessionStorage.removeItem('username');
                // Recharger la page pour afficher le formulaire de connexion
                location.reload();
            });
        }

        // ========================================
        // GESTION DE L'UPLOAD GPX (Admin/Contributeur uniquement)
        // ========================================

        // Gestion de la sélection de fichier GPX
        if (gpxFileInput) {
            gpxFileInput.addEventListener('change', function() {
                if (this.files && this.files[0]) {
                    fileName.textContent = this.files[0].name;
                    uploadBtn.disabled = false;
                } else {
                    fileName.textContent = '';
                    uploadBtn.disabled = true;
                }
            });
        }

        // Gestion de la soumission du formulaire d'upload GPX
        if (gpxUploadForm) {
            gpxUploadForm.addEventListener('submit', async function(e) {
                e.preventDefault();
                // Masquer les messages d'erreur/succès précédents
                gpxUploadError.style.display = 'none';
                gpxUploadSuccess.style.display = 'none';

                // Validation : fichier sélectionné
                const file = gpxFileInput.files[0];
                if (!file) {
                    gpxUploadError.textContent = 'Veuillez sélectionner un fichier';
                    gpxUploadError.style.display = 'block';
                    return;
                }

                // Validation : utilisateur authentifié (token JWT requis)
                if (!token) {
                    gpxUploadError.textContent = 'Vous devez être connecté pour uploader un fichier. Veuillez vous reconnecter.';
                    gpxUploadError.style.display = 'block';
                    return;
                }

                // Préparation des données : création d'un FormData avec le fichier GPX
                const formData = new FormData();
                formData.append('file', file);

                try {
                    // Désactiver le bouton pendant l'upload et afficher un indicateur de chargement
                    uploadBtn.disabled = true;
                    uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Upload en cours...';

                    // Appel direct à l'API FastAPI (plus de relais Flask)
                    // Le token JWT est envoyé dans le header Authorization pour authentifier la requête
                    const response = await fetch(`${window.API_BASE}/api/etl/upload_gpx`, {
                        method: 'POST',
                        headers: {
                            'Authorization': 'Bearer ' + token
                        },
                        body: formData
                    });

                    // Traitement de la réponse : gestion des différents types de contenu (JSON ou texte brut)
                    let data = null;
                    const contentType = response.headers.get('content-type') || '';

                    if (contentType.includes('application/json')) {
                        // Réponse JSON : parser les données
                        try {
                            data = await response.json();
                        } catch (e) {
                            // Erreur de parsing JSON : afficher l'erreur et le contenu brut
                            console.error('Erreur parsing JSON:', e);
                            const text = await response.text();
                            gpxUploadError.textContent = `Réponse serveur non valide (status ${response.status}): ${text}`;
                            gpxUploadError.style.display = 'block';
                            uploadBtn.disabled = false;
                            uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Uploader le tracé';
                            return;
                        }
                    } else {
                        // Réponse non-JSON (HTML ou texte brut)
                        const text = await response.text();
                        if (response.ok) {
                            // Succès mais réponse non-JSON : afficher le texte brut et recharger la page
                            gpxUploadSuccess.textContent = text;
                            gpxUploadSuccess.style.display = 'block';
                            gpxUploadForm.reset();
                            fileName.textContent = '';
                            uploadBtn.disabled = true;
                            uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Uploader le tracé';
                            setTimeout(() => { location.reload(); }, 2000);
                            return;
                        } else {
                            // Erreur serveur avec réponse non-JSON : afficher le message d'erreur
                            gpxUploadError.textContent = `Erreur serveur (status ${response.status}): ${text}`;
                            gpxUploadError.style.display = 'block';
                            uploadBtn.disabled = false;
                            uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Uploader le tracé';
                            return;
                        }
                    }

                    // Traitement du succès de l'upload
                    if (response.ok && data && data.success) {
                        // Construire le message de succès avec la ville détectée si disponible
                        const cityMsg = data.city ? ` - Ville détectée : ${data.city}. Vous pourrez la sélectionner à l'étape suivante.` : '';
                        gpxUploadSuccess.textContent = data.message + cityMsg;
                        gpxUploadSuccess.style.display = 'block';

                        // Réinitialiser le formulaire d'upload
                        gpxUploadForm.reset();
                        fileName.textContent = '';
                        uploadBtn.disabled = true;
                        uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Uploader le tracé';
                    } else {
                        // Traitement de l'échec de l'upload
                        gpxUploadError.textContent = data.message || 'Erreur lors de l\'upload';
                        gpxUploadError.style.display = 'block';
                        uploadBtn.disabled = false;
                        uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Uploader le tracé';
                    }
                } catch (err) {
                    console.error('Erreur upload:', err);
                    gpxUploadError.textContent = 'Erreur réseau ou serveur';
                    gpxUploadError.style.display = 'block';
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Uploader le tracé';
                }
            });
        }

        let selectedDays = null;
        const durationCards = document.querySelectorAll('.duration-card');
        const nextButton = document.getElementById('nextButton');
        const dayBadge = document.getElementById('dayBadge');

        // Date du premier jour du séjour : par défaut aujourd'hui, modifiable,
        // jamais dans le passé (utilisée ensuite pour les dates du PDF).
        const startDateInput = document.getElementById('startDate');
        if (startDateInput) {
            const todayStr = new Date().toISOString().slice(0, 10);
            startDateInput.value = todayStr;
            startDateInput.min = todayStr;
        }

        function updateNextButton() {
            if (!selectedDays) {
                nextButton.innerHTML = `Choisissez une durée <i class="fas fa-arrow-right"></i>`;
                nextButton.disabled = true;
                return;
            }
            const dayText = selectedDays === 1 ? 'jour' : 'jours';
            nextButton.innerHTML = `Planifier ces ${selectedDays} ${dayText} <i class="fas fa-arrow-right"></i>`;
            nextButton.disabled = false;
        }

        function showDayBadge() {
            if (!dayBadge) return;
            dayBadge.textContent = `Jours : ${selectedDays}`;
            dayBadge.style.display = '';
        }

        durationCards.forEach(card => {
            card.addEventListener('click', function () {
                durationCards.forEach(c => c.classList.remove('active'));
                this.classList.add('active');

                const days = this.getAttribute('data-days');
                if (days === 'custom') {
                    const customInput = document.getElementById('customDays');
                    customInput.focus();
                    selectedDays = parseInt(customInput.value) || null;
                    updateNextButton();
                    if (selectedDays) showDayBadge();
                    customInput.addEventListener('input', function () {
                        selectedDays = parseInt(this.value) || null;
                        updateNextButton();
                        if (selectedDays) showDayBadge();
                    });
                } else {
                    selectedDays = parseInt(days);
                    updateNextButton();
                    showDayBadge();
                }
            });
        });

        nextButton.addEventListener('click', function (e) {
            e.preventDefault();
            if (!selectedDays) return;
            localStorage.setItem('selectedDays', selectedDays);
            const startDate = (startDateInput && startDateInput.value) || new Date().toISOString().slice(0, 10);
            localStorage.setItem('selectedStartDate', startDate);
            window.location.href = window.APP_URLS.step1;
        });
    });
