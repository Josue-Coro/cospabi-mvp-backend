"""Crea el archivo .env de la API y prueba la conexion con Supabase.

Uso (con el entorno virtual activo y las librerias instaladas):
    python configurar.py
"""
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, text

ARCHIVO_ENV = Path(__file__).parent / ".env"


def pedir_cadena() -> str:
    print("Pega la cadena de conexion de Supabase (boton Connect > Session pooler)")
    cadena = input("y pulsa Enter: ").strip().strip('"').strip("'")

    if not cadena.startswith(("postgresql://", "postgres://")):
        sys.exit("ERROR: la cadena debe empezar con postgresql://  Vuelve a copiarla de Supabase.")

    # Supabase muestra [YOUR-PASSWORD] en lugar de la contrasena real
    if "[YOUR-PASSWORD]" in cadena:
        clave = input("Escribe la contrasena de tu base de datos de Supabase: ").strip()
        if not clave:
            sys.exit("ERROR: la contrasena no puede estar vacia.")
        # quote() protege los simbolos (@, #, /, ...) para que no rompan la cadena
        cadena = cadena.replace("[YOUR-PASSWORD]", quote(clave, safe=""))
    return cadena


def probar_conexion(cadena: str) -> None:
    # Se indica el driver psycopg2, igual que hace database.py
    for prefijo in ("postgresql://", "postgres://"):
        if cadena.startswith(prefijo):
            url = "postgresql+psycopg2://" + cadena[len(prefijo):]

    print("\nProbando la conexion con Supabase...")
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 15})
        with engine.connect() as conexion:
            tablas = conexion.execute(text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )).scalar()
    except Exception as error:
        mensaje = str(error)
        print("\nNO SE PUDO CONECTAR.")
        if "password authentication failed" in mensaje:
            print("Causa: la contrasena es incorrecta.")
        elif "Tenant or user not found" in mensaje:
            print("Causa: el usuario o el proyecto de la cadena no existe. Copiala de nuevo.")
        elif "could not translate host name" in mensaje:
            print("Causa: no se encontro el servidor. Revisa tu internet y que la cadena este completa.")
        elif "Network is unreachable" in mensaje or "timeout" in mensaje.lower():
            print("Causa: tu red no llega a ese servidor. Usa la cadena 'Session pooler',")
            print("no la 'Direct connection' (esa solo funciona con IPv6).")
        else:
            print("Detalle:", mensaje.splitlines()[0])
        sys.exit("No se guardo nada. Corrige el problema y ejecuta de nuevo: python configurar.py")

    print(f"Conexion exitosa. Tablas encontradas en Supabase: {tablas}")


def main() -> None:
    if ARCHIVO_ENV.exists():
        respuesta = input("Ya existe un archivo .env. Reemplazarlo? (s/n): ").strip().lower()
        if respuesta != "s":
            sys.exit("No se cambio nada.")

    cadena = pedir_cadena()
    probar_conexion(cadena)

    ARCHIVO_ENV.write_text(
        "# Configuracion de la API de COSPABI. Este archivo NO se sube a GitHub.\n"
        f"DATABASE_URL={cadena}\n"
        "\n"
        "# Clave para firmar los tokens JWT (generada al azar)\n"
        f"SECRET_KEY={secrets.token_hex(32)}\n"
        "\n"
        "# Primer usuario del sistema: se crea la primera vez que arranca la API\n"
        "ADMIN_USUARIO=admin\n"
        "ADMIN_CLAVE=admin123\n",
        encoding="utf-8",
    )
    print("\nArchivo .env creado. Ya puedes iniciar la API con:")
    print("    uvicorn main:app --reload --port 8000")


if __name__ == "__main__":
    main()
