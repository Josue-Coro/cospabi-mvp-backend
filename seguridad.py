"""Seguridad: contrasenas cifradas con bcrypt y sesiones con tokens JWT."""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import models
from database import get_db

SECRET_KEY = os.getenv("SECRET_KEY", "")
ALGORITHM = "HS256"
HORAS_TOKEN = 2

if len(SECRET_KEY) < 32:
    raise RuntimeError("Falta SECRET_KEY en el archivo .env (minimo 32 caracteres).")

# Hace que Swagger muestre el boton "Authorize" para pegar el token
esquema_bearer = HTTPBearer(auto_error=False)


def cifrar_contrasena(contrasena: str) -> str:
    return bcrypt.hashpw(contrasena.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_contrasena(contrasena: str, contrasena_cifrada: str) -> bool:
    try:
        return bcrypt.checkpw(contrasena.encode("utf-8"), contrasena_cifrada.encode("utf-8"))
    except ValueError:
        return False


def crear_token(usuario: models.UsuarioAdmin) -> str:
    datos = {
        "sub": str(usuario.id_usuario_admin),
        "usuario": usuario.usuario,
        "rol": usuario.rol.nombre,
        "exp": datetime.now(timezone.utc) + timedelta(hours=HORAS_TOKEN),
    }
    return jwt.encode(datos, SECRET_KEY, algorithm=ALGORITHM)


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(esquema_bearer),
    db: Session = Depends(get_db),
) -> models.UsuarioAdmin:
    """Dependencia que protege los endpoints: exige un token valido."""
    if credenciales is None:
        raise HTTPException(status_code=401, detail="Token no proporcionado")

    try:
        datos = jwt.decode(credenciales.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Token inválido o expirado")

    usuario = db.get(models.UsuarioAdmin, int(datos["sub"]))
    if usuario is None or not usuario.estado:
        raise HTTPException(status_code=403, detail="Usuario inexistente o desactivado")
    return usuario
