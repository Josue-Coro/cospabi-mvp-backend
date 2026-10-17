"""Carga datos de demostracion para presentar el MVP.

Uso (con el entorno virtual activo):
    python datos_demo.py

Crea tres meses de historia (08/2026 a 10/2026): personal, rutas, socios,
medidores, lecturas, avisos, pagos en caja y en el portal, facturas, cargos
extra, un credito de inscripcion, socios morosos y cuentas del portal.
Si los datos ya existen no hace nada.

Usuarios de demostracion (cambiarlos en un sistema real):
    Personal:  cajero / cajero123   plomero / plomero123
    Portal:    usuario = codigo fijo (por ejemplo 2001) / socio123
"""
from datetime import date, datetime
from decimal import Decimal

import models
from database import SessionLocal, engine
from datos_iniciales import cargar_datos_iniciales, configurar_base_datos
from reglas import (
    cobrar_aviso,
    crear_aviso,
    emitir_factura,
    generar_credito_inscripcion,
    obtener_o_crear_periodo,
    registrar_bitacora,
)
from seguridad import cifrar_contrasena

CLAVE_PORTAL = "socio123"

PERSONAL = [
    ("María", "López Vaca", "cajero", "cajero123", 2),
    ("Pedro", "Rojas Suárez", "plomero", "plomero123", 3),
]

RUTAS = [(2, "Barrio Norte"), (3, "Barrio Sur")]

# codigo, nombre, CI, telefono, genero, ruta, rol_socio (1 socio, 2 usuario), categoria,
# consumos de agosto, septiembre y octubre (None = todavia no se leyo)
SOCIOS = [
    (2001, "Rosa Mamani Quispe", "6234512", 71234501, "Femenino", 1, 1, "Doméstico", (12, 14, 11)),
    (2002, "Carlos Gutiérrez Flores", "5876234", 72345602, "Masculino", 1, 1, "Doméstico", (8, 9, 7)),
    (2003, "Ana Choque Mendoza", "7012345", 73456703, "Femenino", 1, 1, "Doméstico", (15, 13, 16)),
    (2004, "Luis Fernández Rojas", "6543210", 74567804, "Masculino", 1, 2, "Comercial", (22, 25, 24)),
    (2005, "Silvia Vargas Arteaga", "8123456", 75678905, "Femenino", 2, 1, "Doméstico", (6, 5, 6)),
    (2006, "Jorge Medina Salvatierra", "5345678", 76789006, "Masculino", 2, 1, "Doméstico", (10, 11, 9)),
    (2007, "Elena Torrez Cuéllar", "6789012", 77890107, "Femenino", 2, 1, "Doméstico", (9, 10, 12)),
    (2008, "Mario Justiniano Paz", "7456123", 78901208, "Masculino", 2, 2, "Social", (18, 17, 19)),
    (2009, "Julia Ribera Moreno", "6012987", 60123409, "Femenino", 3, 1, "Doméstico", (7, 8, None)),
    (2010, "Raúl Añez Pinto", "5987654", 61234510, "Masculino", 3, 1, "Doméstico", (13, 12, None)),
    (2011, "Teresa Soliz Herrera", "7321098", 62345611, "Femenino", 3, 1, "Doméstico", (11, 14, None)),
    # Socio nuevo: se inscribio en septiembre y paga la inscripcion en 4 cuotas
    (2012, "Daniel Coca Montaño", "8234567", 63456712, "Masculino", 3, 1, "Doméstico", (None, 6, None)),
]

# Avisos que quedan sin pagar (los de agosto vencen el 19/09 y pasan a morosidad)
SIN_PAGAR = {"08/2026": {2003, 2007}, "09/2026": {2003, 2007, 2008, 2011}}
CON_FACTURA = {("08/2026", 2001), ("08/2026", 2005), ("09/2026", 2002), ("09/2026", 2009)}
CON_CUENTA = {2001, 2002, 2003, 2005, 2009, 2012}

FECHAS = {
    "08/2026": {"lectura": date(2026, 8, 19), "emision": date(2026, 8, 20),
                "caja": datetime(2026, 8, 25, 8, 30)},
    "09/2026": {"lectura": date(2026, 9, 19), "emision": date(2026, 9, 20),
                "caja": datetime(2026, 9, 25, 8, 30)},
    "10/2026": {"lectura": date(2026, 10, 15), "emision": date(2026, 10, 16)},
}


def main() -> None:
    models.Base.metadata.create_all(bind=engine)
    configurar_base_datos()
    cargar_datos_iniciales()

    db = SessionLocal()
    try:
        if db.query(models.Socio).filter(models.Socio.codigo_fijo == 2001).first():
            print("Los datos de demostración ya estaban cargados. No se hizo nada.")
            return

        admin = db.query(models.UsuarioAdmin).filter(models.UsuarioAdmin.rol_id_rol == 1).first()

        # Personal
        personal = {}
        for nombre, apellido, usuario, clave, rol in PERSONAL:
            existente = (
                db.query(models.UsuarioAdmin).filter(models.UsuarioAdmin.usuario == usuario).first()
            )
            personal[usuario] = existente or models.UsuarioAdmin(
                nombre=nombre, apellido=apellido, usuario=usuario,
                contrasena=cifrar_contrasena(clave), estado=True,
                fecha_creacion=date(2026, 8, 1), rol_id_rol=rol,
            )
            db.add(personal[usuario])
        db.flush()
        cajero, plomero = personal["cajero"], personal["plomero"]

        # Rutas (la ruta 1 ya existe)
        rutas = {r.ruta: r for r in db.query(models.Ruta).all()}
        if 1 not in rutas:
            rutas[1] = models.Ruta(ruta=1, descripcion="Zona central")
            db.add(rutas[1])
        for numero, descripcion in RUTAS:
            if numero not in rutas:
                rutas[numero] = models.Ruta(ruta=numero, descripcion=descripcion)
                db.add(rutas[numero])
        db.flush()

        periodos = {p: obtener_o_crear_periodo(db, p) for p in FECHAS}

        # Personas, medidores y socios
        socios = {}
        for indice, (codigo, nombre, ci, telefono, genero, ruta, rol, categoria, _) in enumerate(SOCIOS):
            persona = models.Persona(
                nombre_completo=nombre, ci=ci, telefono=telefono, genero=genero,
                fecha_nacimiento=date(1965 + indice * 2, (indice % 12) + 1, 10),
                fecha_registro=date(2026, 8, 1), estado=True,
            )
            medidor = models.Medidor(
                serie=f"M-{codigo}", numero=indice + 2,
                fecha_instalacion=date(2026, 9, 5) if codigo == 2012 else date(2019, 3, 1),
            )
            db.add_all([persona, medidor])
            db.flush()
            socio = models.Socio(
                nombre_socio=nombre, persona_id_persona=persona.id_persona,
                rol_socio_id_rol_socio=rol, ruta_id_ruta=rutas[ruta].id_ruta,
                medidor_id_medidor=medidor.id_medidor, codigo_fijo=codigo,
                actividad="Comercio" if categoria == "Comercial" else "Vivienda",
                categoria=categoria, correo=f"socio{codigo}@correo.com",
                ubicacion=indice + 1, num_casa=100 + indice * 4, num_ocupantes=3 + indice % 4,
                tipo_instalacion="PVC", dim_instalacion="1/2 pulgada",
                fecha_registro=date(2026, 9, 5) if codigo == 2012 else date(2026, 8, 1),
                estado=True,
            )
            db.add(socio)
            db.flush()
            socios[codigo] = socio

        # Credito de inscripcion del socio nuevo: cuotas de 09/2026 a 12/2026
        generar_credito_inscripcion(db, socios[2012], date(2026, 9, 5))

        # Cargos extra de octubre (entran en el aviso de octubre)
        tipos = {t.id_tipo: t for t in db.query(models.TipoCargo).all()}
        for codigo, id_tipo, detalle in [
            (2004, 1, "Falta a la asamblea del 04/10/2026"),
            (2006, 3, "Reconexión del 08/10/2026"),
        ]:
            db.add(models.CargoExtra(
                monto=tipos[id_tipo].monto, descripcion=detalle, fecha_registro=date(2026, 10, 8),
                estado="PENDIENTE", tipo_cargo_id_tipo=id_tipo,
                socio_id_socio=socios[codigo].id_socio,
                periodo_id_periodo=periodos["10/2026"].id_periodo,
            ))
        db.flush()

        # Lecturas y avisos de cada mes
        efectivo = db.get(models.MetodoPago, 1)
        qr = db.get(models.MetodoPago, 2)
        ultima = {codigo: 100 + i * 37 for i, codigo in enumerate(socios)}
        ultima[2012] = 0
        fecha_anterior = {}
        for numero_mes, (periodo, fechas) in enumerate(FECHAS.items()):
            avisos = {}
            for codigo, *_, consumos in SOCIOS:
                consumo = consumos[numero_mes]
                if consumo is None:
                    continue
                socio = socios[codigo]
                anterior = ultima[codigo]
                lectura = models.Lectura(
                    fecha_lectura=fechas["lectura"], lectura_anterior=anterior,
                    lectura_actual=anterior + consumo, consumo_m3=consumo,
                    dias_lectura=(fechas["lectura"] - fecha_anterior[codigo]).days
                    if codigo in fecha_anterior else 0,
                    usuario_admin_id_usuario_admin=plomero.id_usuario_admin,
                    medidor_id_medidor=socio.medidor_id_medidor,
                    periodo_id_periodo=periodos[periodo].id_periodo,
                )
                db.add(lectura)
                db.flush()
                ultima[codigo] = anterior + consumo
                fecha_anterior[codigo] = fechas["lectura"]
                avisos[codigo] = crear_aviso(db, lectura, fechas["emision"])

            if "caja" not in fechas:
                continue

            # Cobros en ventanilla de ese mes
            apertura = fechas["caja"]
            caja = models.Caja(
                fecha=apertura.date(), hora_apertura=apertura, estado=True,
                usuario_admin_id_usuario_admin=cajero.id_usuario_admin, monto_apertura=Decimal("100"),
            )
            db.add(caja)
            db.flush()
            cobrado = Decimal("0")
            for minuto, (codigo, aviso) in enumerate(avisos.items()):
                if codigo in SIN_PAGAR.get(periodo, set()):
                    continue
                total = Decimal(aviso.total_aviso)
                pago = cobrar_aviso(
                    db, aviso, efectivo, cajero="María López Vaca", caja=caja,
                    monto_recibido=total + (Decimal("10") - total % 10),
                )
                pago.fecha_pago = apertura.replace(hour=9, minute=minuto * 4)
                if (periodo, codigo) in CON_FACTURA:
                    persona = socios[codigo].persona
                    factura = emitir_factura(
                        db, pago, persona.ci, persona.nombre_completo, cajero.id_usuario_admin
                    )
                    factura.fecha_emision = pago.fecha_pago
                cobrado += total
            caja.monto_cobrado = cobrado
            caja.monto_contado = Decimal("100") + cobrado
            caja.diferencia_arqueo = Decimal("0")
            caja.hora_cierre = apertura.replace(hour=12)
            caja.estado = False
            db.flush()

        # Pago de octubre hecho por el socio 2001 desde el portal con QR
        aviso_portal = (
            db.query(models.Aviso)
            .filter(
                models.Aviso.socio_id_socio == socios[2001].id_socio,
                models.Aviso.periodo_id_periodo == periodos["10/2026"].id_periodo,
            )
            .first()
        )
        pago = cobrar_aviso(
            db, aviso_portal, qr, cajero="PORTAL", caja=None,
            forma_pago="PORTAL", id_transaccion="QR-DEMO-20261016-0001",
        )
        pago.fecha_pago = datetime(2026, 10, 16, 20, 15)
        persona = socios[2001].persona
        factura = emitir_factura(db, pago, persona.ci, persona.nombre_completo, None)
        factura.fecha_emision = pago.fecha_pago

        # Cuentas del portal
        for codigo in CON_CUENTA:
            db.add(models.CuentaSocio(
                usuario=str(codigo), contrasena=cifrar_contrasena(CLAVE_PORTAL),
                estado=True, socio_id_socio=socios[codigo].id_socio,
            ))

        registrar_bitacora(db, admin, "Cargó los datos de demostración del MVP")
        db.commit()
        print(f"Datos de demostración cargados: {len(socios)} socios, 3 periodos.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
