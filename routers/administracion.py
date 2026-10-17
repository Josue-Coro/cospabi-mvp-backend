"""Modulo de Administracion: inicio de sesion y caja."""
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import ahora, hoy
from seguridad import crear_token, usuario_actual, verificar_contrasena

router = APIRouter(prefix="/api/v1")


# ------------------------------ Seguridad ------------------------------
@router.post("/auth/login", response_model=schemas.TokenOut, tags=["Seguridad"])
def iniciar_sesion(datos: schemas.LoginIn, db: Session = Depends(get_db)):
    """HU1: valida usuario y contrasena y devuelve un token JWT."""
    usuario = (
        db.query(models.UsuarioAdmin).filter(models.UsuarioAdmin.usuario == datos.usuario).first()
    )
    if usuario is None:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    if not verificar_contrasena(datos.contrasena, usuario.contrasena):
        usuario.intentos_fallidos += 1
        db.commit()
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    if not usuario.estado:
        raise HTTPException(status_code=403, detail="Usuario desactivado")

    usuario.intentos_fallidos = 0
    db.commit()
    return {
        "access_token": crear_token(usuario),
        "token_type": "bearer",
        "usuario": usuario.usuario,
        "rol": usuario.rol.nombre,
    }


@router.get("/auth/yo", response_model=schemas.UsuarioOut, tags=["Seguridad"])
def ver_mi_usuario(usuario: models.UsuarioAdmin = Depends(usuario_actual)):
    """Muestra a que usuario pertenece el token."""
    return {
        "id_usuario_admin": usuario.id_usuario_admin,
        "nombre": usuario.nombre,
        "apellido": usuario.apellido,
        "usuario": usuario.usuario,
        "rol": usuario.rol.nombre,
    }


# -------------------------------- Caja --------------------------------
def buscar_caja_abierta(db: Session, id_usuario: int):
    return (
        db.query(models.Caja)
        .filter(
            models.Caja.usuario_admin_id_usuario_admin == id_usuario,
            models.Caja.estado.is_(True),
        )
        .first()
    )


@router.post("/caja/abrir", response_model=schemas.CajaOut, status_code=201, tags=["Caja"])
def abrir_caja(
    datos: schemas.CajaAbrirIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """HU5: abre la caja del usuario. La fecha y la hora se toman del servidor."""
    if buscar_caja_abierta(db, usuario.id_usuario_admin):
        raise HTTPException(status_code=400, detail="Ya tiene una caja abierta")

    caja = models.Caja(
        fecha=hoy(),
        hora_apertura=ahora(),
        usuario_admin_id_usuario_admin=usuario.id_usuario_admin,
        estado=True,
        monto_apertura=Decimal(str(datos.monto_apertura)),
    )
    db.add(caja)
    db.commit()
    db.refresh(caja)
    return caja


@router.get("/caja/actual", response_model=schemas.CajaOut, tags=["Caja"])
def ver_caja_actual(
    db: Session = Depends(get_db), usuario: models.UsuarioAdmin = Depends(usuario_actual)
):
    caja = buscar_caja_abierta(db, usuario.id_usuario_admin)
    if caja is None:
        raise HTTPException(status_code=404, detail="No tiene una caja abierta")
    return caja


@router.post("/caja/cerrar", response_model=schemas.CajaOut, tags=["Caja"])
def cerrar_caja(
    datos: schemas.CajaCerrarIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """HU5: cierra la caja con arqueo.

    Compara el efectivo contado con el esperado (monto de apertura + cobros en
    efectivo). Si no cuadra, exige una observacion.
    """
    caja = buscar_caja_abierta(db, usuario.id_usuario_admin)
    if caja is None:
        raise HTTPException(status_code=400, detail="No tiene una caja abierta")

    def total_cobrado(solo_efectivo: bool) -> Decimal:
        consulta = (
            db.query(func.coalesce(func.sum(models.Pago.monto_pagado), 0))
            .join(models.MetodoPago)
            .filter(models.Pago.caja_id_caja == caja.id_caja, models.Pago.estado_pago == "APROBADO")
        )
        if solo_efectivo:
            consulta = consulta.filter(models.MetodoPago.metodo == "Efectivo")
        return Decimal(consulta.scalar())

    contado = Decimal(str(datos.monto_contado))
    esperado = Decimal(caja.monto_apertura) + total_cobrado(solo_efectivo=True)
    diferencia = contado - esperado

    if diferencia != 0 and not datos.observacion_cierre:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El arqueo no cuadra: se esperaban {esperado:.2f} Bs en efectivo y se contaron "
                f"{contado:.2f} Bs. Registre una observación de cierre."
            ),
        )

    caja.monto_cobrado = total_cobrado(solo_efectivo=False)
    caja.monto_contado = contado
    caja.diferencia_arqueo = diferencia
    caja.observacion_cierre = datos.observacion_cierre
    caja.hora_cierre = ahora()
    caja.estado = False
    db.commit()
    db.refresh(caja)
    return caja


@router.get(
    "/cajas",
    response_model=List[schemas.CajaOut],
    tags=["Caja"],
    dependencies=[Depends(usuario_actual)],
)
def listar_cajas(db: Session = Depends(get_db)):
    return db.query(models.Caja).order_by(models.Caja.id_caja.desc()).all()
