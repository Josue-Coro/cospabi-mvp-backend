"""Cliente de la pasarela de pagos Libelula (pago con QR desde el portal del socio).

Servicios usados (Guia de integracion v2.145):
- REGISTRAR DEUDA: devuelve el QR, la URL de la pasarela y el id de transaccion.
- CONSULTAR DEUDAS POR IDENTIFICADOR: indica si la deuda ya fue pagada.
Para pruebas se apunta a produccion con la llave de pruebas que asigna Libelula.
"""
import json
import os
import urllib.error
import urllib.request

from fastapi import HTTPException

URL_API = os.getenv("LIBELULA_URL", "https://api.libelula.bo/rest/deuda").rstrip("/")
APPKEY = os.getenv("LIBELULA_APPKEY", "")

# URL publica de esta API (Render la define en RENDER_EXTERNAL_URL) y del portal del socio
URL_PUBLICA_API = (
    os.getenv("API_PUBLICA_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:8000"
).rstrip("/")
URL_PORTAL = os.getenv("PORTAL_URL", "https://cospabi-socio.vercel.app").rstrip("/")


def _llamar(servicio: str, cuerpo: dict) -> dict:
    if not APPKEY:
        raise HTTPException(status_code=503, detail="El pago con QR no está configurado (falta LIBELULA_APPKEY)")
    solicitud = urllib.request.Request(
        f"{URL_API}/{servicio}",
        data=json.dumps({"appkey": APPKEY, **cuerpo}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(solicitud, timeout=30) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"No se pudo conectar con Libélula: {error}")
    if datos.get("error") not in (0, False, None):
        raise HTTPException(status_code=502, detail=f"Libélula: {datos.get('mensaje', 'error desconocido')}")
    return datos


def registrar_deuda(cuerpo: dict) -> dict:
    """Registra la deuda y devuelve id_transaccion, codigo_recaudacion, qr_simple_url, url_pasarela_pagos."""
    return _llamar("registrar", cuerpo)


def consultar_deuda(identificador: str) -> dict:
    """Datos de la deuda en Libelula: pagado, fecha_pago, forma_pago, facturas, deuda_expirada..."""
    return _llamar("consultar_deudas/por_identificador", {"identificador": identificador}).get("datos") or {}
