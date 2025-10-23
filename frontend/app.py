from flask import Flask, render_template, request, jsonify, session, redirect, url_for


app = Flask(__name__)
app.secret_key = 'randovango-secret-key-change-in-production'

# Configuration
app.config['STATIC_FOLDER'] = 'static'
app.config['TEMPLATES_FOLDER'] = 'templates'

@app.route('/')
def index():
    """Page d'accueil - Redirection vers le planificateur"""
    return redirect(url_for('planificateur_etape1'))

# ===== PLANIFICATEUR PRINCIPAL =====
@app.route('/etape1')
def planificateur_etape1():
    """Étape 1 - Choix de la ville"""
    return render_template('pages/etape1_ville.html')

@app.route('/etape2')
def planificateur_etape2():
    """Étape 2 - Choix de la randonnée"""
    return render_template('pages/etape2_randonnee.html')

@app.route('/etape3')
def planificateur_etape3():
    """Étape 3 - Choix de la nuit"""
    return render_template('pages/etape3_nuit.html')

@app.route('/etape4')
def planificateur_etape4():
    """Étape 4 - Services et POI"""
    return render_template('pages/etape4_services.html')

@app.route('/resultat')
def planificateur_resultat():
    """Résultat final du planning"""
    return render_template('pages/resultat.html')

@app.route('/api/search')
def search():
    """API de recherche pour l'assistant van"""
    query = request.args.get('q', '')
    category = request.args.get('category', 'all')
    
    # Ici vous pourrez appeler votre backend FastAPI
    # Pour l'instant, retourne des données mock
    
    return jsonify({
        'query': query,
        'category': category,
        'results': [],
        'status': 'success'
    })

@app.route('/api/weather')
def weather():
    """API météo"""
    # Ici vous appellerez votre service météo
    return jsonify({
        'temperature': 15,
        'condition': 'partly-cloudy',
        'description': 'Partiellement nuageux'
    })

@app.route('/login', methods=['POST'])
def login():
    """Gestion de la connexion"""
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    # Authentification simple pour demo
    if email == 'admin@test.com' and password == 'password123':
        session['user'] = {
            'email': email,
            'name': 'Administrateur'
        }
        return jsonify({'status': 'success', 'message': 'Connexion réussie'})
    
    return jsonify({'status': 'error', 'message': 'Email ou mot de passe incorrect'}), 401

@app.route('/logout', methods=['POST'])
def logout():
    """Déconnexion"""
    session.pop('user', None)
    return jsonify({'status': 'success', 'message': 'Déconnexion réussie'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
