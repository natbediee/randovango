import mysql.connector
import os
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT/".env")

MYSQL_CONF = {
    'host':     os.getenv('DB_HOST'),
    'user':     os.getenv('DB_USER'),
    'password': os.getenv('DB_PSWD'),
    'database': os.getenv('DB_NAME'),
}

def connect_mysql():
    return mysql.connector.connect(**MYSQL_CONF)

# Exemple d'utilisation :
# cnx = connect_mysql()
# cursor = cnx.cursor()
# ...
# cursor.close()
# cnx.close()
