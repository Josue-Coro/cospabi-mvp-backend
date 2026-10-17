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
]


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
