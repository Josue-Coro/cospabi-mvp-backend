"""Pago de avisos con QR mediante Libelula, usado por el portal del socio y por la caja.

1. crear_pago_qr: deja un pago PENDIENTE y registra la deuda en Libelula (devuelve el QR).
2. confirmar_pago_qr: consulta a Libelula y, si ya se pago, aprueba el pago y el aviso.
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import libelula
import models
import schemas
from reglas import ahora, aplicar_pago, detalle_aviso, hoy, validar_cobro

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


def crear_pago_qr(
    db: Session,
    aviso: models.Aviso,
    datos: schemas.PagoQrIn,
    cajero: str,
    caja: Optional[models.Caja],
    forma_pago: str,
) -> models.Pago:
    """Registra la deuda del aviso en Libélula y deja el pago PENDIENTE (con commit).

    Si el socio pide factura, la emite Libélula con su NIT/CI y razón social.
    Un QR nuevo reemplaza a los anteriores del mismo aviso que no se pagaron.
    """
    validar_cobro(db, aviso)
    if datos.con_factura and not (datos.nit_ci and datos.razon_social):
        raise HTTPException(status_code=400, detail="Para la factura indique NIT/CI y razón social")

    db.query(models.Pago).filter(
        models.Pago.aviso_id_aviso == aviso.id_aviso, models.Pago.estado_pago == "PENDIENTE"
    ).update({models.Pago.estado_pago: "EXPIRADO"}, synchronize_session=False)

    pago = models.Pago(
        fecha_pago=ahora(),
        monto_pagado=Decimal(aviso.total_aviso),
        cajero=cajero,
        aviso_id_aviso=aviso.id_aviso,
        metodo_pago_id_metodo_pago=ID_METODO_QR,
        vuelto=Decimal("0"),
        caja_id_caja=caja.id_caja if caja else None,
        forma_pago=forma_pago,
        estado_pago="PENDIENTE",
    )
    db.add(pago)
    db.flush()
    # Libélula exige un identificador único por deuda; el sufijo evita choques entre bases
    # de prueba y producción que comparten la misma llave
    pago.identificador_deuda = f"COSPABI-{aviso.id_aviso}-{pago.id_pago}-{uuid.uuid4().hex[:8]}"

    socio = aviso.socio
    persona = socio.persona
    nombres = socio.nombre_socio.split(" ", 1)
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
        "numero_documento": datos.nit_ci if datos.con_factura else persona.ci,
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
    return pago


def confirmar_pago_qr(db: Session, id_pago: int) -> models.Pago:
    """Consulta a Libélula si la deuda se pagó y, si es así, aprueba el pago y el aviso.

    Se bloquea la fila del pago para que el callback y las consultas del portal o de
    la caja no lo apliquen dos veces al mismo tiempo.

    Un QR EXPIRADO aquí (reemplazado por otro, por ejemplo tras un doble clic) sigue
    vigente en Libélula: si el socio igual lo pagó, el dinero se registra en vez de perderse.
    """
    # FOR UPDATE OF pago: las relaciones se cargan con LEFT JOIN y no se pueden bloquear
    pago = (
        db.query(models.Pago).filter(models.Pago.id_pago == id_pago).with_for_update(of=models.Pago).one()
    )
    if pago.estado_pago == "APROBADO" or not pago.identificador_deuda:
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
