"""Prueba rápida de cuota: envía 'Hola' a varios modelos con la primera llave de Gemini."""
from google import genai

import config

client = genai.Client(api_key=config.GEMINI_API_KEY)
models_to_test = ["gemini-2.5-flash", "gemini-2.5-flash-lite", config.GEMINI_MODEL]

for m in dict.fromkeys(models_to_test):
    try:
        res = client.models.generate_content(model=m, contents="Hola")
        print(f"{m} SUCCESS: {res.text}")
    except Exception as e:
        print(f"{m} ERROR: {e}")
