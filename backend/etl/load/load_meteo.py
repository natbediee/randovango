
from backend.utils.mysql_utils import MySQLUtils

def insert_weather_data(data) -> None:
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    # Filtrer les tuples déjà présents (city_id, date)
    filtered_data = []
    for row in data:
        city_id, date = row[0], row[1]
        cursor.execute("SELECT 1 FROM weather WHERE city_id = %s AND date = %s", (city_id, date))
        if cursor.fetchone() is None:
            filtered_data.append(row)
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

