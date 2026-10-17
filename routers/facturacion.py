"""Modulo de Facturacion (simulada): consulta de las facturas emitidas al cobrar.

La factura tiene los datos de una factura del SIAT (NIT, numero, CUF, codigo de
control, leyenda), pero no se envia a Impuestos Nacionales: es solo para el MVP.
"""
from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import FACTURA_NIT_EMISOR, FACTURA_RAZON_EMISOR, detalle_aviso
from seguridad import CAJERO, requiere_rol

router = APIRouter(prefix="/api/v1", dependencies=[Depends(requiere_rol(CAJERO))])


def detalle_factura(db: Session, factura: models.Factura) -> dict:
    """Factura completa para imprimir: emisor, cliente y lineas del aviso pagado."""
    pago = factura.pago
    aviso = detalle_aviso(db, pago.aviso) if pago.aviso else None
    lineas = []
    if aviso:
        consumo = aviso["lectura"]["consumo_m3"] if aviso["lectura"] else 0
        lineas.append({
            "concepto": f"Servicio de agua potable {aviso['periodo']} ({consumo} m3)",
            "monto": aviso["total_consumo"],
        })
        lineas += [{"concepto": c["descripcion"], "monto": c["monto"]} for c in aviso["cargos"]]
        lineas += [
            {"concepto": f"Cuota {c['num_cuota']}/4 de inscripción", "monto": c["monto"]}
            for c in aviso["cuotas_inscripcion"]
        ]
    return {
        **schemas.FacturaOut.model_validate(factura).model_dump(),
        "modalidad": "SIMULADA - SIN VALIDEZ FISCAL",
        "emisor": {"nit": FACTURA_NIT_EMISOR, "razon_social": FACTURA_RAZON_EMISOR},
        "metodo_pago": pago.metodo_pago.metodo,
        "id_aviso": pago.aviso_id_aviso,
        "codigo_fijo": aviso["socio"]["codigo_fijo"] if aviso else None,
        "periodo": aviso["periodo"] if aviso else None,
        "lineas": lineas,
    }


@router.get("/facturas", response_model=List[schemas.FacturaOut], tags=["Facturación"])
def listar_facturas(
    q: Optional[str] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Facturas emitidas. `q` busca por NIT/CI o razón social."""
    consulta = db.query(models.Factura)
    if q:
        consulta = consulta.filter(
            or_(models.Factura.nit_ci == q, models.Factura.razon_social.ilike(f"%{q}%"))
        )
    if desde:
        consulta = consulta.filter(models.Factura.fecha_emision >= datetime.combine(desde, time.min))
    if hasta:
        consulta = consulta.filter(models.Factura.fecha_emision <= datetime.combine(hasta, time.max))
    return consulta.order_by(models.Factura.numero_factura.desc()).all()


@router.get("/facturas/{id_factura}", tags=["Facturación"])
def ver_factura(id_factura: int, db: Session = Depends(get_db)):
    factura = db.get(models.Factura, id_factura)
    if factura is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return detalle_factura(db, factura)
