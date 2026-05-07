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
- **Lo que pasa:** Ribby abre las inscripciones. Los usuarios pueden usar el comando `/participante_registrar` para subir el título de su obra, adjuntar su archivo (PDF/DOCX) y una imagen de portada. Si se equivocan, pueden volver a usar el comando para actualizar su obra.

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

## 📋 Resumen de Comandos

**Para Administradores (Staff):**
1. `/evento crear [nombre]`: Inicia un nuevo reto.
2. `/evento configurar [canal_voz] [canal_envio]`: Le dice a Ribby dónde debe monitorear las narraciones y dónde debe mandar los anuncios oficiales.
3. `/evento iniciar_narracion`: Inicia una sesión de narración.
4. `/evento cerrar_narracion`: Pausa la sesión y guarda los datos del día.
5. `/evento iniciar_votacion`: Abre las urnas y permite que los usuarios voten.
6. `/evento cerrar`: Finaliza todo y anuncia al gran ganador.

**Para la Comunidad (Todos):**
1. `/participante_registrar [titulo] [archivo] [portada]`: Inscribe tu historia en el reto activo.
2. `/votar`: Abre la boleta secreta de votación. Solo funciona en la fase de votación.
3. `/reto info`: Abre el libro interactivo para ver las obras inscritas y descargar los PDFs.
4. `/reto historial`: Abre el archivo de eventos pasados.
5. `/help`: Muestra este manual de usuario.

---
Con Ribby al mando, los líderes del servidor pueden despreocuparse de las hojas de Excel, conteo de votos manuales y desorganización. Ribby es justa, exacta, interactiva y asegura que los retos literarios sean profesionales y divertidos.
