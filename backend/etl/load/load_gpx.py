import json
import pymysql
import mongoengine
import os

# Connexion MySQL
mysql_conn = pymysql.connect(
    host='localhost', user='root', password='motdepasse', database='randovango', charset='utf8mb4'
)
# Connexion MongoDB
mongoengine.connect('randovango')

class GPXPoint(mongoengine.EmbeddedDocument):
    lat = mongoengine.FloatField(required=True)
    lon = mongoengine.FloatField(required=True)
    ele = mongoengine.FloatField()

class GPXWaypoint(mongoengine.EmbeddedDocument):
    name = mongoengine.StringField()
    lat = mongoengine.FloatField(required=True)
    lon = mongoengine.FloatField(required=True)
    ele = mongoengine.FloatField()
    desc = mongoengine.StringField()

class GPXTrace(mongoengine.Document):
    gpxtrace_id = mongoengine.IntField()  # id MySQL
    name = mongoengine.StringField(required=True)
    distance_km = mongoengine.FloatField()
    denivele_m = mongoengine.FloatField()
    points = mongoengine.ListField(mongoengine.EmbeddedDocumentField(GPXPoint))
    waypoints = mongoengine.ListField(mongoengine.EmbeddedDocumentField(GPXWaypoint))
    meta = {'collection': 'gpx_traces'}

# Dossier des fichiers transformés
INPUT = '../../in/gpx_transformed/'

def load_gpx():
    for fname in os.listdir(INPUT):
        if fname.endswith('.json'):
            with open(os.path.join(INPUT, fname), 'r') as f:
                data = json.load(f)
            source_name = data.get('source') or 'inconnue'
            # Gestion de la source : vérifie si elle existe, sinon crée
            with mysql_conn.cursor() as cursor:
                cursor.execute("SELECT id FROM sources WHERE nom = %s", (source_name,))
                result = cursor.fetchone()
                if result:
                    source_id = result[0]
                else:
                    cursor.execute("INSERT INTO sources (nom) VALUES (%s)", (source_name,))
                    mysql_conn.commit()
                    source_id = cursor.lastrowid
            # Insert MongoDB
            points = [GPXPoint(**pt) for pt in data['points']]
            waypoints = [GPXWaypoint(**wpt) for wpt in data['waypoints']]
            trace = GPXTrace(
                name=data['name'],
                distance_km=data['distance_km'],
                denivele_m=data['denivele_m'],
                points=points,
                waypoints=waypoints
            )
            trace.save()
            id_mongo = str(trace.id)
            # Insert MySQL avec id_mongo et source_id
            with mysql_conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO randonnee (name, distance_km, denivele_m, id_mongo, source_id) VALUES (%s, %s, %s, %s, %s)",
                    (data['name'], data['distance_km'], data['denivele_m'], id_mongo, source_id)
                )
                mysql_conn.commit()
                gpxtrace_id = cursor.lastrowid
            # Mise à jour du document MongoDB avec l'id MySQL
            trace.gpxtrace_id = gpxtrace_id
            trace.save()
            print(f'Loaded: {fname} (MySQL id={gpxtrace_id}, Mongo id={id_mongo})')

if __name__ == '__main__':
    load_gpx()
