"""
Script de test : génère une carte Folium pour une randonnée à partir de son id MySQL ou mongo_id.
"""
import folium
import sys
from utils.db_utils import MySQLUtils
from utils.mongo_utils import MongoUtils


# Paramètre : id MySQL de la randonnée
if len(sys.argv) > 1:
    hike_id = int(sys.argv[1])
else:
    print("Usage: python test_folium_hike.py <hike_id>")
    sys.exit(1)


# Connexion MySQL via utilitaire
mysql_conn = MySQLUtils.connect()
mysql_cursor = mysql_conn.cursor(dictionary=True)

# Connexion MongoDB via utilitaire
MongoUtils.connect()
gpx_collection = MongoUtils.get_collection("gpx_traces")



# Recherche du document MongoDB via hike_mysql_id
trace = gpx_collection.find_one({"hike_mysql_id": hike_id})
if not trace:
    print("Trace non trouvée dans MongoDB pour hike_mysql_id=", hike_id)
    sys.exit(1)

# Extraction des points
points = [(pt["lat"], pt["lon"]) for pt in trace["points"]]
if not points:
    print("Aucun point dans la trace.")
    sys.exit(1)

# Création de la carte Folium
m = folium.Map(location=points[0], zoom_start=15)
folium.PolyLine(points, color="blue", weight=3).add_to(m)
folium.Marker(points[0], tooltip="Départ").add_to(m)

# Sauvegarde
m.save("carte_randonnee.html")
print("Carte générée : carte_randonnee.html")
