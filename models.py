"""Modelos SQLAlchemy de COSPABI R.L.

Tablas del script BD_COSPABI.sql con los mismos nombres de tablas y columnas,
mas la tabla factura (facturacion simulada del MVP). Cubren los 6 modulos:
socio -> lectura -> aviso (consumo + cargos extra + cuota de inscripcion) -> pago.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from database import Base


# =========================== ADMINISTRACION ===========================
class Rol(Base):
    __tablename__ = "rol"

    id_rol = Column(Integer, Identity(), primary_key=True)
    nombre = Column(String(150), nullable=False)
    descripcion = Column(String(250))
    estado = Column(Boolean, nullable=False)


class UsuarioAdmin(Base):
    __tablename__ = "usuario_admin"
    __table_args__ = (UniqueConstraint("usuario", name="usuario_admin_usuario_uq"),)

    id_usuario_admin = Column(Integer, Identity(), primary_key=True)
    nombre = Column(String(255), nullable=False)
    apellido = Column(String(255), nullable=False)
    usuario = Column(String(255), nullable=False)
    # En la base la columna se llama "contraseña"; en Python se usa sin la ñ
    contrasena = Column("contraseña", String(550), nullable=False)
    estado = Column(Boolean, nullable=False)
    fecha_creacion = Column(Date, nullable=False)
    rol_id_rol = Column(Integer, ForeignKey("rol.id_rol"), nullable=False)
    intentos_fallidos = Column(Integer, nullable=False, server_default=text("0"))
    bloqueado_hasta = Column(DateTime)
    correo = Column(String(150))
    debe_cambiar_clave = Column(Boolean, nullable=False, server_default=text("false"))

    rol = relationship("Rol")


class Caja(Base):
    __tablename__ = "caja"
    __table_args__ = (
        CheckConstraint(
            "monto_contado >= 0 AND (diferencia_arqueo = 0 OR observacion_cierre IS NOT NULL)",
            name="caja_contado_ck",
        ),
        CheckConstraint("monto_apertura >= 0 AND monto_cobrado >= 0", name="caja_montos_ck"),
    )

    id_caja = Column(Integer, Identity(), primary_key=True)
    fecha = Column(Date, nullable=False)
    hora_apertura = Column(DateTime, nullable=False)
    hora_cierre = Column(DateTime)
    monto_cobrado = Column(Numeric(30, 2))
    usuario_admin_id_usuario_admin = Column(
        Integer, ForeignKey("usuario_admin.id_usuario_admin"), nullable=False
    )
    estado = Column(Boolean, nullable=False)  # True = abierta, False = cerrada
    monto_apertura = Column(Numeric(30, 2), nullable=False, server_default=text("0"))
    monto_contado = Column(Numeric(30, 2))
    diferencia_arqueo = Column(Numeric(30, 2))
    observacion_cierre = Column(String(255))

    usuario_admin = relationship("UsuarioAdmin")


class Bitacora(Base):
    """Historial de acciones. Un trigger en PostgreSQL impide editar o borrar filas."""

    __tablename__ = "bitacora"

    id_bitacora = Column(Integer, Identity(), primary_key=True)
    accion = Column(String(255), nullable=False)
    fecha_hora = Column(DateTime, nullable=False)
    usuario_admin_id_usuario_admin = Column(
        Integer, ForeignKey("usuario_admin.id_usuario_admin"), nullable=False
    )

    usuario_admin = relationship("UsuarioAdmin")


# =========================== CONFIGURACION ===========================
class RolSocio(Base):
    __tablename__ = "rol_socio"

    id_rol_socio = Column(Integer, Identity(), primary_key=True)
    rol_socio = Column(String(150), nullable=False)  # Socio / Usuario


class Tarifa(Base):
    __tablename__ = "tarifa"
    __table_args__ = (
        CheckConstraint(
            "consumo_minimo_m3 >= 0 AND monto_minimo >= 0 AND precio_m3 >= 0",
            name="tarifa_valores_ck",
        ),
    )

    id_tarifa = Column(Integer, Identity(), primary_key=True)
    consumo_minimo_m3 = Column(Integer)
    monto_minimo = Column(Numeric(30, 2), nullable=False)
    precio_m3 = Column(Integer, nullable=False)
    rol_socio_id_rol_socio = Column(Integer, ForeignKey("rol_socio.id_rol_socio"), nullable=False)

    rol_socio = relationship("RolSocio")


class Medidor(Base):
    __tablename__ = "medidor"
    __table_args__ = (
        UniqueConstraint("serie", name="medidor_serie_uq"),
        CheckConstraint("numero > 0", name="medidor_numero_ck"),
    )

    id_medidor = Column(Integer, Identity(), primary_key=True)
    serie = Column(String(150), nullable=False)
    numero = Column(Integer, nullable=False)
    fecha_instalacion = Column(Date)


class Periodo(Base):
    __tablename__ = "periodo"
    __table_args__ = (UniqueConstraint("periodo", name="periodo_periodo_uq"),)

    id_periodo = Column(Integer, Identity(), primary_key=True)
    periodo = Column(String(50), nullable=False)  # formato MM/yyyy, ej. 10/2026
    costo_inscripcion = Column(Numeric(10, 2))


class TipoCargo(Base):
    """Catalogo de conceptos adicionales: multas, reconexion, etc."""

    __tablename__ = "tipo_cargo"
    __table_args__ = (
        UniqueConstraint("nombre", name="tipo_cargo_nombre_uq"),
        CheckConstraint("monto >= 0", name="tipo_cargo_monto_ck"),
    )

    id_tipo = Column(Integer, Identity(), primary_key=True)
    nombre = Column(String(150), nullable=False)
    descripcion = Column(String(255))
    monto = Column(Numeric(30, 2), nullable=False)
    estado = Column(Boolean, nullable=False, server_default=text("true"))


# ======================== ATENCION AL CLIENTE ========================
class Persona(Base):
    __tablename__ = "persona"
    __table_args__ = (
        UniqueConstraint("ci", name="persona_ci_uq"),
        CheckConstraint("ci ~ '^[0-9]{4,10}$'", name="persona_ci_ck"),
        CheckConstraint("genero IN ('Masculino', 'Femenino', 'Otro')", name="persona_genero_ck"),
        CheckConstraint(
            "telefono >= 10000000 AND telefono <= 99999999", name="persona_telefono_ck"
        ),
    )

    id_persona = Column(Integer, Identity(), primary_key=True)
    genero = Column(String(255))
    nombre_completo = Column(String(250), nullable=False)
    ci = Column(String(50), nullable=False)
    fecha_nacimiento = Column(Date, nullable=False)
    fecha_registro = Column(Date, nullable=False)
    estado = Column(Boolean, nullable=False)
    telefono = Column(Integer)


class Ruta(Base):
    __tablename__ = "ruta"
    __table_args__ = (CheckConstraint("ruta > 0", name="ruta_ruta_ck"),)

    id_ruta = Column(Integer, Identity(), primary_key=True)
    ruta = Column(Integer, nullable=False)
    descripcion = Column(String(150))


class Socio(Base):
    __tablename__ = "socio"
    __table_args__ = (
        UniqueConstraint("codigo_fijo", name="socio_codigo_fijo_uq"),
        CheckConstraint(
            "categoria IN ('Social', 'Industrial', 'Comercial', 'Doméstico')",
            name="socio_categoria_ck",
        ),
        CheckConstraint("codigo_fijo > 0", name="socio_codigo_fijo_ck"),
        CheckConstraint(
            "dim_instalacion IN ('1 pulgada', '3/4 pulgada', '1/2 pulgada')",
            name="socio_dim_instalacion_ck",
        ),
        CheckConstraint(
            "num_ocupantes >= 0 AND num_ocupantes <= 50", name="socio_num_ocupantes_ck"
        ),
        CheckConstraint(
            "tipo_instalacion IN ('Tubería negra', 'Polipropileno', 'CPVC', 'PVC')",
            name="socio_tipo_instalacion_ck",
        ),
        CheckConstraint("ubicacion >= 0 AND num_casa >= 0", name="socio_ubicacion_casa_ck"),
    )

    id_socio = Column(Integer, Identity(), primary_key=True)
    nombre_socio = Column(String(255), nullable=False)
    persona_id_persona = Column(Integer, ForeignKey("persona.id_persona"), nullable=False)
    rol_socio_id_rol_socio = Column(Integer, ForeignKey("rol_socio.id_rol_socio"), nullable=False)
    ubicacion = Column(Integer)
    medidor_id_medidor = Column(Integer, ForeignKey("medidor.id_medidor"))
    num_casa = Column(Integer)
    num_ocupantes = Column(Integer)
    tipo_instalacion = Column(String(255))
    dim_instalacion = Column(String(255))
    actividad = Column(String(255), nullable=False)
    categoria = Column(String(255), nullable=False)
    fecha_registro = Column(Date, nullable=False)
    ruta_id_ruta = Column(Integer, ForeignKey("ruta.id_ruta"), nullable=False)
    codigo_fijo = Column(Integer, nullable=False)
    estado = Column(Boolean, nullable=False, server_default=text("true"))
    correo = Column(String(150), nullable=False)
    fecha_baja = Column(Date)
    motivo_baja = Column(String(255))
    acepta_comunicaciones = Column(Boolean)
    fecha_consentimiento = Column(DateTime)

    persona = relationship("Persona")
    rol_socio = relationship("RolSocio")
    medidor = relationship("Medidor")
    ruta = relationship("Ruta")


class CreditoInscripcion(Base):
    """Cuotas del derecho de inscripcion (1.700 Bs en 4 cuotas de 425 Bs)."""

    __tablename__ = "credito_inscripcion"
    __table_args__ = (
        UniqueConstraint("socio_id_socio", "num_cuota", name="credito_socio_cuota_uq"),
        CheckConstraint("num_cuota BETWEEN 1 AND 4", name="credito_num_cuota_ck"),
        CheckConstraint("monto_pago > 0", name="credito_monto_ck"),
        CheckConstraint("estado IN ('PENDIENTE', 'PAGADA')", name="credito_estado_ck"),
    )

    id_credito = Column(Integer, Identity(), primary_key=True)
    monto_pago = Column(Numeric(10, 2), nullable=False)
    estado = Column(String(50), nullable=False)
    num_cuota = Column(Integer, nullable=False)
    socio_id_socio = Column(Integer, ForeignKey("socio.id_socio"), nullable=False)
    periodo_id_periodo = Column(Integer, ForeignKey("periodo.id_periodo"), nullable=False)
    pago_id_pago = Column(Integer, ForeignKey("pago.id_pago"))

    socio = relationship("Socio")
    periodo = relationship("Periodo")


class CuentaSocio(Base):
    """Acceso del socio al portal. El usuario es su codigo fijo."""

    __tablename__ = "cuenta_socio"
    __table_args__ = (
        UniqueConstraint("usuario", name="cuenta_socio_usuario_uq"),
        UniqueConstraint("socio_id_socio", name="cuenta_socio_socio_uq"),
    )

    id_cuenta_socio = Column(Integer, Identity(), primary_key=True)
    usuario = Column(String(150), nullable=False)
    contrasena = Column("contraseña", String(500), nullable=False)
    ultimo_acceso = Column(DateTime)
    estado = Column(Boolean, nullable=False)
    socio_id_socio = Column(Integer, ForeignKey("socio.id_socio"), nullable=False)
    intentos_fallidos = Column(Integer, nullable=False, server_default=text("0"))

    socio = relationship("Socio")


# ============================ OPERACIONES ============================
class Estado(Base):
    __tablename__ = "estado"

    id_estado = Column(Integer, Identity(), primary_key=True)
    estado = Column(String(150), nullable=False)  # PENDIENTE / PAGADO / VENCIDO / ANULADO


class Lectura(Base):
    __tablename__ = "lectura"
    __table_args__ = (
        UniqueConstraint(
            "medidor_id_medidor", "periodo_id_periodo", name="lectura_medidor_periodo_uq"
        ),
        CheckConstraint(
            "lectura_anterior >= 0 AND lectura_actual >= lectura_anterior AND consumo_m3 >= 0",
            name="lectura_valores_ck",
        ),
    )

    id_lectura = Column(Integer, Identity(), primary_key=True)
    fecha_lectura = Column(Date, nullable=False)
    lectura_anterior = Column(Integer, nullable=False)
    lectura_actual = Column(Integer, nullable=False)
    dias_lectura = Column(Integer, nullable=False)
    observacion = Column(String(255))
    usuario_admin_id_usuario_admin = Column(
        Integer, ForeignKey("usuario_admin.id_usuario_admin"), nullable=False
    )
    medidor_id_medidor = Column(Integer, ForeignKey("medidor.id_medidor"), nullable=False)
    periodo_id_periodo = Column(Integer, ForeignKey("periodo.id_periodo"), nullable=False)
    consumo_m3 = Column(Numeric(30, 2), nullable=False)

    medidor = relationship("Medidor")
    periodo = relationship("Periodo")


class Aviso(Base):
    __tablename__ = "aviso"
    __table_args__ = (
        # El estado con id 5 es ANULADO: un aviso anulado debe tener motivo
        CheckConstraint(
            "estado_id_estado <> 5 OR motivo_anulacion IS NOT NULL", name="aviso_anulacion_ck"
        ),
    )

    id_aviso = Column(Integer, Identity(), primary_key=True)
    fecha_emision = Column(Date, nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    total_consumo = Column(Numeric(30, 2), nullable=False)
    total_aviso = Column(Numeric(30, 2), nullable=False)
    periodo_id_periodo = Column(Integer, ForeignKey("periodo.id_periodo"), nullable=False)
    estado_id_estado = Column(Integer, ForeignKey("estado.id_estado"), nullable=False)
    lectura_id_lectura = Column(Integer, ForeignKey("lectura.id_lectura"))
    socio_id_socio = Column(Integer, ForeignKey("socio.id_socio"), nullable=False)
    motivo_anulacion = Column(String(255))
    fecha_anulacion = Column(DateTime)

    periodo = relationship("Periodo")
    estado = relationship("Estado")
    lectura = relationship("Lectura")
    socio = relationship("Socio")


class CargoExtra(Base):
    """Cargo de un socio en un periodo; se suma al aviso de ese periodo."""

    __tablename__ = "cargo_extra"
    __table_args__ = (
        CheckConstraint("monto > 0", name="cargo_extra_monto_ck"),
        CheckConstraint(
            "estado IN ('PENDIENTE', 'APLICADO', 'ANULADO')", name="cargo_extra_estado_ck"
        ),
        CheckConstraint(
            "estado <> 'ANULADO' OR motivo_anulacion IS NOT NULL", name="cargo_extra_anulacion_ck"
        ),
    )

    id_cargo_extra = Column(Integer, Identity(), primary_key=True)
    monto = Column(Numeric(30, 2), nullable=False)
    descripcion = Column(String(150), nullable=False)
    fecha_registro = Column(Date, nullable=False)
    estado = Column(String(150), nullable=False)  # PENDIENTE / APLICADO (pagado) / ANULADO
    tipo_cargo_id_tipo = Column(Integer, ForeignKey("tipo_cargo.id_tipo"), nullable=False)
    socio_id_socio = Column(Integer, ForeignKey("socio.id_socio"), nullable=False)
    periodo_id_periodo = Column(Integer, ForeignKey("periodo.id_periodo"), nullable=False)
    motivo_anulacion = Column(String(255))
    fecha_anulacion = Column(DateTime)
    pago_id_pago = Column(Integer, ForeignKey("pago.id_pago"))

    tipo_cargo = relationship("TipoCargo")
    socio = relationship("Socio")
    periodo = relationship("Periodo")


# ============================= COBRANZA =============================
class MetodoPago(Base):
    __tablename__ = "metodo_pago"

    id_metodo_pago = Column(Integer, Identity(), primary_key=True)
    metodo = Column(String(150), nullable=False)  # Efectivo / QR / Transferencia
    referencia = Column(String(255))


class Pago(Base):
    __tablename__ = "pago"
    __table_args__ = (
        CheckConstraint(
            "estado_pago IN ('PENDIENTE', 'APROBADO', 'EXPIRADO')", name="pago_estado_ck"
        ),
        CheckConstraint("monto_pagado >= 0 AND vuelto >= 0", name="pago_montos_ck"),
    )

    id_pago = Column(Integer, Identity(), primary_key=True)
    fecha_pago = Column(DateTime, nullable=False)
    monto_pagado = Column(Numeric(30, 2), nullable=False)
    cajero = Column(String(150), nullable=False)
    aviso_id_aviso = Column(Integer, ForeignKey("aviso.id_aviso"))
    metodo_pago_id_metodo_pago = Column(
        Integer, ForeignKey("metodo_pago.id_metodo_pago"), nullable=False
    )
    vuelto = Column(Numeric(30, 2))
    caja_id_caja = Column(Integer, ForeignKey("caja.id_caja"))
    identificador_deuda = Column(String(100))
    id_transaccion = Column(String(100))
    forma_pago = Column(String(60))
    codigo_recaudacion = Column(String(50))
    url_pasarela = Column(String(500))
    qr_url = Column(String(500))
    estado_pago = Column(String(30), nullable=False, server_default="APROBADO")

    aviso = relationship("Aviso")
    metodo_pago = relationship("MetodoPago")
    caja = relationship("Caja")
    factura = relationship("Factura", back_populates="pago", uselist=False)

    @property
    def id_factura(self):
        return self.factura.id_factura if self.factura else None


# ============================ FACTURACION ============================
class Factura(Base):
    """Factura simulada del MVP: tiene los datos de una factura del SIAT, pero
    no se envia a Impuestos Nacionales. Se emite al cobrar si el socio la pide."""

    __tablename__ = "factura"
    __table_args__ = (
        UniqueConstraint("numero_factura", name="factura_numero_uq"),
        UniqueConstraint("pago_id_pago", name="factura_pago_uq"),
        CheckConstraint("monto_total >= 0", name="factura_monto_ck"),
        CheckConstraint("estado IN ('VIGENTE', 'ANULADA')", name="factura_estado_ck"),
    )

    id_factura = Column(Integer, Identity(), primary_key=True)
    numero_factura = Column(Integer, nullable=False)
    fecha_emision = Column(DateTime, nullable=False)
    nit_ci = Column(String(20), nullable=False)
    razon_social = Column(String(255), nullable=False)
    monto_total = Column(Numeric(30, 2), nullable=False)
    cuf = Column(String(100), nullable=False)  # codigo unico de factura (simulado)
    codigo_control = Column(String(30), nullable=False)
    leyenda = Column(String(500), nullable=False)
    estado = Column(String(20), nullable=False, server_default="VIGENTE")
    pago_id_pago = Column(Integer, ForeignKey("pago.id_pago"), nullable=False)
    # Nulo cuando el pago se hizo desde el portal del socio
    usuario_admin_id_usuario_admin = Column(Integer, ForeignKey("usuario_admin.id_usuario_admin"))

    pago = relationship("Pago", back_populates="factura")
