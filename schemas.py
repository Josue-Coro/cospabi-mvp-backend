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


class RolOut(Salida):
    id_rol: int
    nombre: str
    descripcion: Optional[str]
    estado: bool


class UsuarioIn(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=255)
    apellido: str = Field(..., min_length=2, max_length=255)
    usuario: str = Field(..., pattern=r"^[a-zA-Z0-9_.]{3,50}$", description="Sin espacios")
    contrasena: str = Field(..., min_length=6, max_length=100)
    rol_id_rol: int = Field(..., description="1 = Administrador, 2 = Cajero, 3 = Plomero")
    correo: Optional[str] = Field(None, max_length=150)


class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=255)
    apellido: Optional[str] = Field(None, min_length=2, max_length=255)
    rol_id_rol: Optional[int] = None
    correo: Optional[str] = Field(None, max_length=150)
    estado: Optional[bool] = Field(None, description="False = dar de baja (sin borrar)")


class ClaveIn(BaseModel):
    contrasena: str = Field(..., min_length=6, max_length=100)


class UsuarioDetalleOut(Salida):
    id_usuario_admin: int
    nombre: str
    apellido: str
    usuario: str
    correo: Optional[str]
    estado: bool
    fecha_creacion: date
    rol_id_rol: int
    rol: RolOut


class BitacoraOut(BaseModel):
    id_bitacora: int
    fecha_hora: datetime
    usuario: str
    accion: str


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


class TipoCargoIn(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=150, examples=["Multa por atraso"])
    descripcion: Optional[str] = Field(None, max_length=255)
    monto: float = Field(..., ge=0, description="Monto por defecto en Bs")


class TipoCargoUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=3, max_length=150)
    descripcion: Optional[str] = Field(None, max_length=255)
    monto: Optional[float] = Field(None, ge=0)
    estado: Optional[bool] = Field(None, description="False = desactivar")


class TipoCargoOut(Salida):
    id_tipo: int
    nombre: str
    descripcion: Optional[str]
    monto: float
    estado: bool


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
    generar_credito: bool = Field(
        True, description="Solo para socios: genera las 4 cuotas del crédito de inscripción"
    )


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


class CuotaOut(Salida):
    id_credito: int
    num_cuota: int
    monto_pago: float
    estado: str
    periodo: str
    pago_id_pago: Optional[int]


class CuentaSocioIn(BaseModel):
    contrasena: str = Field(..., min_length=6, max_length=100, description="Contraseña temporal")


class CuentaSocioEstadoIn(BaseModel):
    estado: bool = Field(..., description="True = habilitada, False = bloqueada")


class CuentaSocioOut(Salida):
    id_cuenta_socio: int
    usuario: str
    estado: bool
    ultimo_acceso: Optional[datetime]
    socio_id_socio: int


class DatosFactura(BaseModel):
    """Datos que se piden cuando el socio quiere factura."""

    con_factura: bool = Field(False, description="¿Desea factura?")
    nit_ci: Optional[str] = Field(None, pattern=r"^[0-9A-Za-z-]{3,20}$", description="NIT o CI")
    razon_social: Optional[str] = Field(None, min_length=2, max_length=255)


class PagoIn(DatosFactura):
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
    forma_pago: Optional[str]
    aviso_id_aviso: Optional[int]
    metodo_pago_id_metodo_pago: int
    caja_id_caja: Optional[int]
    id_factura: Optional[int]
    factura_url: Optional[str]


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


class AvisosPeriodoIn(BaseModel):
    periodo_id_periodo: int


class AvisosPeriodoOut(BaseModel):
    generados: int
    omitidos: list[str] = Field(description="Lecturas sin aviso y el motivo")


class AnularIn(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=255)


class CargoExtraIn(BaseModel):
    socio_id_socio: int
    tipo_cargo_id_tipo: int
    periodo_id_periodo: int
    monto: Optional[float] = Field(None, gt=0, description="Si se omite se usa el monto del tipo")
    descripcion: Optional[str] = Field(
        None, max_length=150, description="Si se omite se usa el nombre del tipo"
    )


class CargoExtraOut(BaseModel):
    id_cargo_extra: int
    socio_id_socio: int
    codigo_fijo: int
    nombre_socio: str
    tipo: str
    periodo: str
    descripcion: str
    monto: float
    estado: str
    fecha_registro: date
    motivo_anulacion: Optional[str]


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


# ============================ FACTURACION ============================
class FacturaOut(Salida):
    id_factura: int
    numero_factura: int
    fecha_emision: datetime
    nit_ci: str
    razon_social: str
    monto_total: float
    cuf: str
    codigo_control: str
    leyenda: str
    estado: str
    pago_id_pago: int


# =========================== PORTAL DEL SOCIO ===========================
class SocioPortalOut(BaseModel):
    id_socio: int
    codigo_fijo: int
    nombre_socio: str


class PagoQrIn(DatosFactura):
    """Datos para pagar un aviso con QR desde el portal (Libelula emite la factura)."""

    tipo_documento: Literal["CI", "NIT"] = Field("CI", description="Tipo de documento para la factura")


class PagoQrOut(BaseModel):
    id_pago: int
    id_aviso: int
    estado: str = Field(description="PENDIENTE, APROBADO o EXPIRADO")
    monto: float
    qr_url: Optional[str]
    url_pasarela: Optional[str]
    codigo_recaudacion: Optional[str]
    factura_url: Optional[str]
