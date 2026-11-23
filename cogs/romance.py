"""
cogs/romance.py — El medidor de corazones de Ribby (relación con cada usuario).

Cada vez que alguien habla con Ribby (cogs/saludos.py), este cog:
  1. Actualiza sus corazones según el tono, los coqueteos y el tope diario.
  2. Detecta si se le está declarando y decide la respuesta.
  3. Devuelve un bloque de contexto para que la IA hable acorde a la relación.
Después de responder, reacciona con 💗 si subió de nivel y anuncia en el
canal cuando alguien se convierte en la pareja de Ribby (solo puede haber una).

Además:
  - Misiones de lectura: Ribby te encarga leer una historia de su biblioteca;
    al reseñarla (/biblioteca resenar) ganas corazones y el autor recibe la reseña.
  - Cumpleaños y aniversarios: Ribby felicita en su canal.
  - Eventos de temporada (temporadas.py) y logros (logros.py).
  - Iniciativa: de vez en cuando Ribby saluda por su cuenta a sus mejores amigos
    o a su pareja (con límites estrictos para no hacer spam; se puede desactivar).

Comandos /ribby: corazones, recuerdos, recordar, olvidar, regalar, cita, evento,
mision, logros, cumpleanos, avisos, terminar; staff: canal, espontanea, reiniciar.

Seguimientos: si alguien le contó algo con fecha ("mañana tengo examen"), Ribby
le pregunta en su canal cómo le fue (con los mismos límites que la iniciativa).
El nivel de cada uno es privado: solo lo ve el propio usuario.
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import copy
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Any, Optional

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

import afinidad as af
import citas as ct
import config
import database
import logros as lg
import memoria as mem
import ribby_lore as lr
import secretos as sec
import temporadas
import comun
from comun import es_admin, md

log = logging.getLogger("bot-literario.afinidad")

COLOR_ROMANCE = 0xF472B6


# ─────────────────────────── Contenido: regalos y citas ───────────────────────────

REGALOS: dict[str, dict[str, Any]] = {
    "libro": {"nombre": "📚 Un libro", "delta": 0.7, "respuestas": [
        "¿U-un libro nuevo? ...Bueno, supongo que tiene un hueco en mi estante favorito. No es que me haga ilusión. 📚",
        "*abraza el libro* ¡Ni se te ocurra pedírmelo prestado de vuelta! ...Gracias. 🎀",
    ]},
    "te": {"nombre": "🍵 Té de jazmín", "delta": 0.7, "respuestas": [
        "Té de jazmín... ¿cómo sabías que es mi favorito? Hmph, seguro fue suerte. 🍵",
        "Justo lo que necesitaba para seguir leyendo. Te has ganado un punto. Solo uno. 😌",
    ]},
    "liston": {"nombre": "🎀 Un listón nuevo", "delta": 0.6, "respuestas": [
        "¿Un listón? *se lo prueba enseguida* ...No me mires así, solo quería ver si combinaba. 🎀",
    ]},
    "flores": {"nombre": "🌸 Flores", "delta": 0.5, "respuestas": [
        "¿Flores? Las pondré junto a la ventana de la biblioteca. Q-quedan bonitas, ya está. 🌸",
    ]},
    "galletas": {"nombre": "🍪 Galletas", "delta": 0.4, "respuestas": [
        "Galletas... prohibidas cerca de los libros, pero haré una excepción. Solo esta vez. 🍪",
    ]},
    "bicho": {"nombre": "🪲 Un escarabajo", "delta": -0.5, "respuestas": [
        "¡¿QUÉ ES ESO?! ¡Sácalo de mi biblioteca ahora mismo! 😤💢",
        "*se sube a una estantería* ...Ni una palabra de esto a nadie. Y llévate eso. 🫠",
    ]},
}

CITAS: list[dict[str, Any]] = [
    {"titulo": "📖 La biblioteca a medianoche",
     "escena": "Todos se han ido y solo quedáis Ribby y tú entre las estanterías, con una vela encendida.",
     "opciones": [
         ("Leerle en voz alta su libro favorito", 1.0, "*se acurruca a escuchar* ...Lees mejor de lo que pensaba. Sigue, no pares. 🕯️"),
         ("Recomendarle tu historia favorita", 0.7, "Hm, buena elección. Tienes mejor gusto del que aparentas. 📚"),
         ("Organizar una guerra de almohadas", -0.3, "¡¿Entre los libros?! ¿Tienes idea de lo que cuesta encuadernar uno? 😤"),
     ]},
    {"titulo": "🌧️ Tarde de lluvia",
     "escena": "Llueve sin parar sobre La Comarca. Ribby mira por la ventana con una taza entre las patas.",
     "opciones": [
         ("Compartir un té junto a la ventana", 1.0, "*te hace sitio sin decir nada* ...Me gusta la lluvia. Y la compañía, supongo. 🍵"),
         ("Salir a saltar en los charcos", 0.3, "¡Me vas a empapar los listones! ...Vale, fue divertido. Un poco. 💦"),
         ("Quejarte de la lluvia", -0.3, "La lluvia es perfecta para leer. Tu actitud, no tanto. 😒"),
     ]},
    {"titulo": "🏮 El festival del pueblo",
     "escena": "Hay farolillos, música y puestos por todas partes. Ribby finge que no le emociona.",
     "opciones": [
         ("Llevarla al puesto de libros usados", 1.0, "*ya tiene tres libros en brazos* ...No me juzgues. Esto ha sido un acierto. 📚"),
         ("Ganarle un peluche de Sylveon", 0.7, "¿Un peluche de... mí? Qué ridículo. *lo abraza fuerte* 🎀"),
         ("Comer de todos los puestos", 0.2, "¿Vas a probar TODO? ...Bueno, guárdame un poco de ese algodón de azúcar. 🍡"),
     ]},
    {"titulo": "🧺 Picnic en el parque",
     "escena": "Un día soleado, una manta sobre el césped y una cesta llena de cosas.",
     "opciones": [
         ("Llevar un libro de poesía para leer juntos", 1.0, "Poesía al aire libre... vale, esto lo apruebo sin reservas. 🌸"),
         ("Hacerle una corona de flores", 0.7, "*se la deja puesta todo el día* ...Es por el sol. Para que no me dé en los ojos. 🌼"),
         ("Echarte una siesta", -0.2, "¿Me invitas a un picnic y te duermes? Increíble. 🙄"),
     ]},
    {"titulo": "✨ Noche de estrellas",
     "escena": "Desde la colina se ve todo el cielo. Ribby señala una constelación.",
     "opciones": [
         ("Pedirle que te cuente la historia de esa constelación", 1.0, "*se le iluminan los ojos* ¿De verdad quieres saberla? Pues ponte cómodo, es larga. 🌌"),
         ("Inventar tus propias constelaciones", 0.6, "¿'El Sándwich Mayor'? ...Eres un desastre. Me gusta. 😂"),
         ("Mirar el móvil", -0.3, "Tenemos todo el cielo delante y tú mirando una pantalla. Hmph. 📱"),
     ]},
]

_FRASE_NIVEL = {
    "desconocido": "\"¿Y tú quién eres? ...Bueno, la biblioteca está abierta para todos.\"",
    "amigo": "\"Ah, eres tú. ...No es que me alegre de verte. Bueno, un poco.\"",
    "mejor_amigo": "\"Si algún día necesitas algo, ya sabes dónde encontrarme. Entre los libros, obviamente.\"",
    "algo_mas": "\"¿P-por qué me miras así? ...Nada. No pasa nada. Sigue leyendo.\"",
    "enamorada": "\"Hay historias en las que alguien tiene que dar el primer paso, ¿sabes? ...Lo digo por los libros.\" 💘",
    "pareja": "\"¿Otra vez por aquí? ...Me alegra. Mucho. No se lo digas a nadie.\" 💞",
    "creador": "\"¿Papá? ...Digo, ¿Tainy? ¿Otra vez durmiendo en el sofá? Hmph. Te guardé té. No te acostumbres.\" 👨‍👧",
}


@dataclass
class Resultado:
    """Lo que pasó en un mensaje, para construir el prompt y reaccionar después."""
    contexto: str = ""
    subio_nivel: bool = False
    nueva_pareja: bool = False
    castigado: bool = False             # El staff le castigó: Ribby sigue enfadada
    logros: list[str] = field(default_factory=list)


def _texto_logros(nuevos: list[str]) -> str:
    if not nuevos:
        return ""
    return "\n🏅 **¡Logro desbloqueado!** " + ", ".join(lg.formatear(c) for c in nuevos)


def _hoy() -> date:
    return datetime.now(af.ZONA).date()


def _evento_hoy() -> Optional[dict[str, Any]]:
    """Evento de temporada vigente. En modo de pruebas se puede forzar con /prueba evento."""
    uid = comun.usuario_actual()
    forzado = comun.eventos_forzados.get(uid) if uid and comun.en_prueba(uid) else None
    if forzado:
        return next((e for e in temporadas.EVENTOS if e["id"] == forzado), None)
    return temporadas.evento_actual(_hoy())


def _contexto_temporada() -> str:
    e = _evento_hoy()
    return f"TEMPORADA ESPECIAL — {e['nombre']}: {e['contexto']}" if e else ""


# Iniciativa de Ribby: límites para que nunca sea spam
INICIATIVA_HORAS = (11, 21)          # Solo escribe entre las 11:00 y las 21:00 (hora de México)
INICIATIVA_SEPARACION_H = 6          # Como mucho un mensaje cada 6 horas en todo el servidor
INICIATIVA_DIAS_POR_PERSONA = 4      # A cada persona, como mucho cada 4 días
INICIATIVA_PROBABILIDAD = 0.3        # Para que no sea a horas fijas
MINUTOS_MINIMOS_MISION = 60          # Tiempo mínimo entre recibir una misión y completarla
SEGUIMIENTOS_POR_DIA = 3
# Castigos del staff (reseñas troll, faltas de respeto...)
CASTIGO_CORAZONES = 50
CASTIGO_DIAS = 3
CASTIGO_UMBRAL_PAREJA = 75           # Si su pareja cae por debajo, Ribby la deja
REGAÑINAS = [
    "¿En serio? ¿Esto es lo que haces en MI biblioteca? Estoy decepcionada. Y enfadada. Sobre todo enfadada. "
    "No me hables en unos días. 😤💢",
    "Vaya. Yo aquí cuidando cada libro como si fuera oro y tú haciendo el payaso. Ni se te ocurra pedirme una cita "
    "en unos días. Ni un regalo. Nada. 😒",
    "He visto muchas cosas en esta biblioteca, pero esto… Me has decepcionado. Cuando aprendas a respetar el trabajo "
    "de los demás, hablamos. Hasta entonces, silencio. 🙄",
]             # Preguntas de "¿cómo te fue...?" por iniciativa propia, en todo el servidor


# ─────────────────────────── Vistas ───────────────────────────

class CitaView(discord.ui.View):
    def __init__(
        self, cog: "Afinidad", usuario: discord.abc.User, cita: dict[str, Any],
        clave_dia: Optional[str] = "ultima_cita", extra_logros: tuple[str, ...] = (), al_terminar=None,
    ):
        super().__init__(timeout=300)
        self.cog, self.usuario, self.cita = cog, usuario, cita
        self.clave_dia, self.extra_logros, self.al_terminar = clave_dia, extra_logros, al_terminar
        self.message: Optional[discord.InteractionMessage] = None
        for i, (texto, _, _) in enumerate(cita["opciones"]):
            boton = discord.ui.Button(label=texto[:80], style=discord.ButtonStyle.secondary)
            boton.callback = self._crear_callback(i)  # type: ignore[method-assign]
            self.add_item(boton)

    def _crear_callback(self, i: int):
        async def callback(interaction: discord.Interaction):
            await self._elegir(interaction, i)
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.usuario.id:
            await interaction.response.send_message("Esta cita no es contigo 😤", ephemeral=True)
            return False
        return True

    async def _elegir(self, interaction: discord.Interaction, i: int):
        texto, delta, reaccion = self.cita["opciones"][i]
        nuevos = await self.cog.aplicar_actividad(
            self.usuario, self.clave_dia, delta,
            f"tuvieron una cita: {self.cita['titulo'][2:].strip()} ({texto.lower()})",
            contador="citas_total", extra_logros=self.extra_logros,
        )
        if self.al_terminar:
            await self.al_terminar()
        self.stop()
        embed = discord.Embed(
            title=self.cita["titulo"],
            description=f"{self.cita['escena']}\n\n**{md(self.usuario.display_name)}:** {texto}\n\n**Ribby:** {reaccion}"
                        f"{_texto_logros(nuevos)}",
            color=COLOR_ROMANCE if delta > 0 else config.COLOR_ADVERTENCIA,
        )
        embed.set_footer(text="💗" if delta >= 0.7 else ("🙂" if delta > 0 else "💢"))
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="*Ribby se cansó de esperar y volvió a sus libros.* 📚", view=None)
            except discord.HTTPException:
                pass


class TerminarView(discord.ui.View):
    def __init__(self, cog: "Afinidad", usuario: discord.abc.User):
        super().__init__(timeout=60)
        self.cog, self.usuario = cog, usuario

    @discord.ui.button(label="Sí, terminar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        estado = await self.cog.cargar(self.usuario.id)
        if estado.get("es_pareja"):
            af.terminar(estado, "decidió terminar la relación; quedaron como buenos amigos")
            await self.cog.guardar(self.usuario, estado)
        self.stop()
        await interaction.response.edit_message(
            content="*Ribby asiente despacio.* ...Está bien. Gracias por todo este tiempo. Seguiré aquí, entre los libros, "
                    "si alguna vez quieres hablar. Como amigos. 📚",
            view=None,
        )

    @discord.ui.button(label="No, me arrepiento", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="*Ribby suspira aliviada.* ...Tonto. Me habías asustado. 💞", view=None)


class _SoloAutor(discord.ui.View):
    """Vista cuyos botones solo puede usar quien ejecutó el comando."""

    def __init__(self, usuario: discord.abc.User, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.usuario = usuario

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.usuario.id:
            await interaction.response.send_message("Esto no es contigo 😤 Usa el comando tú mismo.", ephemeral=True)
            return False
        return True


class EventoView(_SoloAutor):
    def __init__(self, cog: "Afinidad", usuario: discord.abc.User, evento: dict[str, Any], edicion: str):
        super().__init__(usuario)
        self.cog, self.evento, self.edicion = cog, evento, edicion

    def _clave(self, tipo: str) -> str:
        return f"evento:{self.edicion}:{tipo}:{self.usuario.id}"

    @discord.ui.button(label="Regalo especial", emoji="🎁", style=discord.ButtonStyle.primary)
    async def regalo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.cog._rechazo_por_castigo(interaction):
            return
        if await database.config_obtener(self.cog.db, self._clave("regalo")):
            return await interaction.response.send_message("Ya me diste tu regalo de este evento. 🎀", ephemeral=True)
        await database.config_guardar(self.cog.db, self._clave("regalo"), "1")
        datos = self.evento["regalo"]
        nuevos = await self.cog.aplicar_actividad(
            self.usuario, None, datos["delta"], f"le regaló {datos['nombre'][2:].strip().lower()} en {self.evento['nombre'][2:].strip()}",
            contador="regalos_total", extra_logros=("festivo",),
        )
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"**{md(self.usuario.display_name)}** le regala {datos['nombre'].lower()} a Ribby.\n> {datos['respuesta']}"
            f"{_texto_logros(nuevos)}"
        )

    @discord.ui.button(label="Cita especial", emoji="💌", style=discord.ButtonStyle.primary)
    async def cita(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.cog._rechazo_por_castigo(interaction):
            return
        estado = await self.cog.cargar(self.usuario.id)
        if af.nivel(estado) == "desconocido":
            return await interaction.response.send_message("¿Una cita? ¡Si apenas te conozco! 😳", ephemeral=True)
        if estado.get("es_creador") and self.evento["id"] == "san_valentin":
            return await interaction.response.send_message(
                "¿Una cena de San Valentín con mi PADRE? ¡Qué vergüenza! 😭 Regálame chocolates y ya.", ephemeral=True
            )
        if await database.config_obtener(self.cog.db, self._clave("cita")):
            return await interaction.response.send_message("Ya tuvimos nuestra cita de este evento. 💌", ephemeral=True)
        await database.config_guardar(self.cog.db, self._clave("cita"), "1")
        cita = self.evento["cita"]
        button.disabled = True
        await interaction.response.edit_message(view=self)
        aventura = await self.cog.crear_cita(
            self.usuario, extra_logros=("festivo",),
            tema=f"{self.evento['nombre']}: {self.evento['contexto']}. La cita gira en torno a esta celebración.",
        )
        if aventura is not None:
            aventura.message = await interaction.followup.send(  # type: ignore[assignment]
                embed=aventura.embed_escena(), view=aventura, wait=True
            )
            return
        view = CitaView(self.cog, self.usuario, cita, clave_dia=None, extra_logros=("festivo",))
        embed = discord.Embed(title=cita["titulo"], description=f"{cita['escena']}\n\n*¿Qué haces?*", color=COLOR_ROMANCE)
        view.message = await interaction.followup.send(embed=embed, view=view, wait=True)  # type: ignore[assignment]


class CambiarMisionView(_SoloAutor):
    def __init__(self, cog: "Afinidad", usuario: discord.abc.User):
        super().__init__(usuario, timeout=180)
        self.cog = cog

    @discord.ui.button(label="Quiero otra historia", emoji="📚", style=discord.ButtonStyle.secondary)
    async def otra(self, interaction: discord.Interaction, button: discord.ui.Button):
        clave = f"mision_cambio:{self.usuario.id}"
        hoy = _hoy().isoformat()
        if await database.config_obtener(self.cog.db, clave) == hoy:
            return await interaction.response.send_message(
                "Ya cambiaste de misión hoy. Dale una oportunidad a esa historia, ¿quieres? 🙄", ephemeral=True
            )
        await database.config_guardar(self.cog.db, clave, hoy)
        self.stop()
        await interaction.response.edit_message(view=None)
        await self.cog.asignar_mision(interaction, self.usuario, cambio=True)


class CapituloView(_SoloAutor):
    """Lector estilo novela visual: páginas con ◀ ▶ y una decisión al final."""

    def __init__(self, cog: "Afinidad", usuario: discord.abc.User, cap: dict[str, Any], eleccion_previa: Optional[int]):
        super().__init__(usuario, timeout=900)
        self.cog, self.cap, self.previa = cog, cap, eleccion_previa
        self.pagina = 0
        self.preparar()

    def embed(self) -> discord.Embed:
        paginas = self.cap["paginas"]
        if self.pagina < len(paginas):
            texto, pie = paginas[self.pagina], f"Página {self.pagina + 1} de {len(paginas) + 1}"
        else:
            texto, pie = self.cap["pregunta"], "Tu decisión"
            if self.previa is not None:
                texto += f"\n\n*(La última vez elegiste: «{self.cap['opciones'][self.previa][0]}». Ribby lo recuerda.)*"
        e = discord.Embed(title=f"📕  {self.cap['titulo']}", description=texto, color=COLOR_ROMANCE)
        e.set_footer(text=pie)
        return e

    def preparar(self) -> None:
        self.clear_items()
        ultima = len(self.cap["paginas"])
        if self.pagina > 0:
            atras = discord.ui.Button(emoji="◀", style=discord.ButtonStyle.secondary)
            atras.callback = self._mover(-1)  # type: ignore[method-assign]
            self.add_item(atras)
        if self.pagina < ultima:
            sig = discord.ui.Button(label="Continuar", emoji="▶", style=discord.ButtonStyle.primary)
            sig.callback = self._mover(1)  # type: ignore[method-assign]
            self.add_item(sig)
        else:
            for i, (texto, _, _, _) in enumerate(self.cap["opciones"]):
                b = discord.ui.Button(label=texto[:80], style=discord.ButtonStyle.success, row=1 + i // 2)
                b.callback = self._elegir(i)  # type: ignore[method-assign]
                self.add_item(b)

    def _mover(self, paso: int):
        async def callback(interaction: discord.Interaction):
            self.pagina = max(0, min(self.pagina + paso, len(self.cap["paginas"])))
            self.preparar()
            await interaction.response.edit_message(embed=self.embed(), view=self)
        return callback

    def _elegir(self, i: int):
        async def callback(interaction: discord.Interaction):
            texto, delta, reaccion, recuerdo = self.cap["opciones"][i]
            primera_vez = await database.guardar_capitulo(self.cog.db, self.usuario.id, self.cap["id"], i)
            self.cog.invalidar_caches(self.usuario.id, pareja=False)  # Cambian los capítulos leídos (secretos)
            nuevos: list[str] = []
            if primera_vez:
                nuevos = await self.cog.aplicar_actividad(self.usuario, None, delta, recuerdo)
                nuevos += await self.cog.comprobar_logros(self.usuario.id, con_contadores=True)
            self.stop()
            e = discord.Embed(
                title=f"📕  {self.cap['titulo']}",
                description=f"**Tú:** {texto}\n\n**Ribby:** {reaccion}{_texto_logros(nuevos)}",
                color=COLOR_ROMANCE,
            )
            e.set_footer(text="Fin del capítulo" + ("" if primera_vez else " · Ribby recuerda lo que elegiste la primera vez"))
            await interaction.response.edit_message(embed=e, view=None)
        return callback


class QuizView(_SoloAutor):
    def __init__(self, cog: "Afinidad", usuario: discord.abc.User, quiz: dict[str, Any]):
        super().__init__(usuario, timeout=120)
        self.cog, self.quiz = cog, quiz
        self.message: Optional[discord.InteractionMessage] = None
        for i, opcion in enumerate(quiz["opciones"]):
            b = discord.ui.Button(label=opcion[:80], style=discord.ButtonStyle.secondary, row=i // 2)
            b.callback = self._responder(opcion)  # type: ignore[method-assign]
            self.add_item(b)

    def _responder(self, opcion: str):
        async def callback(interaction: discord.Interaction):
            acierto = opcion == self.quiz["correcta"]
            sobre_ribby = self.quiz["sobre"] == "ribby"
            if acierto:
                delta = 1.0 if sobre_ribby else 0.5
                nuevos = await self.cog.aplicar_actividad(
                    self.usuario, None, delta,
                    (f"en el quiz acertó «{self.quiz['pregunta'][:80]}» ({self.quiz['correcta']})" if sobre_ribby
                     else f"en el quiz demostró que recuerda lo que le contó a Ribby ({self.quiz['correcta']})"),
                    contador="quiz_aciertos",
                )
                respuesta = random.choice(lr.FRASES_ACIERTO) + _texto_logros(nuevos)
            else:
                if sobre_ribby:
                    await self.cog.aplicar_actividad(
                        self.usuario, None, -0.2,
                        f"en el quiz falló «{self.quiz['pregunta'][:80]}» (dijo {opcion}; era {self.quiz['correcta']})",
                    )
                respuesta = random.choice(lr.FRASES_FALLO).format(correcta=self.quiz["correcta"])
            self.stop()
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
                    if child.label == self.quiz["correcta"]:
                        child.style = discord.ButtonStyle.success
                    elif child.label == opcion:
                        child.style = discord.ButtonStyle.danger
            e = discord.Embed(
                title="🧠  ¿Me conoces?",
                description=f"**{self.quiz['pregunta']}**\n\n{'✅' if acierto else '❌'} {respuesta}",
                color=COLOR_ROMANCE if acierto else config.COLOR_ADVERTENCIA,
            )
            await interaction.response.edit_message(embed=e, view=self)
        return callback

    async def on_timeout(self):
        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(content="*Ribby se cansó de esperar tu respuesta.* 🙄", view=None)


class CitaAventuraView(_SoloAutor):
    """
    Una cita de varias escenas escrita por la IA para esta persona. Cada escena
    acaba en 3 decisiones con química oculta; al elegir se ve la reacción de
    Ribby y, mientras, se escribe la escena siguiente teniendo en cuenta lo que
    elegiste. Al final: desenlace, corazones y un recuerdo para Ribby.
    """

    LETRAS = ["🇦", "🇧", "🇨"]

    def __init__(self, cog: "Afinidad", usuario: discord.abc.User, plan: dict[str, Any], escena: dict[str, Any],
                 extra_logros: tuple[str, ...] = (), al_terminar=None):
        super().__init__(usuario, timeout=900)  # 15 min por escena (se reinicia con cada decisión)
        self.cog, self.plan, self.escena = cog, plan, escena
        self.extra_logros, self.al_terminar = extra_logros, al_terminar
        self.numero = 1
        self.historial: list[dict[str, Any]] = []
        self.efectos: list[float] = []
        self.terminada = False
        self._ocupada = False
        self.message: Optional[discord.Message] = None
        self.anterior: Optional[tuple[str, list]] = None  # (lo que elegiste, reacción de Ribby) para no perderla
        self._botones()

    _SEPARADOR = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"

    def _bloque_anterior(self) -> str:
        """Tu última elección y cómo reaccionó Ribby (se queda arriba de la escena siguiente)."""
        if not self.anterior:
            return ""
        eleccion, reaccion = self.anterior
        return f"**Tú:** {eleccion}\n\n{ct.formatear(reaccion, narracion_cursiva=True)}\n\n{self._SEPARADOR}\n\n"

    def embed_escena(self) -> discord.Embed:
        e = self.escena
        opciones = "\n".join(f"{self.LETRAS[i]}  {o['texto']}" for i, o in enumerate(e["opciones"]))
        narracion = ct.formatear(e.get("bloques") or ct.bloques_de(e["texto"], ct.LIMITES["texto"]))
        descripcion = f"{self._bloque_anterior()}{narracion}\n\n**{e['pregunta'] or '¿Qué haces?'}**\n\n{opciones}"
        embed = discord.Embed(title=self.plan["titulo"], description=descripcion[:4096], color=COLOR_ROMANCE)
        reto = " · 🧩 Reto" if self.numero == self.plan["escena_reto"] else ""
        final = " · ✨ Momento clave" if self.numero == self.plan["total"] else ""
        cola = "👨‍👧 Tarde con papá" if self.plan.get("familiar") else "Piénsalo bien…"
        embed.set_footer(text=f"Escena {self.numero} de {self.plan['total']}{reto}{final}  •  {cola}")
        return embed

    def _botones(self) -> None:
        self.clear_items()
        for i, _ in enumerate(self.escena["opciones"]):
            b = discord.ui.Button(emoji=self.LETRAS[i], style=discord.ButtonStyle.secondary)
            b.callback = self._crear_callback(i)  # type: ignore[method-assign]
            self.add_item(b)

    def _crear_callback(self, i: int):
        async def callback(interaction: discord.Interaction):
            await self._elegir(interaction, i)
        return callback

    async def _elegir(self, interaction: discord.Interaction, i: int) -> None:
        if self._ocupada or self.terminada:
            return await interaction.response.defer()
        self._ocupada = True
        try:
            opcion = self.escena["opciones"][i]
            self.historial.append({
                "escena": self.escena["texto"][:400], "eleccion": opcion["texto"],
                "reaccion": opcion["reaccion"], "efecto": opcion["efecto"],
            })
            self.efectos.append(opcion["efecto"])
            ultima = self.numero >= self.plan["total"]
            self.anterior = (opcion["texto"], opcion.get("reaccion_bloques") or ct.bloques_de(opcion["reaccion"], ct.LIMITES["reaccion"]))
            espera = ("La tarde llega a su fin…" if self.plan.get("familiar") else "La cita llega a su fin…") if ultima \
                else "Ribby piensa en lo que viene…"
            reaccion = discord.Embed(
                title=self.plan["titulo"],
                description=f"{self._bloque_anterior()}*{espera}* ⏳",
                color=COLOR_ROMANCE,
            )
            reaccion.set_footer(text=f"Escena {self.numero} de {self.plan['total']}")
            await interaction.response.edit_message(embed=reaccion, view=None)

            if ultima:
                return await self.terminar(interaction)
            siguiente = await self.cog.escena_siguiente(self.plan, self.historial, self.numero + 1)
            if siguiente is None:  # La IA falló: se cierra la cita con lo vivido hasta ahora
                return await self.terminar(interaction)
            self.numero += 1
            self.escena = siguiente
            self._botones()
            await interaction.edit_original_response(embed=self.embed_escena(), view=self)
        finally:
            self._ocupada = False

    async def terminar(self, interaction: Optional[discord.Interaction] = None, abandonada: bool = False) -> None:
        if self.terminada:
            return
        self.terminada = True
        self.stop()
        desenlace, corazones = ct.resultado(self.efectos, self.plan["total"], abandonada)
        texto_final, recuerdo = await self.cog.final_cita(self.plan, self.historial, desenlace)
        momento = "pasaron una tarde padre-hija" if self.plan.get("familiar") else "tuvieron una cita"
        nuevos = await self.cog.aplicar_actividad(
            self.usuario, None, corazones, f"{momento}: {self.plan['titulo']} — {recuerdo}",
            contador="citas_total", extra_logros=self.extra_logros,
        )
        with contextlib.suppress(Exception):
            await database.guardar_cita(
                self.cog.db, self.usuario.id, self.plan["titulo"], self.plan["premisa"],
                self.plan["ingredientes_dict"]["lugar"], recuerdo, desenlace, round(ct.quimica(self.efectos), 3),
            )
        if self.al_terminar:
            await self.al_terminar()

        titulos = ct.TITULO_DESENLACE_FAMILIA if self.plan.get("familiar") else ct.TITULO_DESENLACE
        embed = discord.Embed(
            title=f"{titulos[desenlace]}  ·  {self.plan['titulo']}",
            description=f"{self._bloque_anterior()}{texto_final}\n\n📔 *{recuerdo}*{_texto_logros(nuevos)}"[:4096],
            color=COLOR_ROMANCE if corazones > 0 else config.COLOR_ADVERTENCIA,
        )
        if self.efectos:
            embed.add_field(
                name="Complicidad" if self.plan.get("familiar") else "Química",
                value=ct.barra_quimica(ct.quimica(self.efectos), familiar=bool(self.plan.get("familiar"))), inline=False,
            )
        aciertos = sum(1 for e in self.efectos if e >= 0.6)
        embed.set_footer(text=f"Decisiones que le encantaron: {aciertos} de {len(self.efectos)}  •  "
                              + ("Cada tarde es única" if self.plan.get("familiar") else "Cada cita es única: la próxima será distinta"))
        try:
            if interaction is not None:
                await interaction.edit_original_response(embed=embed, view=None)
            elif self.message is not None:
                await self.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass

    async def on_timeout(self):
        if not self.terminada:
            await self.terminar(abandonada=True)


class OlvidarView(_SoloAutor):
    def __init__(self, saludos: Any, usuario: discord.abc.User):
        super().__init__(usuario, timeout=60)
        self.saludos = saludos

    @discord.ui.button(label="Sí, olvídalo todo", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.saludos.olvidar_usuario(self.usuario.id)
        self.stop()
        await interaction.response.edit_message(
            content="🧽 Hecho. ...Es raro, siento que te conocía de algo. Encantada, supongo. 📚", view=None
        )

    @discord.ui.button(label="No, mejor no", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Hmph. Menos mal, me había costado aprenderlo. 📔", view=None)


# ─────────────────────────── Cog ───────────────────────────

class Afinidad(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    async def cog_unload(self):
        self.revisar_pareja.cancel()
        self.tarea_social.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.revisar_pareja.is_running():
            self.revisar_pareja.start()
        if not self.tarea_social.is_running():
            self.tarea_social.start()

    # ── Persistencia ──

    # Cachés de pocos segundos: un mismo mensaje consultaba la relación y la pareja hasta 7 veces
    # (secretos, corazones, confidencias, logros...), y cada consulta es un viaje a Supabase.
    _TTL_RELACION = 10.0
    _TTL_CASTIGO = 30.0

    def _cache(self, nombre: str) -> dict:
        if not hasattr(self, "_caches"):
            self._caches: dict[str, dict] = {"afinidad": {}, "pareja": {}, "castigo": {}}
        return self._caches[nombre]

    def invalidar_caches(self, usuario_id: Any = None, pareja: bool = True) -> None:
        """Olvida lo cacheado (de una persona o de todas)."""
        if pareja:
            self._cache("pareja").clear()
        for nombre in ("afinidad", "castigo"):
            cache = self._cache(nombre)
            if usuario_id is None:
                cache.clear()
            else:
                for clave in [k for k in cache if k[1] in (str(usuario_id), f"capitulos:{usuario_id}")]:
                    cache.pop(clave, None)

    async def _cacheado(self, nombre: str, clave: Any, ttl: float, consulta):
        llave = (comun.en_prueba(), str(clave))
        cache = self._cache(nombre)
        guardado = cache.get(llave)
        if guardado is not None and monotonic() - guardado[0] < ttl:
            return copy.deepcopy(guardado[1])
        valor = await consulta()
        cache[llave] = (monotonic(), valor)
        return copy.deepcopy(valor)

    async def capitulos(self, usuario_id: int) -> dict[int, int]:
        return await self._cacheado(
            "afinidad", f"capitulos:{usuario_id}", self._TTL_RELACION, lambda: database.capitulos_leidos(self.db, usuario_id)
        )

    async def precargar(self, usuario_id: int) -> None:
        """
        Lee de golpe (en paralelo) lo que la charla va a necesitar de esta persona, para
        que mientras se analiza el mensaje todo quede en caché y luego no haya que esperar.
        """
        await asyncio.gather(
            self.cargar(usuario_id), self.pareja(), self.castigo_activo(usuario_id), self.capitulos(usuario_id),
            return_exceptions=True,
        )

    async def pareja(self) -> Optional[dict[str, Any]]:
        return await self._cacheado("pareja", "", self._TTL_RELACION, lambda: database.pareja_actual(self.db))

    async def cargar(self, usuario_id: int) -> dict[str, Any]:
        estado = await self._cacheado(
            "afinidad", usuario_id, self._TTL_RELACION, lambda: database.obtener_afinidad(self.db, usuario_id)
        ) or af.nuevo_estado()
        self._marcar_creador(estado, usuario_id)
        af.aplicar_paso_del_tiempo(estado)
        return estado

    @staticmethod
    def _marcar_creador(estado: dict[str, Any], usuario_id: Any) -> None:
        """Tainy, su creador: cariño de familia al máximo y nunca romántico (salvo en modo de pruebas)."""
        if comun.creador_activo(usuario_id):
            estado.update(es_creador=True, corazones=af.MAX_CORAZONES, es_pareja=False, coqueteos=0, fecha_maximo=None)

    async def guardar(self, usuario: discord.abc.User, estado: dict[str, Any]) -> None:
        ocupada = await self._ocupada_por_otro(usuario.id)
        # La pareja solo cambia si esta persona es (o era) la pareja de Ribby
        pareja_cacheada = self._cache("pareja").get((comun.en_prueba(), ""))
        era_pareja = bool(pareja_cacheada and pareja_cacheada[1]
                          and pareja_cacheada[1].get("usuario_discord_id") == str(usuario.id))
        try:
            await database.guardar_afinidad(self.db, usuario.id, usuario.display_name, estado, af.nivel(estado, ocupada))
        finally:
            # La caché queda con lo recién guardado (o se olvida si el guardado falló)
            self.invalidar_caches(usuario.id, pareja=bool(estado.get("es_pareja")) or era_pareja)
        guardado = dict(copy.deepcopy(estado), usuario_discord_id=str(usuario.id), nombre_display=usuario.display_name)
        guardado.pop("es_creador", None)  # No se guarda en la BD: se recalcula en cada carga (puede cambiar en pruebas)
        self._cache("afinidad")[(comun.en_prueba(), str(usuario.id))] = (monotonic(), guardado)

    async def _ocupada_por_otro(self, usuario_id: int) -> bool:
        pareja = await self.pareja()
        return bool(pareja and pareja["usuario_discord_id"] != str(usuario_id))

    # ── Logros ──

    async def comprobar_logros(
        self, usuario_id: int, estado: Optional[dict[str, Any]] = None, extra: tuple[str, ...] = (),
        con_contadores: bool = False,
    ) -> list[str]:
        """Evalúa y guarda logros. Retorna los recién desbloqueados."""
        try:
            ctx: dict[str, Any] = {}
            if estado is not None:
                ctx.update(
                    nivel=af.nivel(estado, await self._ocupada_por_otro(usuario_id)),
                    total_interacciones=estado.get("total_interacciones"), racha_dias=estado.get("racha_dias"),
                    citas_total=estado.get("citas_total"), regalos_total=estado.get("regalos_total"),
                    quiz_aciertos=estado.get("quiz_aciertos"),
                )
            if con_contadores:
                ctx["misiones"] = await database.contar_misiones_completadas(self.db, usuario_id)
                ctx["resenas"] = await database.contar_resenas_usuario(self.db, usuario_id)
                ctx["capitulos"] = len(await database.capitulos_leidos(self.db, usuario_id))
            return await database.otorgar_logros(self.db, usuario_id, sorted(lg.evaluar(ctx) | set(extra)))
        except Exception as e:  # noqa: BLE001
            log.warning(f"No se pudieron comprobar logros de {usuario_id}: {e}")
            return []

    # ── Integración con Saludos ──

    async def procesar_mensaje(
        self, message: discord.Message, texto: str, tono: str, coqueteo: Optional[bool] = None
    ) -> Resultado:
        """
        Actualiza la relación con quien le habla y devuelve el contexto para la IA.
        `tono` y `coqueteo` vienen del análisis del mensaje (Hugging Face o reglas).
        """
        if coqueteo is None:
            coqueteo = af.es_coqueteo(texto)
        usuario = message.author
        estado = await self.cargar(usuario.id)
        pareja = await self.pareja()
        ocupada = bool(pareja and pareja["usuario_discord_id"] != str(usuario.id))
        nombre_pareja = pareja["nombre_display"] if ocupada and pareja else None

        castigo = await self.castigo_activo(usuario.id)
        corazones_antes = float(estado.get("corazones") or 0)
        _, previo, nuevo = af.aplicar_interaccion(estado, tono, coqueteo, ocupada)
        if castigo and estado["corazones"] > corazones_antes:  # Castigado: hablar no le da corazones
            estado["corazones"] = corazones_antes
            nuevo = af.nivel(estado, ocupada)
        resultado = Resultado(subio_nivel=_orden(nuevo) > _orden(previo), castigado=bool(castigo))

        declaracion = af.declarar(estado, ocupada) if af.es_declaracion(texto) else None
        if declaracion == "acepta":
            try:
                await self.guardar(usuario, estado)
                resultado.nueva_pareja = True
            except asyncpg.UniqueViolationError:
                # Otra persona se declaró justo a la vez y llegó primero
                estado = await self.cargar(usuario.id)
                declaracion, ocupada = "ocupada", True
                af.aplicar_interaccion(estado, tono, False, ocupada)
                await self.guardar(usuario, estado)
        else:
            await self.guardar(usuario, estado)

        extra = ("rechazado",) if declaracion in ("pronto", "casi") else ()
        resultado.logros = await self.comprobar_logros(usuario.id, estado, extra)

        partes = [af.contexto_prompt(estado, ocupada, nombre_pareja, declaracion)]
        if castigo:
            partes.append(
                f"AHORA MISMO ESTÁS ENFADADA con esta persona (hasta el {castigo['hasta_texto']}) porque "
                f"{castigo['motivo']}. Le contestas seca y cortante, con sarcasmo, y se lo recuerdas si viene a cuento; "
                "no aceptas coqueteos ni planes. Sin insultos fuertes ni humillaciones: estás dolida, no eres cruel."
            )
        temporada = _contexto_temporada()
        if temporada:
            partes.append(temporada)
        resultado.contexto = "\n".join(partes)
        return resultado

    async def despues_de_responder(self, message: discord.Message, resultado: Resultado) -> None:
        try:
            if resultado.nueva_pareja:
                embed = discord.Embed(
                    title="💞  ¡Noticias en la biblioteca!",
                    description=(
                        f"{message.author.mention} se armó de valor y le pidió a Ribby ser su pareja...\n\n"
                        "**¡Y ella dijo que sí!** 🎀\n\n*Ribby se esconde detrás de un libro, completamente roja.*"
                    ),
                    color=COLOR_ROMANCE,
                    timestamp=datetime.now(timezone.utc),
                )
                await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[message.author]))
            elif resultado.subio_nivel:
                await message.add_reaction("💗")
            if resultado.logros:
                await message.add_reaction("🏅")  # Discreto: el detalle se ve en /ribby logros
        except discord.HTTPException:
            pass

    async def aplicar_actividad(
        self, usuario: discord.abc.User, clave: Optional[str], delta: float, evento: str,
        contador: Optional[str] = None, extra_logros: tuple[str, ...] = (),
    ) -> list[str]:
        """Regalos, citas, misiones... Retorna los logros recién desbloqueados."""
        estado = await self.cargar(usuario.id)
        ocupada = await self._ocupada_por_otro(usuario.id)
        af.aplicar_bonus(estado, delta, ocupada)
        if clave:
            af.marcar_hoy(estado, clave)
        if contador:
            estado[contador] = int(estado.get(contador) or 0) + 1
        af.registrar_evento(estado, (clave or contador or "actividad").replace("ultimo_", "").replace("ultima_", ""), evento)
        await self.guardar(usuario, estado)
        return await self.comprobar_logros(usuario.id, estado, extra_logros)

    # ── Misiones de lectura (las completa /biblioteca resenar) ──

    async def al_resenar(self, usuario: discord.abc.User, historia: dict[str, Any]) -> str:
        """Llamado por la biblioteca tras guardar una reseña. Retorna un mensaje privado (o "")."""
        mision = await database.mision_activa(self.db, usuario.id)
        texto = ""
        if mision and mision["historia_id"] == historia["id"]:
            minutos = (datetime.now(timezone.utc) - mision["fecha_asignada"]).total_seconds() / 60
            if minutos < MINUTOS_MINIMOS_MISION:
                return (f"🤨 ¿Ya te leíste **{md(historia['titulo'])}**? Hace {int(minutos)} minutos que te la encargué. "
                        "Guardé tu reseña, pero la misión la daré por cumplida cuando haya pasado al menos una hora.")
            await database.completar_mision(self.db, mision["id"])
            nuevos = await self.aplicar_actividad(
                usuario, None, 2.0, f"leyó «{historia['titulo']}» por recomendación de Ribby y le contó qué le pareció",
            )
            nuevos += await self.comprobar_logros(usuario.id, con_contadores=True)
            texto = ("📚 **¡Misión cumplida!** *Ribby sonríe sin poder evitarlo.* Hm. Así que de verdad la leíste... "
                     "Eso me gusta. Pide otra cuando quieras con `/ribby mision`. 💗")
            return texto + _texto_logros(nuevos)
        nuevos = await self.comprobar_logros(usuario.id, con_contadores=True)
        return _texto_logros(nuevos).strip()

    # ── Castigos del staff ──

    async def castigo_activo(self, usuario_id: Any) -> Optional[dict[str, Any]]:
        """{"hasta", "hasta_texto", "motivo"} si Ribby sigue enfadada con esta persona; None si no."""
        valor = await self._cacheado(
            "castigo", usuario_id, self._TTL_CASTIGO, lambda: database.config_obtener(self.db, f"castigo:{usuario_id}")
        )
        if not valor:
            return None
        try:
            datos = json.loads(valor)
            hasta = date.fromisoformat(datos["hasta"])
        except (ValueError, KeyError, TypeError):
            return None
        if hasta < _hoy():
            await database.config_borrar(self.db, f"castigo:{usuario_id}")
            return None
        return {"hasta": hasta, "hasta_texto": f"{hasta.day}/{hasta.month}", "motivo": datos.get("motivo") or ""}

    async def aplicar_castigo(
        self, interaction: discord.Interaction, usuario: discord.abc.User, motivo: str,
        corazones: int = CASTIGO_CORAZONES, dias: int = CASTIGO_DIAS,
    ) -> None:
        """
        Quita corazones, deja a Ribby enfadada unos días (seca en la charla, sin citas,
        regalos ni reseñas) y la regaña en público. Si era su pareja y cae por debajo
        del umbral, Ribby la deja. La respuesta del comando ya debe estar enviada.
        """
        estado = await self.cargar(usuario.id)
        antes = float(estado.get("corazones") or 0)
        nuevo = max(0.0, antes - corazones)
        termino = False
        if estado.get("es_pareja") and nuevo < CASTIGO_UMBRAL_PAREJA:
            af.terminar(estado, f"Ribby terminó la relación porque {motivo}")
            termino = True
            nuevo = min(nuevo, estado["corazones"])
        estado["corazones"] = nuevo
        af.registrar_evento(estado, "castigo", f"Ribby se enfadó muchísimo porque {motivo}")
        await self.guardar(usuario, estado)
        hasta = _hoy() + timedelta(days=dias)
        await database.config_guardar(
            self.db, f"castigo:{usuario.id}", json.dumps({"hasta": hasta.isoformat(), "motivo": motivo}, ensure_ascii=False)
        )
        self.invalidar_caches(usuario.id)
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:  # En la charla también se le nota
            estado_charla = await saludos._obtener_estado(usuario.id)  # type: ignore[attr-defined]
            estado_charla["mood"] = "tsundere"
        log.info(f"💢 {interaction.user} castigó a {usuario} ({motivo}): {antes:.0f} → {nuevo:.0f} corazones, {dias} día(s)")

        estado["usuario_discord_id"] = str(usuario.id)
        texto = await self._generar(
            estado, usuario.display_name,
            f"El staff te ha contado que {usuario.display_name} {motivo}. Estás MUY enfadada. Regáñale en público: "
            "sarcasmo afilado, dignidad herida, deja claro que eso no se hace en tu biblioteca y que vas a estar "
            f"enfadada con esta persona unos días{' y que lo vuestro se ha terminado' if termino else ''}. Puedes ser "
            "dura, pero sin palabrotas, sin insultos fuertes y sin burlarte de su físico, identidad o vida personal.",
        ) or random.choice(REGAÑINAS)
        aviso = discord.Embed(
            description=f"💢 **−{antes - nuevo:.0f} corazones**  ·  Ribby estará enfadada hasta el {hasta.day}/{hasta.month}"
                        + ("\n💔 **Ribby ha terminado la relación.**" if termino else ""),
            color=config.COLOR_ERROR,
        )
        with contextlib.suppress(discord.HTTPException, AttributeError):
            await interaction.channel.send(  # type: ignore[union-attr]
                f"{usuario.mention} {texto}", embed=aviso, allowed_mentions=discord.AllowedMentions(users=[usuario])
            )

    async def _rechazo_por_castigo(self, interaction: discord.Interaction) -> bool:
        castigo = await self.castigo_activo(interaction.user.id)
        if not castigo:
            return False
        await interaction.response.send_message(
            f"¿Ahora vienes con esas? Sigo enfadada contigo hasta el {castigo['hasta_texto']}. Ya sabes por qué. 😤",
            ephemeral=True,
        )
        return True

    # ── Secretos escondidos ──

    async def _ctx_secretos(self, usuario: discord.abc.User) -> sec.Contexto:
        estado = await self.cargar(usuario.id)
        ocupada = await self._ocupada_por_otro(usuario.id)
        ahora_local = datetime.now(af.ZONA)
        return sec.Contexto(
            hora=ahora_local.hour, fecha=ahora_local.date(), nivel=af.nivel(estado, ocupada),
            capitulos=set(await self.capitulos(usuario.id)),
            es_pareja=bool(estado.get("es_pareja")), es_creador=bool(estado.get("es_creador")),
        )

    async def _descubrir(self, usuario: discord.abc.User, s: sec.Secreto, canal: Any) -> Optional[discord.Embed]:
        """
        Registra el secreto. Si es la primera vez para esta persona devuelve el embed
        de la reacción (y, si nadie lo había encontrado antes, lo anuncia al servidor).
        None si ya lo conocía.
        """
        antes = await database.secretos_descubiertos(self.db)
        nuevos = await database.otorgar_logros(self.db, usuario.id, [s.logro])
        if not nuevos:
            return None
        mios = {k for k in await database.logros_de(self.db, usuario.id) if k.startswith("secreto_")}
        pendientes = [x for x in sec.SECRETOS if x.logro not in mios]
        otros = await self.aplicar_actividad(usuario, None, s.corazones, f"descubrió el secreto «{s.nombre}» de Ribby")

        embed = discord.Embed(
            title=f"🔓  {s.emoji}  Secreto descubierto: {s.nombre}",
            description=f"{sec.reaccion(s, pendientes)}{_texto_logros([s.logro] + otros)}",
            color=config.COLOR_ORO,
        )
        embed.set_footer(text=f"Has descubierto {len(mios)} de {len(sec.SECRETOS)} secretos de Ribby  •  /ribby secretos")
        log.info(f"🔓 {usuario.display_name} descubrió el secreto «{s.id}»")

        if s.logro not in antes:  # ¡Nadie lo había encontrado! Se anuncia sin revelar cómo
            total = len(antes) + 1
            anuncio = discord.Embed(
                title="🔓  ¡Un secreto de Ribby ha sido descubierto!",
                description=(
                    f"**{md(usuario.display_name)}** es la primera persona en descubrir **{s.emoji} {s.nombre}**.\n\n"
                    f"La comunidad lleva **{total} de {len(sec.SECRETOS)}** secretos. ¿Quién encontrará el siguiente?\n"
                    "*Las pistas están en `/ribby secretos`.*"
                ),
                color=config.COLOR_ORO,
            )
            destino = await self._canal() or canal
            with contextlib.suppress(discord.HTTPException, AttributeError):
                await destino.send(embed=anuncio, allowed_mentions=discord.AllowedMentions.none())
        return embed

    async def revisar_secreto_frase(self, message: discord.Message, texto: str) -> tuple[bool, str]:
        """
        Lo llama la charla antes de responder. (respondido, contexto_para_la_IA):
          - Secreto nuevo para esta persona → reacción especial (y no responde la IA).
          - Aún no le toca → Ribby lo esquiva, nerviosa (eso ya es una pista).
          - Ya lo conocía → la IA responde normal, sabiendo que es "su" secreto compartido.
        """
        ctx = await self._ctx_secretos(message.author)
        encontrado = sec.detectar_frase(texto, ctx)
        if encontrado is None:
            return False, ""
        s, permitido = encontrado
        if not permitido:
            with contextlib.suppress(discord.HTTPException):
                await message.reply(s.esquiva, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return True, ""
        embed = await self._descubrir(message.author, s, message.channel)
        if embed is None:
            return False, (
                f"Este mensaje toca uno de tus secretos («{s.nombre}»: {s.descripcion.lower()}), y esta persona ya "
                "lo descubrió antes. Reacciona con complicidad, como quien comparte un secreto, sin repetir lo de "
                "la primera vez."
            )
        with contextlib.suppress(discord.HTTPException):
            await message.reply(embed=embed, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        return True, ""

    async def revisar_secreto_accion(self, usuario: discord.abc.User, accion: str, canal: Any) -> Optional[discord.Embed]:
        """Secretos que se desbloquean haciendo algo (regalos, citas a cierta hora...)."""
        try:
            s = sec.detectar_accion(accion, await self._ctx_secretos(usuario))
            return await self._descubrir(usuario, s, canal) if s else None
        except Exception as e:  # noqa: BLE001 — un secreto nunca debe romper el comando
            log.warning(f"No se pudo revisar el secreto de la acción {accion}: {e}")
            return None

    # ── Confidencias: Ribby se abre según la confianza ──

    async def confidencias_para_charla(self, usuario: discord.abc.User, subio_nivel: bool = False) -> tuple[Optional[str], list[str]]:
        """
        (nueva, ya_contadas). Como mucho una confidencia nueva al día (o al subir de
        nivel), y no siempre: Ribby se abre poco a poco.
        """
        uid = usuario.id
        if await self.castigo_activo(uid):
            return None, []
        estado = await self.cargar(uid)
        nivel = af.nivel(estado, await self._ocupada_por_otro(uid))
        clave = f"confidencias:{uid}"
        try:
            contadas: list[str] = json.loads(await database.config_obtener(self.db, clave) or "[]")
        except ValueError:
            contadas = []
        textos = sec.texto_confidencias(contadas)
        hoy = _hoy().isoformat()
        if await database.config_obtener(self.db, f"confidencia_dia:{uid}") == hoy:
            return None, textos
        if not subio_nivel and random.random() > sec.PROBABILIDAD_CONFIDENCIA:
            return None, textos
        siguiente = sec.siguiente_confidencia(nivel, contadas)
        if siguiente is None:
            return None, textos
        cid, texto = siguiente
        await database.config_guardar(self.db, clave, json.dumps(contadas + [cid]))
        await database.config_guardar(self.db, f"confidencia_dia:{uid}", hoy)
        af.registrar_evento(estado, "confidencia", f"Ribby le contó un secreto: {texto[0].lower()}{texto[1:]}")
        await self.guardar(usuario, estado)
        log.info(f"🤫 Ribby le cuenta una confidencia a {usuario.display_name} ({cid})")
        return texto, textos

    # ── Citas: aventuras generadas por la IA ──

    def _modelo(self):
        modelo = getattr(self.bot.get_cog("Saludos"), "model", None)
        return modelo if modelo is not None and getattr(modelo, "providers", None) else None

    async def _ia_cita(self, pedido: str) -> Optional[str]:
        modelo = self._modelo()
        if modelo is None:
            return None
        try:
            return await modelo.generate(
                ct.SYSTEM_DIRECTOR, [{"role": "user", "content": pedido}], max_tokens=ct.MAX_TOKENS_ESCENA
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"La IA no pudo escribir la cita: {e}")
            return None

    async def crear_cita(
        self, usuario: discord.abc.User, extra_logros: tuple[str, ...] = (), tema: str = "", al_terminar=None,
    ) -> Optional[CitaAventuraView]:
        """Prepara una cita única para esta persona (título, premisa y escena 1). None si la IA no está disponible."""
        if self._modelo() is None:
            return None
        estado = await self.cargar(usuario.id)
        pareja = await self.pareja()
        ocupada = bool(pareja and pareja["usuario_discord_id"] != str(usuario.id))
        nivel = af.nivel(estado, ocupada)
        familiar = nivel == "creador"  # Con Tainy: tarde padre-hija, nunca una cita romántica
        hechos, _, resumen = await self._datos_memoria(usuario.id)
        previas = await database.citas_de(self.db, usuario.id)
        ingredientes = ct.sortear_ingredientes((c.get("lugar") or "" for c in previas), familiar=familiar)
        noticias = await self._noticias_para_papa(usuario) if familiar else ""
        total = random.randint(ct.ESCENAS_MIN, ct.ESCENAS_MAX)
        escena_reto = random.randint(2, total - 1)
        datos = mem.texto_hechos([h for h in hechos if h.get("tipo") != "vida"])
        pedido = ct.pedido_inicio(
            usuario.display_name, nivel,
            af.contexto_prompt(estado, ocupada, pareja["nombre_display"] if ocupada and pareja else None),
            resumen, datos, previas, await database.premisas_recientes(self.db, 15), ingredientes, total, escena_reto,
            ct.gustos_ribby(lr.PREGUNTAS_RIBBY, await database.capitulos_leidos(self.db, usuario.id)),
            _contexto_temporada(), tema, noticias,
        )
        inicio = ct.parsear_inicio(await self._ia_cita(pedido) or "")
        if inicio is None:
            return None
        titulo, premisa, escena = inicio
        plan = {
            "titulo": titulo, "premisa": premisa, "total": total, "escena_reto": escena_reto,
            "nombre": usuario.display_name, "datos": datos, "tono": ct.TONO_POR_NIVEL.get(nivel, ct.TONO_POR_NIVEL["amigo"]),
            "ingredientes": f"lugar = {ingredientes['lugar']}; objeto = {ingredientes['objeto']}; giro = {ingredientes['giro']}",
            "ingredientes_dict": ingredientes,
            "familiar": familiar, "noticias": noticias,
        }
        log.info(f"💌 Cita para {usuario.display_name}: «{titulo}» ({total} escenas, {nivel})")
        return CitaAventuraView(self, usuario, plan, escena, extra_logros, al_terminar)

    async def _noticias_para_papa(self, usuario: discord.abc.User) -> str:
        """Lo que Ribby puede contarle a su creador: su pareja, sus amigos, La Comarca, el reto y la biblioteca."""
        lineas: list[str] = []

        async def datos_de(uid: str) -> str:
            memoria = await database.obtener_memoria_usuario(self.db, uid) or {}
            partes = []
            if memoria.get("resumen"):
                partes.append(str(memoria["resumen"])[:220])
            datos = [h["texto"] for h in mem.cargar_lista(memoria.get("hechos")) if h.get("tipo") in mem.TIPOS_COMPARTIBLES]
            if datos:
                partes.append("Datos: " + "; ".join(datos[-4:]))
            return " ".join(partes)

        try:
            pareja = await self.pareja()
            if pareja:
                uid = pareja["usuario_discord_id"]
                dias = af.dias_desde(pareja.get("fecha_inicio_pareja"))
                linea = f"- SU PAREJA es {pareja['nombre_display']} (llevan {dias} días juntos). {await datos_de(uid)}"
                momentos = [e["texto"] for e in pareja.get("eventos", []) if e.get("tipo") != "nivel"][-4:]
                if momentos:
                    linea += " Momentos juntos: " + "; ".join(momentos) + "."
                citas_pareja = await database.citas_de(self.db, uid, 3)
                if citas_pareja:
                    linea += " Sus últimas citas: " + "; ".join(
                        f"«{c['titulo']}» ({c.get('resumen') or c.get('premisa') or ''})" for c in citas_pareja
                    ) + "."
                lineas.append(linea)
            else:
                lineas.append("- Ahora mismo no tiene pareja.")

            amigos = [a for a in await database.mejores_amigos_ribby(self.db, 8)
                      if not comun.es_creador_id(a["usuario_discord_id"])][:5]
            for a in amigos:
                n = af.nivel(a, bool(pareja))
                if n in ("algo_mas", "enamorada"):
                    texto = f"- Alguien que LE GUSTA (aún no son pareja; le da mucha vergüenza contarlo): {a['nombre_display']}."
                else:
                    texto = f"- Amigo/a ({af.NIVELES[n][0]}): {a['nombre_display']}."
                extra = await datos_de(a["usuario_discord_id"])
                lineas.append(f"{texto} {extra[:260]}".strip())

            guild = getattr(usuario, "guild", None)
            if guild is not None:
                comunidad = await database.config_obtener(self.db, f"memoria_comunidad:{guild.id}")
                if comunidad:
                    lineas.append(f"- Lo que pasa últimamente en La Comarca: {comunidad}")

            activo = await database.obtener_evento_activo(self.db)
            if activo:
                lineas.append(f"- Hay un reto literario en marcha: «{activo['nombre']}» (fase: {activo['estado']}).")

            biblioteca = self.bot.get_cog("Biblioteca")
            if biblioteca is not None:
                catalogo = await biblioteca.catalogo()  # type: ignore[attr-defined]
                nuevas = sorted((h for h in catalogo if h.get("fecha_alta")), key=lambda h: h["fecha_alta"], reverse=True)[:3]
                lineas.append(
                    f"- Su biblioteca tiene {len(catalogo)} historias."
                    + (" Las últimas que llegaron: " + "; ".join(
                        f"«{h['titulo']}» de {h.get('autor_nombre') or 'alguien'}" for h in nuevas) + "." if nuevas else "")
                )

            otras = await database.premisas_recientes(self.db, 4)
            if otras:
                lineas.append("- Sus últimas citas con gente del servidor: " + "; ".join(otras) + ".")
        except Exception as e:  # noqa: BLE001 — la tarde sigue aunque falte alguna noticia
            log.warning(f"No se pudieron reunir todas las noticias para Tainy: {e}")
        return "\n".join(lineas)

    async def escena_siguiente(self, plan: dict[str, Any], historial: list[dict[str, Any]], numero: int) -> Optional[dict[str, Any]]:
        pedido = ct.pedido_siguiente(plan, historial, numero, plan["total"], plan["escena_reto"])
        for _ in range(2):  # Un reintento si el JSON no viene bien
            escena = ct.parsear_escena(await self._ia_cita(pedido) or "")
            if escena is not None:
                return escena
        return None

    async def final_cita(self, plan: dict[str, Any], historial: list[dict[str, Any]], desenlace: str) -> tuple[str, str]:
        final = ct.parsear_final(await self._ia_cita(ct.pedido_final(plan, historial, desenlace)) or "")
        if final is not None:
            texto, recuerdo = final
            return texto, recuerdo or f"Ribby recuerda la cita «{plan['titulo']}»."
        respaldo = {
            "perfecta": "Ribby no deja de sonreír en todo el camino de vuelta. \"...Repetimos. Pronto. Es una orden.\" 💗",
            "bonita": "\"Ha estado bien. Muy bien, de hecho.\" Ribby se despide con un saludo de pata y una sonrisa. 🌸",
            "regular": "\"Bueno... no todo salió como esperaba. Pero gracias por venir.\" 🙂",
            "desastre": "Ribby suspira... y acaba riéndose. \"Ha sido un desastre. Pero un desastre contigo.\" 💥",
            "a_medias": "Ribby se queda esperando un rato más antes de volver sola a la biblioteca. 🕯️",
        }[desenlace]
        return ct.formatear(ct.bloques_de(respaldo, ct.LIMITES["final"])), f"Ribby recuerda la cita «{plan['titulo']}»."

    # ── Generación de mensajes propios (iniciativa, cumpleaños, aniversarios) ──

    async def _generar(self, estado: dict[str, Any], nombre: str, instruccion: str) -> Optional[str]:
        saludos = self.bot.get_cog("Saludos")
        modelo = getattr(saludos, "model", None)
        if not modelo or not getattr(modelo, "providers", None):
            return None
        self._marcar_creador(estado, estado.get("usuario_discord_id"))
        memoria = await database.obtener_memoria_usuario(self.db, estado.get("usuario_discord_id") or "0")
        datos = mem.texto_hechos(mem.cargar_lista((memoria or {}).get("hechos")))
        sistema = (
            "Eres Ribby, la bibliotecaria del servidor de Discord 'La Comarca': una Sylveon lista, simpática y "
            "cariñosa, con un toque tsundere que se nota menos cuanta más confianza hay. Escribes en español, con tu voz, en 1-3 frases y con 1-2 emojis como mucho. "
            "Nunca suenes a asistente virtual. Sin acotaciones de narrador ni asteriscos.\n"
            f"{af.REGLAS_ROMANCE}\n"
            f"Sobre {nombre}: {(memoria or {}).get('resumen') or 'aún sabes poco de esta persona.'}\n"
            + (f"Datos que recuerdas de {nombre} (úsalos con naturalidad, sin recitarlos):\n{datos}\n" if datos else "")
            + f"Vuestra relación:\n{af.contexto_prompt(estado, False)}\n{_contexto_temporada()}"
        )
        try:
            texto = await modelo.generate(sistema, [{"role": "user", "content": instruccion}])
            return texto.strip()[:1500] if texto else None
        except Exception as e:  # noqa: BLE001
            log.warning(f"No se pudo generar un mensaje propio de Ribby: {e}")
            return None

    async def _canal(self) -> Optional[discord.TextChannel]:
        valor = await database.config_obtener(self.db, "canal_ribby")
        canal = self.bot.get_channel(int(valor)) if valor and valor.isdigit() else None
        return canal if isinstance(canal, discord.TextChannel) else None

    # ── Tareas programadas ──

    @tasks.loop(hours=6)
    async def revisar_pareja(self):
        """Si la pareja lleva semanas sin aparecer, la relación termina y el puesto queda libre."""
        try:
            pareja = await self.pareja()
            if pareja and af.aplicar_paso_del_tiempo(pareja):
                await database.guardar_afinidad(
                    self.db, pareja["usuario_discord_id"], pareja["nombre_display"], pareja, af.nivel(pareja)
                )
                self.invalidar_caches()
                log.info(f"💔 La relación con {pareja['nombre_display']} terminó por inactividad")
        except Exception as e:  # noqa: BLE001
            log.warning(f"No se pudo revisar la pareja de Ribby: {e}")

    @tasks.loop(minutes=30)
    async def tarea_social(self):
        try:
            canal = await self._canal()
            if canal is None:
                return
            ahora_local = datetime.now(af.ZONA)
            hoy = ahora_local.date()
            clave = f"celebrado:{hoy.isoformat()}"
            if ahora_local.hour >= 9 and await database.config_obtener(self.db, clave) is None:
                await database.config_guardar(self.db, clave, "1")
                await self._celebraciones(canal, hoy)
            await self._seguimientos(canal, ahora_local)
            await self._iniciativa(canal, ahora_local)
        except Exception as e:  # noqa: BLE001
            log.exception(f"Error en la tarea social de Ribby: {e}")

    async def _seguimientos(self, canal: discord.TextChannel, ahora_local: datetime) -> None:
        """
        "¿Qué tal te fue en el examen?": si alguien le contó algo con fecha y ya
        llegó el día, Ribby le pregunta por su cuenta. Uno por vuelta, como mucho
        SEGUIMIENTOS_POR_DIA al día, nunca a quien desactivó los avisos y solo a
        quien ya es al menos su amigo.
        """
        if not INICIATIVA_HORAS[0] <= ahora_local.hour < INICIATIVA_HORAS[1]:
            return
        hoy = ahora_local.date()
        clave_dia = f"seguimientos:{hoy.isoformat()}"
        hechos_hoy = int(await database.config_obtener(self.db, clave_dia) or 0)
        if hechos_hoy >= SEGUIMIENTOS_POR_DIA:
            return

        saludos = self.bot.get_cog("Saludos")
        for fila in await database.memorias_con_pendientes(self.db):
            uid = fila["usuario_discord_id"]
            pendientes = mem.cargar_lista(fila.get("pendientes"))
            # Solo lo que tocaba ayer o antes: lo de hoy se le pregunta si aparece por la charla
            debidos = [p for p in mem.pendientes_para_hoy(pendientes, hoy) if mem.cuando(p.get("fecha"), hoy) != "hoy"]
            if not debidos or not uid.isdigit():
                continue
            if await database.config_obtener(self.db, f"sin_avisos:{uid}") or await self.castigo_activo(uid):
                continue
            miembro = canal.guild.get_member(int(uid))
            if miembro is None:
                continue
            estado = await self.cargar(miembro.id)
            if af.nivel(estado) == "desconocido":
                continue
            estado["usuario_discord_id"] = uid
            p = debidos[0]
            texto = await self._generar(
                estado, miembro.display_name,
                f"{miembro.display_name} te contó que {mem.cuando(p.get('fecha'), hoy)} tenía esto: «{p['texto']}». "
                "Escríbele por tu cuenta en el canal para preguntarle cómo le fue, de forma natural y breve, acorde "
                "a vuestra relación. Sin presionar.",
            )
            if not texto:
                continue
            await canal.send(f"{miembro.mention} {texto}", allowed_mentions=discord.AllowedMentions(users=[miembro]))
            nuevos = mem.marcar_preguntados(pendientes, [p])
            if saludos is not None:  # Mantiene coherente la copia en memoria de la charla
                datos, pend_ram, _ = await saludos.datos_de(miembro.id)  # type: ignore[attr-defined]
                pend_ram[:] = mem.marcar_preguntados(pend_ram, [p])
            await database.guardar_hechos_pendientes(self.db, uid, pendientes=mem.a_json(nuevos))
            await database.config_guardar(self.db, clave_dia, str(hechos_hoy + 1))
            log.info(f"📅 Ribby preguntó a {miembro.display_name} por «{p['texto']}»")
            return

    async def _celebraciones(self, canal: discord.TextChannel, hoy: date) -> None:
        # 1) Empieza un evento de temporada
        evento = temporadas.evento_actual(hoy)
        if evento and temporadas.es_primer_dia(evento, hoy):
            await canal.send(embed=discord.Embed(
                title=f"{evento['nombre']} llega a la biblioteca",
                description=f"*{evento['anuncio']}*\n\n"
                            "Usa `/ribby evento` para un regalo y una cita especiales. ¡Solo durante estos días! 🎀",
                color=COLOR_ROMANCE,
            ))

        # 2) Cumpleaños (los del 29 de febrero se celebran el 28 en años no bisiestos)
        ids = await database.cumpleanos_del_dia(self.db, hoy.day, hoy.month)
        if hoy.month == 2 and hoy.day == 28 and not calendar.isleap(hoy.year):
            ids += await database.cumpleanos_del_dia(self.db, 29, 2)
        for uid in ids:
            miembro = canal.guild.get_member(int(uid))
            if miembro is None:
                continue
            estado = await self.cargar(miembro.id)
            estado["usuario_discord_id"] = uid
            texto = await self._generar(
                estado, miembro.display_name,
                f"Hoy es el cumpleaños de {miembro.display_name}. Felicítale con cariño acorde a vuestra relación.",
            ) or f"¡Feliz cumpleaños! 🎂 ...Te guardé el mejor sillón de la biblioteca hoy. No te acostumbres."
            await canal.send(
                f"🎂 {miembro.mention} {texto}", allowed_mentions=discord.AllowedMentions(users=[miembro])
            )
            await self.aplicar_actividad(miembro, None, 3.0, f"Ribby le felicitó por su cumpleaños ({hoy.year})")

        # 3) Aniversario mensual con la pareja
        pareja = await self.pareja()
        inicio = pareja and pareja.get("fecha_inicio_pareja")
        if pareja and inicio:
            fecha = datetime.fromisoformat(inicio).astimezone(af.ZONA).date()
            meses = (hoy.year - fecha.year) * 12 + hoy.month - fecha.month
            ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
            if meses >= 1 and hoy.day == min(fecha.day, ultimo_dia):
                miembro = canal.guild.get_member(int(pareja["usuario_discord_id"]))
                if miembro:
                    texto = await self._generar(
                        pareja, miembro.display_name,
                        f"Hoy se cumplen {meses} mes(es) desde que tú y {miembro.display_name} sois pareja. "
                        "Dedícale unas palabras de aniversario.",
                    ) or "...¿Sabes qué día es hoy? Claro que lo sabes. Yo también. 💞"
                    await canal.send(
                        f"💞 **{meses} {'mes' if meses == 1 else 'meses'} juntos** — {miembro.mention} {texto}",
                        allowed_mentions=discord.AllowedMentions(users=[miembro]),
                    )
                    await self.aplicar_actividad(miembro, None, 0, f"celebraron {meses} mes(es) como pareja")

    async def _iniciativa(self, canal: discord.TextChannel, ahora_local: datetime) -> None:
        """De vez en cuando, Ribby saluda por su cuenta a un mejor amigo o a su pareja."""
        if not INICIATIVA_HORAS[0] <= ahora_local.hour < INICIATIVA_HORAS[1]:
            return
        ultima = await database.config_obtener(self.db, "iniciativa:ultima")
        ahora_utc = ahora_local.astimezone(timezone.utc)
        if ultima and ahora_utc - datetime.fromisoformat(ultima) < timedelta(hours=INICIATIVA_SEPARACION_H):
            return
        if random.random() > INICIATIVA_PROBABILIDAD:
            return

        candidatos, pesos = [], []
        for estado in await database.candidatos_iniciativa(self.db):
            uid = estado["usuario_discord_id"]
            dias = af.dias_desde(estado.get("ultima_interaccion"), ahora_utc)
            if not 1 <= dias <= 6:
                continue  # Ni a quien acaba de hablarle, ni a quien lleva mucho sin aparecer
            if await database.config_obtener(self.db, f"sin_avisos:{uid}"):
                continue
            previa = await database.config_obtener(self.db, f"iniciativa:{uid}")
            if previa and ahora_utc - datetime.fromisoformat(previa) < timedelta(days=INICIATIVA_DIAS_POR_PERSONA):
                continue
            miembro = canal.guild.get_member(int(uid))
            if miembro is None:
                continue
            if await self.castigo_activo(uid):
                continue
            candidatos.append((miembro, estado, dias))
            pesos.append(3 if estado.get("es_pareja") else 1)
        if not candidatos:
            return

        miembro, estado, dias = random.choices(candidatos, weights=pesos)[0]
        texto = await self._generar(
            estado, miembro.display_name,
            f"Hace {dias} día(s) que no hablas con {miembro.display_name} y decides escribirle tú primero, por iniciativa "
            "propia, en el canal. Salúdale de forma natural: puedes mencionar algo que recuerdes de esta persona, "
            "preguntarle qué tal, o recomendarle leer algo. Sin reproches ni culpas.",
        )
        if not texto:
            texto = random.choice([
                "Hm. Estaba ordenando estanterías y me acordé de ti. ...Solo eso. ¿Qué tal todo? 📚",
                "¿Sigues vivo? Lo pregunto por curiosidad científica, nada más. 🙄",
                "Encontré un libro que creo que te gustaría. Pásate por la biblioteca cuando puedas. 🎀",
            ])
        await canal.send(f"{miembro.mention} {texto}", allowed_mentions=discord.AllowedMentions(users=[miembro]))
        await database.config_guardar(self.db, "iniciativa:ultima", ahora_utc.isoformat())
        await database.config_guardar(self.db, f"iniciativa:{miembro.id}", ahora_utc.isoformat())
        estado_actual = await self.cargar(miembro.id)
        af.registrar_evento(estado_actual, "iniciativa", "Ribby le escribió por iniciativa propia")
        await self.guardar(miembro, estado_actual)
        log.info(f"💌 Ribby escribió por iniciativa propia a {miembro.display_name}")

    # ── Comandos ──

    grupo = app_commands.Group(
        name="ribby", description="Tu relación con Ribby 🎀", guild_ids=config.GUILD_IDS or None,
    )

    @grupo.command(name="corazones", description="Mira cómo te ve Ribby (solo lo ves tú)")
    async def cmd_corazones(self, interaction: discord.Interaction):
        estado = await self.cargar(interaction.user.id)
        ocupada = await self._ocupada_por_otro(interaction.user.id)
        n = af.nivel(estado, ocupada)
        nombre, emoji = af.NIVELES[n]

        embed = discord.Embed(title=f"{emoji}  {nombre}", description=_FRASE_NIVEL[n], color=COLOR_ROMANCE)
        embed.add_field(name="Corazones", value=af.barra(estado["corazones"]), inline=False)
        embed.add_field(name="🔥 Racha", value=f"{estado.get('racha_dias') or 0} día(s)", inline=True)
        embed.add_field(name="💬 Charlas", value=str(estado.get("total_interacciones") or 0), inline=True)
        if estado.get("es_pareja") and estado.get("fecha_inicio_pareja"):
            dias = af.dias_desde(estado["fecha_inicio_pareja"])
            embed.add_field(name="💞 Juntos", value=f"{dias} día(s)", inline=True)
        elif ocupada and n in ("mejor_amigo", "algo_mas"):
            embed.add_field(name="💭", value="Ribby ya tiene pareja... por ahora.", inline=False)
        embed.set_footer(text="Habla con Ribby, hazle regalos (/ribby regalar) o invítala a una cita (/ribby cita)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _datos_memoria(self, usuario_id: int) -> tuple[list[dict], list[dict], str]:
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:
            return await saludos.datos_de(usuario_id)  # type: ignore[attr-defined]
        memoria = await database.obtener_memoria_usuario(self.db, usuario_id) or {}
        return mem.cargar_lista(memoria.get("hechos")), mem.cargar_lista(memoria.get("pendientes")), memoria.get("resumen") or ""

    @grupo.command(name="recuerdos", description="Lo que Ribby recuerda de ti (solo lo ves tú)")
    async def cmd_recuerdos(self, interaction: discord.Interaction):
        estado = await self.cargar(interaction.user.id)
        hechos, pendientes, resumen = await self._datos_memoria(interaction.user.id)
        resumen = resumen or "*Todavía no sé gran cosa de ti. Tendrás que hablarme más.*"
        momentos = [e for e in estado.get("eventos", [])][-8:]
        embed = discord.Embed(title="📔  El diario de Ribby", description=f"*\"{resumen}\"*", color=COLOR_ROMANCE)
        if hechos:
            embed.add_field(
                name="Lo que sé de ti",
                value="\n".join(
                    f"{'📌' if h.get('fuente') == 'usuario' else '•'} {md(h['texto'])}" for h in hechos
                )[:1024],
                inline=False,
            )
        hoy = _hoy()
        vigentes = [p for p in pendientes if not p.get("preguntado")]
        if vigentes:
            embed.add_field(
                name="Lo que tengo apuntado para preguntarte",
                value="\n".join(f"📅 {md(p['texto'])} ({mem.cuando(p.get('fecha'), hoy)})" for p in vigentes)[:1024],
                inline=False,
            )
        if momentos:
            embed.add_field(
                name="Momentos juntos",
                value="\n".join(f"`{e['fecha']}` {md(e['texto'])}" for e in reversed(momentos))[:1024],
                inline=False,
            )
        embed.set_footer(text="📌 = me pediste recordarlo · /ribby recordar para añadir · /ribby olvidar para borrar")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @grupo.command(name="recordar", description="Pídele a Ribby que recuerde algo de ti")
    @app_commands.describe(dato="Lo que quieres que recuerde (ej. 'llámame Emlo', 'mi Pokémon favorito es Leafeon')")
    async def cmd_recordar(self, interaction: discord.Interaction, dato: app_commands.Range[str, 3, 160]):
        saludos = self.bot.get_cog("Saludos")
        if saludos is None:
            return await interaction.response.send_message("Ahora mismo no puedo apuntar nada 😶", ephemeral=True)
        await saludos.recordar_dato(interaction.user.id, dato)  # type: ignore[attr-defined]
        await interaction.response.send_message(
            f"📌 Apuntado: *{md(dato)}*. ...No es que me importe. Pero no lo olvidaré. 📔", ephemeral=True
        )

    @grupo.command(name="olvidar", description="Haz que Ribby olvide un dato tuyo o todo lo que hablasteis")
    @app_commands.describe(dato="(Opcional) El dato concreto que quieres que olvide. Sin indicarlo: TODO")
    async def cmd_olvidar(self, interaction: discord.Interaction, dato: Optional[str] = None):
        saludos = self.bot.get_cog("Saludos")
        if saludos is None:
            return await interaction.response.send_message("Ahora mismo no puedo hacerlo 😶", ephemeral=True)
        if dato is not None:
            quitado = await saludos.quitar_dato(interaction.user.id, int(dato)) if dato.isdigit() else None  # type: ignore[attr-defined]
            if quitado is None:
                return await interaction.response.send_message("No encuentro ese dato 🤔 Elígelo de la lista.", ephemeral=True)
            return await interaction.response.send_message(f"🧽 Olvidado: *{md(quitado)}*.", ephemeral=True)
        await interaction.response.send_message(
            "¿Quieres que olvide **todo** lo que recuerdo de nuestras charlas (resumen, datos, pendientes y lo que "
            "dijiste en los canales)? Tu relación, tus logros y tus reseñas no se tocan.",
            view=OlvidarView(saludos, interaction.user), ephemeral=True,
        )

    @cmd_olvidar.autocomplete("dato")
    async def _autocompletar_dato(self, interaction: discord.Interaction, actual: str) -> list[app_commands.Choice[str]]:
        hechos, _, _ = await self._datos_memoria(interaction.user.id)
        actual_l = actual.lower()
        return [
            app_commands.Choice(name=h["texto"][:100], value=str(i))
            for i, h in enumerate(hechos) if actual_l in h["texto"].lower()
        ][:25]

    @grupo.command(name="castigar", description="(Staff) Ribby castiga a alguien por trolear: le quita corazones y se enfada")
    @app_commands.describe(
        usuario="A quién castigar", motivo="Qué hizo (Ribby se lo echará en cara), ej. 'escribió una reseña troll'",
        corazones="Corazones que pierde (por defecto 50)", dias="Días que Ribby estará enfadada (por defecto 3)",
    )
    async def cmd_castigar(
        self, interaction: discord.Interaction, usuario: discord.Member, motivo: app_commands.Range[str, 3, 200],
        corazones: app_commands.Range[int, 0, 100] = CASTIGO_CORAZONES, dias: app_commands.Range[int, 1, 14] = CASTIGO_DIAS,
    ):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede castigar.", ephemeral=True)
        if usuario.bot:
            return await interaction.response.send_message("A los bots no se les castiga. Se les ignora. 🙄", ephemeral=True)
        await interaction.response.send_message(
            f"💢 Castigo aplicado a {usuario.mention}: −{corazones} corazones y {dias} día(s) de enfado.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )
        await self.aplicar_castigo(interaction, usuario, motivo, corazones, dias)

    @grupo.command(name="limpiar_memoria", description="(Staff) Ribby olvida las conversaciones recientes y lo que recuerda de la comunidad")
    async def cmd_limpiar_memoria(self, interaction: discord.Interaction):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede hacer esto.", ephemeral=True)
        saludos = self.bot.get_cog("Saludos")
        if saludos is None:
            return await interaction.response.send_message("Ahora mismo no puedo hacerlo 😶", ephemeral=True)
        await saludos.olvidar_conversaciones(interaction.guild_id, comunidad=True)  # type: ignore[attr-defined]
        await interaction.response.send_message(
            "🧽 Ribby ha olvidado las conversaciones recientes de los canales y lo que recordaba de la comunidad. "
            "Lo que recuerda de cada persona no se toca (cada uno puede borrarlo con `/ribby olvidar`).",
            ephemeral=True,
        )

    @grupo.command(name="perdonar", description="(Staff) Levanta el castigo: Ribby deja de estar enfadada con alguien")
    @app_commands.describe(usuario="A quién perdonar")
    async def cmd_perdonar(self, interaction: discord.Interaction, usuario: discord.Member):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede hacer esto.", ephemeral=True)
        if not await self.castigo_activo(usuario.id):
            return await interaction.response.send_message("Esa persona no está castigada. 🤔", ephemeral=True)
        await database.config_borrar(self.db, f"castigo:{usuario.id}")
        self.invalidar_caches(usuario.id)
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:
            (await saludos._obtener_estado(usuario.id))["mood"] = "frio"  # type: ignore[attr-defined]
        await interaction.response.send_message(
            f"🕊️ {usuario.mention}, el staff ha intercedido por ti. ...Vale. Te perdono. Pero que no se repita. 😒",
            allowed_mentions=discord.AllowedMentions(users=[usuario]),
        )

    @grupo.command(name="secretos", description="Los secretos escondidos de Ribby: pistas y lo que lleva descubierto la comunidad")
    async def cmd_secretos(self, interaction: discord.Interaction):
        comunidad = await database.secretos_descubiertos(self.db)
        mios = {k for k in await database.logros_de(self.db, interaction.user.id) if k.startswith("secreto_")}
        lineas = []
        for s in sec.SECRETOS:
            if s.logro in mios:
                lineas.append(f"✅ {s.emoji} **{s.nombre}** — {s.descripcion}")
            elif s.logro in comunidad:
                lineas.append(f"🔓 {s.emoji} **{s.nombre}** — *alguien ya lo encontró…*\n╰ {s.pista}")
            else:
                lineas.append(f"🔒 **???** — {s.pista}")
        embed = discord.Embed(
            title="🗝️  Los secretos de Ribby",
            description=(
                "Hay frases y acciones que hacen reaccionar a Ribby de una forma muy especial. Algunas solo funcionan "
                "a ciertas horas, en ciertos días… o si te has ganado su confianza.\n\n"
                f"**Comunidad:** {len(comunidad)} de {len(sec.SECRETOS)} descubiertos  ·  **Tú:** {len(mios)}\n\n"
                + "\n".join(lineas)
            )[:4096],
            color=config.COLOR_ORO,
        )
        embed.set_footer(text="Si Ribby esquiva una pregunta nerviosa… quizá aún no te toca. Sigue intentándolo.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @grupo.command(name="espontanea", description="(Staff) Que Ribby intervenga sin que la mencionen (por su nombre o en su canal)")
    @app_commands.describe(activar="¿Puede Ribby meterse en las conversaciones por su cuenta?")
    async def cmd_espontanea(self, interaction: discord.Interaction, activar: bool):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede hacer esto.", ephemeral=True)
        if activar:
            await database.config_borrar(self.db, "espontanea")
        else:
            await database.config_guardar(self.db, "espontanea", "off")
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:
            saludos.invalidar_config()  # type: ignore[attr-defined]
        await interaction.response.send_message(
            "✅ Ribby contestará cuando digan su nombre y a veces opinará cuando se hable de libros en su canal."
            if activar else "🔕 Ribby solo responderá cuando la mencionen o respondan a sus mensajes.",
            ephemeral=True,
        )

    @grupo.command(name="regalar", description="Hazle un regalo a Ribby (uno al día)")
    @app_commands.describe(regalo="¿Qué le quieres regalar?")
    @app_commands.choices(regalo=[app_commands.Choice(name=v["nombre"], value=k) for k, v in REGALOS.items()])
    async def cmd_regalar(self, interaction: discord.Interaction, regalo: app_commands.Choice[str]):
        if await self._rechazo_por_castigo(interaction):
            return
        estado = await self.cargar(interaction.user.id)
        if not af.puede_hoy(estado, "ultimo_regalo"):
            return await interaction.response.send_message(
                "Ya me diste algo hoy. ...No hace falta que me compres, ¿sabes? Vuelve mañana. 🎀", ephemeral=True
            )
        datos = REGALOS[regalo.value]
        nuevos = await self.aplicar_actividad(
            interaction.user, "ultimo_regalo", datos["delta"], f"le regaló {datos['nombre'][2:].strip().lower()}",
            contador="regalos_total", extra_logros=("escarabajo",) if regalo.value == "bicho" else (),
        )
        await interaction.response.send_message(
            f"**{md(interaction.user.display_name)}** le regala {datos['nombre'].lower()} a Ribby.\n> {random.choice(datos['respuestas'])}"
        )
        if nuevos:
            await interaction.followup.send(_texto_logros(nuevos).strip(), ephemeral=True)
        secreto = await self.revisar_secreto_accion(interaction.user, f"regalo:{regalo.value}", interaction.channel)
        if secreto is not None:
            await interaction.followup.send(embed=secreto)

    @grupo.command(name="cita", description="Invita a Ribby a una cita (una al día)")
    async def cmd_cita(self, interaction: discord.Interaction):
        if await self._rechazo_por_castigo(interaction):
            return
        estado = await self.cargar(interaction.user.id)
        n = af.nivel(estado, await self._ocupada_por_otro(interaction.user.id))
        if n == "desconocido":
            return await interaction.response.send_message(
                "¿Una cita? ¡Si apenas te conozco! 😳 Habla un poco más conmigo primero.", ephemeral=True
            )
        if not af.puede_hoy(estado, "ultima_cita"):
            return await interaction.response.send_message(
                "Ya salimos hoy. Necesito tiempo para... leer. Sí, para leer. Mañana. 📚", ephemeral=True
            )
        await interaction.response.defer()
        # La cita del día cuenta desde que empieza (si no, se podría reiniciar hasta que saliera "fácil")
        af.marcar_hoy(estado, "ultima_cita")
        await self.guardar(interaction.user, estado)

        secreto = await self.revisar_secreto_accion(interaction.user, "cita", interaction.channel)
        if secreto is not None:
            await interaction.followup.send(embed=secreto)
        tema = "Es MEDIANOCHE: la cita transcurre de noche, bajo las estrellas." if datetime.now(af.ZONA).hour == 0 else ""
        aventura = await self.crear_cita(interaction.user, tema=tema)
        if aventura is not None:
            aventura.message = await interaction.followup.send(  # type: ignore[assignment]
                embed=aventura.embed_escena(), view=aventura, wait=True
            )
            return

        # Sin IA: las citas clásicas de una escena
        evento = _evento_hoy()
        if evento and random.random() < 0.5:  # En temporada, a veces toca la escena especial
            cita, extra = evento["cita"], ("festivo",)
        else:
            cita, extra = random.choice(CITAS), ()
        embed = discord.Embed(title=cita["titulo"], description=f"{cita['escena']}\n\n*¿Qué haces?*", color=COLOR_ROMANCE)
        view = CitaView(self, interaction.user, cita, clave_dia=None, extra_logros=extra)
        view.message = await interaction.followup.send(embed=embed, view=view, wait=True)  # type: ignore[assignment]

    @grupo.command(name="evento", description="El evento de temporada actual: regalo y cita especiales")
    async def cmd_evento(self, interaction: discord.Interaction):
        hoy = _hoy()
        evento = _evento_hoy()
        if not evento:
            proximo = min(
                temporadas.EVENTOS,
                key=lambda e: (date(hoy.year, *e["inicio"]) if date(hoy.year, *e["inicio"]) >= hoy
                               else date(hoy.year + 1, *e["inicio"])),
            )
            dia, mes = proximo["inicio"][1], proximo["inicio"][0]
            return await interaction.response.send_message(
                f"Ahora no hay ningún evento especial. El próximo es **{proximo['nombre']}** "
                f"(a partir del {dia}/{mes}). ...No es que lo esté esperando. 📅",
                ephemeral=True,
            )
        edicion = temporadas.edicion(evento, hoy)
        embed = discord.Embed(
            title=evento["nombre"],
            description=f"*{evento['anuncio']}*\n\nDurante el evento puedes hacerle **un regalo especial** "
                        "y tener **una cita especial** con Ribby (una vez cada uno).",
            color=COLOR_ROMANCE,
        )
        await interaction.response.send_message(embed=embed, view=EventoView(self, interaction.user, evento, edicion))

    @grupo.command(name="mision", description="Ribby te encarga leer una historia de su biblioteca")
    async def cmd_mision(self, interaction: discord.Interaction):
        biblioteca = self.bot.get_cog("Biblioteca")
        if biblioteca is None:
            return await interaction.response.send_message("La biblioteca está cerrada ahora mismo 😶", ephemeral=True)
        await interaction.response.defer()
        actual = await database.mision_activa(self.db, interaction.user.id)
        if actual:
            historia = await database.obtener_historia_biblioteca(self.db, actual["historia_id"])
            if historia:
                embeds = await biblioteca.tarjetas([historia])  # type: ignore[attr-defined]
                return await interaction.followup.send(
                    f"📖 Tu misión sigue siendo **{md(historia['titulo'])}**. Cuando la termines, cuéntame qué te pareció "
                    "con `/biblioteca resenar`. ¿O prefieres otra?",
                    embeds=embeds, view=CambiarMisionView(self, interaction.user),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        await self.asignar_mision(interaction, interaction.user)

    async def asignar_mision(self, interaction: discord.Interaction, usuario: discord.abc.User, cambio: bool = False) -> None:
        biblioteca = self.bot.get_cog("Biblioteca")
        catalogo = await biblioteca.catalogo()  # type: ignore[union-attr]
        leidas = await database.historias_leidas(self.db, usuario.id)
        mision = await database.mision_activa(self.db, usuario.id)
        excluir = leidas | ({mision["historia_id"]} if mision else set())
        posibles = [
            h for h in catalogo
            if h["id"] not in excluir and str(h.get("autor_discord") or "") != str(usuario.id)
            and (h.get("url") or h.get("url_pdf"))
        ]
        if not posibles:
            return await interaction.followup.send("¡Te has leído toda mi biblioteca! ...Estoy impresionada. De verdad. 📚✨")

        # Personalizada: Ribby elige según lo que recuerda de tus gustos
        memoria = await database.obtener_memoria_usuario(self.db, usuario.id)
        consulta = f"algo que le guste a alguien así: {memoria['resumen']}" if memoria and memoria.get("resumen") else ""
        mensaje, sugeridas = await biblioteca.recomendar(consulta, usuario.id)  # type: ignore[union-attr]
        ids_posibles = {h["id"] for h in posibles}
        elegida = next((h for h in sugeridas if h["id"] in ids_posibles), None) or random.choice(posibles)

        await database.crear_mision(self.db, usuario.id, elegida["id"])
        embeds = await biblioteca.tarjetas([elegida])  # type: ignore[union-attr]
        intro = "Hmph, ¿no te convenció la anterior? Vale. Prueba con esta." if cambio else (
            "Tengo una misión para ti. Lee esta historia y luego cuéntame qué te pareció con `/biblioteca resenar`. "
            "Si lo haces... quizá te tenga en mejor estima. 📚"
        )
        await interaction.followup.send(f"📖 {intro}", embeds=embeds, allowed_mentions=discord.AllowedMentions.none())

    @grupo.command(name="logros", description="Tus insignias con Ribby (solo las ves tú)")
    async def cmd_logros(self, interaction: discord.Interaction):
        tiene = await database.logros_de(self.db, interaction.user.id)
        lineas = []
        for clave, (emoji, nombre, como, secreto) in lg.LOGROS.items():
            if clave in tiene:
                lineas.append(f"{emoji} **{nombre}** — {como}")
            elif not secreto:
                lineas.append(f"🔒 {nombre} — *{como}*")
            else:
                lineas.append("🔒 ??? — *Logro secreto*")
        embed = discord.Embed(
            title=f"🏅  Logros  ({len(tiene)}/{len(lg.LOGROS)})", description="\n".join(lineas)[:4096], color=COLOR_ROMANCE,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @grupo.command(name="cumpleanos", description="Dile a Ribby cuándo es tu cumpleaños")
    @app_commands.describe(dia="Día (1-31)", mes="Mes (1-12)")
    async def cmd_cumpleanos(
        self, interaction: discord.Interaction, dia: app_commands.Range[int, 1, 31], mes: app_commands.Range[int, 1, 12]
    ):
        try:
            date(2024, mes, dia)  # 2024 es bisiesto: acepta el 29 de febrero
        except ValueError:
            return await interaction.response.send_message("Esa fecha no existe 🤨", ephemeral=True)
        await database.guardar_cumpleanos(self.db, interaction.user.id, dia, mes)
        nuevos = await self.comprobar_logros(interaction.user.id, extra=("cumple",))
        await interaction.response.send_message(
            f"🎂 Apuntado: {dia}/{mes}. ...No es que vaya a prepararte nada. Bueno, quizá. {_texto_logros(nuevos)}",
            ephemeral=True,
        )

    @grupo.command(name="avisos", description="Permite (o no) que Ribby te escriba por su cuenta")
    @app_commands.describe(activar="¿Quieres que Ribby pueda saludarte por iniciativa propia?")
    async def cmd_avisos(self, interaction: discord.Interaction, activar: bool):
        clave = f"sin_avisos:{interaction.user.id}"
        if activar:
            await database.config_borrar(self.db, clave)
            texto = "Vale. Si me acuerdo de ti, quizá te escriba. Quizá. 🎀"
        else:
            await database.config_guardar(self.db, clave, "1")
            texto = "Entendido, no te escribiré por mi cuenta. Pero la biblioteca sigue abierta para ti. 📚"
        await interaction.response.send_message(texto, ephemeral=True)

    @grupo.command(name="canal", description="(Staff) Canal donde Ribby felicita, anuncia eventos y saluda por su cuenta")
    @app_commands.describe(canal="Canal de texto para los mensajes propios de Ribby")
    async def cmd_canal(self, interaction: discord.Interaction, canal: discord.TextChannel):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede hacer esto.", ephemeral=True)
        await database.config_guardar(self.db, "canal_ribby", str(canal.id))
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:
            saludos.invalidar_config()  # type: ignore[attr-defined]
        await interaction.response.send_message(
            f"📌 A partir de ahora Ribby usará {canal.mention} para cumpleaños, aniversarios, eventos y sus saludos.",
            ephemeral=True,
        )

    @grupo.command(name="historia", description="Los capítulos de la historia de Ribby (se desbloquean con vuestra relación)")
    async def cmd_historia(self, interaction: discord.Interaction):
        estado = await self.cargar(interaction.user.id)
        orden_actual = _orden(af.nivel(estado, await self._ocupada_por_otro(interaction.user.id)))
        leidos = await database.capitulos_leidos(self.db, interaction.user.id)

        es_papa = bool(estado.get("es_creador"))
        lineas, disponibles = [], []
        for cap in lr.CAPITULOS:
            if es_papa:
                if cap["nivel"] not in _CAPITULOS_FAMILIARES:
                    lineas.append(f"🙈 {cap['titulo'].split('·')[0].strip()} — *Este capítulo no es para papá. ¡Ni lo intentes!* 😳")
                    continue
                abierto = True
            else:
                abierto = cap["id"] in leidos or orden_actual >= _orden(cap["nivel"])
            if abierto:
                disponibles.append(cap)
                marca = "✅" if cap["id"] in leidos else "🆕"
                lineas.append(f"{marca} **{md(cap['titulo'])}**")
            else:
                lineas.append(f"🔒 {cap['titulo'].split('·')[0].strip()} — *cuando Ribby te vea como «{af.NIVELES[cap['nivel']][0]}»*")

        embed = discord.Embed(
            title="📕  La historia de Ribby",
            description="*Hay cosas que Ribby solo cuenta a quien se ha ganado su confianza.*\n\n" + "\n".join(lineas),
            color=COLOR_ROMANCE,
        )
        if not disponibles:
            embed.set_footer(text="Habla más con Ribby para desbloquear el primer capítulo.")
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        select = discord.ui.Select(
            placeholder="Elige un capítulo para leer...",
            options=[discord.SelectOption(label=c["titulo"][:100], value=str(c["id"])) for c in disponibles],
        )

        async def al_elegir(inter: discord.Interaction):
            cap = lr.capitulo(int(select.values[0]))
            vista = CapituloView(self, interaction.user, cap, leidos.get(cap["id"]))  # type: ignore[arg-type]
            await inter.response.edit_message(embed=vista.embed(), view=vista)

        select.callback = al_elegir  # type: ignore[method-assign]
        vista = _SoloAutor(interaction.user)
        vista.add_item(select)
        await interaction.response.send_message(embed=embed, view=vista, ephemeral=True)

    @grupo.command(name="quiz", description="«¿Me conoces?»: Ribby te pregunta sobre ella o sobre lo que le contaste (una al día)")
    async def cmd_quiz(self, interaction: discord.Interaction):
        clave, hoy = f"quiz:{interaction.user.id}", _hoy().isoformat()
        if await database.config_obtener(self.db, clave) == hoy:
            return await interaction.response.send_message(
                "Ya te pregunté hoy. Mañana más, que no soy un examen. 🙄", ephemeral=True
            )
        await interaction.response.defer()
        await database.config_guardar(self.db, clave, hoy)

        quiz = None
        if random.random() < 0.4:  # A veces pregunta sobre lo que le contaste tú
            quiz = await self._pregunta_sobre_usuario(interaction.user)
        if quiz is None:
            leidos = set(await database.capitulos_leidos(self.db, interaction.user.id))
            quiz = lr.pregunta_sobre_ribby(leidos)

        intro = "A ver si me prestas atención..." if quiz["sobre"] == "ribby" else "A ver si tú también te acuerdas..."
        embed = discord.Embed(
            title="🧠  ¿Me conoces?", description=f"*{intro}*\n\n**{quiz['pregunta']}**", color=COLOR_ROMANCE,
        )
        vista = QuizView(self, interaction.user, quiz)
        vista.message = await interaction.followup.send(embed=embed, view=vista, wait=True)  # type: ignore[assignment]

    async def _pregunta_sobre_usuario(self, usuario: discord.abc.User) -> Optional[dict[str, Any]]:
        """Pregunta generada por la IA a partir de lo que Ribby recuerda del usuario."""
        hechos, _, resumen = await self._datos_memoria(usuario.id)
        modelo = getattr(self.bot.get_cog("Saludos"), "model", None)
        if not (resumen or hechos) or not modelo or not getattr(modelo, "providers", None):
            return None
        # Los datos concretos dan mejores preguntas ("¿cuál es mi Pokémon favorito?")
        datos = mem.texto_hechos([h for h in hechos if h.get("tipo") != "vida"])
        try:
            texto = await modelo.generate(
                lr.SYSTEM_PREGUNTA_USUARIO,
                [{"role": "user", "content": f"Recuerdos sobre {usuario.display_name}: {resumen}\nDatos concretos:\n{datos}"}],
            )
            m = re.search(r"\{.*\}", texto or "", re.S)
            datos = json.loads(m.group(0)) if m else {}
        except Exception as e:  # noqa: BLE001
            log.info(f"No se pudo generar una pregunta personal: {e}")
            return None
        pregunta, correcta = datos.get("pregunta"), datos.get("correcta")
        incorrectas = [str(x)[:80] for x in (datos.get("incorrectas") or []) if x][:3]
        if not pregunta or not correcta or len(incorrectas) < 3 or str(correcta) in incorrectas:
            return None
        opciones = [str(correcta)[:80], *incorrectas]
        random.shuffle(opciones)
        return {"pregunta": str(pregunta)[:300], "opciones": opciones, "correcta": str(correcta)[:80], "sobre": "usuario"}

    @grupo.command(name="terminar", description="Termina tu relación con Ribby")
    async def cmd_terminar(self, interaction: discord.Interaction):
        estado = await self.cargar(interaction.user.id)
        if not estado.get("es_pareja"):
            return await interaction.response.send_message("¿Terminar qué? Si no somos nada... 🙄", ephemeral=True)
        await interaction.response.send_message(
            "¿Seguro que quieres terminar con Ribby? Volveréis a ser amigos.", view=TerminarView(self, interaction.user),
            ephemeral=True,
        )

    @grupo.command(name="reiniciar", description="(Staff) Borra la relación de un usuario con Ribby")
    @app_commands.describe(usuario="Usuario a reiniciar")
    async def cmd_reiniciar(self, interaction: discord.Interaction, usuario: discord.Member):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede hacer esto.", ephemeral=True)
        ok = await database.reiniciar_afinidad(self.db, usuario.id)
        self.invalidar_caches(usuario.id)
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:  # Que no siga citando lo que dijo de esa persona en las conversaciones recientes
            await saludos.olvidar_conversaciones()  # type: ignore[attr-defined]
        await interaction.response.send_message(
            f"🔄 Relación de {usuario.mention} con Ribby reiniciada." if ok else "Ese usuario no tenía nada con Ribby.",
            ephemeral=True,
        )


_ORDEN = ["desconocido", "amigo", "mejor_amigo", "algo_mas", "enamorada", "pareja"]
_CAPITULOS_FAMILIARES = {"amigo", "mejor_amigo"}  # Los únicos que Ribby le contaría a su creador


def _orden(nivel: Optional[str]) -> int:
    return _ORDEN.index(nivel) if nivel in _ORDEN else 0


async def setup(bot: commands.Bot):
    await bot.add_cog(Afinidad(bot))
