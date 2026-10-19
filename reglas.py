"""Reglas de negocio de COSPABI R.L.

En el sistema original viven en procedimientos y funciones de SQL Server;
aqui estan reescritas en Python para que la API las aplique.
"""
import hashlib
import math
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models

# Bolivia esta siempre en UTC-4 (no tiene horario de verano)
ZONA_BOLIVIA = timezone(timedelta(hours=-4))

# Dias de plazo para pagar un aviso desde su emision
DIAS_VENCIMIENTO = 30

# Credito de inscripcion: 1.700 Bs en 4 cuotas mensuales de 425 Bs
MONTO_INSCRIPCION = Decimal("1700")
CUOTAS_INSCRIPCION = 4

# Datos del emisor para la factura simulada (no se envia al SIAT)
FACTURA_NIT_EMISOR = os.getenv("FACTURA_NIT_EMISOR", "0000000000")
FACTURA_RAZON_EMISOR = "COOPERATIVA DE AGUA POTABLE COSPABI R.L."
FACTURA_LEYENDA = (
    "Ley N° 453: Tienes derecho a recibir información sobre las características "
    "y contenidos de los servicios que utilices."
)


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


# ------------------------------- Bitacora -------------------------------
def registrar_bitacora(db: Session, usuario: models.UsuarioAdmin, accion: str) -> None:
    """Agrega una accion a la bitacora. Se guarda junto con el commit del endpoint."""
    db.add(models.Bitacora(
        accion=accion[:255],
        fecha_hora=ahora(),
        usuario_admin_id_usuario_admin=usuario.id_usuario_admin,
    ))


# ------------------------------- Periodos -------------------------------
def texto_periodo(fecha: date) -> str:
    return f"{fecha.month:02d}/{fecha.year}"


def periodo_siguiente(periodo: str, meses: int = 1) -> str:
    """'10/2026' + 3 meses -> '01/2027'."""
    mes, anio = (int(parte) for parte in periodo.split("/"))
    total = anio * 12 + (mes - 1) + meses
    return f"{total % 12 + 1:02d}/{total // 12}"


def obtener_o_crear_periodo(db: Session, periodo: str) -> models.Periodo:
    existente = db.query(models.Periodo).filter(models.Periodo.periodo == periodo).first()
    if existente:
        return existente
    nuevo = models.Periodo(periodo=periodo)
    db.add(nuevo)
    db.flush()
    return nuevo


# ------------------------ Credito de inscripcion ------------------------
def generar_credito_inscripcion(
    db: Session, socio: models.Socio, fecha: date
) -> List[models.CreditoInscripcion]:
    """Divide la inscripcion en 4 cuotas: la del mes de registro y las de los 3 meses siguientes.

    Cada cuota se cobra dentro del aviso de su periodo.
    """
    monto_cuota = (MONTO_INSCRIPCION / CUOTAS_INSCRIPCION).quantize(Decimal("0.01"))
    primer_periodo = texto_periodo(fecha)
    cuotas = []
    for numero in range(1, CUOTAS_INSCRIPCION + 1):
        periodo = obtener_o_crear_periodo(db, periodo_siguiente(primer_periodo, numero - 1))
        cuota = models.CreditoInscripcion(
            monto_pago=monto_cuota,
            estado="PENDIENTE",
            num_cuota=numero,
            socio_id_socio=socio.id_socio,
            periodo_id_periodo=periodo.id_periodo,
        )
        db.add(cuota)
        cuotas.append(cuota)
    return cuotas


# -------------------------------- Avisos --------------------------------
def componentes_aviso(
    db: Session, id_socio: int, id_periodo: int
) -> Tuple[List[models.CargoExtra], List[models.CreditoInscripcion]]:
    """Cargos extra y cuotas de inscripcion pendientes del socio en ese periodo."""
    cargos = (
        db.query(models.CargoExtra)
        .filter(
            models.CargoExtra.socio_id_socio == id_socio,
            models.CargoExtra.periodo_id_periodo == id_periodo,
            models.CargoExtra.estado == "PENDIENTE",
        )
        .order_by(models.CargoExtra.id_cargo_extra)
        .all()
    )
    cuotas = (
        db.query(models.CreditoInscripcion)
        .filter(
            models.CreditoInscripcion.socio_id_socio == id_socio,
            models.CreditoInscripcion.periodo_id_periodo == id_periodo,
            models.CreditoInscripcion.estado == "PENDIENTE",
        )
        .all()
    )
    return cargos, cuotas


def recalcular_total_aviso(db: Session, aviso: models.Aviso) -> None:
    """total_aviso = consumo + cargos extra pendientes + cuota de inscripcion del periodo."""
    cargos, cuotas = componentes_aviso(db, aviso.socio_id_socio, aviso.periodo_id_periodo)
    total = Decimal(aviso.total_consumo)
    total += sum((Decimal(c.monto) for c in cargos), Decimal("0"))
    total += sum((Decimal(c.monto_pago) for c in cuotas), Decimal("0"))
    aviso.total_aviso = total.quantize(Decimal("0.01"))


def aviso_abierto(db: Session, id_socio: int, id_periodo: int) -> Optional[models.Aviso]:
    """Aviso del socio en el periodo que todavia se puede modificar (pendiente o vencido)."""
    return (
        db.query(models.Aviso)
        .join(models.Estado)
        .filter(
            models.Aviso.socio_id_socio == id_socio,
            models.Aviso.periodo_id_periodo == id_periodo,
            models.Estado.estado.in_(["PENDIENTE", "VENCIDO"]),
        )
        .first()
    )


def crear_aviso(db: Session, lectura: models.Lectura, emision: date) -> models.Aviso:
    """Genera el aviso de cobranza de una lectura (sin commit).

    Busca al socio dueño del medidor, aplica la tarifa de su categoría (Socio o
    Usuario), suma los cargos extra y la cuota de inscripción del periodo y deja
    el aviso en estado PENDIENTE.
    """
    # Dos generaciones a la vez de la misma lectura: la segunda espera y ve el aviso ya creado
    bloquear_fila(db, models.Lectura, lectura.id_lectura)
    ya_existe = (
        db.query(models.Aviso)
        .join(models.Estado)
        .filter(
            models.Aviso.lectura_id_lectura == lectura.id_lectura,
            models.Estado.estado != "ANULADO",
        )
        .first()
    )
    if ya_existe:
        raise HTTPException(
            status_code=400, detail=f"Esa lectura ya tiene el aviso N° {ya_existe.id_aviso}"
        )

    socio = (
        db.query(models.Socio)
        .filter(
            models.Socio.medidor_id_medidor == lectura.medidor_id_medidor,
            models.Socio.estado.is_(True),
        )
        .first()
    )
    if socio is None:
        raise HTTPException(
            status_code=400, detail="El medidor de esa lectura no está asignado a un socio activo"
        )

    tarifa = (
        db.query(models.Tarifa)
        .filter(models.Tarifa.rol_socio_id_rol_socio == socio.rol_socio_id_rol_socio)
        .first()
    )
    if tarifa is None:
        raise HTTPException(status_code=400, detail="No hay tarifa para la categoría del socio")

    total_consumo = calcular_total_consumo(tarifa, lectura.consumo_m3)
    aviso = models.Aviso(
        fecha_emision=emision,
        fecha_vencimiento=emision + timedelta(days=DIAS_VENCIMIENTO),
        total_consumo=total_consumo,
        total_aviso=total_consumo,
        periodo_id_periodo=lectura.periodo_id_periodo,
        estado_id_estado=obtener_estado(db, "PENDIENTE").id_estado,
        lectura_id_lectura=lectura.id_lectura,
        socio_id_socio=socio.id_socio,
    )
    db.add(aviso)
    recalcular_total_aviso(db, aviso)
    db.flush()
    return aviso


def actualizar_vencidos(db: Session) -> None:
    """Pasa a VENCIDO los avisos pendientes cuya fecha de vencimiento ya paso."""
    pendiente = obtener_estado(db, "PENDIENTE")
    vencido = obtener_estado(db, "VENCIDO")
    cambiados = (
        db.query(models.Aviso)
        .filter(
            models.Aviso.estado_id_estado == pendiente.id_estado,
            models.Aviso.fecha_vencimiento < hoy(),
        )
        .update({models.Aviso.estado_id_estado: vencido.id_estado}, synchronize_session=False)
    )
    if cambiados:
        db.commit()


# ------------------------- Bloqueo de filas -------------------------
def bloquear_fila(db: Session, modelo, id_fila: int):
    """Lee la fila con SELECT ... FOR UPDATE y la deja bloqueada hasta el commit.

    Si llegan dos pedidos iguales a la vez (doble clic, reintento, dos pestañas), el
    segundo espera a que el primero termine y luego ve el estado ya actualizado, en
    lugar de repetir la operacion (por ejemplo, cobrar dos veces el mismo aviso).
    """
    columna_id = modelo.__mapper__.primary_key[0]
    # Se bloquea solo el id: si se bloqueara junto con las relaciones joined, al
    # esperar a otro pedido PostgreSQL puede devolver esas relaciones vacias
    if db.query(columna_id).filter(columna_id == id_fila).with_for_update().scalar() is None:
        return None
    # Con el bloqueo tomado se lee la fila completa de nuevo, ya con los cambios del otro pedido
    return db.get(modelo, id_fila, populate_existing=True)


# -------------------------------- Cobro --------------------------------
def validar_cobro(db: Session, aviso: models.Aviso) -> None:
    """El aviso debe estar pendiente o vencido y no puede haber uno anterior sin pagar."""
    if aviso.estado.estado in ("PAGADO", "ANULADO"):
        raise HTTPException(
            status_code=400, detail=f"El aviso está {aviso.estado.estado} y no se puede cobrar"
        )

    periodo_bloqueante = aviso_anterior_pendiente(db, aviso)
    if periodo_bloqueante:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El socio tiene un aviso anterior sin pagar del periodo {periodo_bloqueante}. "
                "Se cobra primero la deuda más antigua."
            ),
        )


def aplicar_pago(db: Session, aviso: models.Aviso, pago: models.Pago) -> None:
    """Marca el aviso como pagado junto con sus cargos extra y su cuota de inscripcion."""
    cargos, cuotas = componentes_aviso(db, aviso.socio_id_socio, aviso.periodo_id_periodo)
    for cargo in cargos:
        cargo.estado = "APLICADO"
        cargo.pago_id_pago = pago.id_pago
    for cuota in cuotas:
        cuota.estado = "PAGADA"
        cuota.pago_id_pago = pago.id_pago
    aviso.estado_id_estado = obtener_estado(db, "PAGADO").id_estado


def cobrar_aviso(
    db: Session,
    aviso: models.Aviso,
    metodo: models.MetodoPago,
    cajero: str,
    caja: Optional[models.Caja],
    monto_recibido: Optional[Decimal] = None,
    forma_pago: str = "VENTANILLA",
    id_transaccion: Optional[str] = None,
) -> models.Pago:
    """Registra el pago completo de un aviso (sin commit).

    Reglas: el aviso debe estar pendiente o vencido, no puede haber un aviso
    anterior sin pagar del mismo socio y no hay pagos parciales. Los cargos
    extra y la cuota de inscripcion del aviso quedan pagados con el.
    """
    validar_cobro(db, aviso)

    total = Decimal(aviso.total_aviso)
    vuelto = Decimal("0")
    if metodo.metodo == "Efectivo":
        if monto_recibido is None:
            raise HTTPException(
                status_code=400, detail="Para pagos en efectivo indique el monto recibido"
            )
        if monto_recibido < total:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"El monto recibido ({monto_recibido:.2f} Bs) no cubre el total "
                    f"del aviso ({total:.2f} Bs)"
                ),
            )
        vuelto = monto_recibido - total

    pago = models.Pago(
        fecha_pago=ahora(),
        monto_pagado=total,
        cajero=cajero,
        aviso_id_aviso=aviso.id_aviso,
        metodo_pago_id_metodo_pago=metodo.id_metodo_pago,
        vuelto=vuelto,
        caja_id_caja=caja.id_caja if caja else None,
        identificador_deuda=f"AVISO-{aviso.id_aviso}",
        id_transaccion=id_transaccion,
        forma_pago=forma_pago,
        estado_pago="APROBADO",
    )
    db.add(pago)
    db.flush()
    aplicar_pago(db, aviso, pago)
    return pago


def pago_del_aviso(db: Session, id_aviso: int) -> Optional[models.Pago]:
    return (
        db.query(models.Pago)
        .filter(models.Pago.aviso_id_aviso == id_aviso, models.Pago.estado_pago == "APROBADO")
        .order_by(models.Pago.id_pago.desc())
        .first()
    )


def detalle_aviso(db: Session, aviso: models.Aviso) -> dict:
    """Aviso completo para mostrar o imprimir: consumo, tarifa, cargos, cuota y pago."""
    socio = aviso.socio
    tarifa = (
        db.query(models.Tarifa)
        .filter(models.Tarifa.rol_socio_id_rol_socio == socio.rol_socio_id_rol_socio)
        .first()
    )
    cargos = (
        db.query(models.CargoExtra)
        .filter(
            models.CargoExtra.socio_id_socio == socio.id_socio,
            models.CargoExtra.periodo_id_periodo == aviso.periodo_id_periodo,
            models.CargoExtra.estado != "ANULADO",
        )
        .order_by(models.CargoExtra.id_cargo_extra)
        .all()
    )
    cuotas = (
        db.query(models.CreditoInscripcion)
        .filter(
            models.CreditoInscripcion.socio_id_socio == socio.id_socio,
            models.CreditoInscripcion.periodo_id_periodo == aviso.periodo_id_periodo,
        )
        .all()
    )
    pago = pago_del_aviso(db, aviso.id_aviso)
    lectura = aviso.lectura
    return {
        "id_aviso": aviso.id_aviso,
        "periodo": aviso.periodo.periodo,
        "estado": aviso.estado.estado,
        "fecha_emision": aviso.fecha_emision,
        "fecha_vencimiento": aviso.fecha_vencimiento,
        "motivo_anulacion": aviso.motivo_anulacion,
        "socio": {
            "id_socio": socio.id_socio,
            "codigo_fijo": socio.codigo_fijo,
            "nombre_socio": socio.nombre_socio,
            "categoria": socio.rol_socio.rol_socio,
            "ruta": socio.ruta.ruta,
            "ubicacion": socio.ubicacion,
            "num_casa": socio.num_casa,
        },
        "lectura": {
            "fecha_lectura": lectura.fecha_lectura,
            "lectura_anterior": lectura.lectura_anterior,
            "lectura_actual": lectura.lectura_actual,
            "consumo_m3": lectura.consumo_m3,
        } if lectura else None,
        "tarifa": {
            "consumo_minimo_m3": tarifa.consumo_minimo_m3,
            "monto_minimo": tarifa.monto_minimo,
            "precio_m3": tarifa.precio_m3,
        } if tarifa else None,
        "total_consumo": aviso.total_consumo,
        "cargos": [
            {
                "id_cargo_extra": cargo.id_cargo_extra,
                "tipo": cargo.tipo_cargo.nombre,
                "descripcion": cargo.descripcion,
                "monto": cargo.monto,
                "estado": cargo.estado,
            }
            for cargo in cargos
        ],
        "cuotas_inscripcion": [
            {"num_cuota": cuota.num_cuota, "monto": cuota.monto_pago, "estado": cuota.estado}
            for cuota in cuotas
        ],
        "total_aviso": aviso.total_aviso,
        "pago": {
            "id_pago": pago.id_pago,
            "fecha_pago": pago.fecha_pago,
            "metodo": pago.metodo_pago.metodo,
            "monto_pagado": pago.monto_pagado,
            "forma_pago": pago.forma_pago,
            "id_factura": pago.id_factura,
            "factura_url": pago.factura_url,
        } if pago else None,
    }


# ----------------------------- Facturacion -----------------------------
def emitir_factura(
    db: Session,
    pago: models.Pago,
    nit_ci: str,
    razon_social: str,
    id_usuario: Optional[int],
) -> models.Factura:
    """Emite la factura simulada de un pago (sin commit).

    El CUF y el codigo de control se generan con un hash de los datos de la
    factura; tienen el formato de una factura real pero no se validan en el SIAT.
    """
    numero = (db.query(func.coalesce(func.max(models.Factura.numero_factura), 0)).scalar()) + 1
    fecha = ahora()
    semilla = f"{FACTURA_NIT_EMISOR}|{numero}|{nit_ci}|{pago.monto_pagado}|{fecha.isoformat()}"
    huella = hashlib.sha256(semilla.encode("utf-8")).hexdigest().upper()
    factura = models.Factura(
        numero_factura=numero,
        fecha_emision=fecha,
        nit_ci=nit_ci.strip(),
        razon_social=razon_social.strip().upper(),
        monto_total=pago.monto_pagado,
        cuf=huella[:48],
        codigo_control="-".join(huella[i:i + 2] for i in range(48, 58, 2)),
        leyenda=FACTURA_LEYENDA,
        estado="VIGENTE",
        pago_id_pago=pago.id_pago,
        usuario_admin_id_usuario_admin=id_usuario,
    )
    db.add(factura)
    return factura
