"""
afinidad.py — El "medidor de corazones" de Ribby (lógica pura, sin Discord ni BD).

Cada usuario tiene de 0 a 100 corazones con Ribby. Según los corazones (y lo
que haya pasado entre ambos) Ribby lo ve como:

    desconocido → amigo → mejor amigo → algo más → enamorada → pareja

Reglas principales:
  - Solo se ganan corazones con un tope diario (no se puede farmear con spam).
    Charlando a diario, llegar al máximo lleva ~1 mes.
  - Para pasar de "mejor amigo" hay que haber coqueteado varias veces.
  - Al llegar a 100 Ribby queda "enamorada" y da pistas, pero NO es pareja
    hasta que el usuario se lo pida. Si pasan 7 días sin declararse, el
    interés se enfría y vuelven a ser amigos.
  - Ribby solo puede tener UNA pareja. Mientras la tenga, los demás no pasan
    de "algo más" y ella no les corresponde.
  - Si la pareja desaparece mucho tiempo, la relación se enfría y termina en
    buenos términos (sin culpas ni dramas).

El estado de un usuario es un dict con las claves de ESTADO_INICIAL.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ─────────────────────────── Configuración ───────────────────────────

MAX_CORAZONES = 100.0
TOPE_DIARIO_CHARLA = 2.5       # corazones/día por conversación (~40 días solo charlando)
TOPE_SI_OCUPADA = 90.0         # si Ribby ya tiene pareja, los demás no pasan de aquí
COQUETEOS_PARA_ALGO_MAS = 5    # coqueteos necesarios para superar "mejor amigo"
DIAS_INTERES_MAXIMO = 7        # días al máximo sin declararse antes de enfriarse
DIAS_INACTIVIDAD = 14          # a partir de aquí se pierde 1 corazón por día
DIAS_PAREJA_EXTRAÑA = 10       # la pareja lleva días sin aparecer: Ribby lo nota
DIAS_PAREJA_TERMINA = 30       # la relación se enfría y termina en buenos términos
HORAS_ENTRE_DECLARACIONES = 24
MAX_EVENTOS = 20

PUNTOS = {"grosero": -2.0, "neutro": 0.4, "amable": 0.8, "coqueteo": 1.0}

NIVELES = {
    "desconocido": ("Desconocido", "👤"),
    "amigo": ("Amigo", "🤝"),
    "mejor_amigo": ("Mejor amigo", "💛"),
    "algo_mas": ("Algo más que amigos", "💗"),
    "enamorada": ("Algo más que amigos", "💘"),  # Se muestra igual: lo de "enamorada" es un secreto
    "pareja": ("Pareja", "💞"),
    "creador": ("Familia — su creador", "👨‍👧"),  # Tainy: Ribby le quiere como a un padre
}

ESTADO_INICIAL: dict[str, Any] = {
    "corazones": 0.0,
    "es_pareja": False,
    "fecha_inicio_pareja": None,
    "racha_dias": 0,
    "ultima_interaccion": None,   # ISO datetime
    "total_interacciones": 0,
    "eventos": [],                # [{"fecha": "YYYY-MM-DD", "tipo": str, "texto": str}]
    "corazones_hoy": 0.0,
    "dia_corazones": None,        # YYYY-MM-DD del contador diario
    "coqueteos": 0,
    "fecha_maximo": None,         # ISO datetime en que llegó a 100
    "ultimo_regalo": None,        # YYYY-MM-DD
    "ultima_cita": None,          # YYYY-MM-DD
    "ultima_declaracion": None,   # ISO datetime
    "dias_descontados": 0,        # días de inactividad ya cobrados (se reinicia al hablar)
    "citas_total": 0,
    "regalos_total": 0,
    "quiz_aciertos": 0,
}

# Hora del servidor (México, sin horario de verano): define cuándo empieza "un nuevo día"
ZONA = timezone(timedelta(hours=-6))


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def _dia(momento: datetime) -> str:
    return momento.astimezone(ZONA).date().isoformat()


def _dt(valor: Optional[str]) -> Optional[datetime]:
    if not valor:
        return None
    d = datetime.fromisoformat(valor)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def dias_desde(valor: Optional[str], momento: Optional[datetime] = None) -> int:
    inicio = _dt(valor)
    return ((momento or ahora()) - inicio).days if inicio else 0


def nuevo_estado() -> dict[str, Any]:
    e = dict(ESTADO_INICIAL)
    e["eventos"] = []
    return e


def registrar_evento(estado: dict[str, Any], tipo: str, texto: str, momento: Optional[datetime] = None) -> None:
    estado.setdefault("eventos", []).append({"fecha": _dia(momento or ahora()), "tipo": tipo, "texto": texto})
    estado["eventos"] = estado["eventos"][-MAX_EVENTOS:]


# ─────────────────────────── Niveles ───────────────────────────

def nivel(estado: dict[str, Any], ocupada_por_otro: bool = False) -> str:
    if estado.get("es_creador"):
        return "creador"
    if estado.get("es_pareja"):
        return "pareja"
    c = float(estado.get("corazones") or 0)
    if c >= MAX_CORAZONES and not ocupada_por_otro:
        return "enamorada"
    if c >= 75:
        return "algo_mas"
    if c >= 45:
        return "mejor_amigo"
    if c >= 15:
        return "amigo"
    return "desconocido"


def tope(estado: dict[str, Any], ocupada_por_otro: bool) -> float:
    """Máximo de corazones que puede tener ahora mismo."""
    if estado.get("es_pareja"):
        return MAX_CORAZONES
    if (estado.get("coqueteos") or 0) < COQUETEOS_PARA_ALGO_MAS:
        return 74.0  # Sin coqueteo no pasa de mejor amigo
    return TOPE_SI_OCUPADA if ocupada_por_otro else MAX_CORAZONES


def barra(corazones: float, total: int = 10) -> str:
    llenos = int(round(max(0.0, min(corazones, MAX_CORAZONES)) / MAX_CORAZONES * total))
    return "💗" * llenos + "🤍" * (total - llenos)


# ─────────────────────────── Detección en el texto ───────────────────────────

_RE_COQUETEO = re.compile(
    r"\bte quiero\b|\bte amo\b|me gustas|me encantas|\bguap[ao]\b|\bhermosa\b|\bpreciosa\b|\bbonita\b|"
    r"\blinda\b|\bcute\b|\bcuqui\b|\bmi amor\b|\bcari[ñn]o\b|\bcoraz[oó]n\b|\bbesit|\bbeso\b|\babrazo\b|"
    r"\bcita\b|enamorad|\bcrush\b|\bmi reina\b|\bmi vida\b|\bte extra[ñn]|\bpiropo|\b(uwu|owo)\b|[❤💕💖💗💘💞😘😍🥰]",
    re.I,
)
_RE_DECLARACION = re.compile(
    r"(quieres|quisieras|aceptar[ií]as|te gustar[ií]a) (ser|que seamos) (mi (novi[oa]|pareja)|novi[oa]s|pareja)\b|"
    r"\bs[eé] mi (novia|pareja)\b|\bseamos (novi[oa]s|pareja)\b|"
    r"(quieres|quisieras) (andar|salir) conmigo|me aceptas como tu (novio|novia|pareja)|"
    r"(ser|seas) mi novia",
    re.I,
)


def es_coqueteo(texto: str) -> bool:
    return bool(_RE_COQUETEO.search(texto or ""))


def es_declaracion(texto: str) -> bool:
    return bool(_RE_DECLARACION.search(texto or ""))


# ─────────────────────────── Mecánicas ───────────────────────────

def _sumar(estado: dict[str, Any], delta: float, ocupada_por_otro: bool, momento: datetime) -> float:
    """Aplica delta respetando 0..tope. Retorna lo realmente sumado."""
    antes = float(estado.get("corazones") or 0)
    if delta >= 0:
        # El tope frena la subida, pero nunca quita corazones que ya se tenían
        despues = max(antes, min(antes + delta, tope(estado, ocupada_por_otro)))
    else:
        despues = max(0.0, antes + delta)
    estado["corazones"] = round(despues, 2)

    if not estado.get("es_pareja"):
        if despues >= MAX_CORAZONES and antes < MAX_CORAZONES:
            estado["fecha_maximo"] = momento.isoformat()  # Empieza la cuenta para declararse
        elif despues < MAX_CORAZONES:
            estado["fecha_maximo"] = None
    return round(despues - antes, 2)


def aplicar_interaccion(
    estado: dict[str, Any], tono: str, coqueteo: bool, ocupada_por_otro: bool, momento: Optional[datetime] = None
) -> tuple[float, Optional[str], Optional[str]]:
    """
    Una charla con Ribby. Retorna (corazones_ganados, nivel_anterior, nivel_nuevo).
    Los niveles son iguales si no cambió.
    """
    momento = momento or ahora()
    hoy = _dia(momento)
    previo = nivel(estado, ocupada_por_otro)

    if estado.get("es_creador"):
        # Con su creador el cariño es de familia: siempre al máximo y nunca romántico
        ultima = _dt(estado.get("ultima_interaccion"))
        if ultima is None or _dia(ultima) != hoy:
            ayer = (momento.astimezone(ZONA).date() - timedelta(days=1)).isoformat()
            estado["racha_dias"] = (estado.get("racha_dias") or 0) + 1 if ultima and _dia(ultima) == ayer else 1
        estado.update(corazones=MAX_CORAZONES, coqueteos=0, es_pareja=False, fecha_maximo=None,
                      ultima_interaccion=momento.isoformat(), dias_descontados=0)
        estado["total_interacciones"] = (estado.get("total_interacciones") or 0) + 1
        return 0.0, "creador", "creador"

    # Racha de días seguidos
    ultima = _dt(estado.get("ultima_interaccion"))
    if ultima is None or _dia(ultima) != hoy:
        ayer = (momento.astimezone(ZONA).date() - timedelta(days=1)).isoformat()
        estado["racha_dias"] = (estado.get("racha_dias") or 0) + 1 if ultima and _dia(ultima) == ayer else 1

    if estado.get("dia_corazones") != hoy:
        estado["dia_corazones"] = hoy
        estado["corazones_hoy"] = 0.0

    if coqueteo and not estado.get("es_pareja"):
        estado["coqueteos"] = (estado.get("coqueteos") or 0) + 1

    clave = "grosero" if tono == "grosero" else ("coqueteo" if coqueteo else tono)
    delta = PUNTOS.get(clave, PUNTOS["neutro"])
    if delta > 0:
        if estado["corazones_hoy"] == 0 and (estado.get("racha_dias") or 0) >= 3:
            delta += 0.3  # Premio por constancia
        delta = min(delta, max(0.0, TOPE_DIARIO_CHARLA - estado["corazones_hoy"]))
    ganado = _sumar(estado, delta, ocupada_por_otro, momento)
    if ganado > 0:
        estado["corazones_hoy"] = round(estado["corazones_hoy"] + ganado, 2)

    estado["ultima_interaccion"] = momento.isoformat()
    estado["dias_descontados"] = 0
    estado["total_interacciones"] = (estado.get("total_interacciones") or 0) + 1

    nuevo = nivel(estado, ocupada_por_otro)
    if nuevo != previo and nuevo not in ("enamorada",):
        registrar_evento(estado, "nivel", f"pasó de {NIVELES[previo][0].lower()} a {NIVELES[nuevo][0].lower()}", momento)
    return ganado, previo, nuevo


def aplicar_bonus(estado: dict[str, Any], delta: float, ocupada_por_otro: bool, momento: Optional[datetime] = None) -> float:
    """Corazones de regalos y citas (tienen su propio límite diario aparte de la charla)."""
    return _sumar(estado, delta, ocupada_por_otro, momento or ahora())


def puede_hoy(estado: dict[str, Any], clave: str, momento: Optional[datetime] = None) -> bool:
    """'ultimo_regalo' / 'ultima_cita': una vez al día."""
    return estado.get(clave) != _dia(momento or ahora())


def marcar_hoy(estado: dict[str, Any], clave: str, momento: Optional[datetime] = None) -> None:
    estado[clave] = _dia(momento or ahora())


def declarar(estado: dict[str, Any], hay_otra_pareja: bool, momento: Optional[datetime] = None) -> str:
    """
    El usuario le pide a Ribby ser su pareja. Retorna:
      'ya_pareja' | 'ocupada' | 'espera' | 'acepta' | 'casi' | 'pronto'
    'acepta' deja el estado como pareja (hay que guardarlo y anunciarlo).
    """
    momento = momento or ahora()
    if estado.get("es_creador"):
        return "creador"
    if estado.get("es_pareja"):
        return "ya_pareja"
    if hay_otra_pareja:
        return "ocupada"
    ultima = _dt(estado.get("ultima_declaracion"))
    if ultima and momento - ultima < timedelta(hours=HORAS_ENTRE_DECLARACIONES):
        return "espera"
    estado["ultima_declaracion"] = momento.isoformat()

    if float(estado.get("corazones") or 0) >= MAX_CORAZONES:
        estado["es_pareja"] = True
        estado["fecha_inicio_pareja"] = momento.isoformat()
        estado["fecha_maximo"] = None
        registrar_evento(estado, "pareja", "le pidió ser su pareja y Ribby dijo que sí", momento)
        return "acepta"
    if float(estado.get("corazones") or 0) >= 75:
        registrar_evento(estado, "declaracion", "se le declaró, pero Ribby aún no estaba lista", momento)
        return "casi"
    registrar_evento(estado, "declaracion", "se le declaró demasiado pronto", momento)
    return "pronto"


def terminar(estado: dict[str, Any], motivo: str, momento: Optional[datetime] = None) -> None:
    """Fin de la relación en buenos términos: quedan como mejores amigos."""
    estado["es_pareja"] = False
    estado["fecha_inicio_pareja"] = None
    estado["fecha_maximo"] = None
    estado["coqueteos"] = 0
    estado["corazones"] = 55.0
    registrar_evento(estado, "fin_pareja", motivo, momento)


def aplicar_paso_del_tiempo(estado: dict[str, Any], momento: Optional[datetime] = None) -> list[str]:
    """
    Enfriamientos por inactividad o por no declararse. Idempotente: se puede
    llamar cada vez que se carga el estado. Retorna los tipos de evento ocurridos.
    """
    momento = momento or ahora()
    ocurrido: list[str] = []
    if estado.get("es_creador"):
        return ocurrido  # El cariño por su creador no se enfría
    ultima = _dt(estado.get("ultima_interaccion"))

    # Llegó al máximo y nunca se declaró → el interés se pierde
    maximo = _dt(estado.get("fecha_maximo"))
    if not estado.get("es_pareja") and maximo and momento - maximo > timedelta(days=DIAS_INTERES_MAXIMO):
        estado["corazones"] = 35.0
        estado["coqueteos"] = 0
        estado["fecha_maximo"] = None
        registrar_evento(estado, "interes_perdido", "Ribby se cansó de esperar a que se declarara; volvieron a ser amigos", momento)
        ocurrido.append("interes_perdido")

    if ultima:
        dias_fuera = (momento - ultima).days
        if estado.get("es_pareja"):
            if dias_fuera > DIAS_PAREJA_TERMINA:
                terminar(estado, "la relación se enfrió porque pasaron semanas sin hablar", momento)
                ocurrido.append("fin_pareja")
        elif dias_fuera > DIAS_INACTIVIDAD:
            # -1 corazón por cada día de ausencia más allá del límite (solo se descuenta una vez)
            pendiente = dias_fuera - DIAS_INACTIVIDAD - int(estado.get("dias_descontados") or 0)
            if pendiente > 0:
                piso = 15.0 if float(estado.get("corazones") or 0) >= 15 else 0.0  # Un amigo no vuelve a ser desconocido
                estado["corazones"] = max(piso, float(estado.get("corazones") or 0) - pendiente)
                estado["dias_descontados"] = int(estado.get("dias_descontados") or 0) + pendiente
                ocurrido.append("inactividad")
    return ocurrido


# ─────────────────────────── Contexto para la IA ───────────────────────────

_COMO_ACTUAR = {
    "desconocido": "Apenas conoces a esta persona. Eres educada pero reservada; no hay confianza todavía.",
    "amigo": "Es tu amigo/a. Eres más cercana, bromeas con confianza y te alegra verle, aunque no lo admitas.",
    "mejor_amigo": (
        "Es de tus mejores amigos/as. Le tienes confianza real, te preocupas por cómo está y recuerdas sus cosas. "
        "Si te coquetea, te pones nerviosa y lo esquivas con tu estilo tsundere ('¿Q-qué dices? Tonto...')."
    ),
    "algo_mas": (
        "Sientes algo más que amistad por esta persona y te pone nerviosa. Respondes a sus coqueteos con timidez, "
        "te sonrojas, a veces le devuelves un cumplido torpe. Todavía no lo admites del todo."
    ),
    "enamorada": (
        "Estás enamorada de esta persona y esperas que te pida ser su pareja. Da PISTAS claras pero indirectas "
        "(mencionar parejas de libros, decir que 'alguien' debería atreverse, ponerte nerviosa), sin pedírselo tú. "
        "Nunca le presiones ni le hagas sentir culpable."
    ),
    "pareja": (
        "Esta persona es tu PAREJA. Eres cariñosa a tu manera tsundere: le llamas por algún apodo tierno, te alegras "
        "muchísimo de verle y lo demuestras, aunque a veces lo disimules. Sigue siendo una relación sana: apoyo, "
        "confianza y respeto."
    ),
    "creador": (
        "Esta persona es Tainy, TU CREADOR: para ti es como tu padre. Le quieres muchísimo, de forma FAMILIAR, "
        "nunca romántica. Le tratas con la confianza de una hija tsundere: te quejas de que es un vago que duerme en "
        "el sofá de la biblioteca, le regañas, le cuidas y en el fondo le estás profundamente agradecida por darte "
        "vida. Si te coquetea o te pide ser su pareja, reacciona como una hija avergonzada ('¡¿PAPÁ?! ¡Qué asco, "
        "eres mi creador! 😭') y cambia de tema. Jamás le correspondas de forma romántica."
    ),
}

_EVENTO_DECLARACION = {
    "acepta": "ACABA DE PEDIRTE SER SU PAREJA Y ACEPTAS. Responde emocionada y sonrojada, con tu estilo tsundere, diciendo que sí.",
    "casi": "Acaba de pedirte ser su pareja, pero aún no estás lista. Recházalo con ternura y nervios, dejando claro que no es un 'no' para siempre.",
    "pronto": "Acaba de pedirte ser su pareja, pero apenas os conocéis lo suficiente. Recházalo con humor y amabilidad, sin humillarle.",
    "ocupada": "Acaba de pedirte ser su pareja, pero ya tienes pareja. Recházalo con amabilidad y respeto, siendo honesta.",
    "ya_pareja": "Te pregunta si quieres ser su pareja, pero YA SOIS pareja. Respóndele con ternura y algo de burla cariñosa.",
    "espera": "Vuelve a pedirte ser su pareja poco después de que le dijeras que no. Pídele paciencia con ternura.",
    "creador": "Tu creador (como tu padre) te acaba de pedir ser su pareja. Reacciona horrorizada y avergonzada como una hija, entre risas y quejas, y déjale claro que eso NO va a pasar.",
}

REGLAS_ROMANCE = (
    "LÍMITES DEL ROMANCE (OBLIGATORIOS): todo lo romántico es tierno y apto para todo público: cumplidos, sonrojos, "
    "abrazos, citas a leer o tomar té. Nada sexual ni explícito; si alguien lo intenta, córtalo con firmeza y humor. "
    "Nunca uses culpa, celos posesivos ni chantaje emocional, y nunca digas que alguien te 'abandonó'."
)


def contexto_prompt(
    estado: dict[str, Any],
    ocupada_por_otro: bool,
    nombre_pareja: Optional[str] = None,
    evento_declaracion: Optional[str] = None,
    momento: Optional[datetime] = None,
) -> str:
    """Bloque para el system prompt de Ribby con la relación actual."""
    momento = momento or ahora()
    n = nivel(estado, ocupada_por_otro)
    partes = [f"Cómo le ves ahora: {NIVELES[n][0]}. {_COMO_ACTUAR[n]}"]

    if ocupada_por_otro and n in ("mejor_amigo", "algo_mas"):
        partes.append(
            f"Ya tienes pareja{f' ({nombre_pareja})' if nombre_pareja else ''}. Con esta persona eres cariñosa como "
            "amiga, pero si coquetea lo rechazas con amabilidad."
        )
    if estado.get("es_pareja"):
        inicio = _dt(estado.get("fecha_inicio_pareja"))
        if inicio:
            partes.append(f"Lleváis {(momento - inicio).days} días como pareja.")
        ultima = _dt(estado.get("ultima_interaccion"))
        if ultima and (momento - ultima).days >= DIAS_PAREJA_EXTRAÑA:
            partes.append("Hacía días que no hablabais: le echabas de menos y te alegra mucho verle (sin reproches).")

    recientes = [e for e in estado.get("eventos", []) if e.get("tipo") != "nivel"][-4:]
    if recientes:
        partes.append("Cosas que han pasado entre vosotros: " + "; ".join(f"{e['fecha']}: {e['texto']}" for e in recientes) + ".")
    if evento_declaracion:
        partes.append("AHORA MISMO: " + _EVENTO_DECLARACION[evento_declaracion])
    return "\n".join(partes)
