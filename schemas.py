"""Esquemas Pydantic: validan lo que entra a la API y dan forma a lo que sale."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Valores permitidos (los mismos CHECK del script SQL)
Genero = Literal["Masculino", "Femenino", "Otro"]
Categoria = Literal["Social", "Industrial", "Comercial", "Doméstico"]
TipoInstalacion = Literal["Tubería negra", "Polipropileno", "CPVC", "PVC"]
DimInstalacion = Literal["1 pulgada", "3/4 pulgada", "1/2 pulgada"]


class Salida(BaseModel):
    """Base de los esquemas de salida: permite leer objetos SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)


# =========================== ADMINISTRACION ===========================
class LoginIn(BaseModel):
    usuario: str
    contrasena: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: str
    rol: str


class UsuarioOut(BaseModel):
    id_usuario_admin: int
    nombre: str
    apellido: str
    usuario: str
    rol: str


class CajaAbrirIn(BaseModel):
    monto_apertura: float = Field(0, ge=0, description="Efectivo inicial en Bs")


class CajaCerrarIn(BaseModel):
    monto_contado: float = Field(..., ge=0, description="Efectivo contado al cierre en Bs")
    observacion_cierre: Optional[str] = Field(
        None, max_length=255, description="Obligatoria si el arqueo no cuadra"
    )


class CajaOut(Salida):
    id_caja: int
    fecha: date
    hora_apertura: datetime
    hora_cierre: Optional[datetime]
    estado: bool
    monto_apertura: float
    monto_cobrado: Optional[float]
    monto_contado: Optional[float]
    diferencia_arqueo: Optional[float]
    observacion_cierre: Optional[str]
    usuario_admin_id_usuario_admin: int


# =========================== CONFIGURACION ===========================
class RolSocioOut(Salida):
    id_rol_socio: int
    rol_socio: str


class EstadoOut(Salida):
    id_estado: int
    estado: str


class MetodoPagoOut(Salida):
    id_metodo_pago: int
    metodo: str
    referencia: Optional[str]


class TarifaUpdate(BaseModel):
    consumo_minimo_m3: int = Field(..., ge=0)
    monto_minimo: float = Field(..., ge=0)
    precio_m3: int = Field(..., ge=0)


class TarifaOut(Salida):
    id_tarifa: int
    consumo_minimo_m3: Optional[int]
    monto_minimo: float
    precio_m3: int
    rol_socio_id_rol_socio: int


class MedidorIn(BaseModel):
    serie: str = Field(..., min_length=1, max_length=150)
    numero: int = Field(..., gt=0)
    fecha_instalacion: Optional[date] = None


class MedidorOut(Salida):
    id_medidor: int
    serie: str
    numero: int
    fecha_instalacion: Optional[date]


class PeriodoIn(BaseModel):
    periodo: str = Field(
        ..., pattern=r"^(0[1-9]|1[0-2])/\d{4}$", description="Formato MM/yyyy", examples=["10/2026"]
    )
    costo_inscripcion: Optional[float] = Field(None, ge=0)


class PeriodoOut(Salida):
    id_periodo: int
    periodo: str
    costo_inscripcion: Optional[float]


# ======================== ATENCION AL CLIENTE ========================
class PersonaIn(BaseModel):
    nombre_completo: str = Field(..., min_length=3, max_length=250)
    ci: str = Field(..., pattern=r"^[0-9]{4,10}$", description="Solo numeros, de 4 a 10 digitos")
    fecha_nacimiento: date
    genero: Optional[Genero] = None
    telefono: Optional[int] = Field(None, ge=10000000, le=99999999)


class PersonaUpdate(BaseModel):
    nombre_completo: Optional[str] = Field(None, min_length=3, max_length=250)
    fecha_nacimiento: Optional[date] = None
    genero: Optional[Genero] = None
    telefono: Optional[int] = Field(None, ge=10000000, le=99999999)


class PersonaOut(Salida):
    id_persona: int
    nombre_completo: str
    ci: str
    fecha_nacimiento: date
    fecha_registro: date
    genero: Optional[str]
    telefono: Optional[int]
    estado: bool


class SocioIn(BaseModel):
    persona_id_persona: int
    rol_socio_id_rol_socio: int = Field(..., description="1 = Socio, 2 = Usuario")
    ruta_id_ruta: int
    codigo_fijo: int = Field(..., gt=0)
    actividad: str = Field(..., min_length=1, max_length=255, examples=["Vivienda"])
    categoria: Categoria
    correo: str = Field(..., min_length=3, max_length=150)
    nombre_socio: Optional[str] = Field(
        None, max_length=255, description="Si se omite se usa el nombre de la persona"
    )
    medidor_id_medidor: Optional[int] = None
    ubicacion: Optional[int] = Field(None, ge=0)
    num_casa: Optional[int] = Field(None, ge=0)
    num_ocupantes: Optional[int] = Field(None, ge=0, le=50)
    tipo_instalacion: Optional[TipoInstalacion] = None
    dim_instalacion: Optional[DimInstalacion] = None


class SocioUpdate(BaseModel):
    nombre_socio: Optional[str] = Field(None, min_length=1, max_length=255)
    rol_socio_id_rol_socio: Optional[int] = None
    ruta_id_ruta: Optional[int] = None
    medidor_id_medidor: Optional[int] = None
    actividad: Optional[str] = Field(None, min_length=1, max_length=255)
    categoria: Optional[Categoria] = None
    correo: Optional[str] = Field(None, min_length=3, max_length=150)
    ubicacion: Optional[int] = Field(None, ge=0)
    num_casa: Optional[int] = Field(None, ge=0)
    num_ocupantes: Optional[int] = Field(None, ge=0, le=50)
    tipo_instalacion: Optional[TipoInstalacion] = None
    dim_instalacion: Optional[DimInstalacion] = None


class SocioBajaIn(BaseModel):
    motivo_baja: str = Field(..., min_length=3, max_length=255)


class SocioOut(Salida):
    id_socio: int
    codigo_fijo: int
    nombre_socio: str
    persona_id_persona: int
    rol_socio_id_rol_socio: int
    ruta_id_ruta: int
    medidor_id_medidor: Optional[int]
    actividad: str
    categoria: str
    correo: str
    ubicacion: Optional[int]
    num_casa: Optional[int]
    num_ocupantes: Optional[int]
    tipo_instalacion: Optional[str]
    dim_instalacion: Optional[str]
    fecha_registro: date
    estado: bool
    fecha_baja: Optional[date]
    motivo_baja: Optional[str]


class PagoIn(BaseModel):
    aviso_id_aviso: int
    metodo_pago_id_metodo_pago: int = Field(..., description="1 = Efectivo, 2 = QR, 3 = Transferencia")
    monto_recibido: Optional[float] = Field(
        None, ge=0, description="Solo para efectivo: lo que entrega el socio"
    )


class PagoOut(Salida):
    id_pago: int
    fecha_pago: datetime
    monto_pagado: float
    vuelto: Optional[float]
    cajero: str
    estado_pago: str
    aviso_id_aviso: Optional[int]
    metodo_pago_id_metodo_pago: int
    caja_id_caja: Optional[int]


# ============================ OPERACIONES ============================
class RutaIn(BaseModel):
    ruta: int = Field(..., gt=0)
    descripcion: Optional[str] = Field(None, max_length=150)


class RutaOut(Salida):
    id_ruta: int
    ruta: int
    descripcion: Optional[str]


class LecturaIn(BaseModel):
    medidor_id_medidor: int
    periodo_id_periodo: int
    lectura_actual: int = Field(..., ge=0, description="Valor que marca hoy el medidor")
    fecha_lectura: Optional[date] = Field(None, description="Si se omite se usa la fecha de hoy")
    observacion: Optional[str] = Field(None, max_length=255)
    lectura_inicial: Optional[int] = Field(
        None, ge=0, description="Solo para la primera lectura de un medidor que no empieza en 0"
    )


class LecturaOut(Salida):
    id_lectura: int
    fecha_lectura: date
    lectura_anterior: int
    lectura_actual: int
    consumo_m3: float
    dias_lectura: int
    observacion: Optional[str]
    medidor_id_medidor: int
    periodo_id_periodo: int
    usuario_admin_id_usuario_admin: int


class AvisoGenerarIn(BaseModel):
    lectura_id_lectura: int


class AvisoOut(BaseModel):
    id_aviso: int
    periodo: str
    estado: str
    codigo_fijo: int
    nombre_socio: str
    consumo_m3: Optional[float]
    total_consumo: float
    total_aviso: float
    fecha_emision: date
    fecha_vencimiento: date
    socio_id_socio: int
    lectura_id_lectura: Optional[int]
