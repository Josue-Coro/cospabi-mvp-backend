# cospabi-mvp-backend

API REST del MVP del sistema de gestión de la Cooperativa de Agua Potable **COSPABI R.L.**
(FastAPI + SQLAlchemy + PostgreSQL en Supabase). La consumen el panel administrativo
(`cospabi-mvp-frontend`) y el portal del socio (`cospabi_socio`).

## Módulos

| Módulo | Qué incluye | Roles |
|---|---|---|
| Administración | login JWT, usuarios, roles, caja con arqueo, bitácora de solo lectura | Admin (caja: Cajero) |
| Configuración | tarifas, tipos de cargo, medidores, periodos | Admin / Cajero |
| Atención al Cliente | personas, socios, crédito de inscripción (4 × 425 Bs), cuenta del portal, pagos | Cajero |
| Operaciones | rutas y planilla de lectura por ruta, lecturas, avisos (uno o todo el periodo), cargos extra | Cajero / Plomero |
| Facturación | factura simulada al cobrar si el socio la pide (NIT/CI y razón social) | Cajero |
| Reportes | caja, morosidad, pagos del portal, pagos de inscripción | Cajero |
| Portal del Socio | login con código fijo, avisos, pagos y facturas propias | Socio |

El Administrador puede usar todo. El portal usa un token distinto al del personal.

## Ejecutar en local

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python configurar.py                      # crea el .env y prueba la conexión a Supabase
uvicorn main:app --reload --port 8000
```

Documentación interactiva: http://localhost:8000/docs

Al arrancar, la API crea las tablas que falten, activa RLS en todas (para que la API
pública de Supabase no las exponga), protege la bitácora con un trigger y carga los catálogos.

## Datos de demostración

```bash
python datos_demo.py
```

Carga tres meses (08/2026 a 10/2026) con socios, lecturas, avisos pagados y pendientes,
morosos, facturas, cargos extra, un crédito de inscripción y un pago desde el portal.
Usuarios de demostración (cambiarlos en un sistema real):

- Personal: `admin` (clave del `.env`), `cajero` / `cajero123`, `plomero` / `plomero123`
- Portal: código fijo `2001`, `2002`, `2003`, `2005`, `2009` o `2012` / `socio123`

## Pago con QR (Libélula)

El portal del socio paga con la pasarela **Libélula** (`libelula.py`):

1. `POST /api/v1/portal/avisos/{id}/pagar-qr` registra la deuda en Libélula (REGISTRAR DEUDA) y
   devuelve el QR y la URL de la pasarela. El pago queda `PENDIENTE`.
2. Libélula llama a `/api/v1/portal/libelula/pago-exitoso?transaction_id=...` al pagarse. La API
   no confía en esa llamada: confirma con CONSULTAR DEUDAS POR IDENTIFICADOR antes de aprobar.
3. El portal consulta `GET /api/v1/portal/pagos-qr/{id}` cada pocos segundos; si Libélula ya lo
   registra como pagado, se aprueba el pago, el aviso pasa a PAGADO y se guarda la factura que
   emite Libélula (`factura_url`).

Requiere `LIBELULA_APPKEY` (para pruebas, la llave de pruebas que asigna Libélula).

## Variables de entorno

Ver `.env.example`. El archivo `.env` real nunca se sube al repositorio.

Para probar sin tocar los datos reales, `DB_ESQUEMA=prueba` hace que la API use otro
esquema de la misma base (se crea solo); luego se borra con `DROP SCHEMA prueba CASCADE`.

## Despliegue en Render (Docker)

1. En Render: **New → Blueprint** y elegir este repositorio (usa `render.yaml`),
   o **New → Web Service** con runtime **Docker**.
2. Variables: `DATABASE_URL` (cadena del *Session pooler* de Supabase), `ADMIN_CLAVE`;
   `SECRET_KEY` se genera sola con el Blueprint.
3. `CORS_ORIGENES` (en `render.yaml`) solo permite los dos frontends de Vercel.

URLs desplegadas:

- API: https://cospabi-mvp-backend.onrender.com (documentación en `/docs`)
- Panel administrativo: https://cospabi-mvp-frontend.vercel.app
- Portal del socio: https://cospabi-socio.vercel.app

El plan gratuito de Render apaga el servicio tras 15 minutos sin uso: la primera
petición después tarda unos segundos en responder.

## Base de datos

`sql/01_tablas_cospabi.sql` y `sql/02_datos_iniciales.sql` crean las 21 tablas y los catálogos
(se pueden ejecutar en el SQL Editor de Supabase en una base vacía).
