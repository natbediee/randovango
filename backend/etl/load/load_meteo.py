
from backend.utils.mysql_utils import connect_mysql

def insert_weather_data(data):
    cnx = connect_mysql()
    cursor = cnx.cursor()
    sql = ("""
        INSERT INTO weather (
            city_id, date, temp_max_c, temp_min_c, precipitation_mm, wind_max_kmh, weather_code, solar_energy_sum
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """)
    cursor.executemany(sql, data)
    cnx.commit()
    cursor.close()
    cnx.close()

