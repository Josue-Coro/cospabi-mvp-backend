"""Modulo Portal del Socio: el socio consulta sus avisos, pagos y facturas y paga con QR.

Usa su propio token (tipo "socio"), distinto del token del personal. El pago con QR
se hace con la pasarela Libelula (ver libelula.py).
"""
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import libelula
import models
import schemas
from database import get_db
from reglas import actualizar_vencidos, ahora, aplicar_pago, detalle_aviso, hoy, validar_cobro
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
ID_METODO_QR = 2  # catalogo metodo_pago


def pago_qr_a_salida(pago: models.Pago) -> dict:
    return {
        "id_pago": pago.id_pago,
        "id_aviso": pago.aviso_id_aviso,
        "estado": pago.estado_pago,
        "monto": pago.monto_pagado,
        "qr_url": pago.qr_url,
        "url_pasarela": pago.url_pasarela,
        "codigo_recaudacion": pago.codigo_recaudacion,
        "factura_url": pago.factura_url,
    }


def lineas_para_libelula(detalle: dict) -> list:
    """Detalle del aviso en el formato lineas_detalle_deuda de Libelula."""
    consumo = detalle["lectura"]["consumo_m3"] if detalle["lectura"] else 0
    lineas = [{
        "concepto": f"Servicio de agua potable {detalle['periodo']} ({consumo} m3)",
        "cantidad": 1,
        "costo_unitario": float(detalle["total_consumo"]),
        "codigo_producto": "AGUA",
    }]
    lineas += [
        {"concepto": c["descripcion"], "cantidad": 1, "costo_unitario": float(c["monto"]),
         "codigo_producto": "CARGO"}
        for c in detalle["cargos"]
    ]
    lineas += [
        {"concepto": f"Cuota {c['num_cuota']}/4 de inscripción", "cantidad": 1,
         "costo_unitario": float(c["monto"]), "codigo_producto": "INSCRIPCION"}
        for c in detalle["cuotas_inscripcion"]
    ]
    return lineas


@router.post("/avisos/{id_aviso}/pagar-qr", response_model=schemas.PagoQrOut)
def generar_pago_qr(
    id_aviso: int,
    datos: schemas.PagoQrIn,
    socio: models.Socio = Depends(socio_actual),
    db: Session = Depends(get_db),
):
    """Registra la deuda del aviso en Libélula y devuelve el QR para pagarlo.

    El pago queda PENDIENTE hasta que Libélula lo confirma (callback o consulta).
    Si el socio pide factura, la emite Libélula con su NIT/CI y razón social.
    """
    actualizar_vencidos(db)
    aviso = aviso_del_socio(db, socio, id_aviso)
    validar_cobro(db, aviso)
    if datos.con_factura and not (datos.nit_ci and datos.razon_social):
        raise HTTPException(status_code=400, detail="Para la factura indique NIT/CI y razón social")

    # Un QR nuevo reemplaza a los anteriores que no se pagaron
    db.query(models.Pago).filter(
        models.Pago.aviso_id_aviso == aviso.id_aviso, models.Pago.estado_pago == "PENDIENTE"
    ).update({models.Pago.estado_pago: "EXPIRADO"}, synchronize_session=False)

    pago = models.Pago(
        fecha_pago=ahora(),
        monto_pagado=Decimal(aviso.total_aviso),
        cajero="PORTAL",
        aviso_id_aviso=aviso.id_aviso,
        metodo_pago_id_metodo_pago=ID_METODO_QR,
        vuelto=Decimal("0"),
        caja_id_caja=None,
        forma_pago="PORTAL",
        estado_pago="PENDIENTE",
    )
    db.add(pago)
    db.flush()
    pago.identificador_deuda = f"COSPABI-{aviso.id_aviso}-{pago.id_pago}"

    persona = socio.persona
    nombres = socio.nombre_socio.split(" ", 1)
    documento = datos.nit_ci if datos.con_factura else persona.ci
    cuerpo = {
        "email_cliente": socio.correo,
        "identificador": pago.identificador_deuda,
        "descripcion": (
            f"Aviso N° {aviso.id_aviso} - periodo {aviso.periodo.periodo} - código fijo {socio.codigo_fijo}"
        ),
        "callback_url": f"{libelula.URL_PUBLICA_API}/api/v1/portal/libelula/pago-exitoso",
        "url_retorno": f"{libelula.URL_PORTAL}/avisos/{aviso.id_aviso}",
        "fecha_vencimiento": (hoy() + timedelta(days=2)).isoformat(),
        "nombre_cliente": nombres[0],
        "apellido_cliente": nombres[1] if len(nombres) > 1 else "",
        "codigo_cliente": str(socio.codigo_fijo),
        "ci": persona.ci,
        "numero_documento": documento,
        "codigo_tipo_documento": "5" if datos.con_factura and datos.tipo_documento == "NIT" else "1",
        "emite_factura": datos.con_factura,
        "moneda": "BOB",
        "lineas_detalle_deuda": lineas_para_libelula(detalle_aviso(db, aviso)),
        "lineas_metadatos": [
            {"nombre": "Código fijo", "dato": str(socio.codigo_fijo)},
            {"nombre": "Periodo", "dato": aviso.periodo.periodo},
        ],
    }
    if datos.con_factura:
        cuerpo["razon_social"] = datos.razon_social
        if datos.tipo_documento == "NIT":
            cuerpo["nit"] = datos.nit_ci

    try:
        respuesta = libelula.registrar_deuda(cuerpo)
    except HTTPException:
        db.rollback()
        raise
    pago.id_transaccion = respuesta.get("id_transaccion")
    pago.codigo_recaudacion = respuesta.get("codigo_recaudacion")
    pago.qr_url = respuesta.get("qr_simple_url")
    pago.url_pasarela = respuesta.get("url_pasarela_pagos")
    db.commit()
    db.refresh(pago)
    return pago_qr_a_salida(pago)


def confirmar_pago_qr(db: Session, id_pago: int) -> models.Pago:
    """Consulta a Libélula si la deuda se pagó y, si es así, aprueba el pago y el aviso.

    Se bloquea la fila del pago para que el callback y la consulta del portal no lo
    apliquen dos veces al mismo tiempo.
    """
    # FOR UPDATE OF pago: las relaciones se cargan con LEFT JOIN y no se pueden bloquear
    pago = (
        db.query(models.Pago).filter(models.Pago.id_pago == id_pago).with_for_update(of=models.Pago).one()
    )
    if pago.estado_pago != "PENDIENTE" or not pago.identificador_deuda:
        db.commit()  # libera el bloqueo
        return pago

    deuda = libelula.consultar_deuda(pago.identificador_deuda)
    if not deuda.get("pagado"):
        if deuda.get("deuda_expirada"):
            pago.estado_pago = "EXPIRADO"
        db.commit()
        return pago

    pago.estado_pago = "APROBADO"
    pago.fecha_pago = ahora()
    facturas = deuda.get("facturas") or []
    if facturas:
        pago.factura_url = facturas[0].get("url")
    aviso = pago.aviso
    if aviso.estado.estado not in ("PAGADO", "ANULADO"):
        aplicar_pago(db, aviso, pago)
    db.commit()
    db.refresh(pago)
    return pago


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
    """PAGO EXITOSO: Libélula avisa aquí que se pagó una deuda.

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
