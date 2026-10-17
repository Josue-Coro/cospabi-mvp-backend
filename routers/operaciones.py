"""Modulo de Operaciones: rutas, lecturas y avisos de cobranza."""
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import (
    DIAS_VENCIMIENTO,
    calcular_total_consumo,
    hoy,
    obtener_estado,
    umbral_consumo,
)
from seguridad import usuario_actual

# Todos los endpoints de este modulo exigen token
router = APIRouter(prefix="/api/v1", dependencies=[Depends(usuario_actual)])


# --------------------------------- Rutas ---------------------------------
@router.get("/rutas", response_model=List[schemas.RutaOut], tags=["Rutas"])
def listar_rutas(db: Session = Depends(get_db)):
    return db.query(models.Ruta).order_by(models.Ruta.ruta).all()


@router.post("/rutas", response_model=schemas.RutaOut, status_code=201, tags=["Rutas"])
def registrar_ruta(datos: schemas.RutaIn, db: Session = Depends(get_db)):
    """HU17: registra una ruta de lecturación."""
    if db.query(models.Ruta).filter(models.Ruta.ruta == datos.ruta).first():
        raise HTTPException(status_code=400, detail="Ya existe una ruta con ese número")

    ruta = models.Ruta(**datos.model_dump())
    db.add(ruta)
    db.commit()
    db.refresh(ruta)
    return ruta


# -------------------------------- Lecturas --------------------------------
@router.get("/lecturas", response_model=List[schemas.LecturaOut], tags=["Lecturas"])
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
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
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


@router.get("/avisos", response_model=List[schemas.AvisoOut], tags=["Avisos"])
def listar_avisos(
    codigo_fijo: Optional[int] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """HU15: consulta avisos. Se puede filtrar por código fijo del socio y por estado."""
    consulta = db.query(models.Aviso)
    if codigo_fijo is not None:
        consulta = consulta.join(models.Socio).filter(models.Socio.codigo_fijo == codigo_fijo)
    if estado:
        consulta = consulta.join(models.Estado).filter(models.Estado.estado == estado.upper())
    avisos = consulta.order_by(models.Aviso.id_aviso.desc()).all()
    return [aviso_a_salida(aviso) for aviso in avisos]


@router.get("/avisos/{id_aviso}", response_model=schemas.AvisoOut, tags=["Avisos"])
def ver_aviso(id_aviso: int, db: Session = Depends(get_db)):
    aviso = db.get(models.Aviso, id_aviso)
    if aviso is None:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")
    return aviso_a_salida(aviso)


@router.post("/avisos/generar", response_model=schemas.AvisoOut, status_code=201, tags=["Avisos"])
def generar_aviso(datos: schemas.AvisoGenerarIn, db: Session = Depends(get_db)):
    """HU15: genera el aviso de cobranza a partir de una lectura.

    Busca al socio dueño del medidor, aplica la tarifa de su categoría
    (Socio o Usuario) y deja el aviso en estado PENDIENTE.
    """
    lectura = db.get(models.Lectura, datos.lectura_id_lectura)
    if lectura is None:
        raise HTTPException(status_code=404, detail="Lectura no encontrada")

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
    emision = hoy()
    aviso = models.Aviso(
        fecha_emision=emision,
        fecha_vencimiento=emision + timedelta(days=DIAS_VENCIMIENTO),
        total_consumo=total_consumo,
        total_aviso=total_consumo,  # en esta etapa el aviso solo cobra el consumo
        periodo_id_periodo=lectura.periodo_id_periodo,
        estado_id_estado=obtener_estado(db, "PENDIENTE").id_estado,
        lectura_id_lectura=lectura.id_lectura,
        socio_id_socio=socio.id_socio,
    )
    db.add(aviso)
    db.commit()
    db.refresh(aviso)
    return aviso_a_salida(aviso)
