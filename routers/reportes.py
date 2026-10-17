"""Modulo de Reportes: caja, morosidad, pagos del portal y pagos de inscripcion.

No tiene tablas propias: consulta las de los otros modulos.
"""
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import models
from database import get_db
from reglas import MONTO_INSCRIPCION, actualizar_vencidos, hoy
from seguridad import CAJERO, requiere_rol

router = APIRouter(
    prefix="/api/v1/reportes", tags=["Reportes"], dependencies=[Depends(requiere_rol(CAJERO))]
)


def rango(desde: Optional[date], hasta: Optional[date]) -> Tuple[datetime, datetime]:
    """Por defecto el reporte va del primer día del mes actual hasta hoy."""
    fin = hasta or hoy()
    inicio = desde or fin.replace(day=1)
    return datetime.combine(inicio, time.min), datetime.combine(fin, time.max)


def fila_pago(pago: models.Pago) -> dict:
    socio = pago.aviso.socio if pago.aviso else None
    return {
        "id_pago": pago.id_pago,
        "fecha_pago": pago.fecha_pago,
        "id_aviso": pago.aviso_id_aviso,
        "periodo": pago.aviso.periodo.periodo if pago.aviso else None,
        "codigo_fijo": socio.codigo_fijo if socio else None,
        "nombre_socio": socio.nombre_socio if socio else None,
        "metodo": pago.metodo_pago.metodo,
        "monto": pago.monto_pagado,
        "cajero": pago.cajero,
        "id_transaccion": pago.id_transaccion,
        "numero_factura": pago.factura.numero_factura if pago.factura else None,
        "factura_url": pago.factura_url,
    }


@router.get("/caja")
def reporte_caja(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    id_usuario: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """HU21: cobros en ventanilla del periodo, con filtro por cajero y total por método."""
    inicio, fin = rango(desde, hasta)
    consulta = (
        db.query(models.Pago)
        .join(models.Caja)
        .filter(
            models.Pago.estado_pago == "APROBADO",
            models.Pago.fecha_pago.between(inicio, fin),
        )
    )
    if id_usuario is not None:
        consulta = consulta.filter(models.Caja.usuario_admin_id_usuario_admin == id_usuario)
    pagos = consulta.order_by(models.Pago.fecha_pago).all()

    por_metodo = defaultdict(Decimal)
    for pago in pagos:
        por_metodo[pago.metodo_pago.metodo] += Decimal(pago.monto_pagado)
    return {
        "desde": inicio.date(),
        "hasta": fin.date(),
        "pagos": [fila_pago(p) for p in pagos],
        "total_por_metodo": dict(por_metodo),
        "total": sum(por_metodo.values(), Decimal("0")),
        "cantidad": len(pagos),
    }


@router.get("/morosidad")
def reporte_morosidad(id_ruta: Optional[int] = None, db: Session = Depends(get_db)):
    """HU22: avisos vencidos agrupados por socio, con monto adeudado y días de mora."""
    actualizar_vencidos(db)
    consulta = (
        db.query(models.Aviso)
        .join(models.Estado)
        .join(models.Socio)
        .filter(models.Estado.estado == "VENCIDO")
    )
    if id_ruta is not None:
        consulta = consulta.filter(models.Socio.ruta_id_ruta == id_ruta)

    socios = {}
    for aviso in consulta.order_by(models.Aviso.fecha_vencimiento).all():
        socio = aviso.socio
        fila = socios.setdefault(socio.id_socio, {
            "id_socio": socio.id_socio,
            "codigo_fijo": socio.codigo_fijo,
            "nombre_socio": socio.nombre_socio,
            "ruta": socio.ruta.ruta,
            "periodos": [],
            "monto_adeudado": Decimal("0"),
            "dias_mora": 0,
        })
        fila["periodos"].append(aviso.periodo.periodo)
        fila["monto_adeudado"] += Decimal(aviso.total_aviso)
        fila["dias_mora"] = max(fila["dias_mora"], (hoy() - aviso.fecha_vencimiento).days)

    filas = sorted(socios.values(), key=lambda f: f["dias_mora"], reverse=True)
    for fila in filas:
        fila["meses_adeudados"] = len(fila["periodos"])
    return {
        "socios": filas,
        "total_adeudado": sum((f["monto_adeudado"] for f in filas), Decimal("0")),
        "cantidad_socios": len(filas),
    }


@router.get("/pagos-portal")
def reporte_pagos_portal(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """HU23: pagos hechos por los socios desde el portal (sin caja), con su transacción."""
    inicio, fin = rango(desde, hasta)
    pagos = (
        db.query(models.Pago)
        .filter(
            models.Pago.estado_pago == "APROBADO",
            models.Pago.forma_pago == "PORTAL",
            models.Pago.fecha_pago.between(inicio, fin),
        )
        .order_by(models.Pago.fecha_pago)
        .all()
    )
    return {
        "desde": inicio.date(),
        "hasta": fin.date(),
        "pagos": [fila_pago(p) for p in pagos],
        "total": sum((Decimal(p.monto_pagado) for p in pagos), Decimal("0")),
        "cantidad": len(pagos),
    }


@router.get("/inscripcion")
def reporte_inscripcion(solo_pendientes: bool = False, db: Session = Depends(get_db)):
    """HU24: cuotas del crédito de inscripción por socio: pagadas, pendientes y saldo."""
    cuotas = (
        db.query(models.CreditoInscripcion)
        .order_by(models.CreditoInscripcion.socio_id_socio, models.CreditoInscripcion.num_cuota)
        .all()
    )
    socios = {}
    for cuota in cuotas:
        socio = cuota.socio
        fila = socios.setdefault(socio.id_socio, {
            "id_socio": socio.id_socio,
            "codigo_fijo": socio.codigo_fijo,
            "nombre_socio": socio.nombre_socio,
            "monto_credito": MONTO_INSCRIPCION,
            "cuotas": [],
            "pagado": Decimal("0"),
        })
        pago = db.get(models.Pago, cuota.pago_id_pago) if cuota.pago_id_pago else None
        fila["cuotas"].append({
            "num_cuota": cuota.num_cuota,
            "periodo": cuota.periodo.periodo,
            "monto": cuota.monto_pago,
            "estado": cuota.estado,
            "fecha_pago": pago.fecha_pago if pago else None,
        })
        if cuota.estado == "PAGADA":
            fila["pagado"] += Decimal(cuota.monto_pago)

    filas = []
    for fila in socios.values():
        fila["saldo_pendiente"] = MONTO_INSCRIPCION - fila["pagado"]
        fila["completo"] = fila["saldo_pendiente"] <= 0
        if not (solo_pendientes and fila["completo"]):
            filas.append(fila)
    return {
        "socios": filas,
        "completos": sum(1 for f in filas if f["completo"]),
        "con_cuotas_pendientes": sum(1 for f in filas if not f["completo"]),
    }
