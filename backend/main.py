from fastapi import FastAPI
from api.routers import etape1, etape2, etape3, etape4, resultat

app = FastAPI(
    title="RandoVanGo API",
    description="API du planificateurs",
)

app.include_router(etape1.router, prefix="/api/etape1", tags=["Etape 1"])
app.include_router(etape2.router, prefix="/api/etape2", tags=["Etape 2"])
app.include_router(etape3.router, prefix="/api/etape3", tags=["Etape 3"])
app.include_router(etape4.router, prefix="/api/etape4", tags=["Etape 4"])
app.include_router(resultat.router, prefix="/api/resultat", tags=["Résultat"])
