"""Modulo Atencion al Cliente: personas, socios y pagos."""
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import ahora, aviso_anterior_pendiente, hoy, obtener_estado
from routers.administracion import buscar_caja_abierta
from seguridad import usuario_actual

# Todos los endpoints de este modulo exigen token
router = APIRouter(prefix="/api/v1", dependencies=[Depends(usuario_actual)])


# ------------------------------- Personas -------------------------------
def buscar_persona(db: Session, id_persona: int) -> models.Persona:
    persona = db.get(models.Persona, id_persona)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    return persona


@router.get("/personas", response_model=List[schemas.PersonaOut], tags=["Personas"])
def listar_personas(q: Optional[str] = None, db: Session = Depends(get_db)):
    """HU10: lista las personas. Con `q` busca por nombre o por CI."""
    consulta = db.query(models.Persona)
    if q:
        consulta = consulta.filter(
            or_(models.Persona.nombre_completo.ilike(f"%{q}%"), models.Persona.ci == q)
        )
    return consulta.order_by(models.Persona.id_persona).all()


@router.post("/personas", response_model=schemas.PersonaOut, status_code=201, tags=["Personas"])
def registrar_persona(datos: schemas.PersonaIn, db: Session = Depends(get_db)):
    """HU10: registra una persona. No se permite repetir el CI."""
    if db.query(models.Persona).filter(models.Persona.ci == datos.ci).first():
        raise HTTPException(status_code=400, detail="Ya existe una persona con ese CI")

    persona = models.Persona(**datos.model_dump(), fecha_registro=hoy(), estado=True)
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona


@router.get("/personas/{id_persona}", response_model=schemas.PersonaOut, tags=["Personas"])
def ver_persona(id_persona: int, db: Session = Depends(get_db)):
    return buscar_persona(db, id_persona)


@router.put("/personas/{id_persona}", response_model=schemas.PersonaOut, tags=["Personas"])
def editar_persona(id_persona: int, datos: schemas.PersonaUpdate, db: Session = Depends(get_db)):
    """Actualiza solo los campos que se envian."""
    persona = buscar_persona(db, id_persona)
    for campo, valor in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(persona, campo, valor)
    db.commit()
    db.refresh(persona)
    return persona


@router.delete("/personas/{id_persona}", response_model=schemas.PersonaOut, tags=["Personas"])
def dar_baja_persona(id_persona: int, db: Session = Depends(get_db)):
    """Baja logica: la persona no se borra, solo se desactiva."""
    persona = buscar_persona(db, id_persona)
    socios_activos = (
        db.query(models.Socio)
        .filter(models.Socio.persona_id_persona == id_persona, models.Socio.estado.is_(True))
        .count()
    )
    if socios_activos:
        raise HTTPException(
            status_code=400, detail="La persona tiene socios activos; delos de baja primero"
        )
    persona.estado = False
    db.commit()
    db.refresh(persona)
    return persona


# -------------------------------- Socios --------------------------------
def buscar_socio(db: Session, id_socio: int) -> models.Socio:
    socio = db.get(models.Socio, id_socio)
    if socio is None:
        raise HTTPException(status_code=404, detail="Socio no encontrado")
    return socio


def validar_referencias_socio(db: Session, datos: dict, id_socio: Optional[int] = None) -> None:
    """Revisa que la categoria, la ruta y el medidor existan y esten disponibles."""
    id_rol_socio = datos.get("rol_socio_id_rol_socio")
    if id_rol_socio is not None and db.get(models.RolSocio, id_rol_socio) is None:
        raise HTTPException(status_code=404, detail="Rol de socio no encontrado (1 = Socio, 2 = Usuario)")

    id_ruta = datos.get("ruta_id_ruta")
    if id_ruta is not None and db.get(models.Ruta, id_ruta) is None:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")

    id_medidor = datos.get("medidor_id_medidor")
    if id_medidor is not None:
        if db.get(models.Medidor, id_medidor) is None:
            raise HTTPException(status_code=404, detail="Medidor no encontrado")
        ocupado = db.query(models.Socio).filter(
            models.Socio.medidor_id_medidor == id_medidor, models.Socio.estado.is_(True)
        )
        if id_socio is not None:
            ocupado = ocupado.filter(models.Socio.id_socio != id_socio)
        if ocupado.first():
            raise HTTPException(
                status_code=400, detail="Ese medidor ya está asignado a otro socio activo"
            )


@router.get("/socios", response_model=List[schemas.SocioOut], tags=["Socios"])
def listar_socios(q: Optional[str] = None, db: Session = Depends(get_db)):
    """HU11: lista los socios. Con `q` busca por código fijo, nombre o CI."""
    consulta = db.query(models.Socio).join(models.Persona)
    if q:
        filtros = [models.Socio.nombre_socio.ilike(f"%{q}%"), models.Persona.ci == q]
        if q.isdigit():
            filtros.append(models.Socio.codigo_fijo == int(q))
        consulta = consulta.filter(or_(*filtros))
    return consulta.order_by(models.Socio.id_socio).all()


@router.post("/socios", response_model=schemas.SocioOut, status_code=201, tags=["Socios"])
def registrar_socio(datos: schemas.SocioIn, db: Session = Depends(get_db)):
    """HU11: registra la conexión de agua de una persona."""
    persona = buscar_persona(db, datos.persona_id_persona)
    if not persona.estado:
        raise HTTPException(status_code=400, detail="La persona está dada de baja")

    if db.query(models.Socio).filter(models.Socio.codigo_fijo == datos.codigo_fijo).first():
        raise HTTPException(status_code=400, detail="Ya existe un socio con ese código fijo")

    valores = datos.model_dump()
    validar_referencias_socio(db, valores)
    if not valores["nombre_socio"]:
        valores["nombre_socio"] = persona.nombre_completo

    socio = models.Socio(**valores, fecha_registro=hoy(), estado=True)
    db.add(socio)
    db.commit()
    db.refresh(socio)
    return socio


@router.get("/socios/{id_socio}", response_model=schemas.SocioOut, tags=["Socios"])
def ver_socio(id_socio: int, db: Session = Depends(get_db)):
    return buscar_socio(db, id_socio)


@router.put("/socios/{id_socio}", response_model=schemas.SocioOut, tags=["Socios"])
def editar_socio(id_socio: int, datos: schemas.SocioUpdate, db: Session = Depends(get_db)):
    """Actualiza solo los campos que se envian."""
    socio = buscar_socio(db, id_socio)
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    validar_referencias_socio(db, cambios, id_socio=id_socio)
    for campo, valor in cambios.items():
        setattr(socio, campo, valor)
    db.commit()
    db.refresh(socio)
    return socio


@router.post("/socios/{id_socio}/baja", response_model=schemas.SocioOut, tags=["Socios"])
def dar_baja_socio(id_socio: int, datos: schemas.SocioBajaIn, db: Session = Depends(get_db)):
    """Baja logica del socio: guarda la fecha y el motivo."""
    socio = buscar_socio(db, id_socio)
    if not socio.estado:
        raise HTTPException(status_code=400, detail="El socio ya está dado de baja")
    socio.estado = False
    socio.fecha_baja = hoy()
    socio.motivo_baja = datos.motivo_baja
    db.commit()
    db.refresh(socio)
    return socio


# --------------------------------- Pagos ---------------------------------
@router.get("/pagos", response_model=List[schemas.PagoOut], tags=["Pagos"])
def listar_pagos(id_aviso: Optional[int] = None, db: Session = Depends(get_db)):
    consulta = db.query(models.Pago)
    if id_aviso is not None:
        consulta = consulta.filter(models.Pago.aviso_id_aviso == id_aviso)
    return consulta.order_by(models.Pago.id_pago.desc()).all()


@router.post("/pagos", response_model=schemas.PagoOut, status_code=201, tags=["Pagos"])
def registrar_pago(
    datos: schemas.PagoIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """HU13: cobra un aviso completo.

    Reglas: requiere una caja abierta, el aviso debe estar pendiente, no puede
    haber un aviso anterior sin pagar del mismo socio y no hay pagos parciales.
    El pago y el cambio de estado del aviso se guardan en una sola transaccion.
    """
    aviso = db.get(models.Aviso, datos.aviso_id_aviso)
    if aviso is None:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")
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

    caja = buscar_caja_abierta(db, usuario.id_usuario_admin)
    if caja is None:
        raise HTTPException(status_code=400, detail="Debe abrir una caja antes de cobrar")

    metodo = db.get(models.MetodoPago, datos.metodo_pago_id_metodo_pago)
    if metodo is None:
        raise HTTPException(status_code=404, detail="Método de pago no encontrado")

    total = Decimal(aviso.total_aviso)
    vuelto = Decimal("0")
    if metodo.metodo == "Efectivo":
        if datos.monto_recibido is None:
            raise HTTPException(
                status_code=400, detail="Para pagos en efectivo indique el monto recibido"
            )
        recibido = Decimal(str(datos.monto_recibido))
        if recibido < total:
            raise HTTPException(
                status_code=400,
                detail=f"El monto recibido ({recibido:.2f} Bs) no cubre el total del aviso ({total:.2f} Bs)",
            )
        vuelto = recibido - total

    try:
        pago = models.Pago(
            fecha_pago=ahora(),
            monto_pagado=total,
            cajero=f"{usuario.nombre} {usuario.apellido}",
            aviso_id_aviso=aviso.id_aviso,
            metodo_pago_id_metodo_pago=metodo.id_metodo_pago,
            vuelto=vuelto,
            caja_id_caja=caja.id_caja,
            estado_pago="APROBADO",
        )
        db.add(pago)
        aviso.estado_id_estado = obtener_estado(db, "PAGADO").id_estado
        db.commit()  # confirma el pago y el cambio de estado juntos
        db.refresh(pago)
        return pago
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la transacción: {error}")
