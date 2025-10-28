from fastapi import FastAPI
from api.routers import step1, step2, step3, step4, result, auth, etl_gpx

app = FastAPI(
    title="RandoVanGo API",
    description="API du planificateurs",
)

app.include_router(step1.router, prefix="/api/step1", tags=["Step 1 Cities"])
app.include_router(step2.router, prefix="/api/step2", tags=["Step 2 Hikes"])
app.include_router(step3.router, prefix="/api/step3", tags=["Step 3 Spots"])
app.include_router(step4.router, prefix="/api/step4", tags=["Step 4 Services"])
app.include_router(result.router, prefix="/api/result", tags=["Result Plan"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(etl_gpx.router, prefix="/api/etl_gpx", tags=["ETL GPX"])
