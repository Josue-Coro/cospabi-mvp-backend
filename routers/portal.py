"""Modulo Portal del Socio: el socio consulta sus avisos, pagos y facturas y paga con QR.

Usa su propio token (tipo "socio"), distinto del token del personal. El pago con QR
se hace con la pasarela Libelula (ver pagos_qr.py y libelula.py).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from pagos_qr import confirmar_pago_qr, crear_pago_qr, pago_qr_a_salida
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
    """Detalle del aviso. Si tiene un pago con QR pendiente, primero se consulta a Libélula
    (por ejemplo, cuando el socio vuelve de la pasarela antes de que llegue el callback)."""
    aviso = aviso_del_socio(db, socio, id_aviso)
    pendiente = (
        db.query(models.Pago)
        .filter(models.Pago.aviso_id_aviso == aviso.id_aviso, models.Pago.estado_pago == "PENDIENTE")
        .order_by(models.Pago.id_pago.desc())
        .first()
    )
    if pendiente:
        confirmar_pago_qr(db, pendiente.id_pago)
        db.refresh(aviso)
    return {**detalle_aviso(db, aviso), "pago_qr_pendiente": pago_qr_a_salida(pendiente) if pendiente
            and pendiente.estado_pago == "PENDIENTE" else None}


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
            "factura_url": pago.factura_url,
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


# ------------------------------ Pago con QR ------------------------------
@router.post("/avisos/{id_aviso}/pagar-qr", response_model=schemas.PagoQrOut)
def generar_pago_qr(
    id_aviso: int,
    datos: schemas.PagoQrIn,
    socio: models.Socio = Depends(socio_actual),
    db: Session = Depends(get_db),
):
    """Registra la deuda del aviso en Libélula y devuelve el QR para pagarlo desde el portal.

    El pago queda PENDIENTE hasta que Libélula lo confirma (callback o consulta).
    """
    actualizar_vencidos(db)
    aviso = aviso_del_socio(db, socio, id_aviso)
    pago = crear_pago_qr(db, aviso, datos, cajero="PORTAL", caja=None, forma_pago="PORTAL")
    return pago_qr_a_salida(pago)


@router.get("/pagos-qr/{id_pago}", response_model=schemas.PagoQrOut)
def ver_pago_qr(id_pago: int, socio: models.Socio = Depends(socio_actual), db: Session = Depends(get_db)):
    """Estado del pago con QR; si sigue pendiente, se consulta a Libélula en ese momento."""
    pago = db.get(models.Pago, id_pago)
    if pago is None or pago.aviso is None or pago.aviso.socio_id_socio != socio.id_socio:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    return pago_qr_a_salida(confirmar_pago_qr(db, id_pago))


@router.api_route("/libelula/pago-exitoso", methods=["GET", "POST"])
def libelula_pago_exitoso(
    transaction_id: str,
    invoice_url: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """PAGO EXITOSO: Libélula avisa aquí que se pagó una deuda (del portal o de la caja).

    No se confía en la llamada: el pago se confirma consultando a Libélula.
    """
    pago = db.query(models.Pago).filter(models.Pago.id_transaccion == transaction_id).first()
    if pago is None:
        raise HTTPException(status_code=404, detail="Transacción desconocida")
    pago = confirmar_pago_qr(db, pago.id_pago)
    if invoice_url and pago.estado_pago == "APROBADO" and not pago.factura_url:
        pago.factura_url = invoice_url
        db.commit()
    mensaje = "Pago registrado" if pago.estado_pago == "APROBADO" else "Pago todavía no confirmado"
    return {"error": 0, "mensaje": mensaje, "estado": pago.estado_pago}
