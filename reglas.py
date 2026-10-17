"""Reglas de negocio de COSPABI R.L.

En el sistema original viven en procedimientos y funciones de SQL Server;
aqui estan reescritas en Python para que la API las aplique.
"""
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models

# Bolivia esta siempre en UTC-4 (no tiene horario de verano)
ZONA_BOLIVIA = timezone(timedelta(hours=-4))

# Dias de plazo para pagar un aviso desde su emision
DIAS_VENCIMIENTO = 30


def ahora() -> datetime:
    """Fecha y hora actual de Bolivia, tomada del servidor."""
    return datetime.now(ZONA_BOLIVIA).replace(tzinfo=None)


def hoy() -> date:
    return ahora().date()


def obtener_estado(db: Session, nombre: str) -> models.Estado:
    """Busca un estado del catalogo por su nombre (PENDIENTE, PAGADO, ...)."""
    estado = db.query(models.Estado).filter(models.Estado.estado == nombre).first()
    if estado is None:
        raise HTTPException(status_code=500, detail=f"Falta el estado '{nombre}' en el catálogo")
    return estado


def clave_periodo(periodo: str) -> int:
    """Convierte 'MM/yyyy' en el numero yyyyMM para poder comparar periodos."""
    mes, anio = periodo.split("/")
    return int(anio) * 100 + int(mes)


def calcular_total_consumo(tarifa: models.Tarifa, consumo_m3: Decimal) -> Decimal:
    """Importe del agua segun la tarifa.

    Si el consumo no supera el minimo se cobra el monto minimo; si lo supera,
    se suma el precio por cada m3 adicional.
    Ej. socio (minimo 6 m3 = 15 Bs, 2 Bs por m3): 10 m3 -> 15 + (10 - 6) * 2 = 23 Bs
    """
    consumo = Decimal(consumo_m3)
    minimo_m3 = Decimal(tarifa.consumo_minimo_m3 or 0)
    total = Decimal(tarifa.monto_minimo)
    if consumo > minimo_m3:
        total += (consumo - minimo_m3) * Decimal(tarifa.precio_m3)
    return total.quantize(Decimal("0.01"))


def umbral_consumo(db: Session, id_medidor: int, id_periodo: int) -> int:
    """Consumo en m3 a partir del cual una lectura es anomala (fn_umbral_consumo).

    Es el triple del promedio de las ultimas 3 lecturas del medidor, con piso
    de 30 m3 y tope de 100 m3. Sin historial, el umbral es 100 m3.
    """
    ultimas = (
        db.query(models.Lectura.consumo_m3)
        .filter(
            models.Lectura.medidor_id_medidor == id_medidor,
            models.Lectura.periodo_id_periodo != id_periodo,
        )
        .order_by(models.Lectura.fecha_lectura.desc(), models.Lectura.id_lectura.desc())
        .limit(3)
        .all()
    )
    if not ultimas:
        return 100
    promedio = sum(Decimal(fila.consumo_m3) for fila in ultimas) / len(ultimas)
    triple = promedio * 3
    if triple < 30:
        return 30
    if triple > 100:
        return 100
    return math.floor(triple)


def aviso_anterior_pendiente(db: Session, aviso: models.Aviso) -> Optional[str]:
    """Periodo mas antiguo sin pagar del mismo socio (fn_aviso_anterior_pendiente).

    Los avisos se cobran del mas antiguo al mas reciente. Devuelve el periodo
    que bloquea el cobro, o None si el aviso se puede cobrar.
    """
    otros = (
        db.query(models.Aviso)
        .join(models.Estado, models.Estado.id_estado == models.Aviso.estado_id_estado)
        .filter(
            models.Aviso.socio_id_socio == aviso.socio_id_socio,
            models.Aviso.id_aviso != aviso.id_aviso,
            models.Estado.estado.notin_(["PAGADO", "ANULADO"]),
        )
        .all()
    )
    clave_actual = clave_periodo(aviso.periodo.periodo)
    anteriores = [
        otro.periodo.periodo
        for otro in otros
        if clave_periodo(otro.periodo.periodo) < clave_actual
    ]
    if not anteriores:
        return None
    return min(anteriores, key=clave_periodo)
