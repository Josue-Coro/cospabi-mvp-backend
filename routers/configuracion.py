"""Modulo de Configuracion: tarifas, tipos de cargo, medidores, periodos y catalogos."""
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from reglas import registrar_bitacora
from seguridad import CAJERO, requiere_rol, usuario_actual

# Todos los endpoints de este modulo exigen token; escribir depende del rol
router = APIRouter(prefix="/api/v1", dependencies=[Depends(usuario_actual)])


# ------------------------------ Catalogos ------------------------------
@router.get("/roles-socio", response_model=List[schemas.RolSocioOut], tags=["Catálogos"])
def listar_roles_socio(db: Session = Depends(get_db)):
    return db.query(models.RolSocio).order_by(models.RolSocio.id_rol_socio).all()


@router.get("/estados", response_model=List[schemas.EstadoOut], tags=["Catálogos"])
def listar_estados(db: Session = Depends(get_db)):
    return db.query(models.Estado).order_by(models.Estado.id_estado).all()


@router.get("/metodos-pago", response_model=List[schemas.MetodoPagoOut], tags=["Catálogos"])
def listar_metodos_pago(db: Session = Depends(get_db)):
    return db.query(models.MetodoPago).order_by(models.MetodoPago.id_metodo_pago).all()


# ------------------------------- Tarifas -------------------------------
@router.get("/tarifas", response_model=List[schemas.TarifaOut], tags=["Tarifas"])
def listar_tarifas(db: Session = Depends(get_db)):
    return db.query(models.Tarifa).order_by(models.Tarifa.id_tarifa).all()


@router.put("/tarifas/{id_tarifa}", response_model=schemas.TarifaOut, tags=["Tarifas"])
def editar_tarifa(
    id_tarifa: int,
    datos: schemas.TarifaUpdate,
    db: Session = Depends(get_db),
    admin: models.UsuarioAdmin = Depends(requiere_rol()),
):
    """HU7: cambia el minimo y el precio por m3 de una categoria (solo Administrador)."""
    tarifa = db.get(models.Tarifa, id_tarifa)
    if tarifa is None:
        raise HTTPException(status_code=404, detail="Tarifa no encontrada")

    tarifa.consumo_minimo_m3 = datos.consumo_minimo_m3
    tarifa.monto_minimo = Decimal(str(datos.monto_minimo))
    tarifa.precio_m3 = datos.precio_m3
    registrar_bitacora(
        db, admin, f"Editó la tarifa {tarifa.rol_socio.rol_socio}: mínimo {datos.monto_minimo:.2f} Bs"
                   f" hasta {datos.consumo_minimo_m3} m3, {datos.precio_m3} Bs por m3 adicional"
    )
    db.commit()
    db.refresh(tarifa)
    return tarifa


# ---------------------------- Tipos de cargo ----------------------------
@router.get("/tipos-cargo", response_model=List[schemas.TipoCargoOut], tags=["Tipos de cargo"])
def listar_tipos_cargo(solo_activos: bool = False, db: Session = Depends(get_db)):
    consulta = db.query(models.TipoCargo)
    if solo_activos:
        consulta = consulta.filter(models.TipoCargo.estado.is_(True))
    return consulta.order_by(models.TipoCargo.id_tipo).all()


@router.post("/tipos-cargo", response_model=schemas.TipoCargoOut, status_code=201,
             tags=["Tipos de cargo"])
def registrar_tipo_cargo(
    datos: schemas.TipoCargoIn,
    db: Session = Depends(get_db),
    admin: models.UsuarioAdmin = Depends(requiere_rol()),
):
    """HU8: registra un concepto de cobro adicional (multa, reconexion, ...)."""
    if db.query(models.TipoCargo).filter(models.TipoCargo.nombre == datos.nombre).first():
        raise HTTPException(status_code=400, detail="Ya existe un tipo de cargo con ese nombre")
    tipo = models.TipoCargo(
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        monto=Decimal(str(datos.monto)),
        estado=True,
    )
    db.add(tipo)
    registrar_bitacora(db, admin, f"Registró el tipo de cargo {datos.nombre}")
    db.commit()
    db.refresh(tipo)
    return tipo


@router.put("/tipos-cargo/{id_tipo}", response_model=schemas.TipoCargoOut,
            tags=["Tipos de cargo"])
def editar_tipo_cargo(
    id_tipo: int,
    datos: schemas.TipoCargoUpdate,
    db: Session = Depends(get_db),
    admin: models.UsuarioAdmin = Depends(requiere_rol()),
):
    """HU8: edita o desactiva un tipo de cargo. No se borra porque puede estar en avisos."""
    tipo = db.get(models.TipoCargo, id_tipo)
    if tipo is None:
        raise HTTPException(status_code=404, detail="Tipo de cargo no encontrado")
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    if "monto" in cambios:
        cambios["monto"] = Decimal(str(cambios["monto"]))
    for campo, valor in cambios.items():
        setattr(tipo, campo, valor)
    registrar_bitacora(db, admin, f"Editó el tipo de cargo {tipo.nombre}")
    db.commit()
    db.refresh(tipo)
    return tipo


# ------------------------------ Medidores ------------------------------
@router.get("/medidores", response_model=List[schemas.MedidorOut], tags=["Medidores"])
def listar_medidores(db: Session = Depends(get_db)):
    return db.query(models.Medidor).order_by(models.Medidor.id_medidor).all()


@router.post("/medidores", response_model=schemas.MedidorOut, status_code=201, tags=["Medidores"])
def registrar_medidor(
    datos: schemas.MedidorIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """HU9: registra un medidor. No se permite repetir el numero de serie."""
    if db.query(models.Medidor).filter(models.Medidor.serie == datos.serie).first():
        raise HTTPException(status_code=400, detail="Ya existe un medidor con esa serie")

    medidor = models.Medidor(**datos.model_dump())
    db.add(medidor)
    registrar_bitacora(db, usuario, f"Registró el medidor {datos.serie}")
    db.commit()
    db.refresh(medidor)
    return medidor


# ------------------------------- Periodos -------------------------------
@router.get("/periodos", response_model=List[schemas.PeriodoOut], tags=["Periodos"])
def listar_periodos(db: Session = Depends(get_db)):
    return db.query(models.Periodo).order_by(models.Periodo.id_periodo).all()


@router.post("/periodos", response_model=schemas.PeriodoOut, status_code=201, tags=["Periodos"])
def registrar_periodo(
    datos: schemas.PeriodoIn,
    db: Session = Depends(get_db),
    usuario: models.UsuarioAdmin = Depends(requiere_rol(CAJERO)),
):
    """Crea el mes de facturacion en formato MM/yyyy."""
    if db.query(models.Periodo).filter(models.Periodo.periodo == datos.periodo).first():
        raise HTTPException(status_code=400, detail="Ese periodo ya existe")

    periodo = models.Periodo(
        periodo=datos.periodo,
        costo_inscripcion=(
            Decimal(str(datos.costo_inscripcion)) if datos.costo_inscripcion is not None else None
        ),
    )
    db.add(periodo)
    registrar_bitacora(db, usuario, f"Registró el periodo {datos.periodo}")
    db.commit()
    db.refresh(periodo)
    return periodo
