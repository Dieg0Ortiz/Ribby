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

Comandos /ribby: corazones, recuerdos, regalar, cita, evento, mision, logros,
cumpleanos, avisos, terminar; staff: canal, reiniciar.
El nivel de cada uno es privado: solo lo ve el propio usuario.
"""

from __future__ import annotations

import calendar
import contextlib
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

import afinidad as af
import config
import database
import logros as lg
import ribby_lore as lr
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
                    "acertó una pregunta sobre Ribby" if sobre_ribby else "demostró que recuerda lo que le contó a Ribby",
                    contador="quiz_aciertos",
                )
                respuesta = random.choice(lr.FRASES_ACIERTO) + _texto_logros(nuevos)
            else:
                if sobre_ribby:
                    await self.cog.aplicar_actividad(self.usuario, None, -0.2, "falló una pregunta sobre Ribby")
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

    async def cargar(self, usuario_id: int) -> dict[str, Any]:
        estado = await database.obtener_afinidad(self.db, usuario_id) or af.nuevo_estado()
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
        await database.guardar_afinidad(self.db, usuario.id, usuario.display_name, estado, af.nivel(estado, ocupada))

    async def _ocupada_por_otro(self, usuario_id: int) -> bool:
        pareja = await database.pareja_actual(self.db)
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
        pareja = await database.pareja_actual(self.db)
        ocupada = bool(pareja and pareja["usuario_discord_id"] != str(usuario.id))
        nombre_pareja = pareja["nombre_display"] if ocupada and pareja else None

        _, previo, nuevo = af.aplicar_interaccion(estado, tono, coqueteo, ocupada)
        resultado = Resultado(subio_nivel=_orden(nuevo) > _orden(previo))

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

    # ── Generación de mensajes propios (iniciativa, cumpleaños, aniversarios) ──

    async def _generar(self, estado: dict[str, Any], nombre: str, instruccion: str) -> Optional[str]:
        saludos = self.bot.get_cog("Saludos")
        modelo = getattr(saludos, "model", None)
        if not modelo or not getattr(modelo, "providers", None):
            return None
        self._marcar_creador(estado, estado.get("usuario_discord_id"))
        memoria = await database.obtener_memoria_usuario(self.db, estado.get("usuario_discord_id") or "0")
        sistema = (
            "Eres Ribby, la bibliotecaria del servidor de Discord 'La Comarca': una Sylveon tsundere, intelectual y "
            "cariñosa a su manera. Escribes en español, con tu voz, en 1-3 frases y con 1-2 emojis como mucho. "
            "Nunca suenes a asistente virtual.\n"
            f"{af.REGLAS_ROMANCE}\n"
            f"Sobre {nombre}: {(memoria or {}).get('resumen') or 'aún sabes poco de esta persona.'}\n"
            f"Vuestra relación:\n{af.contexto_prompt(estado, False)}\n{_contexto_temporada()}"
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
            pareja = await database.pareja_actual(self.db)
            if pareja and af.aplicar_paso_del_tiempo(pareja):
                await database.guardar_afinidad(
                    self.db, pareja["usuario_discord_id"], pareja["nombre_display"], pareja, af.nivel(pareja)
                )
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
            await self._iniciativa(canal, ahora_local)
        except Exception as e:  # noqa: BLE001
            log.exception(f"Error en la tarea social de Ribby: {e}")

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
        pareja = await database.pareja_actual(self.db)
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

    @grupo.command(name="recuerdos", description="Lo que Ribby recuerda de ti (solo lo ves tú)")
    async def cmd_recuerdos(self, interaction: discord.Interaction):
        estado = await self.cargar(interaction.user.id)
        memoria = await database.obtener_memoria_usuario(self.db, interaction.user.id)
        resumen = (memoria or {}).get("resumen") or "*Todavía no sé gran cosa de ti. Tendrás que hablarme más.*"
        momentos = [e for e in estado.get("eventos", [])][-8:]
        embed = discord.Embed(title="📔  El diario de Ribby", description=f"*\"{resumen}\"*", color=COLOR_ROMANCE)
        if momentos:
            embed.add_field(
                name="Momentos juntos",
                value="\n".join(f"`{e['fecha']}` {md(e['texto'])}" for e in reversed(momentos))[:1024],
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @grupo.command(name="regalar", description="Hazle un regalo a Ribby (uno al día)")
    @app_commands.describe(regalo="¿Qué le quieres regalar?")
    @app_commands.choices(regalo=[app_commands.Choice(name=v["nombre"], value=k) for k, v in REGALOS.items()])
    async def cmd_regalar(self, interaction: discord.Interaction, regalo: app_commands.Choice[str]):
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

    @grupo.command(name="cita", description="Invita a Ribby a una cita (una al día)")
    async def cmd_cita(self, interaction: discord.Interaction):
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
        evento = _evento_hoy()
        if evento and random.random() < 0.5:  # En temporada, a veces toca la escena especial
            cita, extra = evento["cita"], ("festivo",)
        else:
            cita, extra = random.choice(CITAS), ()
        embed = discord.Embed(title=cita["titulo"], description=f"{cita['escena']}\n\n*¿Qué haces?*", color=COLOR_ROMANCE)
        view = CitaView(self, interaction.user, cita, extra_logros=extra)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

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
        memoria = await database.obtener_memoria_usuario(self.db, usuario.id)
        resumen = (memoria or {}).get("resumen")
        modelo = getattr(self.bot.get_cog("Saludos"), "model", None)
        if not resumen or not modelo or not getattr(modelo, "providers", None):
            return None
        try:
            texto = await modelo.generate(
                lr.SYSTEM_PREGUNTA_USUARIO,
                [{"role": "user", "content": f"Recuerdos sobre {usuario.display_name}: {resumen}"}],
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
