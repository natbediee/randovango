

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from backend.utils.service_category_map import SERVICE_CATEGORY_MAP
from backend.utils.service_utils import ServiceUtil
from backend.utils.mysql_utils import MySQLUtils


ServiceUtil.load_env()
conn = MySQLUtils.connect()
cursor = MySQLUtils.get_cursor(conn)

cursor.execute("SELECT id, name FROM services")
rows = cursor.fetchall()

update_sql = "UPDATE services SET category=%s WHERE id=%s"
updated = 0
for service_id, name in rows:
    category = SERVICE_CATEGORY_MAP.get(name)
    if category:
        cursor.execute(update_sql, (category, service_id))
        updated += 1

conn.commit()
cursor.close()
conn.close()
print(f"{updated} services mis à jour avec une catégorie.")
