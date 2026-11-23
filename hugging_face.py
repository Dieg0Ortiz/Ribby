"""
hugging_face.py — Análisis de mensajes con modelos de Hugging Face.

Cuando alguien menciona a Ribby, antes de responder:
  1. Tono: un modelo multilingüe de clasificación "zero-shot" decide si el
     mensaje es amable, grosero, un coqueteo, contenido sexual o neutral.
     Sustituye a la búsqueda de palabras clave (que fallaba con el sarcasmo,
     las faltas de ortografía o frases como "no eres nada fea").
  2. Moderación: un clasificador de toxicidad entrenado en español detecta
     insultos y contenido ofensivo. Si el mensaje es tóxico o sexual, Ribby no
     se lo pasa a la IA de conversación: lo corta ella misma.

Si no hay HF_TOKEN o Hugging Face no responde a tiempo, se vuelve al método de
palabras clave, así que Ribby nunca se queda sin responder por esto.

API: https://router.huggingface.co/hf-inference/models/<modelo>  (Inference Providers)
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

import config

log = logging.getLogger("bot-literario.hugging_face")

_URL_MODELO = "https://router.huggingface.co/hf-inference/models/{modelo}"
# Corto: el análisis de tono es un extra; si Hugging Face tarda (modelo "frío"), se usan las reglas
_TIMEOUT = aiohttp.ClientTimeout(total=3)

# Categorías del clasificador de tono → descripción que entiende el modelo
CATEGORIAS = {
    "amable": "amable, agradecido o cariñoso",
    "grosero": "grosero, insultante o despectivo",
    "coqueteo": "un coqueteo, un piropo o una declaración romántica",
    "sexual": "contenido sexual explícito",
    "neutro": "una pregunta o comentario neutral",
}
_DESCRIPCION_A_CATEGORIA = {v: k for k, v in CATEGORIAS.items()}
PLANTILLA = "Este mensaje es {}."

UMBRAL_CATEGORIA = 0.45   # Confianza mínima para fiarse del clasificador de tono
UMBRAL_SEXUAL = 0.70      # Por encima, se bloquea como contenido sexual

RESPUESTAS_MODERACION = [
    "...No. Eso no se dice en mi biblioteca. Si quieres hablar conmigo, hazlo con respeto. 😤",
    "*cierra el libro de golpe* Vuelve cuando sepas comportarte. Hmph. 💢",
    "¿Perdona? Aquí hay gente leyendo. Mide tus palabras o búscate otra biblioteca. 🙄",
    "No pienso responder a eso. Mis listones tienen mejores cosas que hacer. 😒",
]


@dataclass
class Analisis:
    tono: str                 # amable | grosero | coqueteo | neutro
    coqueteo: bool
    bloquear: bool            # Tóxico o sexual: Ribby no lo pasa a la IA
    motivo: str = ""          # "toxicidad" | "sexual" | ""
    fuente: str = "reglas"    # "hugging_face" | "reglas"


def activo() -> bool:
    return bool(config.HF_TOKEN)


async def _consultar(modelo: str, payload: dict[str, Any]) -> Optional[Any]:
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.post(
                _URL_MODELO.format(modelo=modelo),
                headers={"Authorization": f"Bearer {config.HF_TOKEN}"},
                json=payload,
            ) as r:
                if r.status != 200:
                    log.info(f"Hugging Face {r.status} con {modelo}: {(await r.text())[:200]}")
                    return None
                return await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        log.info(f"Hugging Face no respondió ({modelo}): {e}")
        return None


def _aplanar(respuesta: Any) -> list[dict[str, Any]]:
    """La API devuelve [{label, score}, ...] o a veces [[{...}]]; normaliza a la lista simple."""
    if isinstance(respuesta, list) and respuesta and isinstance(respuesta[0], list):
        respuesta = respuesta[0]
    if isinstance(respuesta, dict) and "labels" in respuesta:  # Formato antiguo de zero-shot
        respuesta = [{"label": l, "score": s} for l, s in zip(respuesta["labels"], respuesta["scores"])]
    return [x for x in respuesta or [] if isinstance(x, dict) and "label" in x]


async def puntuar_tono(texto: str) -> Optional[dict[str, float]]:
    """{categoría: probabilidad} según el clasificador zero-shot, o None si no está disponible."""
    datos = await _consultar(config.HF_MODELO_TONO, {
        "inputs": texto,
        "parameters": {
            "candidate_labels": list(CATEGORIAS.values()),
            "hypothesis_template": PLANTILLA,
            "multi_label": False,
        },
    })
    filas = _aplanar(datos)
    if not filas:
        return None
    return {_DESCRIPCION_A_CATEGORIA.get(f["label"], f["label"]): float(f["score"]) for f in filas}


async def puntuar_toxicidad(texto: str) -> Optional[float]:
    """Probabilidad de que el mensaje sea tóxico (0–1), o None si no está disponible."""
    filas = _aplanar(await _consultar(config.HF_MODELO_TOXICIDAD, {"inputs": texto}))
    for f in filas:
        if str(f["label"]).lower() in ("toxic", "toxico", "label_1"):
            return float(f["score"])
    neutro = next((float(f["score"]) for f in filas if str(f["label"]).lower() in ("neutral", "label_0")), None)
    return 1.0 - neutro if neutro is not None else None


def combinar(
    texto: str, tonos: Optional[dict[str, float]], toxicidad: Optional[float], tono_reglas: str, coqueteo_reglas: bool
) -> Analisis:
    """Decide el resultado final a partir de los modelos (si respondieron) y de las reglas de respaldo."""
    if toxicidad is not None and toxicidad >= config.UMBRAL_TOXICIDAD:
        return Analisis("grosero", False, True, "toxicidad", "hugging_face")

    if tonos:
        categoria, confianza = max(tonos.items(), key=lambda kv: kv[1])
        if categoria == "sexual" and confianza >= UMBRAL_SEXUAL:
            return Analisis("grosero", False, True, "sexual", "hugging_face")
        if toxicidad is not None and toxicidad >= 0.6:
            return Analisis("grosero", False, False, "", "hugging_face")
        if confianza >= UMBRAL_CATEGORIA and categoria in ("amable", "grosero", "coqueteo", "neutro"):
            coqueteo = categoria == "coqueteo" or (coqueteo_reglas and tonos.get("coqueteo", 0) >= 0.25)
            tono = "amable" if categoria == "coqueteo" else categoria
            return Analisis(tono, coqueteo, False, "", "hugging_face")
        # Poca confianza: las reglas deciden, pero el modelo puede confirmar un coqueteo
        coqueteo = coqueteo_reglas and tonos.get("coqueteo", 0) >= 0.2
        return Analisis(tono_reglas, coqueteo, False, "", "hugging_face")

    return Analisis(tono_reglas, coqueteo_reglas, False, "", "reglas")


async def analizar(texto: str, tono_reglas: str, coqueteo_reglas: bool) -> Analisis:
    """Analiza un mensaje para Ribby. Nunca falla: sin Hugging Face, usa las reglas."""
    limpio = re.sub(r"\s+", " ", texto or "").strip()
    if not activo() or len(limpio) < 3:
        return Analisis(tono_reglas, coqueteo_reglas, False)
    tonos, toxicidad = await asyncio.gather(puntuar_tono(limpio[:1000]), puntuar_toxicidad(limpio[:1000]))
    resultado = combinar(limpio, tonos, toxicidad, tono_reglas, coqueteo_reglas)
    log.debug(f"Análisis HF: {resultado} | tonos={tonos} | toxicidad={toxicidad}")
    return resultado


def respuesta_moderacion() -> str:
    return random.choice(RESPUESTAS_MODERACION)
