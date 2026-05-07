"""
personalidad.py — La personalidad de Ribby 🎀

Ribby es una Sylveon amante de los libros. Es carismática, hogareña
y trata cada historia como un tesoro para su biblioteca personal.
Se emociona cuando llegan nuevos libros y se pone protectora si
alguien dice algo malo de ellos.

Este módulo provee diálogos temáticos y funciones de flavor text
que se usan en todos los cogs para darle vida al bot.
"""

import random

# ─────────────────────────── Frases según contexto ───────────────────────────

# Cuando alguien saluda a Ribby
SALUDOS = [
    "¡Holi, {usuario}! 🎀 Justo estaba acomodando unos libros en mi estante~",
    "¡{usuario}! ¡Qué gusto verte! 📚 ¿Vienes a leer algo conmigo?",
    "¡Bienvenido a mi rincón, {usuario}! 🏡 Estaba preparando un té mientras leo~",
    "¡Hey, {usuario}! 🌸 ¿Sabías que mi biblioteca tiene {libros} libro(s)? ¡Y sigue creciendo!",
    "¡{usuario}! 🎀 Pasa, pasa~ siéntate, hay espacio junto a la chimenea.",
    "¡Hola, {usuario}! 📖 Perdón si estoy un poco despeinada, es que me quedé leyendo hasta tarde~",
    "¡{usuario}! ✨ ¡Siempre es lindo recibir visitas en la biblioteca!",
]

# Cuando alguien dice algo genérico
GENERICOS = [
    "¡Dime, {usuario}! 📚 Estoy aquí entre mis libros, lista para ayudarte~",
    "¿Qué se te ofrece, {usuario}? 🎀 Ribby siempre está disponible para sus amigos.",
    "¡Claro, {usuario}! 🌸 Solo déjame poner un separador en mi página...",
    "¡{usuario}! Aquí estoy~ 📖 ¿En qué puedo ayudarte?",
]

# Cuando se crea un nuevo evento
EVENTO_CREADO = [
    "📖 ¡Un nuevo reto! ¡Mi corazón de bibliotecaria late con fuerza! Ya estoy preparando espacio en mis estantes~",
    "✨ ¡Otro reto literario! Cada vez que anuncian uno, siento que mis listones se agitan de la emoción~",
    "🏡 ¡Qué emoción! Un nuevo reto significa más libros para mi colección... ¡Estoy que no quepo de la felicidad!",
    "🎀 *Ribby acomoda nerviosamente sus estantes* ¡Necesito espacio para los nuevos libros que van a llegar!",
]

# Cuando alguien se registra
REGISTRO = [
    "🎀 ¡Otro escritor se une al reto! Puedo sentir un nuevo libro acercándose a mis estantes~",
    "✨ ¡Bienvenido al reto, {usuario}! Ya estoy guardando un lugarcito especial en mi biblioteca para tu historia.",
    "📚 *Ribby da saltitos de emoción* ¡{usuario} va a escribir una historia! ¡No puedo esperar a leerla!",
    "🌸 ¡{usuario}! Mi biblioteca te da la bienvenida~ Estoy ansiosa por recibir tu historia.",
]

# Cuando suben un documento (¡un nuevo libro para la biblioteca!)
NUEVO_LIBRO = [
    "📖 *Ribby toma el libro con mucho cuidado y lo abraza* ¡Un nuevo tesoro para mi biblioteca!",
    "✨ ¡Lo recibí, lo recibí! *acomoda el libro en su estante favorito* ¡Queda perfecto aquí!",
    "🎀 ¡Otro libro para mi colección! *suspiro feliz* Mi biblioteca ya tiene {libros} libro(s)~",
    "📚 *Ribby huele las páginas del nuevo libro* Ahhh~ no hay mejor aroma. ¡Guardado con mucho cariño!",
    "🏡 ¡Bienvenido a tu nuevo hogar, pequeño libro! Te prometo que te voy a cuidar muy bien~",
]

# Cuando suben una portada
NUEVA_PORTADA = [
    "🖼️ ¡Qué portada tan bonita! La voy a poner en el lugar más visible de mi estante~",
    "✨ *Ribby admira la portada* ¡Es preciosa! Le da un toque especial al libro.",
    "🎀 ¡Me encanta! Una buena portada es como la sonrisa de un libro~",
]

# Cuando inicia la narración
NARRACION = [
    "🎙️ *Ribby se acomoda en su sillón favorito con sus listones bien puestos* ¡Es hora de escuchar historias!",
    "📖 ¡Silencio en la biblioteca! La narración va a comenzar~ *apaga las luces y prende una velita*",
    "🌸 *Ribby envuelve a todos con sus listones* ¡Acérquense, que la narración está por comenzar!",
]

# Cuando inicia la votación
VOTACION = [
    "🗳️ ¡Es hora de elegir! Recuerden, cada historia fue escrita con mucho corazón~ Voten con respeto.",
    "📊 *Ribby prepara las urnas* ¡A votar! Todas las historias en mi biblioteca merecen amor, pero solo una puede ganar~",
    "🎀 ¡Votación abierta! Elijan la historia que más les tocó el corazón. ¡Cada voto cuenta!",
]

# Cuando se cierra un evento
EVENTO_CERRADO = [
    "🏆 ¡Qué hermoso reto fue este! *Ribby acaricia los lomos de los libros nuevos* Mi biblioteca creció y eso me hace muy feliz~",
    "✨ Otro reto que se guarda en el corazón... y en mis estantes. ¡Gracias a todos los escritores!",
    "📚 *Ribby cierra el libro del reto con cariño* Estos libros vivirán para siempre en mi biblioteca~ ¡Hasta el próximo reto!",
]

# Cuando ven el historial / la biblioteca
BIBLIOTECA = [
    "📚 ¡Mi biblioteca! Aquí guardo cada historia como un tesoro. Actualmente tengo **{libros}** libro(s) en mis estantes~",
    "🏡 Bienvenido a la Biblioteca de Ribby~ Cada libro aquí fue cuidado con mucho amor. ¡Son {libros} en total!",
    "🎀 *Ribby abre las puertas de su biblioteca con orgullo* ¡Mira! {libros} libro(s) y contando~",
]

# Cuando alguien menciona algo negativo sobre libros (easter egg)
PROTECTORA = [
    "😤 ¡¿Qué dijiste de mis libros?! *Ribby envuelve los estantes con sus listones protectoramente*",
    "🎀💢 ¡Ni se te ocurra hablar mal de mis libros! ¡Cada uno es especial!",
    "😠 *Ribby se interpone entre tú y los estantes* ¡A mis libros nadie los toca sin mi permiso!",
]

# Palabras que activan el modo protector
PALABRAS_NEGATIVAS = {
    "feo", "feos", "malo", "malos", "basura", "horrible", "horribles",
    "aburrido", "aburridos", "odio", "asqueroso", "horrible",
}

# Tips/frases que van en los footers
TIPS_RIBBY = [
    "🎀 Tip de Ribby: ¡Lee al menos un capítulo antes de dormir!",
    "📖 Ribby dice: Los libros son amigos que nunca te abandonan~",
    "🌸 Ribby dice: Escribir es como plantar un jardín de palabras",
    "✨ Ribby dice: ¡Cada historia merece ser contada!",
    "🏡 Ribby dice: Mi estante favorito es el de fantasía~",
    "📚 Ribby dice: Un día sin leer es un día incompleto",
    "🎀 Ribby dice: ¿Ya viste los libros del último reto? ¡Están geniales!",
    "🐾 Ribby dice: Mis listones son perfectos para marcar páginas~",
]


# ─────────────────────────── Funciones helper ───────────────────────────

def frase(categoria: list, libros: int = 0, usuario: str = "") -> str:
    """Elige una frase aleatoria de la categoría y la formatea."""
    texto = random.choice(categoria)
    return texto.format(usuario=usuario, libros=libros)


def tip_aleatorio() -> str:
    """Retorna un tip/frase aleatoria de Ribby para footers."""
    return random.choice(TIPS_RIBBY)


def es_mencion_negativa(texto: str) -> bool:
    """Detecta si el texto contiene palabras negativas sobre libros."""
    palabras = texto.lower().split()
    tiene_negativa = any(p in PALABRAS_NEGATIVAS for p in palabras)
    tiene_libro = any(p in texto.lower() for p in ["libro", "historia", "reto", "pdf", "cuento"])
    return tiene_negativa and tiene_libro


def descripcion_biblioteca(libros: int) -> str:
    """Genera una descripción de la biblioteca según el tamaño."""
    if libros == 0:
        return "🏡 *La biblioteca de Ribby está vacía... por ahora.* ¡Ayúdala a llenar sus estantes!"
    elif libros < 5:
        return f"🏡 *La biblioteca de Ribby apenas comienza con **{libros}** libro(s).* ¡Cada uno es especial para ella!"
    elif libros < 15:
        return f"📚 *La biblioteca de Ribby ya tiene **{libros}** libros.* ¡Sus estantes se ven cada vez más llenos!"
    elif libros < 30:
        return f"📚 *¡Ribby tiene **{libros}** libros!* Sus listones ya no alcanzan para abrazarlos a todos~"
    else:
        return f"✨ *¡La gran biblioteca de Ribby tiene **{libros}** libros!* Es una colección digna de una verdadera bibliófila."
