"""Seguridad: contrasenas cifradas con bcrypt, sesiones con tokens JWT y permisos por rol."""
import math
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import models
from database import get_db
from reglas import ahora

SECRET_KEY = os.getenv("SECRET_KEY", "")
ALGORITHM = "HS256"
HORAS_TOKEN = 2

# Tras MAX_INTENTOS contrasenas erradas seguidas la cuenta se bloquea MINUTOS_BLOQUEO
MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15

if len(SECRET_KEY) < 32:
    raise RuntimeError("Falta SECRET_KEY en el archivo .env (minimo 32 caracteres).")

# Roles del personal (tabla rol)
ADMINISTRADOR = "Administrador"
CAJERO = "Cajero"
PLOMERO = "Plomero"

# Hace que Swagger muestre el boton "Authorize" para pegar el token
esquema_bearer = HTTPBearer(auto_error=False)


def cifrar_contrasena(contrasena: str) -> str:
    return bcrypt.hashpw(contrasena.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_contrasena(contrasena: str, contrasena_cifrada: str) -> bool:
    try:
        return bcrypt.checkpw(contrasena.encode("utf-8"), contrasena_cifrada.encode("utf-8"))
    except ValueError:
        return False


# Sirven para UsuarioAdmin y CuentaSocio: ambos tienen intentos_fallidos y bloqueado_hasta
def revisar_bloqueo(cuenta) -> None:
    """Rechaza el login si la cuenta sigue bloqueada, sin mirar la contrasena."""
    if cuenta.bloqueado_hasta and cuenta.bloqueado_hasta > ahora():
        minutos = math.ceil((cuenta.bloqueado_hasta - ahora()).total_seconds() / 60)
        raise HTTPException(
            status_code=429,
            detail=f"Cuenta bloqueada por intentos fallidos. Intente de nuevo en {minutos} min.",
        )


def registrar_intento_fallido(cuenta) -> bool:
    """Suma un intento errado; al llegar al maximo bloquea la cuenta. Devuelve si se bloqueo."""
    cuenta.intentos_fallidos += 1
    if cuenta.intentos_fallidos < MAX_INTENTOS:
        return False
    # El contador vuelve a cero: al vencer el bloqueo hay otros MAX_INTENTOS
    cuenta.intentos_fallidos = 0
    cuenta.bloqueado_hasta = ahora() + timedelta(minutes=MINUTOS_BLOQUEO)
    return True


def desbloquear(cuenta) -> None:
    cuenta.intentos_fallidos = 0
    cuenta.bloqueado_hasta = None


def _firmar(datos: dict) -> str:
    datos["exp"] = datetime.now(timezone.utc) + timedelta(hours=HORAS_TOKEN)
    return jwt.encode(datos, SECRET_KEY, algorithm=ALGORITHM)


def crear_token(usuario: models.UsuarioAdmin) -> str:
    return _firmar({
        "sub": str(usuario.id_usuario_admin),
        "tipo": "personal",
        "usuario": usuario.usuario,
        "rol": usuario.rol.nombre,
    })


def crear_token_socio(cuenta: models.CuentaSocio) -> str:
    return _firmar({"sub": str(cuenta.socio_id_socio), "tipo": "socio", "usuario": cuenta.usuario})


def _leer_token(credenciales: HTTPAuthorizationCredentials, tipo: str) -> dict:
    if credenciales is None:
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    try:
        datos = jwt.decode(credenciales.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    # Un token del portal no sirve para el sistema interno y viceversa
    if datos.get("tipo", "personal") != tipo:
        raise HTTPException(status_code=403, detail="Este token no es válido para este sistema")
    return datos


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(esquema_bearer),
    db: Session = Depends(get_db),
) -> models.UsuarioAdmin:
    """Dependencia que protege los endpoints del personal: exige un token valido."""
    datos = _leer_token(credenciales, "personal")
    usuario = db.get(models.UsuarioAdmin, int(datos["sub"]))
    if usuario is None or not usuario.estado:
        raise HTTPException(status_code=403, detail="Usuario inexistente o desactivado")
    return usuario


def requiere_rol(*roles: str):
    """Dependencia que deja pasar solo a los roles indicados (el Administrador siempre puede)."""
    permitidos = {ADMINISTRADOR, *roles}

    def verificar(usuario: models.UsuarioAdmin = Depends(usuario_actual)) -> models.UsuarioAdmin:
        if usuario.rol.nombre not in permitidos:
            raise HTTPException(
                status_code=403,
                detail=f"El rol {usuario.rol.nombre} no tiene permiso para esta acción",
            )
        return usuario

    return verificar


def socio_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(esquema_bearer),
    db: Session = Depends(get_db),
) -> models.Socio:
    """Dependencia del portal del socio: exige un token de socio valido."""
    datos = _leer_token(credenciales, "socio")
    socio = db.get(models.Socio, int(datos["sub"]))
    cuenta = (
        db.query(models.CuentaSocio)
        .filter(models.CuentaSocio.socio_id_socio == int(datos["sub"]))
        .first()
    )
    if socio is None or cuenta is None or not cuenta.estado:
        raise HTTPException(status_code=403, detail="Cuenta de socio inexistente o desactivada")
    return socio
