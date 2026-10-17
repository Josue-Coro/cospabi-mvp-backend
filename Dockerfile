# Imagen de la API de COSPABI R.L. para desplegar en Render (o cualquier servidor con Docker)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Primero las dependencias, para reutilizar la capa si solo cambia el codigo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# La API no corre como root dentro del contenedor
RUN useradd --create-home cospabi
USER cospabi

# Render indica el puerto en la variable PORT; en local se usa 8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
