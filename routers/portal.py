"""Modulo Portal del Socio: el socio consulta sus avisos, pagos y facturas.

Usa su propio token (tipo "socio"), distinto del token del personal.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import actualizar_vencidos, ahora, detalle_aviso
from routers.facturacion import detalle_factura
from routers.operaciones import aviso_a_salida
from seguridad import crear_token_socio, socio_actual, verificar_contrasena

router = APIRouter(prefix="/api/v1/portal", tags=["Portal del Socio"])


@router.post("/login", response_model=schemas.TokenOut)
def iniciar_sesion_socio(datos: schemas.LoginIn, db: Session = Depends(get_db)):
    """HU18: el socio ingresa con su código fijo y su contraseña."""
    cuenta = (
        db.query(models.CuentaSocio).filter(models.CuentaSocio.usuario == datos.usuario.strip()).first()
    )
    if cuenta is None:
        raise HTTPException(status_code=401, detail="Código fijo o contraseña incorrectos")
    if not verificar_contrasena(datos.contrasena, cuenta.contrasena):
        cuenta.intentos_fallidos += 1
        db.commit()
        raise HTTPException(status_code=401, detail="Código fijo o contraseña incorrectos")
    if not cuenta.estado:
        raise HTTPException(status_code=403, detail="Su cuenta está bloqueada; acérquese a la oficina")

    cuenta.intentos_fallidos = 0
    cuenta.ultimo_acceso = ahora()
    db.commit()
    return {
        "access_token": crear_token_socio(cuenta),
        "token_type": "bearer",
        "usuario": cuenta.usuario,
        "rol": "Socio",
    }


@router.get("/yo", response_model=schemas.SocioPortalOut)
def ver_mis_datos(socio: models.Socio = Depends(socio_actual)):
    return {
        "id_socio": socio.id_socio,
        "codigo_fijo": socio.codigo_fijo,
        "nombre_socio": socio.nombre_socio,
    }


@router.get("/avisos", response_model=List[schemas.AvisoOut])
def ver_mis_avisos(socio: models.Socio = Depends(socio_actual), db: Session = Depends(get_db)):
    """Avisos del socio, del más reciente al más antiguo (sin los anulados)."""
    actualizar_vencidos(db)
    avisos = (
        db.query(models.Aviso)
        .join(models.Estado)
        .filter(models.Aviso.socio_id_socio == socio.id_socio, models.Estado.estado != "ANULADO")
        .order_by(models.Aviso.id_aviso.desc())
        .all()
    )
    return [aviso_a_salida(aviso) for aviso in avisos]


def aviso_del_socio(db: Session, socio: models.Socio, id_aviso: int) -> models.Aviso:
    aviso = db.get(models.Aviso, id_aviso)
    # Un socio solo puede ver sus propios avisos
    if aviso is None or aviso.socio_id_socio != socio.id_socio:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")
    return aviso


@router.get("/avisos/{id_aviso}")
def ver_mi_aviso(
    id_aviso: int, socio: models.Socio = Depends(socio_actual), db: Session = Depends(get_db)
):
    return detalle_aviso(db, aviso_del_socio(db, socio, id_aviso))


@router.get("/pagos")
def ver_mis_pagos(socio: models.Socio = Depends(socio_actual), db: Session = Depends(get_db)):
    """Historial de pagos del socio, con su factura si la pidió."""
    pagos = (
        db.query(models.Pago)
        .join(models.Aviso)
        .filter(models.Aviso.socio_id_socio == socio.id_socio, models.Pago.estado_pago == "APROBADO")
        .order_by(models.Pago.fecha_pago.desc())
        .all()
    )
    return [
        {
            "id_pago": pago.id_pago,
            "fecha_pago": pago.fecha_pago,
            "id_aviso": pago.aviso_id_aviso,
            "periodo": pago.aviso.periodo.periodo,
            "monto_pagado": pago.monto_pagado,
            "metodo": pago.metodo_pago.metodo,
            "forma_pago": pago.forma_pago,
            "id_factura": pago.id_factura,
        }
        for pago in pagos
    ]


@router.get("/facturas/{id_factura}")
def ver_mi_factura(
    id_factura: int, socio: models.Socio = Depends(socio_actual), db: Session = Depends(get_db)
):
    factura = db.get(models.Factura, id_factura)
    if factura is None or factura.pago.aviso is None or factura.pago.aviso.socio_id_socio != socio.id_socio:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return detalle_factura(db, factura)
