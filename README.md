# cospabi-mvp-backend

API REST del MVP del sistema de gestión de la Cooperativa de Agua Potable **COSPABI R.L.**
(FastAPI + SQLAlchemy + PostgreSQL en Supabase).

## Ejecutar en local

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python configurar.py                      # crea el .env y prueba la conexión a Supabase
uvicorn main:app --reload --port 8000
```

Documentación interactiva: http://localhost:8000/docs

## Variables de entorno

Ver `.env.example`. El archivo `.env` real nunca se sube al repositorio.

## Base de datos

`sql/01_tablas_cospabi.sql` y `sql/02_datos_iniciales.sql` crean las tablas y los catálogos.
La API también crea las tablas que falten y carga los catálogos al arrancar.
