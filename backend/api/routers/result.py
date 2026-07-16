from fastapi import APIRouter, Query
from fastapi.responses import Response
from utils.db_utils import MySQLUtils
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP
from utils.display_utils import result_day_display
from services.pdf_service import render_trip_pdf_html

router = APIRouter()


def _fetch_plan_data(plan_id: int):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)

    # Plan principal (avec la ville associée)
    cursor.execute("""
        SELECT tp.*, c.name AS city_name, c.latitude AS city_latitude, c.longitude AS city_longitude,
               c.department AS city_department, c.region AS city_region
        FROM trip_plans tp
        LEFT JOIN cities c ON tp.city_id = c.id
        WHERE tp.id = %s
    """, (plan_id,))
    plan = cursor.fetchone()

    if not plan:
        cursor.close()
        MySQLUtils.disconnect(cnx)
        return None

    # Jours du plan avec randonnée et spot (spot_id FK → spots)
    cursor.execute("""
        SELECT
            td.id,
            td.day_number,
            td.hike_id,
            td.spot_id,
            td.city_id,
            c2.name               AS city_name,
            c2.latitude           AS city_latitude,
            c2.longitude          AS city_longitude,
            h.name               AS hike_name,
            h.description        AS hike_description,
            h.distance_km,
            h.difficulte,
            h.elevation_gain_m,
            h.estimated_duration_h AS hike_duration_h,
            h.verifie            AS hike_verifie,
            h.start_latitude     AS hike_latitude,
            h.start_longitude    AS hike_longitude,
            h.address            AS hike_address,
            h.mongo_id           AS hike_mongo_id,
            p.name               AS spot_name,
            p.description        AS spot_description,
            p.type                AS spot_type,
            p.rating              AS spot_rating,
            p.url                 AS spot_url,
            p.latitude           AS spot_latitude,
            p.longitude          AS spot_longitude,
            p.address            AS spot_address
        FROM trip_days td
        LEFT JOIN hikes h ON td.hike_id = h.id
        LEFT JOIN spots p ON td.spot_id = p.id
        LEFT JOIN cities c2 ON td.city_id = c2.id
        WHERE td.trip_plan_id = %s
        ORDER BY td.day_number ASC
    """, (plan_id,))
    days = cursor.fetchall()

    # POI/services pour chaque jour
    for day in days:
        cursor.execute("""
            SELECT p.id, p.name, p.latitude, p.longitude, p.address,
                   s.name AS service_type, s.category AS service_category
            FROM trip_day_pois tdp
            JOIN poi p        ON tdp.poi_id = p.id
            LEFT JOIN poi_service ps ON p.id = ps.poi_id
            LEFT JOIN services s     ON ps.service_id = s.id
            WHERE tdp.trip_day_id = %s
        """, (day["id"],))
        pois = cursor.fetchall()
        for poi in pois:
            raw_category = (poi.pop("service_category") or "").lower()
            poi["category"] = POI_FRONTEND_CATEGORY_MAP.get(raw_category)
        day["pois"] = pois
        # Textes prêts à afficher pour le tableau récapitulatif de la page
        # results (le PDF, lui, utilise son propre gabarit et ignore ce champ).
        day["display"] = result_day_display(day)

    plan["days"] = days
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return plan


@router.get("/", summary="Retrieve the trip plan details by plan ID.")
def get_plan(
    plan_id: int = Query(...),
    up_to_day: int = Query(None, description="Ne renvoyer que les jours 1 à up_to_day (récapitulatif partiel)")
):
    plan = _fetch_plan_data(plan_id)
    # Sans up_to_day, comportement inchangé : tous les jours sont renvoyés
    # (l'endpoint est aussi utilisé ailleurs sans filtre).
    if plan and up_to_day is not None:
        plan["days"] = [d for d in plan["days"] if d["day_number"] <= up_to_day]
    return plan


@router.get("/pdf", summary="Download the trip plan as a printable PDF booklet.")
def get_plan_pdf(plan_id: int = Query(...)):
    plan = _fetch_plan_data(plan_id)
    if not plan:
        return Response(content="Plan introuvable", status_code=404)

    # Ne garder que les jours réellement complétés (create_plan pré-crée tous les
    # jours du séjour, vides, dès le départ).
    plan["days"] = [d for d in plan["days"] if d.get("hike_id") or d.get("spot_id")]

    html = render_trip_pdf_html(plan)
    from weasyprint import HTML
    pdf_bytes = HTML(string=html).write_pdf()

    city_name = (plan.get("city_name") or "voyage").lower().replace(" ", "-")
    filename = f"carnet-voyage-{city_name}-{plan_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
