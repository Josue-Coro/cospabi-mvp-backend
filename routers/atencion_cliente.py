"""Modulo Atencion al Cliente: personas, socios, credito de inscripcion, cuentas del portal y pagos."""
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from pagos_qr import ID_METODO_QR, confirmar_pago_qr, crear_pago_qr, pago_qr_a_salida
from reglas import cobrar_aviso, emitir_factura, generar_credito_inscripcion, hoy, registrar_bitacora
from routers.administracion import buscar_caja_abierta
from seguridad import CAJERO, cifrar_contrasena, requiere_rol, usuario_actual

# Todo este modulo es para el Administrador y el Cajero
router = APIRouter(prefix="/api/v1", dependencies=[Depends(requiere_rol(CAJERO))])


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
def registrar_persona(
    datos: schemas.PersonaIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """HU10: registra una persona. No se permite repetir el CI."""
    if db.query(models.Persona).filter(models.Persona.ci == datos.ci).first():
        raise HTTPException(status_code=400, detail="Ya existe una persona con ese CI")

    persona = models.Persona(**datos.model_dump(), fecha_registro=hoy(), estado=True)
    db.add(persona)
    registrar_bitacora(db, usuario, f"Registró a la persona {datos.nombre_completo} (CI {datos.ci})")
    db.commit()
    db.refresh(persona)
    return persona


@router.get("/personas/{id_persona}", response_model=schemas.PersonaOut, tags=["Personas"])
def ver_persona(id_persona: int, db: Session = Depends(get_db)):
    return buscar_persona(db, id_persona)


@router.put("/personas/{id_persona}", response_model=schemas.PersonaOut, tags=["Personas"])
def editar_persona(
    id_persona: int,
    datos: schemas.PersonaUpdate,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """Actualiza solo los campos que se envian."""
    persona = buscar_persona(db, id_persona)
    for campo, valor in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(persona, campo, valor)
    registrar_bitacora(db, usuario, f"Editó a la persona {persona.nombre_completo}")
    db.commit()
    db.refresh(persona)
    return persona


@router.delete("/personas/{id_persona}", response_model=schemas.PersonaOut, tags=["Personas"])
def dar_baja_persona(
    id_persona: int,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
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
    registrar_bitacora(db, usuario, f"Dio de baja a la persona {persona.nombre_completo}")
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
def listar_socios(
    q: Optional[str] = None, id_ruta: Optional[int] = None, db: Session = Depends(get_db)
):
    """HU11: lista los socios. Con `q` busca por código fijo, nombre o CI; con `id_ruta` filtra la ruta."""
    consulta = db.query(models.Socio).join(models.Persona)
    if q:
        filtros = [models.Socio.nombre_socio.ilike(f"%{q}%"), models.Persona.ci == q]
        if q.isdigit():
            filtros.append(models.Socio.codigo_fijo == int(q))
        consulta = consulta.filter(or_(*filtros))
    if id_ruta is not None:
        consulta = consulta.filter(models.Socio.ruta_id_ruta == id_ruta)
    return consulta.order_by(models.Socio.id_socio).all()


@router.post("/socios", response_model=schemas.SocioOut, status_code=201, tags=["Socios"])
def registrar_socio(
    datos: schemas.SocioIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """HU11 y HU12: registra la conexión de agua de una persona.

    Si la categoría es Socio, genera el crédito de inscripción: 4 cuotas de
    425 Bs que se cobran en los avisos de este mes y de los 3 siguientes.
    """
    persona = buscar_persona(db, datos.persona_id_persona)
    if not persona.estado:
        raise HTTPException(status_code=400, detail="La persona está dada de baja")

    if db.query(models.Socio).filter(models.Socio.codigo_fijo == datos.codigo_fijo).first():
        raise HTTPException(status_code=400, detail="Ya existe un socio con ese código fijo")

    valores = datos.model_dump(exclude={"generar_credito"})
    validar_referencias_socio(db, valores)
    if not valores["nombre_socio"]:
        valores["nombre_socio"] = persona.nombre_completo

    socio = models.Socio(**valores, fecha_registro=hoy(), estado=True)
    db.add(socio)
    db.flush()
    if datos.generar_credito and socio.rol_socio_id_rol_socio == 1:
        generar_credito_inscripcion(db, socio, hoy())
    registrar_bitacora(db, usuario, f"Registró al socio {socio.codigo_fijo} - {socio.nombre_socio}")
    db.commit()
    db.refresh(socio)
    return socio


@router.get("/socios/{id_socio}", response_model=schemas.SocioOut, tags=["Socios"])
def ver_socio(id_socio: int, db: Session = Depends(get_db)):
    return buscar_socio(db, id_socio)


@router.put("/socios/{id_socio}", response_model=schemas.SocioOut, tags=["Socios"])
def editar_socio(
    id_socio: int,
    datos: schemas.SocioUpdate,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """Actualiza solo los campos que se envian (también reasigna ruta o medidor)."""
    socio = buscar_socio(db, id_socio)
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    validar_referencias_socio(db, cambios, id_socio=id_socio)
    for campo, valor in cambios.items():
        setattr(socio, campo, valor)
    registrar_bitacora(db, usuario, f"Editó al socio {socio.codigo_fijo}")
    db.commit()
    db.refresh(socio)
    return socio


@router.post("/socios/{id_socio}/baja", response_model=schemas.SocioOut, tags=["Socios"])
def dar_baja_socio(
    id_socio: int,
    datos: schemas.SocioBajaIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """Baja logica del socio: guarda la fecha y el motivo."""
    socio = buscar_socio(db, id_socio)
    if not socio.estado:
        raise HTTPException(status_code=400, detail="El socio ya está dado de baja")
    socio.estado = False
    socio.fecha_baja = hoy()
    socio.motivo_baja = datos.motivo_baja
    registrar_bitacora(db, usuario, f"Dio de baja al socio {socio.codigo_fijo}: {datos.motivo_baja}")
    db.commit()
    db.refresh(socio)
    return socio


# ------------------------ Credito de inscripcion ------------------------
@router.get("/socios/{id_socio}/credito", response_model=List[schemas.CuotaOut],
            tags=["Crédito de inscripción"])
def ver_credito_socio(id_socio: int, db: Session = Depends(get_db)):
    """HU12: las 4 cuotas del crédito de inscripción del socio y su estado."""
    buscar_socio(db, id_socio)
    cuotas = (
        db.query(models.CreditoInscripcion)
        .filter(models.CreditoInscripcion.socio_id_socio == id_socio)
        .order_by(models.CreditoInscripcion.num_cuota)
        .all()
    )
    return [
        {
            "id_credito": c.id_credito,
            "num_cuota": c.num_cuota,
            "monto_pago": c.monto_pago,
            "estado": c.estado,
            "periodo": c.periodo.periodo,
            "pago_id_pago": c.pago_id_pago,
        }
        for c in cuotas
    ]


@router.post("/socios/{id_socio}/credito", response_model=List[schemas.CuotaOut],
             status_code=201, tags=["Crédito de inscripción"])
def generar_credito_socio(
    id_socio: int,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """Genera el crédito de inscripción de un socio que no lo tiene (desde el mes actual)."""
    socio = buscar_socio(db, id_socio)
    if socio.rol_socio_id_rol_socio != 1:
        raise HTTPException(status_code=400, detail="Solo los socios pagan inscripción, no los usuarios")
    existe = (
        db.query(models.CreditoInscripcion)
        .filter(models.CreditoInscripcion.socio_id_socio == id_socio)
        .first()
    )
    if existe:
        raise HTTPException(status_code=400, detail="El socio ya tiene su crédito de inscripción")
    generar_credito_inscripcion(db, socio, hoy())
    registrar_bitacora(db, usuario, f"Generó el crédito de inscripción del socio {socio.codigo_fijo}")
    db.commit()
    return ver_credito_socio(id_socio, db)


# ------------------------- Cuenta del portal -------------------------
def buscar_cuenta(db: Session, id_socio: int) -> Optional[models.CuentaSocio]:
    return (
        db.query(models.CuentaSocio).filter(models.CuentaSocio.socio_id_socio == id_socio).first()
    )


@router.get("/socios/{id_socio}/cuenta", response_model=schemas.CuentaSocioOut,
            tags=["Cuenta del portal"])
def ver_cuenta_socio(id_socio: int, db: Session = Depends(get_db)):
    cuenta = buscar_cuenta(db, id_socio)
    if cuenta is None:
        raise HTTPException(status_code=404, detail="El socio todavía no tiene cuenta en el portal")
    return cuenta


@router.post("/socios/{id_socio}/cuenta", response_model=schemas.CuentaSocioOut,
             tags=["Cuenta del portal"])
def crear_cuenta_socio(
    id_socio: int,
    datos: schemas.CuentaSocioIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """HU18: crea la cuenta del portal (usuario = código fijo) o restablece su contraseña."""
    socio = buscar_socio(db, id_socio)
    cuenta = buscar_cuenta(db, id_socio)
    if cuenta is None:
        cuenta = models.CuentaSocio(
            usuario=str(socio.codigo_fijo),
            contrasena=cifrar_contrasena(datos.contrasena),
            estado=True,
            socio_id_socio=socio.id_socio,
        )
        db.add(cuenta)
        accion = f"Creó la cuenta del portal del socio {socio.codigo_fijo}"
    else:
        cuenta.contrasena = cifrar_contrasena(datos.contrasena)
        cuenta.intentos_fallidos = 0
        accion = f"Restableció la contraseña del portal del socio {socio.codigo_fijo}"
    registrar_bitacora(db, usuario, accion)
    db.commit()
    db.refresh(cuenta)
    return cuenta


@router.put("/socios/{id_socio}/cuenta", response_model=schemas.CuentaSocioOut,
            tags=["Cuenta del portal"])
def cambiar_estado_cuenta_socio(
    id_socio: int,
    datos: schemas.CuentaSocioEstadoIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """HU18: habilita o bloquea el acceso del socio al portal."""
    cuenta = ver_cuenta_socio(id_socio, db)
    cuenta.estado = datos.estado
    registrar_bitacora(
        db, usuario, f"{'Habilitó' if datos.estado else 'Bloqueó'} la cuenta del portal {cuenta.usuario}"
    )
    db.commit()
    db.refresh(cuenta)
    return cuenta


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
    """HU13: cobra un aviso completo en ventanilla y, si el socio la pide, emite la factura.

    Reglas: requiere una caja abierta, el aviso debe estar pendiente o vencido, no
    puede haber un aviso anterior sin pagar del mismo socio y no hay pagos
    parciales. El pago, el cambio de estado del aviso, sus cargos, su cuota de
    inscripción y la factura se guardan en una sola transacción.
    """
    aviso = db.get(models.Aviso, datos.aviso_id_aviso)
    if aviso is None:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")

    caja = buscar_caja_abierta(db, usuario.id_usuario_admin)
    if caja is None:
        raise HTTPException(status_code=400, detail="Debe abrir una caja antes de cobrar")

    metodo = db.get(models.MetodoPago, datos.metodo_pago_id_metodo_pago)
    if metodo is None:
        raise HTTPException(status_code=404, detail="Método de pago no encontrado")

    if datos.con_factura and not (datos.nit_ci and datos.razon_social):
        raise HTTPException(status_code=400, detail="Para emitir factura indique NIT/CI y razón social")

    try:
        pago = cobrar_aviso(
            db,
            aviso,
            metodo,
            cajero=f"{usuario.nombre} {usuario.apellido}",
            caja=caja,
            monto_recibido=(
                Decimal(str(datos.monto_recibido)) if datos.monto_recibido is not None else None
            ),
        )
        accion = f"Cobró el aviso N° {aviso.id_aviso} ({pago.monto_pagado:.2f} Bs, {metodo.metodo})"
        if datos.con_factura:
            factura = emitir_factura(
                db, pago, datos.nit_ci, datos.razon_social, usuario.id_usuario_admin
            )
            accion += f" con factura N° {factura.numero_factura}"
        registrar_bitacora(db, usuario, accion)
        db.commit()  # confirma todo junto
        db.refresh(pago)
        return pago
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la transacción: {error}")


@router.post("/pagos/qr", response_model=schemas.PagoQrOut, tags=["Pagos"])
def generar_cobro_qr(
    datos: schemas.CobroQrIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(usuario_actual),
):
    """Cobro con QR en ventanilla: genera el QR de Libélula para que el socio lo escanee.

    El pago queda PENDIENTE en la caja abierta del cajero y se registra solo cuando
    Libélula lo confirma. Si el socio pide factura, la emite Libélula.
    """
    aviso = db.get(models.Aviso, datos.aviso_id_aviso)
    if aviso is None:
        raise HTTPException(status_code=404, detail="Aviso no encontrado")
    caja = buscar_caja_abierta(db, usuario.id_usuario_admin)
    if caja is None:
        raise HTTPException(status_code=400, detail="Debe abrir una caja antes de cobrar")

    pago = crear_pago_qr(
        db, aviso, datos, cajero=f"{usuario.nombre} {usuario.apellido}", caja=caja, forma_pago="VENTANILLA",
    )
    registrar_bitacora(
        db, usuario, f"Generó el QR de cobro del aviso N° {aviso.id_aviso} ({pago.monto_pagado:.2f} Bs)"
    )
    db.commit()
    return pago_qr_a_salida(pago)


@router.get("/pagos/qr/{id_pago}", response_model=schemas.PagoQrOut, tags=["Pagos"])
def ver_cobro_qr(id_pago: int, db: Session = Depends(get_db)):
    """Estado del cobro con QR; si sigue pendiente, se consulta a Libélula en ese momento."""
    pago = db.get(models.Pago, id_pago)
    if pago is None or pago.metodo_pago_id_metodo_pago != ID_METODO_QR:
        raise HTTPException(status_code=404, detail="Cobro con QR no encontrado")
    return pago_qr_a_salida(confirmar_pago_qr(db, id_pago))
