"""API de COSPABI R.L. - MVP de los 6 modulos del sistema mas la facturacion simulada."""
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

import models
from database import engine
from datos_iniciales import cargar_datos_iniciales, configurar_base_datos
from routers import (
    administracion,
    atencion_cliente,
    configuracion,
    facturacion,
    operaciones,
    portal,
    reportes,
)

# Crea las tablas en Supabase si no existen y carga los datos iniciales que falten
models.Base.metadata.create_all(bind=engine)
configurar_base_datos()
cargar_datos_iniciales()

app = FastAPI(
    title="API COSPABI R.L.",
    version="1.1.0",
    description=(
        "Sistema de gestión de la Cooperativa de Agua Potable COSPABI R.L. "
        "MVP de los módulos Administración, Configuración, Atención al Cliente, "
        "Operaciones, Portal del Socio, Reportes y Facturación (simulada). "
        "Primero inicie sesión en /api/v1/auth/login (personal) o /api/v1/portal/login "
        "(socio) y pegue el token en el botón Authorize."
    ),
)

# Permite que los frontends (Vercel) consuman la API. CORS_ORIGENES admite una
# lista separada por comas; si no se define se permite cualquier origen.
origenes = [o.strip() for o in os.getenv("CORS_ORIGENES", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origenes,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Si un pedido repetido llega a la base y choca con una restriccion UNIQUE (por ejemplo,
# la misma lectura dos veces), se responde 409 con un mensaje claro en lugar de un 500
@app.exception_handler(IntegrityError)
def registro_duplicado(_request: Request, _error: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={"detail": "Ese registro ya existe o choca con otro dato (¿se envió dos veces?)"},
    )


# Cada router es un modulo del sistema
app.include_router(administracion.router)
app.include_router(configuracion.router)
app.include_router(atencion_cliente.router)
app.include_router(operaciones.router)
app.include_router(facturacion.router)
app.include_router(reportes.router)
app.include_router(portal.router)


@app.get("/", tags=["Inicio"])
def inicio():
    return {"sistema": "API COSPABI R.L.", "estado": "en línea", "documentacion": "/docs"}
