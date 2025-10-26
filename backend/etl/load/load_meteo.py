
from backend.utils.mysql_utils import MySQLUtils
from backend.utils.service_utils import ServiceUtil

def load_weather_data(data, city) -> None:
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    city_id = ServiceUtil.get_city_id(cursor, city)
    if city_id is None:
        print(f"Ville {city} absente de la base. Aucune donnée météo insérée.")
        cursor.close()
        MySQLUtils.disconnect(cnx)
        return
    # Filtrer les tuples déjà présents (city_id, date)
    filtered_data = []
    for row in data:
        date = row[0]
        cursor.execute("SELECT 1 FROM weather WHERE city_id = %s AND date = %s", (city_id, date))
        if cursor.fetchone() is None:
            # On recompose le tuple avec city_id devant
            filtered_data.append((city_id, *row))
    if filtered_data:
        sql = ("""
            INSERT INTO weather (
                city_id, date, temp_max_c, temp_min_c, precipitation_mm, wind_max_kmh, weather_code, solar_energy_sum
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """)
        cursor.executemany(sql, filtered_data)
        cnx.commit()
    cursor.close()
    MySQLUtils.disconnect(cnx)

