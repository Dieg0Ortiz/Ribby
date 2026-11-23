# 🎀 Manual de Usuario Detallado: Ribby (Bot de Retos Literarios)

Bienvenidos al manual de operación de **Ribby**, el bot oficial diseñado para la gestión de retos literarios en la comunidad. Ribby no es solo una herramienta automatizada; tiene la personalidad de una atenta bibliotecaria (una Sylveon) que ama los libros y se encarga de proteger, organizar y garantizar la total equidad en los eventos de escritura del servidor.

Este documento explica **a detalle** todas y cada una de las funcionalidades del bot.

---

## 🎯 1. ¿Por qué existe Ribby? (Finalidad)
Los retos literarios en servidores de Discord suelen enfrentar problemas logísticos cuando la comunidad crece:
1. **Votaciones desordenadas:** Es difícil llevar el conteo de votos de forma manual y transparente.
2. **Falta de historial:** Una vez terminado el reto, las obras y los ganadores se pierden con el tiempo.

**Ribby soluciona estos problemas de forma 100% automatizada.**

---

## 🔄 2. El Flujo de Vida de un Reto Literario
Un reto literario gestionado por Ribby pasa por varias fases. Las transiciones entre estas fases son controladas **únicamente por los administradores** mediante comandos.

### Fase 1: Creación y Registro (Estado: `abierto`)
- El administrador usa `/evento crear`. 
- **Lo que pasa:** Ribby abre las inscripciones. Los usuarios usan el comando `/participante_registrar` con el título de su obra y después suben su archivo (PDF/DOCX) y una imagen de portada en el canal de envío; Ribby los recoge automáticamente. Si se equivocan de título, pueden volver a usar el comando (sus archivos se conservan) o volver a subir el archivo para reemplazarlo.

### Fase 2: Múltiples Sesiones de Narración (Estado: `narrando` / `abierto`)
Los retos con muchas participaciones no se leen en un solo día. Ribby soporta múltiples sesiones.
- El administrador usa `/evento iniciar_narracion`. Ribby empieza a cronometrar la sesión de narración.
- Al terminar el día, el administrador usa `/evento cerrar_narracion`. Ribby detiene el cronómetro y guarda el tiempo exacto de esa "Sesión #1".
- Al día siguiente, se puede iniciar otra narración (Sesión #2), y así sucesivamente.

### Fase 3: Votación (Estado: `votando`)
- El administrador usa `/evento iniciar_votacion`.
- **Lo que pasa:** Ribby cierra las inscripciones y las narraciones automáticamente. Anuncia que la votación está abierta.
- A partir de este momento, todos los usuarios pueden usar `/votar`.

### Fase 4: Voto Secreto en Interfaz Interactiva
- El usuario usa `/votar`. Ribby le envía un **mensaje privado (ephemeral)** que nadie más puede ver.
- Despliega un menú interactivo con los nombres de todos los participantes. El usuario selecciona a su favorito.
- El bot registra el voto en la base de datos de forma anónima y única (no se puede votar dos veces).

### Fase 5: Cierre y Ganador (Estado: `cerrado`)
- El administrador usa `/evento cerrar`.
- **Lo que pasa:** Ribby hace el conteo final de los votos en la base de datos.
- Anuncia al ganador absoluto en un Embed dorado, con la cantidad de votos recibidos y cierra el evento.
- El evento, sus estadísticas y el ganador pasan automáticamente al "Histórico" del bot.

---

## 📚 3. Funciones de Consulta (UI Interactiva)
Ribby tiene interfaces modernas con botones y menús desplegables para que la experiencia sea fluida, evitando saturar el chat de texto.

- **`/reto info`**: Este comando despliega un libro virtual. 
  - Aparece un "Resumen" del evento activo.
  - Usando botones (`◀` y `▶`), los usuarios pueden "pasar las páginas" para ver cada historia participante, viendo la imagen de portada y el título.
  - Tiene un botón verde de **`[📥 Descargar Documento]`**. Al hacer clic, Ribby le entrega el PDF en un mensaje privado para que puedas leerlo cómodamente.

- **`/reto historial`**: Si los usuarios sienten nostalgia o quieren leer obras pasadas, este comando despliega un menú interactivo con todos los retos literarios cerrados de meses anteriores. Al seleccionar uno, muestra sus estadísticas, participantes, ganador de esa edición y enlaces de descarga.

---

## 💬 4. Interacciones y Personalidad (Saludos)
Ribby no es un robot frío; está programada para reaccionar de forma orgánica y mantener vivo el chat:
- Si alguien la etiqueta y la saluda (Ej: "Hola @Ribby"), responderá con saludos aleatorios y amables, indicando cuántos libros lleva guardados en su base de datos.
- Si alguien la menciona y dice una palabra grosera relacionada con libros (Ej: "Odio los libros"), Ribby se pondrá a la defensiva (modo protector) y regañará al usuario por hablar mal de su preciada biblioteca.
- Si simplemente la mencionan, dará respuestas genéricas de bibliotecaria, sugiriendo hacer silencio para leer o preguntando si buscan algún género en particular.

---

## 📚 5. La Biblioteca de Recomendaciones
Ribby conoce las historias de los escritores de La Comarca: las de nuestra lista de Wattpad, las de los retos literarios y las que la comunidad le va pasando. Cada historia tiene su ficha con título, autor, etiquetas, resumen y, si está en Wattpad, sus lecturas y votos.

**Pedir una recomendación** — Menciónala y dile qué te apetece:
- "@Ribby recomiéndame una historia con Lycanroc"
- "@Ribby ¿qué puedo leer? algo de romance escolar"
- "@Ribby busco una historia de reencarnación"

Entiende errores de escritura y sinónimos. Las historias marcadas como **contenido maduro (+18)** aparecen con un aviso.

**Añadir una historia** — Pásale el enlace de Wattpad mencionándola ("@Ribby esta historia es buenísima, añádela https://www.wattpad.com/story/...") o usa `/biblioteca agregar`. Ribby lee sola el título, autor, etiquetas y resumen.

**¿De qué trata?** — "@Ribby ¿de qué trata Luna de Sangre?". Si no tiene el resumen, etiqueta al autor para que te lo cuente (y se lo queda para la próxima).

**Ayudar a Ribby** — Cuando una ficha está incompleta, Ribby pregunta en el chat ("¿Qué géneros tiene?", "¿Qué Pokémon aparecen?") con opciones para elegir, o "Otro…" para escribirlo tú. ¡Cualquiera puede ayudar!

**Avisos de capítulos nuevos** — Con `/biblioteca seguir` Ribby te avisa cuando una historia de Wattpad publique capítulos nuevos (también si la tienes como misión de lectura). `/biblioteca dejar_de_seguir` para dejar de recibirlos.

**Si eres autor** — Usa `/biblioteca vincular_wattpad` con tu usuario de Wattpad. Así Ribby sabe qué historias son tuyas, te avisa cuando alguien pregunta por ellas, y tu resumen siempre tiene prioridad.

---

## 💞 6. Tu Relación con Ribby
Cuanto más hablas con Ribby, más te conoce: recuerda lo que le cuentas y cómo la tratas. Según vuestra relación, te verá como **Desconocido → Amigo → Mejor amigo → Algo más que amigos → Pareja**.

- **Corazones:** ganas corazones hablando con ella con amabilidad (y los pierdes siendo grosero). Hay un límite diario, así que es mejor hablarle un poco cada día que mucho de golpe. Mantener una racha de días seguidos ayuda.
- **Algo más:** si solo eres amable, te verá como un gran amigo. Para algo más... tendrás que coquetearle un poco.
- **Pareja:** cuando esté enamorada te dará pistas, pero nunca te lo pedirá ella: **tienes que declararte tú** ("Ribby, ¿quieres ser mi novia?"). Si tardas demasiado, se cansará de esperar y volveréis a ser amigos.
- **Solo una:** Ribby solo puede tener una pareja en todo el servidor. Si ya tiene, tendrás que esperar.
- **Todo es tierno y apto para todo público.** Ribby corta en seco cualquier cosa fuera de tono.

**Comandos:** `/ribby corazones` (cómo te ve, solo lo ves tú), `/ribby recuerdos` (lo que recuerda de ti), `/ribby regalar` (un regalo al día), `/ribby cita` (una cita al día, con decisiones que importan) y `/ribby terminar` (si sois pareja).

### Más cosas para hacer con Ribby
- **📖 Misiones de lectura** (`/ribby mision`): Ribby te encarga una historia de su biblioteca, elegida según tus gustos. Léela y cuéntale qué te pareció con `/biblioteca resenar`: ganarás corazones y el autor recibirá tu reseña. Si no te convence, puedes pedir otra (una vez al día).
- **🖋️ Reseñas** (`/biblioteca resenar`, `/biblioteca resenas`): puntúa de 1 a 5 cualquier historia que hayas leído. Las fichas de la biblioteca muestran la nota media.
- **🎂 Cumpleaños** (`/ribby cumpleanos`): Ribby te felicitará ese día en su canal (y te dará un regalito de corazones).
- **💞 Aniversarios:** si eres la pareja de Ribby, ella celebrará cada mes juntos.
- **🎉 Eventos de temporada** (`/ribby evento`): San Valentín, Día del Libro, Halloween / Día de Muertos y Navidad traen un regalo y una cita especiales.
- **🏅 Logros** (`/ribby logros`): insignias por rachas, citas, lecturas... y algún logro secreto.
- **📕 La historia de Ribby** (`/ribby historia`): capítulos sobre su pasado que solo cuenta a quien se gana su confianza. Se desbloquean al ser su amigo, su mejor amigo, algo más... y su pareja. Cada capítulo termina con una decisión que Ribby recordará.
- **🧠 ¿Me conoces?** (`/ribby quiz`): una pregunta al día sobre Ribby (¡o sobre lo que tú le contaste!). Acertar da corazones; las preguntas sobre su pasado solo salen si has leído su historia.
- **💌 Ribby te escribe:** si eres de sus mejores amigos o su pareja, de vez en cuando te saludará por su cuenta. Si prefieres que no, usa `/ribby avisos activar:False`.

---

## 📋 Resumen de Comandos

**Para Administradores (Staff):**
1. `/evento crear [nombre]`: Inicia un nuevo reto.
2. `/evento configurar [canal_voz] [canal_envio]`: Le dice a Ribby dónde debe monitorear las narraciones y dónde debe mandar los anuncios oficiales.
3. `/evento iniciar_narracion`: Inicia una sesión de narración.
4. `/evento cerrar_narracion`: Pausa la sesión y guarda los datos del día.
5. `/evento iniciar_votacion`: Abre las urnas y permite que los usuarios voten.
6. `/evento cerrar`: Finaliza todo y anuncia al gran ganador.

**Para la Comunidad (Todos):**
1. `/participante_registrar [titulo] [etiquetas] [descripcion] [wattpad]`: Inscribe tu historia en el reto activo (etiquetas, descripción y Wattpad son opcionales). Luego sube tu documento y tu portada en el canal de envío.
2. `/votar`: Abre la boleta secreta de votación. Solo funciona en la fase de votación.
3. `/reto info`: Abre el libro interactivo para ver las obras inscritas y descargar los PDFs.
4. `/reto historial`: Abre el archivo de eventos pasados.
5. `/help`: Muestra este manual de usuario.
6. `/biblioteca recomendar [peticion]`: Ribby te recomienda historias.
7. `/biblioteca agregar [link]`: Añade una historia de Wattpad a la biblioteca.
8. `/biblioteca ver [historia]`: Muestra la ficha de una historia.
9. `/biblioteca etiquetar [historia] [etiquetas]` y `/biblioteca resumir [historia]`: Completa los datos de una historia.
10. `/biblioteca vincular_wattpad [usuario]`: Vincula tu cuenta de Wattpad (para autores).
11. `/biblioteca autor [usuario]`: Perfil de autor con sus historias, lecturas, votos y reseñas.
12. `/biblioteca seguir` / `/biblioteca dejar_de_seguir`: Avisos de capítulos nuevos.

**Solo Staff:** `/biblioteca eliminar [historia]` y `/biblioteca sincronizar [lista]` (actualiza desde Wattpad o importa otra lista de lectura).

---
Con Ribby al mando, los líderes del servidor pueden despreocuparse de las hojas de Excel, conteo de votos manuales y desorganización. Ribby es justa, exacta, interactiva y asegura que los retos literarios sean profesionales y divertidos.
