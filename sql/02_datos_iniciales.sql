-- COSPABI R.L. - Datos iniciales de los catalogos

INSERT INTO rol (id_rol, nombre, estado) VALUES
    (1, 'Administrador', true),
    (2, 'Cajero', true),
    (3, 'Plomero', true);

INSERT INTO rol_socio (id_rol_socio, rol_socio) VALUES
    (1, 'Socio'),
    (2, 'Usuario');

-- Minimo de 6 m3: 15 Bs socio, 20 Bs usuario. Cada m3 adicional: 2 Bs.
INSERT INTO tarifa (id_tarifa, consumo_minimo_m3, monto_minimo, precio_m3, rol_socio_id_rol_socio) VALUES
    (1, 6, 15.00, 2, 1),
    (2, 6, 20.00, 2, 2);

-- El id 5 es ANULADO porque asi lo exige la restriccion aviso_anulacion_ck.
INSERT INTO estado (id_estado, estado) VALUES
    (1, 'PENDIENTE'),
    (2, 'PAGADO'),
    (3, 'VENCIDO'),
    (5, 'ANULADO');

INSERT INTO metodo_pago (id_metodo_pago, metodo) VALUES
    (1, 'Efectivo'),
    (2, 'QR'),
    (3, 'Transferencia');

-- Conceptos de cobro adicional; los montos son de ejemplo y se editan en Configuracion.
INSERT INTO tipo_cargo (id_tipo, nombre, descripcion, monto, estado) VALUES
    (1, 'Multa por inasistencia a reunión', 'Falta a reunión o asamblea de socios', 20, true),
    (2, 'Multa por atraso', 'Pago fuera de plazo', 10, true),
    (3, 'Reconexión', 'Reconexión del servicio tras un corte', 50, true),
    (4, 'Tasa AFCOOP', 'Aporte a la Autoridad de Fiscalización de Cooperativas', 2, true),
    (5, 'Baja de medidor', '50 Bs por año de medidor dado de baja', 50, true);

-- Ajusta los contadores para que los proximos registros no choquen con estos ids.
SELECT setval(pg_get_serial_sequence('rol', 'id_rol'), 3);
SELECT setval(pg_get_serial_sequence('rol_socio', 'id_rol_socio'), 2);
SELECT setval(pg_get_serial_sequence('tarifa', 'id_tarifa'), 2);
SELECT setval(pg_get_serial_sequence('estado', 'id_estado'), 5);
SELECT setval(pg_get_serial_sequence('metodo_pago', 'id_metodo_pago'), 3);
SELECT setval(pg_get_serial_sequence('tipo_cargo', 'id_tipo'), 5);

-- Verificacion: cuantas filas quedaron en cada catalogo.
SELECT 'rol' AS tabla, count(*) AS filas FROM rol
UNION ALL SELECT 'rol_socio', count(*) FROM rol_socio
UNION ALL SELECT 'tarifa', count(*) FROM tarifa
UNION ALL SELECT 'estado', count(*) FROM estado
UNION ALL SELECT 'metodo_pago', count(*) FROM metodo_pago
UNION ALL SELECT 'tipo_cargo', count(*) FROM tipo_cargo;
