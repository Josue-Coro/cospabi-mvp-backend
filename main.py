"""API de COSPABI R.L. - MVP del flujo principal: socio -> lectura -> aviso -> pago."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import models
from database import engine
from datos_iniciales import cargar_datos_iniciales
from routers import administracion, atencion_cliente, configuracion, operaciones

# Crea las tablas en Supabase si no existen y carga los datos iniciales que falten
models.Base.metadata.create_all(bind=engine)
cargar_datos_iniciales()

app = FastAPI(
    title="API COSPABI R.L.",
    version="1.0.0",
    description=(
        "Sistema de gestión de la Cooperativa de Agua Potable COSPABI R.L. "
        "MVP del flujo principal: socio, lectura, aviso de cobranza y pago. "
        "Primero inicie sesión en /api/v1/auth/login y pegue el token en el botón Authorize."
    ),
)

# Permite que un frontend en otro origen consuma la API (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cada router es un modulo del sistema
app.include_router(administracion.router)
app.include_router(configuracion.router)
app.include_router(atencion_cliente.router)
app.include_router(operaciones.router)


@app.get("/", tags=["Inicio"])
def inicio():
    return {"sistema": "API COSPABI R.L.", "estado": "en línea", "documentacion": "/docs"}
