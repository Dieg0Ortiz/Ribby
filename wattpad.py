"""
wattpad.py — Cliente mínimo de la API pública de Wattpad.

La API (api/v3) no es oficial ni está documentada: si Wattpad la cambia,
las funciones devuelven None / listas vacías y el resto del bot sigue
funcionando con los datos que ya tiene guardados.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import aiohttp

log = logging.getLogger("bot-literario.wattpad")

_BASE = "https://www.wattpad.com/api/v3"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RibbyBot/1.0)"}
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_CAMPOS_HISTORIA = (
    "id,title,url,user(name,username),tags,description,readCount,voteCount,"
    "numParts,completed,mature,cover"
)

# Formatos de enlace aceptados
_RE_HISTORIA = re.compile(r"wattpad\.com/story/(\d+)", re.I)
_RE_CAPITULO = re.compile(r"wattpad\.com/(\d+)(?:-[\w%-]*)?(?:[/?#]|$)", re.I)
_RE_LISTA = re.compile(r"wattpad\.com/list/(\d+)", re.I)
_RE_USUARIO = re.compile(r"wattpad\.com/user/([\w.-]+)", re.I)
RE_URL_WATTPAD = re.compile(r"https?://(?:www\.|m\.)?wattpad\.com/\S+", re.I)


def extraer_urls(texto: str) -> list[str]:
    """Todas las URLs de Wattpad de un texto (sin signos de puntuación finales)."""
    return [u.rstrip(").,>!?¿¡\"'") for u in RE_URL_WATTPAD.findall(texto or "")]


def id_lista(url: str) -> Optional[str]:
    m = _RE_LISTA.search(url or "")
    return m.group(1) if m else None


def usuario_de_url(valor: str) -> Optional[str]:
    """Username de Wattpad a partir de un link de perfil o de un '@usuario'/'usuario' suelto."""
    valor = (valor or "").strip()
    m = _RE_USUARIO.search(valor)
    if m:
        return m.group(1)
    if re.fullmatch(r"@?[\w.-]{2,40}", valor):
        return valor.lstrip("@")
    return None


async def _get_json(session: aiohttp.ClientSession, url: str, params: dict | None = None) -> Optional[dict]:
    try:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                log.info(f"Wattpad {resp.status} en {url}")
                return None
            return await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as e:
        log.warning(f"Error consultando Wattpad ({url}): {e}")
        return None


def _normalizar(raw: dict[str, Any]) -> dict[str, Any]:
    """Convierte la respuesta de la API al formato que guarda Ribby."""
    user = raw.get("user") or {}
    return {
        "wattpad_id": str(raw.get("id")),
        "titulo": (raw.get("title") or "").strip() or "Sin título",
        "autor_nombre": user.get("name") or user.get("username"),
        "autor_wattpad": user.get("username"),
        "descripcion": (raw.get("description") or "").strip() or None,
        "url": raw.get("url") or f"https://www.wattpad.com/story/{raw.get('id')}",
        "portada_url": raw.get("cover"),
        "lecturas": raw.get("readCount"),
        "votos": raw.get("voteCount"),
        "partes": raw.get("numParts"),
        "completada": raw.get("completed"),
        "madura": bool(raw.get("mature")),
        "tags": [t.strip().lower() for t in (raw.get("tags") or []) if t and t.strip()],
    }


async def obtener_historia(story_id: str) -> Optional[dict[str, Any]]:
    async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as s:
        data = await _get_json(s, f"{_BASE}/stories/{story_id}", {"fields": _CAMPOS_HISTORIA})
    return _normalizar(data) if data and data.get("id") else None


async def historia_desde_url(url: str) -> Optional[dict[str, Any]]:
    """Acepta un link de historia o de un capítulo concreto."""
    m = _RE_HISTORIA.search(url or "")
    if m:
        return await obtener_historia(m.group(1))

    m = _RE_CAPITULO.search(url or "")
    if m:
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as s:
            parte = await _get_json(s, f"{_BASE}/story_parts/{m.group(1)}", {"fields": "groupId"})
        if parte and parte.get("groupId"):
            return await obtener_historia(str(parte["groupId"]))
    return None


async def historias_de_lista(list_id: str) -> list[dict[str, Any]]:
    """Todas las historias accesibles de una lista de lectura (paginando)."""
    resultado: list[dict[str, Any]] = []
    url: Optional[str] = f"{_BASE}/lists/{list_id}/stories"
    params: Optional[dict] = {"limit": 20, "offset": 0, "fields": f"stories({_CAMPOS_HISTORIA}),nextUrl"}
    async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as s:
        for _ in range(50):  # Tope de seguridad: 1000 historias
            data = await _get_json(s, url, params)  # type: ignore[arg-type]
            if not data:
                break
            resultado += [_normalizar(r) for r in data.get("stories", []) if r.get("id")]
            url, params = data.get("nextUrl"), None
            if not url:
                break
    return resultado


async def historias_de_usuario(username: str) -> list[dict[str, Any]]:
    """Historias públicas de un autor de Wattpad (paginando)."""
    from urllib.parse import quote

    resultado: list[dict[str, Any]] = []
    url: Optional[str] = f"{_BASE}/users/{quote(username, safe='')}/stories"
    params: Optional[dict] = {"limit": 50, "offset": 0, "fields": f"stories({_CAMPOS_HISTORIA}),nextUrl"}
    async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as s:
        for _ in range(20):  # Tope de seguridad: 1000 historias
            data = await _get_json(s, url, params)  # type: ignore[arg-type]
            if not data:
                break
            resultado += [_normalizar(r) for r in data.get("stories", []) if r.get("id")]
            url, params = data.get("nextUrl"), None
            if not url:
                break
    return resultado


async def nombres_pokemon() -> set[str]:
    """Nombres de las especies Pokémon (PokeAPI), en minúsculas. Vacío si falla."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.get("https://pokeapi.co/api/v2/pokemon-species", params={"limit": 2000}) as r:
                if r.status != 200:
                    return set()
                data = await r.json()
        nombres = set()
        for x in data.get("results", []):
            n = x["name"]
            nombres.add(n)
            nombres.add(n.replace("-", " "))  # "mr-mime" → "mr mime"
            nombres.add(n.replace("-", ""))   # → "mrmime"
        return nombres
    except Exception as e:  # noqa: BLE001
        log.warning(f"No se pudo descargar la lista de Pokémon: {e}")
        return set()
