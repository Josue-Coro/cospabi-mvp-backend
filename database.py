"""Conexion a la base de datos PostgreSQL de Supabase."""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Lee las variables del archivo .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL or "TU_PASSWORD" in DATABASE_URL or "[YOUR-PASSWORD]" in DATABASE_URL:
    raise RuntimeError(
        "Falta configurar DATABASE_URL en el archivo .env "
        "(pega ahi la cadena de conexion de Supabase con tu contrasena real)."
    )

# SQLAlchemy 2.1 usa por defecto el driver psycopg (version 3) para las URL que
# empiezan con postgresql://. Este proyecto instala psycopg2, asi que se indica.
for prefijo in ("postgresql://", "postgres://"):
    if DATABASE_URL.startswith(prefijo):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len(prefijo):]

# pool_pre_ping revisa que la conexion siga viva antes de usarla
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Entrega una sesion de base de datos a cada endpoint y la cierra al terminar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
