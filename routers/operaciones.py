"""Modulo de Operaciones: rutas, lecturas, avisos de cobranza y cargos extra."""
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import (
    actualizar_vencidos,
    ahora,
    aviso_abierto,
    crear_aviso,
    detalle_aviso,
    hoy,
    obtener_estado,
    recalcular_total_aviso,
    registrar_bitacora,
    umbral_consumo,
)
from seguridad import CAJERO, PLOMERO, requiere_rol, usuario_actual

# Todos los endpoints de este modulo exigen token; cada uno indica que roles lo usan
router = APIRouter(prefix="/api/v1", dependencies=[Depends(usuario_actual)])

solo_caja = [Depends(requiere_rol(CAJERO))]
caja_y_campo = [Depends(requiere_rol(CAJERO, PLOMERO))]


# --------------------------------- Rutas ---------------------------------
@router.get("/rutas", response_model=List[schemas.RutaOut], tags=["Rutas"])
def listar_rutas(db: Session = Depends(get_db)):
    return db.query(models.Ruta).order_by(models.Ruta.ruta).all()


@router.post("/rutas", response_model=schemas.RutaOut, status_code=201, tags=["Rutas"])
def registrar_ruta(
    datos: schemas.RutaIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """HU17: registra una ruta de lecturación."""
    if db.query(models.Ruta).filter(models.Ruta.ruta == datos.ruta).first():
        raise HTTPException(status_code=400, detail="Ya existe una ruta con ese número")

    ruta = models.Ruta(**datos.model_dump())
    db.add(ruta)
    registrar_bitacora(db, usuario, f"Registró la ruta {datos.ruta}")
    db.commit()
    db.refresh(ruta)
    return ruta


@router.get("/rutas/{id_ruta}/planilla", tags=["Rutas"], dependencies=caja_y_campo)
def planilla_ruta(id_ruta: int, id_periodo: int, db: Session = Depends(get_db)):
    """HU14/HU17: medidores de la ruta en orden de recorrido, para que el plomero registre
    las lecturas del periodo desde el celular. Indica cuáles ya se leyeron."""
    ruta = db.get(models.Ruta, id_ruta)
    if ruta is None:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    if db.get(models.Periodo, id_periodo) is None:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    socios = (
        db.query(models.Socio)
        .filter(
            models.Socio.ruta_id_ruta == id_ruta,
            models.Socio.estado.is_(True),
            models.Socio.medidor_id_medidor.isnot(None),
        )
        .order_by(models.Socio.ubicacion, models.Socio.num_casa, models.Socio.codigo_fijo)
        .all()
    )
    filas = []
    for socio in socios:
        lecturas = (
            db.query(models.Lectura)
            .filter(models.Lectura.medidor_id_medidor == socio.medidor_id_medidor)
            .order_by(models.Lectura.fecha_lectura.desc(), models.Lectura.id_lectura.desc())
        )
        del_periodo = lecturas.filter(models.Lectura.periodo_id_periodo == id_periodo).first()
        ultima = lecturas.filter(models.Lectura.periodo_id_periodo != id_periodo).first()
        filas.append({
            "id_socio": socio.id_socio,
            "codigo_fijo": socio.codigo_fijo,
            "nombre_socio": socio.nombre_socio,
            "ubicacion": socio.ubicacion,
            "num_casa": socio.num_casa,
            "id_medidor": socio.medidor_id_medidor,
            "serie_medidor": socio.medidor.serie,
            "lectura_anterior": ultima.lectura_actual if ultima else None,
            "leido": del_periodo is not None,
            "id_lectura": del_periodo.id_lectura if del_periodo else None,
            "lectura_actual": del_periodo.lectura_actual if del_periodo else None,
            "consumo_m3": del_periodo.consumo_m3 if del_periodo else None,
        })
    return {"ruta": ruta.ruta, "descripcion": ruta.descripcion, "medidores": filas}


# -------------------------------- Lecturas --------------------------------
@router.get("/lecturas", response_model=List[schemas.LecturaOut], tags=["Lecturas"],
            dependencies=caja_y_campo)
def listar_lecturas(
    id_medidor: Optional[int] = None,
    id_periodo: Optional[int] = None,
    db: Session = Depends(get_db),
):
    consulta = db.query(models.Lectura)
    if id_medidor is not None:
        consulta = consulta.filter(models.Lectura.medidor_id_medidor == id_medidor)
    if id_periodo is not None:
        consulta = consulta.filter(models.Lectura.periodo_id_periodo == id_periodo)
    return consulta.order_by(models.Lectura.id_lectura.desc()).all()


@router.post("/lecturas", response_model=schemas.LecturaOut, status_code=201, tags=["Lecturas"])
def registrar_lectura(
    datos: schemas.LecturaIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO, PLOMERO)),
):
    """HU14: registra la lectura mensual de un medidor.

    La lectura anterior se copia sola de la ultima registrada y el consumo se
    calcula como lectura actual - lectura anterior.
    """
    medidor = db.get(models.Medidor, datos.medidor_id_medidor)
    if medidor is None:
        raise HTTPException(status_code=404, detail="Medidor no encontrado")
    periodo = db.get(models.Periodo, datos.periodo_id_periodo)
    if periodo is None:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    repetida = (
        db.query(models.Lectura)
        .filter(
            models.Lectura.medidor_id_medidor == medidor.id_medidor,
            models.Lectura.periodo_id_periodo == periodo.id_periodo,
        )
        .first()
    )
    if repetida:
        raise HTTPException(
            status_code=400,
            detail=f"El medidor ya tiene una lectura en el periodo {periodo.periodo}",
        )

    fecha = datos.fecha_lectura or hoy()
    ultima = (
        db.query(models.Lectura)
        .filter(models.Lectura.medidor_id_medidor == medidor.id_medidor)
        .order_by(models.Lectura.fecha_lectura.desc(), models.Lectura.id_lectura.desc())
        .first()
    )
    if ultima:
        lectura_anterior = ultima.lectura_actual
        dias = (fecha - ultima.fecha_lectura).days
        if dias < 0:
            raise HTTPException(
                status_code=400,
                detail=f"La fecha no puede ser anterior a la última lectura ({ultima.fecha_lectura})",
            )
    else:
        lectura_anterior = datos.lectura_inicial or 0
        dias = 0

    if datos.lectura_actual < lectura_anterior:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La lectura actual ({datos.lectura_actual}) no puede ser menor "
                f"a la anterior ({lectura_anterior})"
            ),
        )
    consumo = datos.lectura_actual - lectura_anterior

    # Lectura anomala: exige una observacion (regla N-01 del sistema original)
    umbral = umbral_consumo(db, medidor.id_medidor, periodo.id_periodo)
    if consumo >= umbral and not datos.observacion:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Consumo de {consumo} m3 fuera de lo normal (umbral: {umbral} m3). "
                "Revise la lectura o registre una observación."
            ),
        )

    lectura = models.Lectura(
        fecha_lectura=fecha,
        lectura_anterior=lectura_anterior,
        lectura_actual=datos.lectura_actual,
        dias_lectura=dias,
        observacion=datos.observacion,
        usuario_admin_id_usuario_admin=usuario.id_usuario_admin,
        medidor_id_medidor=medidor.id_medidor,
        periodo_id_periodo=periodo.id_periodo,
        consumo_m3=consumo,
    )
    db.add(lectura)
    registrar_bitacora(
        db, usuario, f"Registró la lectura del medidor {medidor.serie} ({periodo.periodo}): {consumo} m3"
    )
    db.commit()
    db.refresh(lectura)
    return lectura


# --------------------------------- Avisos ---------------------------------
def aviso_a_salida(aviso: models.Aviso) -> dict:
    """Arma la respuesta del aviso con los datos legibles de sus tablas relacionadas."""
    return {
        "id_aviso": aviso.id_aviso,
        "periodo": aviso.periodo.periodo,
        "estado": aviso.estado.estado,
        "codigo_fijo": aviso.socio.codigo_fijo,
        "nombre_socio": aviso.socio.nombre_socio,
        "consumo_m3": aviso.lectura.consumo_m3 if aviso.lectura else None,
        "total_consumo": aviso.total_consumo,
        "total_aviso": aviso.total_aviso,
        "fecha_emision": aviso.fecha_emision,
        "fecha_vencimiento": aviso.fecha_vencimiento,
        "socio_id_socio": aviso.socio_id_socio,
        "lectura_id_lectura": aviso.lectura_id_lectura,
    }


def buscar_aviso(db: Session, id_aviso: int) -> models.Aviso:
    aviso = db.get(models.Aviso, id_aviso)
    if aviso is None:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")
    return aviso


@router.get("/avisos", response_model=List[schemas.AvisoOut], tags=["Avisos"],
            dependencies=solo_caja)
def listar_avisos(
    q: Optional[str] = None,
    codigo_fijo: Optional[int] = None,
    id_periodo: Optional[int] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """HU15: consulta avisos al instante. `q` busca por código fijo o nombre del socio;
    también se filtra por periodo y estado (PENDIENTE, PAGADO, VENCIDO, ANULADO)."""
    actualizar_vencidos(db)
    consulta = db.query(models.Aviso).join(models.Socio)
    if q:
        filtros = [models.Socio.nombre_socio.ilike(f"%{q}%")]
        if q.isdigit():
            filtros.append(models.Socio.codigo_fijo == int(q))
        consulta = consulta.filter(or_(*filtros))
    if codigo_fijo is not None:
        consulta = consulta.filter(models.Socio.codigo_fijo == codigo_fijo)
    if id_periodo is not None:
        consulta = consulta.filter(models.Aviso.periodo_id_periodo == id_periodo)
    if estado:
        consulta = consulta.join(models.Estado).filter(models.Estado.estado == estado.upper())
    avisos = consulta.order_by(models.Aviso.id_aviso.desc()).all()
    return [aviso_a_salida(aviso) for aviso in avisos]


@router.get("/avisos/{id_aviso}", response_model=schemas.AvisoOut, tags=["Avisos"],
            dependencies=solo_caja)
def ver_aviso(id_aviso: int, db: Session = Depends(get_db)):
    return aviso_a_salida(buscar_aviso(db, id_aviso))


@router.get("/avisos/{id_aviso}/detalle", tags=["Avisos"], dependencies=solo_caja)
def ver_detalle_aviso(id_aviso: int, db: Session = Depends(get_db)):
    """HU15: aviso completo para imprimir: consumo, tarifa, cargos extra, cuota y total."""
    actualizar_vencidos(db)
    return detalle_aviso(db, buscar_aviso(db, id_aviso))


@router.post("/avisos/generar", response_model=schemas.AvisoOut, status_code=201, tags=["Avisos"])
def generar_aviso(
    datos: schemas.AvisoGenerarIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """HU15: genera el aviso de cobranza a partir de una lectura."""
    lectura = db.get(models.Lectura, datos.lectura_id_lectura)
    if lectura is None:
        raise HTTPException(status_code=404, detail="Lectura no encontrada")

    aviso = crear_aviso(db, lectura, hoy())
    registrar_bitacora(db, usuario, f"Generó el aviso N° {aviso.id_aviso}")
    db.commit()
    db.refresh(aviso)
    return aviso_a_salida(aviso)


@router.post("/avisos/generar-periodo", response_model=schemas.AvisosPeriodoOut, tags=["Avisos"])
def generar_avisos_periodo(
    datos: schemas.AvisosPeriodoIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """HU15: genera de una vez los avisos de todas las lecturas del periodo que no tienen aviso."""
    periodo = db.get(models.Periodo, datos.periodo_id_periodo)
    if periodo is None:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    con_aviso = (
        db.query(models.Aviso.lectura_id_lectura)
        .join(models.Estado)
        .filter(models.Aviso.lectura_id_lectura.isnot(None), models.Estado.estado != "ANULADO")
    )
    lecturas = (
        db.query(models.Lectura)
        .filter(
            models.Lectura.periodo_id_periodo == periodo.id_periodo,
            models.Lectura.id_lectura.notin_(con_aviso),
        )
        .order_by(models.Lectura.id_lectura)
        .all()
    )
    generados, omitidos = 0, []
    for lectura in lecturas:
        try:
            with db.begin_nested():  # si una lectura falla, las demas siguen
                crear_aviso(db, lectura, hoy())
            generados += 1
        except HTTPException as error:
            omitidos.append(f"Medidor {lectura.medidor.serie}: {error.detail}")
    registrar_bitacora(db, usuario, f"Generó {generados} avisos del periodo {periodo.periodo}")
    db.commit()
    return {"generados": generados, "omitidos": omitidos}


@router.post("/avisos/{id_aviso}/anular", response_model=schemas.AvisoOut, tags=["Avisos"])
def anular_aviso(
    id_aviso: int,
    datos: schemas.AnularIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """Anula un aviso que no fue pagado (por ejemplo, una lectura mal tomada).
    Luego se puede volver a generar desde la misma lectura."""
    aviso = buscar_aviso(db, id_aviso)
    if aviso.estado.estado in ("PAGADO", "ANULADO"):
        raise HTTPException(status_code=400, detail=f"El aviso ya está {aviso.estado.estado}")
    aviso.estado_id_estado = obtener_estado(db, "ANULADO").id_estado
    aviso.motivo_anulacion = datos.motivo
    aviso.fecha_anulacion = ahora()
    registrar_bitacora(db, usuario, f"Anuló el aviso N° {aviso.id_aviso}: {datos.motivo}")
    db.commit()
    db.refresh(aviso)
    return aviso_a_salida(aviso)


# ------------------------------ Cargos extra ------------------------------
def cargo_a_salida(cargo: models.CargoExtra) -> dict:
    return {
        "id_cargo_extra": cargo.id_cargo_extra,
        "socio_id_socio": cargo.socio_id_socio,
        "codigo_fijo": cargo.socio.codigo_fijo,
        "nombre_socio": cargo.socio.nombre_socio,
        "tipo": cargo.tipo_cargo.nombre,
        "periodo": cargo.periodo.periodo,
        "descripcion": cargo.descripcion,
        "monto": cargo.monto,
        "estado": cargo.estado,
        "fecha_registro": cargo.fecha_registro,
        "motivo_anulacion": cargo.motivo_anulacion,
    }


@router.get("/cargos-extra", response_model=List[schemas.CargoExtraOut], tags=["Cargos extra"],
            dependencies=solo_caja)
def listar_cargos_extra(
    id_socio: Optional[int] = None,
    id_periodo: Optional[int] = None,
    db: Session = Depends(get_db),
):
    consulta = db.query(models.CargoExtra)
    if id_socio is not None:
        consulta = consulta.filter(models.CargoExtra.socio_id_socio == id_socio)
    if id_periodo is not None:
        consulta = consulta.filter(models.CargoExtra.periodo_id_periodo == id_periodo)
    return [cargo_a_salida(c) for c in consulta.order_by(models.CargoExtra.id_cargo_extra.desc())]


@router.post("/cargos-extra", response_model=schemas.CargoExtraOut, status_code=201,
             tags=["Cargos extra"])
def registrar_cargo_extra(
    datos: schemas.CargoExtraIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """HU16: asigna un cargo extra (multa, reconexión...) a un socio en un periodo.
    Si el aviso de ese periodo ya existe y no está pagado, se suma a su total."""
    socio = db.get(models.Socio, datos.socio_id_socio)
    if socio is None:
        raise HTTPException(status_code=404, detail="Socio no encontrado")
    tipo = db.get(models.TipoCargo, datos.tipo_cargo_id_tipo)
    if tipo is None or not tipo.estado:
        raise HTTPException(status_code=404, detail="Tipo de cargo no encontrado o inactivo")
    periodo = db.get(models.Periodo, datos.periodo_id_periodo)
    if periodo is None:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    pagado = (
        db.query(models.Aviso)
        .join(models.Estado)
        .filter(
            models.Aviso.socio_id_socio == socio.id_socio,
            models.Aviso.periodo_id_periodo == periodo.id_periodo,
            models.Estado.estado == "PAGADO",
        )
        .first()
    )
    if pagado:
        raise HTTPException(
            status_code=400,
            detail=f"El aviso de {periodo.periodo} ya fue pagado; asigne el cargo a otro periodo",
        )

    cargo = models.CargoExtra(
        monto=Decimal(str(datos.monto)) if datos.monto is not None else tipo.monto,
        descripcion=datos.descripcion or tipo.nombre,
        fecha_registro=hoy(),
        estado="PENDIENTE",
        tipo_cargo_id_tipo=tipo.id_tipo,
        socio_id_socio=socio.id_socio,
        periodo_id_periodo=periodo.id_periodo,
    )
    db.add(cargo)
    db.flush()
    aviso = aviso_abierto(db, socio.id_socio, periodo.id_periodo)
    if aviso:
        recalcular_total_aviso(db, aviso)
    registrar_bitacora(
        db, usuario, f"Asignó {tipo.nombre} ({cargo.monto:.2f} Bs) al socio {socio.codigo_fijo}"
    )
    db.commit()
    db.refresh(cargo)
    return cargo_a_salida(cargo)


@router.post("/cargos-extra/{id_cargo}/anular", response_model=schemas.CargoExtraOut,
             tags=["Cargos extra"])
def anular_cargo_extra(
    id_cargo: int,
    datos: schemas.AnularIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """HU16: anula un cargo extra mientras el aviso no esté pagado; se resta del total."""
    cargo = db.get(models.CargoExtra, id_cargo)
    if cargo is None:
        raise HTTPException(status_code=404, detail="Cargo extra no encontrado")
    if cargo.estado != "PENDIENTE":
        raise HTTPException(
            status_code=400, detail=f"El cargo está {cargo.estado} y ya no se puede anular"
        )
    cargo.estado = "ANULADO"
    cargo.motivo_anulacion = datos.motivo
    cargo.fecha_anulacion = ahora()
    db.flush()
    aviso = aviso_abierto(db, cargo.socio_id_socio, cargo.periodo_id_periodo)
    if aviso:
        recalcular_total_aviso(db, aviso)
    registrar_bitacora(db, usuario, f"Anuló el cargo extra N° {cargo.id_cargo_extra}: {datos.motivo}")
    db.commit()
    db.refresh(cargo)
    return cargo_a_salida(cargo)
