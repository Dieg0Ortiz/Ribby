"""
conversacion.py — Memoria de corto plazo de Ribby: todo lo que se dice en cada canal.

Antes Ribby solo recordaba sus propios intercambios con la persona que le
hablaba, así que negaba cosas que sí habían pasado: las tarjetas que mostró la
biblioteca, lo que otro usuario dijo un minuto antes o lo que ella misma le
contestó a otra persona. Ahora cada canal guarda en memoria sus últimos
mensajes (de todos, incluida Ribby con sus tarjetas y embeds) y con ellos se
construye la conversación que recibe la IA.

Este módulo no depende de discord.py (usa "duck typing" sobre los mensajes)
para poder probarlo sin red.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Iterable, Optional

MAX_ENTRADAS_CANAL = 40           # Mensajes recordados por canal
MAX_CANALES = 300                 # Canales en memoria (se descartan los menos activos)
VENTANA_SEGUNDOS = 60 * 60        # Lo más antiguo que se le pasa a la IA
MAX_CARACTERES_ENTRADA = 450      # Recorte por mensaje
PRESUPUESTO_CARACTERES = 4500     # Tope de toda la conversación enviada a la IA
_MAX_EMBEDS = 4

ROL_USUARIO = "user"
ROL_RIBBY = "ribby"


@dataclass
class Entrada:
    mensaje_id: int
    autor_id: int
    autor: str
    texto: str
    momento: float                      # time.time()
    es_ribby: bool = False
    responde_a: Optional[int] = None    # ID del mensaje al que responde
    nota: str = ""                      # Ej. "usó un comando de Ribby"


# ─────────────────────────── Texto de un mensaje ───────────────────────────

_RE_MARKDOWN = re.compile(r"(\*\*|__|~~|\|\||```|`|^>>> |^> )", re.M)


def _limpiar_markdown(texto: str) -> str:
    texto = _RE_MARKDOWN.sub("", texto or "")
    texto = texto.replace("\\", "")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", texto)).strip()


def recortar(texto: str, limite: int = MAX_CARACTERES_ENTRADA) -> str:
    texto = (texto or "").strip()
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def resumir_embed(embed: Any) -> str:
    """Una tarjeta/embed en una línea: lo que la gente vio en el canal."""
    titulo = _limpiar_markdown(getattr(embed, "title", None) or "")
    desc = _limpiar_markdown(getattr(embed, "description", None) or "")
    autor = getattr(getattr(embed, "author", None), "name", None) or ""
    partes = []
    if titulo:
        partes.append(f"«{titulo}»")
    if desc:
        partes.append(recortar(desc.replace("\n", " "), 260))
    if not partes:
        campos = [f"{_limpiar_markdown(f.name)}: {_limpiar_markdown(f.value)}" for f in (getattr(embed, "fields", None) or [])[:2]]
        partes += [recortar(c, 120) for c in campos if c.strip(": ")]
    if not partes and autor:
        partes.append(autor)
    return f"[tarjeta: {' — '.join(partes)}]" if partes else ""


def texto_de_mensaje(message: Any) -> str:
    """Texto legible de un mensaje de Discord: contenido, tarjetas y adjuntos."""
    partes: list[str] = []
    contenido = (getattr(message, "clean_content", None) or getattr(message, "content", "") or "").strip()
    if contenido:
        partes.append(contenido)
    for e in (getattr(message, "embeds", None) or [])[:_MAX_EMBEDS]:
        r = resumir_embed(e)
        if r:
            partes.append(r)
    adjuntos = getattr(message, "attachments", None) or []
    if adjuntos:
        partes.append("[adjuntó: " + ", ".join(str(getattr(a, "filename", "archivo")) for a in adjuntos[:3]) + "]")
    stickers = getattr(message, "stickers", None) or []
    if stickers:
        partes.append("[sticker: " + ", ".join(str(getattr(s, "name", "")) for s in stickers[:2]) + "]")
    return recortar("\n".join(partes))


def entrada_de_mensaje(message: Any, ribby_id: Optional[int]) -> Entrada:
    autor = message.author
    es_ribby = ribby_id is not None and autor.id == ribby_id
    nota = ""
    meta = getattr(message, "interaction_metadata", None)
    usuario_cmd = getattr(meta, "user", None)
    if es_ribby and usuario_cmd is not None:
        nota = f"respuesta a un comando de {getattr(usuario_cmd, 'display_name', None) or usuario_cmd.name}"
    referencia = getattr(message, "reference", None)
    creado = getattr(message, "created_at", None)
    return Entrada(
        mensaje_id=message.id,
        autor_id=autor.id,
        autor="Ribby" if es_ribby else (getattr(autor, "display_name", None) or autor.name),
        texto=texto_de_mensaje(message),
        momento=creado.timestamp() if creado else time.time(),
        es_ribby=es_ribby,
        responde_a=getattr(referencia, "message_id", None),
        nota=nota,
    )


# ─────────────────────────── Memoria por canal ───────────────────────────

class MemoriaCanales:
    """Últimos mensajes de cada canal, en RAM (se reconstruye leyendo el historial tras reiniciar)."""

    def __init__(self, max_entradas: int = MAX_ENTRADAS_CANAL, max_canales: int = MAX_CANALES):
        self.max_entradas = max_entradas
        self.max_canales = max_canales
        self._canales: "OrderedDict[int, deque[Entrada]]" = OrderedDict()

    def _canal(self, canal_id: int) -> "deque[Entrada]":
        if canal_id in self._canales:
            self._canales.move_to_end(canal_id)
        else:
            while len(self._canales) >= self.max_canales:
                self._canales.popitem(last=False)
            self._canales[canal_id] = deque(maxlen=self.max_entradas)
        return self._canales[canal_id]

    def tiene(self, canal_id: int) -> bool:
        return canal_id in self._canales

    def registrar(self, canal_id: int, entrada: Entrada) -> None:
        if not entrada.texto:
            return
        canal = self._canal(canal_id)
        if any(e.mensaje_id == entrada.mensaje_id for e in canal):
            return
        canal.append(entrada)

    def sembrar(self, canal_id: int, entradas: Iterable[Entrada]) -> None:
        """Mezcla mensajes leídos del historial de Discord con los ya recordados."""
        canal = self._canal(canal_id)
        por_id = {e.mensaje_id: e for e in canal}
        for e in entradas:
            if e.texto:
                por_id.setdefault(e.mensaje_id, e)
        canal.clear()
        canal.extend(sorted(por_id.values(), key=lambda e: e.momento)[-self.max_entradas:])

    def editar(self, canal_id: int, mensaje_id: int, texto: str) -> None:
        for e in self._canales.get(canal_id, ()):
            if e.mensaje_id == mensaje_id:
                e.texto = texto

    def borrar(self, canal_id: int, mensaje_id: int) -> None:
        canal = self._canales.get(canal_id)
        if canal is not None:
            restantes = [e for e in canal if e.mensaje_id != mensaje_id]
            canal.clear()
            canal.extend(restantes)

    def olvidar_autor(self, autor_id: int) -> None:
        """Quita de todos los canales lo que dijo una persona (/ribby olvidar)."""
        for canal in self._canales.values():
            restantes = [e for e in canal if e.autor_id != autor_id]
            canal.clear()
            canal.extend(restantes)

    def buscar(self, canal_id: int, mensaje_id: Optional[int]) -> Optional[Entrada]:
        if mensaje_id is None:
            return None
        return next((e for e in self._canales.get(canal_id, ()) if e.mensaje_id == mensaje_id), None)

    def recientes(
        self, canal_id: int, ahora: Optional[float] = None, excluir_id: Optional[int] = None,
        ventana: float = VENTANA_SEGUNDOS,
    ) -> list[Entrada]:
        ahora = ahora if ahora is not None else time.time()
        return [
            e for e in self._canales.get(canal_id, ())
            if e.mensaje_id != excluir_id and ahora - e.momento <= ventana
        ]

    def limpiar(self) -> None:
        self._canales.clear()


def participantes(entradas: Iterable[Entrada], excluir: Iterable[int] = (), limite: int = 5) -> list[tuple[int, str]]:
    """Personas que hablaron (las más recientes primero), sin Ribby ni los excluidos."""
    vistos: set[int] = set(excluir)
    resultado: list[tuple[int, str]] = []
    for e in reversed(list(entradas)):
        if e.es_ribby or e.autor_id in vistos:
            continue
        vistos.add(e.autor_id)
        resultado.append((e.autor_id, e.autor))
        if len(resultado) >= limite:
            break
    return resultado


# ─────────────────────────── Conversación para la IA ───────────────────────────

def _hace(segundos: float) -> str:
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"hace {minutos} min"
    return f"hace {minutos // 60} h"


def _linea_usuario(e: Entrada, por_id: dict[int, Entrada], ahora: float, marca: str = "") -> str:
    contexto = []
    if ahora - e.momento >= 5 * 60:
        contexto.append(_hace(ahora - e.momento))
    if e.responde_a is not None:
        ref = por_id.get(e.responde_a)
        if ref is not None:
            if ref.es_ribby:
                contexto.append("respondiendo a tu mensaje")
            else:
                contexto.append(f"respondiendo a {ref.autor}: «{recortar(ref.texto, 80)}»")
    extra = f" ({'; '.join(contexto)})" if contexto else ""
    return f"{marca}{e.autor}{extra}: {e.texto}"


def _linea_ribby(e: Entrada) -> str:
    # Sin las acotaciones de narrador de sus mensajes viejos, la IA no las imita
    texto = quitar_accion_inicial(e.texto) if e.es_ribby else e.texto
    return f"[{e.nota}]\n{texto}" if e.nota else texto


def mensajes_para_ia(
    entradas: list[Entrada], actual: Entrada, ahora: Optional[float] = None,
    contexto_respuesta: str = "", presupuesto: int = PRESUPUESTO_CARACTERES,
) -> list[dict[str, str]]:
    """
    Convierte la conversación del canal en el historial que entienden los
    proveedores: turnos "user" (con el nombre de cada persona delante) y
    turnos "ribby" (lo que ella dijo o mostró), alternados. El último turno
    siempre es el mensaje al que Ribby responde ahora, marcado con "»".
    """
    ahora = ahora if ahora is not None else time.time()
    por_id = {e.mensaje_id: e for e in entradas}
    por_id[actual.mensaje_id] = actual

    final = _linea_usuario(actual, por_id, ahora, marca="» ")
    if contexto_respuesta:
        final = f"{final}\n{contexto_respuesta}"

    # Se descartan los mensajes más antiguos hasta que todo quepa en el presupuesto
    lineas: list[tuple[str, str]] = [
        (ROL_RIBBY, _linea_ribby(e)) if e.es_ribby else (ROL_USUARIO, _linea_usuario(e, por_id, ahora))
        for e in entradas if e.mensaje_id != actual.mensaje_id
    ]
    total = len(final)
    inicio = len(lineas)
    while inicio > 0 and total + len(lineas[inicio - 1][1]) + 1 <= presupuesto:
        inicio -= 1
        total += len(lineas[inicio][1]) + 1
    lineas = lineas[inicio:] + [(ROL_USUARIO, final)]

    mensajes: list[dict[str, str]] = []
    for rol, texto in lineas:
        if mensajes and mensajes[-1]["role"] == rol:
            mensajes[-1]["content"] += "\n" + texto
        else:
            mensajes.append({"role": rol, "content": texto})
    if mensajes[0]["role"] != ROL_USUARIO:
        mensajes.insert(0, {"role": ROL_USUARIO, "content": "(La conversación del canal ya estaba en marcha.)"})
    return mensajes


def transcripcion(entradas: Iterable[Entrada]) -> str:
    """Texto plano de la conversación (para los resúmenes de memoria)."""
    return "\n".join(f"{e.autor}: {e.texto}" for e in entradas)


# ─────────────────────────── Relaciones entre usuarios ───────────────────────────

def par(a: Any, b: Any) -> tuple[str, str]:
    """Clave de una pareja de usuarios, igual en los dos sentidos."""
    x, y = str(a), str(b)
    return (x, y) if x < y else (y, x)


def interlocutores(entrada: Entrada, mencionados: Iterable[int], memoria_canal: list[Entrada],
                   ribby_id: Optional[int]) -> set[int]:
    """A quién se dirige una persona en un mensaje: a quien responde y a quien menciona (sin Ribby ni ella misma)."""
    otros = {m for m in mencionados}
    if entrada.responde_a is not None:
        ref = next((e for e in memoria_canal if e.mensaje_id == entrada.responde_a), None)
        if ref is not None and not ref.es_ribby:
            otros.add(ref.autor_id)
    otros.discard(entrada.autor_id)
    if ribby_id is not None:
        otros.discard(ribby_id)
    return otros


# ─────────────────────────── Marcas de acción en la respuesta ───────────────────────────
#
# La IA no tiene herramientas (hay varios proveedores de respaldo), así que pide
# acciones con marcas que el bot interpreta y quita del texto:
#   [[SILENCIO]]               → mejor no decir nada (intervenciones espontáneas)
#   [[REACCION: 📚]]           → reaccionar al mensaje con ese emoji
#   [[RECOMENDAR: misterio]]   → mostrar tarjetas de la biblioteca con esa búsqueda

_RE_MARCA = re.compile(r"\[\[\s*(SILENCIO|REACCI[OÓ]N|RECOMENDAR)\s*(?::\s*([^\]]*))?\]\]", re.I)


@dataclass
class Marcas:
    silencio: bool = False
    reaccion: str = ""
    recomendar: Optional[str] = None


def extraer_marcas(texto: str) -> tuple[str, Marcas]:
    marcas = Marcas()
    for m in _RE_MARCA.finditer(texto or ""):
        tipo, valor = m.group(1).upper(), (m.group(2) or "").strip()
        if tipo == "SILENCIO":
            marcas.silencio = True
        elif tipo.startswith("REACCI") and valor and not marcas.reaccion:
            marcas.reaccion = valor.split()[0][:16]
        elif tipo == "RECOMENDAR" and marcas.recomendar is None:
            marcas.recomendar = valor[:200]
    limpio = re.sub(r"[ \t]+\n", "\n", _RE_MARCA.sub("", texto or "")).strip()
    return limpio, marcas


# ─────────────────────────── Limpieza de la respuesta ───────────────────────────

_RE_ACOTACION = re.compile(r"^\s*(\*[^*\n]+\*|_[^_\n]+_)\s*$")
_RE_PREFIJO = re.compile(r"^\s*(\*\*)?Ribby(\s*\(tú\))?(\*\*)?\s*:\s*", re.I)
# "*Ribby se pone roja hasta las orejas* ¡Tainy!..." → acotación de narrador pegada al principio del mensaje
_RE_ACCION_INICIAL = re.compile(r"^\s*(\*|_)(?:Ribby|Ella)\b[^*_\n]{3,200}\1\s*", re.I)


def quitar_accion_inicial(texto: str) -> str:
    limpio = _RE_ACCION_INICIAL.sub("", texto or "", count=1)
    return limpio if limpio.strip() else (texto or "")


def limpiar_respuesta(texto: str) -> str:
    """
    Quita lo que la IA a veces añade imitando el formato de la conversación:
    acotaciones en cursiva en líneas sueltas ("*Ribby parpadea...*"), su propio
    nombre delante o notas entre corchetes al principio.
    """
    lineas = [l for l in (texto or "").strip().split("\n") if not _RE_ACOTACION.match(l)]
    while lineas and (not lineas[0].strip() or re.match(r"^\s*\[[^\]]*\]\s*$", lineas[0])):
        lineas.pop(0)
    limpio = _RE_PREFIJO.sub("", re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip(), count=1).strip()
    limpio = quitar_accion_inicial(limpio).strip()
    return limpio or (texto or "").strip()
