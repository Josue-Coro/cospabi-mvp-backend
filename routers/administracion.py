"""Modulo de Administracion: inicio de sesion, usuarios, roles, caja y bitacora."""
from datetime import date, datetime, time
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import ahora, hoy, registrar_bitacora
from seguridad import (
    CAJERO,
    MAX_INTENTOS,
    MINUTOS_BLOQUEO,
    cifrar_contrasena,
    crear_token,
    desbloquear,
    registrar_intento_fallido,
    requiere_rol,
    revisar_bloqueo,
    usuario_actual,
    verificar_contrasena,
)

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
    revisar_bloqueo(usuario)

    if not verificar_contrasena(datos.contrasena, usuario.contrasena):
        if registrar_intento_fallido(usuario):
            registrar_bitacora(
                db, usuario, f"Cuenta bloqueada {MINUTOS_BLOQUEO} min por {MAX_INTENTOS} intentos fallidos"
            )
        db.commit()
        revisar_bloqueo(usuario)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    if not usuario.estado:
        raise HTTPException(status_code=403, detail="Usuario desactivado")

    desbloquear(usuario)
    registrar_bitacora(db, usuario, "Inició sesión")
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


# ------------------------------- Usuarios -------------------------------
def buscar_usuario(db: Session, id_usuario: int) -> models.UsuarioAdmin:
    usuario = db.get(models.UsuarioAdmin, id_usuario)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario


def validar_rol(db: Session, id_rol: int) -> None:
    if db.get(models.Rol, id_rol) is None:
        raise HTTPException(status_code=404, detail="Rol no encontrado")


@router.get("/roles", response_model=List[schemas.RolOut], tags=["Usuarios"],
            dependencies=[Depends(requiere_rol())])
def listar_roles(db: Session = Depends(get_db)):
    """HU3: perfiles de acceso del sistema (Administrador, Cajero, Plomero)."""
    return db.query(models.Rol).order_by(models.Rol.id_rol).all()


@router.get("/usuarios", response_model=List[schemas.UsuarioDetalleOut], tags=["Usuarios"],
            dependencies=[Depends(requiere_rol())])
def listar_usuarios(q: Optional[str] = None, db: Session = Depends(get_db)):
    """HU2: lista el personal. Con `q` busca por nombre, apellido o usuario."""
    consulta = db.query(models.UsuarioAdmin)
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(
            models.UsuarioAdmin.nombre.ilike(patron)
            | models.UsuarioAdmin.apellido.ilike(patron)
            | models.UsuarioAdmin.usuario.ilike(patron)
        )
    return consulta.order_by(models.UsuarioAdmin.id_usuario_admin).all()


@router.post("/usuarios", response_model=schemas.UsuarioDetalleOut, status_code=201,
             tags=["Usuarios"])
def registrar_usuario(
    datos: schemas.UsuarioIn,
    db: Session = Depends(get_db),
    admin: models.UsuarioAdmin = Depends(requiere_rol()),
):
    """HU2: registra un usuario del personal. No se permite repetir el nombre de usuario."""
    if db.query(models.UsuarioAdmin).filter(models.UsuarioAdmin.usuario == datos.usuario).first():
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese nombre de usuario")
    validar_rol(db, datos.rol_id_rol)

    usuario = models.UsuarioAdmin(
        nombre=datos.nombre,
        apellido=datos.apellido,
        usuario=datos.usuario,
        contrasena=cifrar_contrasena(datos.contrasena),
        correo=datos.correo,
        rol_id_rol=datos.rol_id_rol,
        estado=True,
        fecha_creacion=hoy(),
    )
    db.add(usuario)
    db.flush()
    registrar_bitacora(db, admin, f"Registró al usuario {usuario.usuario}")
    db.commit()
    db.refresh(usuario)
    return usuario


@router.put("/usuarios/{id_usuario}", response_model=schemas.UsuarioDetalleOut,
            tags=["Usuarios"])
def editar_usuario(
    id_usuario: int,
    datos: schemas.UsuarioUpdate,
    db: Session = Depends(get_db),
    admin: models.UsuarioAdmin = Depends(requiere_rol()),
):
    """HU2/HU3: edita datos, cambia el rol o da de baja (estado = false) sin borrar."""
    usuario = buscar_usuario(db, id_usuario)
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    if "rol_id_rol" in cambios:
        validar_rol(db, cambios["rol_id_rol"])
    if cambios.get("estado") is False and usuario.id_usuario_admin == admin.id_usuario_admin:
        raise HTTPException(status_code=400, detail="No puede darse de baja a sí mismo")

    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)
    registrar_bitacora(db, admin, f"Editó al usuario {usuario.usuario}")
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/usuarios/{id_usuario}/clave", response_model=schemas.UsuarioDetalleOut,
             tags=["Usuarios"])
def cambiar_clave_usuario(
    id_usuario: int,
    datos: schemas.ClaveIn,
    db: Session = Depends(get_db),
    admin: models.UsuarioAdmin = Depends(requiere_rol()),
):
    """Restablece la contraseña de un usuario del personal (y lo desbloquea si estaba bloqueado)."""
    usuario = buscar_usuario(db, id_usuario)
    usuario.contrasena = cifrar_contrasena(datos.contrasena)
    desbloquear(usuario)
    registrar_bitacora(db, admin, f"Restableció la contraseña de {usuario.usuario}")
    db.commit()
    db.refresh(usuario)
    return usuario


# ------------------------------- Bitacora -------------------------------
@router.get("/bitacora", response_model=List[schemas.BitacoraOut], tags=["Bitácora"],
            dependencies=[Depends(requiere_rol())])
def ver_bitacora(
    id_usuario: Optional[int] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """HU6: historial de acciones; se filtra por usuario y fechas. Es de solo lectura."""
    consulta = db.query(models.Bitacora).join(models.UsuarioAdmin)
    if id_usuario is not None:
        consulta = consulta.filter(models.Bitacora.usuario_admin_id_usuario_admin == id_usuario)
    if desde:
        consulta = consulta.filter(models.Bitacora.fecha_hora >= datetime.combine(desde, time.min))
    if hasta:
        consulta = consulta.filter(models.Bitacora.fecha_hora <= datetime.combine(hasta, time.max))
    registros = consulta.order_by(models.Bitacora.id_bitacora.desc()).limit(500).all()
    return [
        {
            "id_bitacora": r.id_bitacora,
            "fecha_hora": r.fecha_hora,
            "usuario": r.usuario_admin.usuario,
            "accion": r.accion,
        }
        for r in registros
    ]


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
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
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
    registrar_bitacora(db, usuario, f"Abrió caja con {datos.monto_apertura:.2f} Bs")
    db.commit()
    db.refresh(caja)
    return caja


@router.get("/caja/actual", response_model=schemas.CajaOut, tags=["Caja"])
def ver_caja_actual(
    db: Session = Depends(get_db), usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO))
):
    caja = buscar_caja_abierta(db, usuario.id_usuario_admin)
    if caja is None:
        raise HTTPException(status_code=404, detail="No tiene una caja abierta")
    return caja


@router.post("/caja/cerrar", response_model=schemas.CajaOut, tags=["Caja"])
def cerrar_caja(
    datos: schemas.CajaCerrarIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
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
    registrar_bitacora(
        db, usuario, f"Cerró caja N° {caja.id_caja}: cobrado {caja.monto_cobrado:.2f} Bs, "
                     f"diferencia {diferencia:.2f} Bs"
    )
    db.commit()
    db.refresh(caja)
    return caja


@router.get(
    "/cajas",
    response_model=List[schemas.CajaOut],
    tags=["Caja"],
    dependencies=[Depends(requiere_rol(CAJERO))],
)
def listar_cajas(db: Session = Depends(get_db)):
    return db.query(models.Caja).order_by(models.Caja.id_caja.desc()).all()

