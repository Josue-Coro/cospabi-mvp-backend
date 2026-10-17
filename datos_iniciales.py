"""Datos iniciales: catalogos y primer usuario administrador.

Se ejecuta al arrancar la API. Solo inserta lo que falta, asi que es seguro
aunque los catalogos ya se hayan cargado con el script SQL en Supabase.
"""
import os

from sqlalchemy import text

import models
from database import SessionLocal, engine
from reglas import hoy
from seguridad import cifrar_contrasena

# (modelo, nombre de la columna id, filas). El orden respeta las claves foraneas.
CATALOGOS = [
    (models.Rol, "id_rol", [
        {"id_rol": 1, "nombre": "Administrador", "estado": True},
        {"id_rol": 2, "nombre": "Cajero", "estado": True},
        {"id_rol": 3, "nombre": "Plomero", "estado": True},
    ]),
    (models.RolSocio, "id_rol_socio", [
        {"id_rol_socio": 1, "rol_socio": "Socio"},
        {"id_rol_socio": 2, "rol_socio": "Usuario"},
    ]),
    # Minimo de 6 m3: 15 Bs socio, 20 Bs usuario. Cada m3 adicional: 2 Bs.
    (models.Tarifa, "id_tarifa", [
        {"id_tarifa": 1, "consumo_minimo_m3": 6, "monto_minimo": 15, "precio_m3": 2,
         "rol_socio_id_rol_socio": 1},
        {"id_tarifa": 2, "consumo_minimo_m3": 6, "monto_minimo": 20, "precio_m3": 2,
         "rol_socio_id_rol_socio": 2},
    ]),
    # El id 5 es ANULADO porque asi lo exige la restriccion aviso_anulacion_ck.
    (models.Estado, "id_estado", [
        {"id_estado": 1, "estado": "PENDIENTE"},
        {"id_estado": 2, "estado": "PAGADO"},
        {"id_estado": 3, "estado": "VENCIDO"},
        {"id_estado": 5, "estado": "ANULADO"},
    ]),
    (models.MetodoPago, "id_metodo_pago", [
        {"id_metodo_pago": 1, "metodo": "Efectivo"},
        {"id_metodo_pago": 2, "metodo": "QR"},
        {"id_metodo_pago": 3, "metodo": "Transferencia"},
    ]),
    # Conceptos del Modelo de Dominio; los montos son de ejemplo y se editan en Configuracion
    (models.TipoCargo, "id_tipo", [
        {"id_tipo": 1, "nombre": "Multa por inasistencia a reunión", "monto": 20, "estado": True,
         "descripcion": "Falta a reunión o asamblea de socios"},
        {"id_tipo": 2, "nombre": "Multa por atraso", "monto": 10, "estado": True,
         "descripcion": "Pago fuera de plazo"},
        {"id_tipo": 3, "nombre": "Reconexión", "monto": 50, "estado": True,
         "descripcion": "Reconexión del servicio tras un corte"},
        {"id_tipo": 4, "nombre": "Tasa AFCOOP", "monto": 2, "estado": True,
         "descripcion": "Aporte a la Autoridad de Fiscalización de Cooperativas"},
        {"id_tipo": 5, "nombre": "Baja de medidor", "monto": 50, "estado": True,
         "descripcion": "50 Bs por año de medidor dado de baja"},
    ]),
]


def configurar_base_datos() -> None:
    """Ajustes de seguridad de PostgreSQL que create_all no hace.

    - Activa RLS en todas las tablas para que la API publica de Supabase no las
      exponga (FastAPI se conecta como postgres y no se ve afectado).
    - Crea un trigger que impide modificar o borrar la bitacora (RNF-08).
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conexion:
        # Columnas agregadas despues de crear la tabla (create_all no altera tablas existentes)
        conexion.execute(text("ALTER TABLE pago ADD COLUMN IF NOT EXISTS factura_url varchar(500)"))
        for tabla in models.Base.metadata.tables:
            conexion.execute(text(f'ALTER TABLE "{tabla}" ENABLE ROW LEVEL SECURITY'))
        conexion.execute(text("""
            CREATE OR REPLACE FUNCTION bitacora_solo_lectura() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'La bitácora no se puede modificar ni eliminar';
            END;
            $$ LANGUAGE plpgsql
        """))
        conexion.execute(text("""
            CREATE OR REPLACE TRIGGER bitacora_solo_lectura_tg
            BEFORE UPDATE OR DELETE ON bitacora
            FOR EACH ROW EXECUTE FUNCTION bitacora_solo_lectura()
        """))


def cargar_datos_iniciales() -> None:
    db = SessionLocal()
    try:
        for modelo, columna_id, filas in CATALOGOS:
            if db.query(modelo).count() > 0:
                continue  # el catalogo ya tiene datos
            db.add_all([modelo(**fila) for fila in filas])
            db.flush()
            if engine.dialect.name == "postgresql":
                # Ajusta el contador para que los proximos ids no choquen
                tabla = modelo.__tablename__
                db.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{tabla}', '{columna_id}'), "
                    f"(SELECT MAX({columna_id}) FROM {tabla}))"
                ))

        # Primer usuario: se crea solo si la tabla usuario_admin esta vacia
        if db.query(models.UsuarioAdmin).count() == 0:
            db.add(models.UsuarioAdmin(
                nombre="Administrador",
                apellido="COSPABI",
                usuario=os.getenv("ADMIN_USUARIO", "admin"),
                contrasena=cifrar_contrasena(os.getenv("ADMIN_CLAVE", "admin123")),
                estado=True,
                fecha_creacion=hoy(),
                rol_id_rol=1,
            ))
        db.commit()
    finally:
        db.close()
