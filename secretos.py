"""
secretos.py — Secretos escondidos de Ribby y confidencias que suelta con la confianza (sin red ni Discord).

SECRETOS: frases o acciones concretas que desbloquean una reacción única de
Ribby y un logro oculto. Algunos dependen de la hora, la fecha, el nivel de
relación o los capítulos leídos; si todavía no te toca, Ribby se pone nerviosa
y lo esquiva (lo que ya es una pista). La primera persona que descubre cada
uno se anuncia en el servidor sin revelar la frase: encontrarlos es un juego
de la comunidad, y /ribby secretos da una adivinanza para cada uno.

CONFIDENCIAS: cosas íntimas que Ribby cuenta poco a poco según el nivel de
relación (algunas esconden pistas de los secretos).
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable, Optional

ORDEN_NIVEL = ["desconocido", "amigo", "mejor_amigo", "algo_mas", "enamorada", "pareja"]


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s↑↓←→]", " ", t)).strip()


def nivel_alcanzado(nivel: str, minimo: Optional[str]) -> bool:
    if not minimo or nivel == "creador":
        return True
    actual = ORDEN_NIVEL.index(nivel) if nivel in ORDEN_NIVEL else 0
    return actual >= ORDEN_NIVEL.index(minimo)


@dataclass
class Contexto:
    hora: int                              # Hora local (México)
    fecha: date
    nivel: str = "desconocido"
    capitulos: set[int] = field(default_factory=set)
    es_pareja: bool = False
    es_creador: bool = False


@dataclass
class Secreto:
    id: str
    emoji: str
    nombre: str
    descripcion: str                       # Lo que hiciste (se ve en /ribby secretos al descubrirlo)
    pista: str                             # Adivinanza pública
    reacciones: list[str]
    patron: Optional[str] = None           # Regex sobre el texto normalizado (frases)
    accion: Optional[str] = None           # "regalo:<tipo>" o "cita" (acciones)
    condicion: Optional[Callable[[Contexto], bool]] = None
    requisito: Optional[Callable[[Contexto], bool]] = None   # Si falla, Ribby lo esquiva
    esquiva: str = ""
    corazones: float = 1.0

    @property
    def logro(self) -> str:
        return f"secreto_{self.id}"


CUENTOS = [
    "Había una vez un libro que nadie abría. Se llenó de polvo, luego de telarañas, y un día una Eevee empapada "
    "se refugió bajo él. Ella no sabía leer. Él no sabía que alguien lo necesitaba. Los dos aprendieron. Fin. "
    "...¿Qué? Los cuentos cortos también cuentan. 🌙",
    "Érase una vez un listón que quería ser marcapáginas. Todos se reían de él, hasta que un día marcó la página "
    "exacta donde alguien dejó de estar triste. Fin. ...Ahora duérmete. 📖",
    "Había un dragón que guardaba libros en vez de oro. Cuando le preguntaban por qué, decía: «el oro no te cuenta "
    "nada por la noche». Fin. ...Me lo he inventado ahora. No se lo digas a nadie. 🐉",
]

SECRETOS: list[Secreto] = [
    Secreto(
        "eevee", "🌧️", "Eevee empapada", "Llamaste a Ribby por su antiguo nombre",
        "Antes de los listones hubo otro nombre. Llámala como cuando llegó con la tormenta.",
        ["¿E-Eevee? ¡Hace siglos que nadie me llama así! *se le enroscan los listones* ...Vale. Te dejo usarlo. "
         "Solo tú. Y solo a veces. 🌧️💜"],
        patron=r"\beevee\b",
        requisito=lambda c: nivel_alcanzado(c.nivel, "amigo"),
        esquiva="¿Eevee? No sé de qué me hablas. Soy una Sylveon. Siempre lo he sido. *mira hacia otro lado* 😶",
    ),
    Secreto(
        "cuarenta_y_dos", "🔥", "Los cuarenta y dos", "Recordaste los libros que Ribby salvó del incendio",
        "Un número que para cualquiera sería una respuesta, para ella es un recuerdo. Pregúntale por él.",
        ["...Cuarenta y dos. *se queda callada un momento* Te acuerdas. De verdad te acuerdas. "
         "Están todos en el estante de fantasía, ¿sabes? Les quito el polvo cada mañana. Gracias por recordarlo. 💛"],
        patron=r"\b(42|cuarenta y dos)\b.*\blibros?\b|\blibros?\b.*\b(42|cuarenta y dos)\b",
        requisito=lambda c: 2 in c.capitulos or nivel_alcanzado(c.nivel, "mejor_amigo"),
        esquiva="¿Cuarenta y dos qué? ...Nada. Es solo un número. Cosas mías. 😶",
        corazones=1.5,
    ),
    Secreto(
        "hora_bruja", "🕯️", "La hora bruja", "Hablaste con Ribby a las 3 de la madrugada",
        "Cuando todos duermen y hasta Tainy ronca, alguien lee a la luz de una vela. Búscala a esa hora.",
        ["*Ribby da un respingo y casi tira la vela* ¡¿Qué haces despierto/a a estas horas?! ...Yo no podía dormir. "
         "A veces me pasa. Leo hasta que el sueño me encuentra. ...Quédate un ratito, si quieres. 🕯️📖"],
        patron=r".",
        condicion=lambda c: c.hora == 3,
    ),
    Secreto(
        "ceres_perremlo", "💘", "El ship sagrado", "Nombraste el ship favorito de Rio",
        "Hay un ship del que Ribby se burla… pero en secreto también lo apoya. Pregúntale a quien lo defiende.",
        ["¿Ceres x Perremlo? *mira a los lados* ...Vale, lo admito: tengo un fanfic guardado. Si Rio se entera, te "
         "destierro de la biblioteca. Para siempre. 🤫💘"],
        patron=r"ceres.{0,15}perremlo|perremlo.{0,15}ceres",
    ),
    Secreto(
        "konami", "🎮", "Código prohibido", "Introdujiste un código muy, muy antiguo",
        "Arriba, arriba, abajo, abajo… los más viejos del lugar saben cómo termina.",
        ["*Ribby parpadea. Por un instante, todo a su alrededor parpadea con ella.* ...¿Qué ha sido eso? Por un "
         "segundo he visto... líneas. Números. Como si la biblioteca entera estuviera escrita. *sacude la cabeza* "
         "Olvídalo. No he dormido bien. 👾"],
        patron=r"(↑\s*↑\s*↓\s*↓\s*←\s*→\s*←\s*→\s*b\s*a)|(arriba arriba abajo abajo izquierda derecha izquierda derecha b a)",
        corazones=0.5,
    ),
    Secreto(
        "tainy_despierto", "😱", "Lo imposible", "Le dijiste a Ribby que Tainy estaba despierto",
        "Dale a Ribby la noticia más increíble que podría oír sobre cierto vago del sofá.",
        ["¡¿QUÉ?! ¡¿TAINY DESPIERTO?! *sale corriendo hacia el sofá... y vuelve* ...Está durmiendo. Como siempre. "
         "Casi me da algo. No me hagas esto. 😤😂"],
        patron=r"tainy (esta|se ha|se) (despierto|desperto|levantado|levanto)",
    ),
    Secreto(
        "cuento", "🌙", "Un cuento para dormir", "Le pediste a Ribby un cuento",
        "Una bibliotecaria conoce mil historias. Pídele una, como hacían los niños antes de dormir.",
        CUENTOS,
        patron=r"\b(leeme|cuentame|cuentas|lees|contarme|leerme)\b.{0,15}\bcuento\b",
        requisito=lambda c: nivel_alcanzado(c.nivel, "amigo"),
        esquiva="¿Un cuento? Apenas te conozco. Los cuentos son para... gente de confianza. Algún día. 📚",
    ),
    Secreto(
        "listones", "🎀", "Listones sagrados", "Le pediste a Ribby tocar sus listones",
        "Lo más suave de una Sylveon no se toca sin permiso… salvo que seas alguien muy especial para ella.",
        ["*Ribby se queda muy quieta... y luego te ofrece un listón, despacio* ...Solo uno. Con cuidado. Es la "
         "primera vez que dejo que alguien... bueno. Ya está. 🎀😳"],
        patron=r"\b(tocar|acariciar|tocarte|acariciarte|peinar)\b.{0,25}\blistone?s?\b",
        requisito=lambda c: nivel_alcanzado(c.nivel, "mejor_amigo"),
        esquiva="¡¿Mis listones?! ¡Ni hablar! Eso es... eso es muy personal. 😤",
        corazones=1.5,
    ),
    Secreto(
        "estante_fantasia", "📕", "Detrás del estante", "Preguntaste qué hay detrás del estante de fantasía",
        "Hay un estante que Ribby cuida más que ninguno. Lo que importa no está en él, sino detrás.",
        ["*Ribby te mira largo rato* ...Así que te acuerdas. Mi cuaderno sigue ahí. Ayer escribí dos páginas "
         "nuevas. Sobre ti. *se tapa la cara con los listones* No preguntes qué dicen. Todavía. 💞"],
        patron=r"(detras|atras) del estante|estante de fantasia.{0,30}(detras|esconde|guardas|hay)",
        requisito=lambda c: 4 in c.capitulos,
        esquiva="¡¿Q-quién te ha dicho que hay algo detrás del estante?! No hay nada. Nada de nada. *se pone delante* 😳",
        corazones=1.5,
    ),
    Secreto(
        "palabras_magicas", "🪄", "Palabras mágicas", "Intentaste abrir la biblioteca con una palabra mágica",
        "En las historias, las puertas se abren con palabras. ¿Funcionará con la sección prohibida?",
        ["*Ribby suspira* La sección prohibida no se abre con palabras mágicas. ...Aunque algunas frases sí abren "
         "cosas en esta biblioteca. Te daré una pista, solo porque me has hecho gracia: «{pista}» 🪄"],
        patron=r"\b(abracadabra|alohomora|abrete sesamo|expecto patronum|bibbidi bobbidi boo)\b",
        corazones=0.5,
    ),
    Secreto(
        "dia_del_libro", "📚", "Su día favorito", "Felicitaste a Ribby el Día del Libro",
        "Hay un día del año en que Ribby es la más feliz del mundo. Felicítala justo ese día.",
        ["¡¡Te acordaste!! *da vueltas con un libro en brazos* Hoy es el mejor día del año y tú... tú me has "
         "felicitado. Voy a apuntarlo. En tinta. Para siempre. 📚✨"],
        patron=r"feliz dia del libro",
        condicion=lambda c: (c.fecha.month, c.fecha.day) == (4, 23),
        corazones=2.0,
    ),
    Secreto(
        "te_lluvia", "🍵", "Tarde perfecta", "Le propusiste a Ribby su plan perfecto",
        "Su bebida favorita, su tiempo favorito y un buen libro. Propónselo todo junto.",
        ["Té de jazmín... lluvia... ¿y un libro? *se le iluminan los ojos* Acabas de describir mi tarde perfecta. "
         "¿Cómo lo sabías? ...No contestes. Pon la tetera. 🍵🌧️"],
        patron=r"(jazmin.*(lluvia|llueve|lloviendo))|((lluvia|llueve|lloviendo).*jazmin)",
    ),
    Secreto(
        "carta", "💌", "La carta", "Le preguntaste a Ribby si envió su carta",
        "Una carta escondida entre páginas, escrita hace semanas. Pregúntale si al final se atrevió.",
        ["*Ribby se pone de todos los colores* ...No. Todavía no la he enviado. Pero la he reescrito. Tres veces. "
         "Ahora es más corta y más valiente. ...Algún día. Quizá antes de lo que crees. 💌"],
        patron=r"\b(enviaste|mandaste|entregaste|enviar|mandar)\b.{0,10}\b(la|tu|esa)\b.{0,10}\bcarta\b",
        requisito=lambda c: 3 in c.capitulos,
        esquiva="¿Q-qué carta? Yo no tengo ninguna carta. Ni en un libro ni en ningún sitio. ¡Ninguna! 😳",
        corazones=1.5,
    ),
    Secreto(
        "papa_tainy", "👨‍👧", "Asuntos de familia", "Le preguntaste a Ribby si Tainy es como su padre",
        "Alguien le enseñó a leer y le dio un hogar. ¿Qué es para ella, en realidad?",
        ["*Ribby se queda muda* ...¿Mi padre? Él... *mira al sofá del fondo* Bueno. Me enseñó a leer, me dio un "
         "hogar y nunca me echó, aunque me colé por una ventana. Si eso no es un padre... No se lo digas. "
         "Se le subiría a la cabeza. 👨‍👧"],
        patron=r"tainy.{0,25}\b(tu papa|tu padre|como un padre|como tu padre)\b|\b(tu papa|tu padre)\b.{0,25}tainy",
        corazones=1.0,
    ),
    # ── Acciones ──
    Secreto(
        "libro_dia_del_libro", "🎁", "El regalo perfecto", "Le regalaste un libro en la semana del Día del Libro",
        "Hay un regalo que siempre le gusta, pero en cierta semana de abril le gusta muchísimo más.",
        ["¿Un libro... esta semana? *lo abraza contra el pecho* Este va directo al estante de fantasía. Al lado de "
         "los cuarenta y dos. Es el sitio más importante que tengo. 📚💛"],
        accion="regalo:libro",
        condicion=lambda c: c.fecha.month == 4 and 20 <= c.fecha.day <= 24,
        corazones=1.5,
    ),
    Secreto(
        "bicho_pareja", "🪲", "Amor a prueba de bichos", "Le regalaste un escarabajo… siendo su pareja",
        "Lo que más odia, de parte de quien más quiere. ¿Qué pesa más?",
        ["*Ribby mira el escarabajo. Te mira a ti. Mira el escarabajo otra vez* ...Solo porque eres tú. Se llamará "
         "Gregorio y vivirá FUERA de la biblioteca. Muy fuera. 🪲💞"],
        accion="regalo:bicho",
        condicion=lambda c: c.es_pareja,
        corazones=1.0,
    ),
    Secreto(
        "cita_medianoche", "🌌", "Cita a medianoche", "Invitaste a Ribby a una cita a medianoche",
        "Las mejores historias empiezan cuando el reloj marca la última campanada del día.",
        ["¿Una cita... a medianoche? *mira por la ventana, hacia las estrellas* Esto parece sacado de una novela. "
         "...De las buenas. 🌌"],
        accion="cita",
        condicion=lambda c: c.hora == 0,
        corazones=1.0,
    ),
]

POR_ID = {s.id: s for s in SECRETOS}


def detectar_frase(texto: str, ctx: Contexto) -> Optional[tuple[Secreto, bool]]:
    """(secreto, permitido) si el mensaje toca un secreto; permitido=False si aún no le toca (Ribby lo esquiva)."""
    normal = normalizar(texto)
    if not normal:
        return None
    for s in SECRETOS:
        if s.patron is None or s.accion is not None:
            continue
        if s.condicion is not None and not s.condicion(ctx):
            continue
        if s.id == "hora_bruja":
            continue  # Se comprueba aparte: cualquier mensaje vale, pero los demás secretos tienen prioridad
        if re.search(s.patron, normal) or (s.id == "konami" and re.search(s.patron, texto or "", re.I)):
            return s, s.requisito is None or s.requisito(ctx)
    hora = POR_ID["hora_bruja"]
    if hora.condicion and hora.condicion(ctx):
        return hora, True
    return None


def detectar_accion(accion: str, ctx: Contexto) -> Optional[Secreto]:
    for s in SECRETOS:
        if s.accion == accion and (s.condicion is None or s.condicion(ctx)) and (s.requisito is None or s.requisito(ctx)):
            return s
    return None


def reaccion(s: Secreto, otros_sin_descubrir: Iterable[Secreto] = (), rng: Optional[random.Random] = None) -> str:
    rng = rng or random.Random()
    texto = rng.choice(s.reacciones)
    if "{pista}" in texto:
        pendientes = [x for x in otros_sin_descubrir if x.id != s.id]
        texto = texto.format(pista=rng.choice(pendientes).pista if pendientes else "ya lo has descubierto todo… ¿o no?")
    return texto


# ─────────────────────────── Confidencias ───────────────────────────

CONFIDENCIAS: dict[str, list[tuple[str, str]]] = {
    "amigo": [
        ("olor_libros", "Le encanta oler los libros viejos al abrirlos, y le da vergüenza que la pillen haciéndolo."),
        ("final_primero", "Cuando un libro la pone nerviosa, lee el final primero. Lo considera una 'medida de seguridad'."),
        ("tararea", "Tararea mientras ordena las estanterías y finge que no cuando alguien entra."),
        ("espejo", "Ensaya delante del espejo lo que va a decir cuando viene gente nueva a la biblioteca."),
        ("liston_izquierdo", "Su listón izquierdo es 'el de leer' y el derecho 'el de no molestar'. Nadie lo había notado."),
    ],
    "mejor_amigo": [
        ("velas", "Desde el incendio le da miedo el fuego: la única vela que enciende es la de su escritorio, y nunca la pierde de vista."),
        ("insomnio", "Algunas noches no puede dormir y lee a la luz de esa vela hasta las tantas, sobre las tres de la madrugada."),
        ("balda", "Cuando alguien deja de venir, guarda su libro favorito en una balda aparte, por si vuelve."),
        ("estrellas", "Lleva una libreta con todas las personas que la visitan; a sus favoritas les pone una estrellita (tú tienes una)."),
        ("lloro", "Una vez lloró con un cuento infantil y nunca se lo ha contado a nadie hasta ahora."),
    ],
    "algo_mas": [
        ("margenes", "Escribió tu nombre en el margen de un libro sin darse cuenta, y luego lo borró con mucho cuidado."),
        ("novelas", "Este año ha leído treinta y siete novelas románticas 'para documentarse'."),
        ("listones_arreglo", "Se arregla los listones justo antes de que llegues, aunque diga que siempre los lleva así."),
        ("aburrir", "Le da miedo que la gente se aburra de ella, por eso a veces finge que está ocupada."),
        ("primer_dia", "Recuerda exactamente qué libro estaba leyendo el día que le hablaste por primera vez."),
    ],
    "pareja": [
        ("capitulo_nuevo", "Ha empezado un capítulo nuevo de su cuaderno secreto, y trata de vosotros dos."),
        ("mar", "Sueña con abrir algún día una pequeña biblioteca junto al mar, contigo."),
        ("hogar", "Su palabra favorita ahora es 'hogar', y sabe perfectamente por qué."),
        ("listón_enroscado", "Cuando dices su nombre se le enrosca un listón sin querer, y lleva semanas intentando que no se note."),
        ("final_quemado", "Le gustaría que algún día inventarais juntos el final del libro quemado."),
    ],
    "creador": [
        ("galleta", "Siempre le guarda a Tainy la última galleta del bote, aunque le riñe por comérsela."),
        ("record", "Lleva la cuenta de las horas que duerme Tainy: el récord son catorce seguidas."),
        ("manta", "Una noche le dejó una manta encima y, cuando él preguntó, dijo que había sido el viento."),
        ("orgullo", "Lo que más quiere en el mundo es que Tainy esté orgulloso de ella."),
        ("primer_libro", "Todavía tiene el primer libro con el que Tainy le enseñó a leer, con sus anotaciones torcidas."),
    ],
}

_NIVELES_CONFIDENCIA = ["amigo", "mejor_amigo", "algo_mas", "pareja"]
PROBABILIDAD_CONFIDENCIA = 0.35


def confidencias_disponibles(nivel: str) -> list[tuple[str, str]]:
    """Las que Ribby está dispuesta a contar a este nivel (las de los niveles anteriores incluidas)."""
    if nivel == "creador":
        return list(CONFIDENCIAS["creador"])
    nivel = "algo_mas" if nivel == "enamorada" else nivel
    if nivel not in _NIVELES_CONFIDENCIA:
        return []
    resultado: list[tuple[str, str]] = []
    for n in _NIVELES_CONFIDENCIA[: _NIVELES_CONFIDENCIA.index(nivel) + 1]:
        resultado += CONFIDENCIAS[n]
    return resultado


def siguiente_confidencia(nivel: str, contadas: Iterable[str]) -> Optional[tuple[str, str]]:
    """La siguiente que aún no ha contado (en orden: primero lo más ligero)."""
    ya = set(contadas)
    return next((c for c in confidencias_disponibles(nivel) if c[0] not in ya), None)


def texto_confidencias(ids: Iterable[str]) -> list[str]:
    todas = {cid: texto for lista in CONFIDENCIAS.values() for cid, texto in lista}
    return [todas[i] for i in ids if i in todas]
