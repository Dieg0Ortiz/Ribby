# Dockerfile para Ribby — Bot Literario en Hugging Face Spaces
FROM python:3.11-slim

# Crear usuario no-root (requerido por HF Spaces)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Instalar dependencias
COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copiar el código del bot
COPY --chown=user . /app

# HF Spaces expone el puerto 7860 por defecto
ENV PORT=7860

# Ejecutar el bot
CMD ["python", "main.py"]
