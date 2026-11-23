# 🔒 Guía del Staff — La nueva Ribby

Documento interno para administradores de La Comarca: cómo funcionan las novedades, qué hay que configurar y cómo resolver problemas. **No lo compartas con los usuarios**: algunas mecánicas son sorpresa para ellos (a la comunidad le llega `NOVEDADES_RIBBY.md`, que no las revela).

---

## ✅ 1. Primeros pasos (hacerlo una vez)

1. **Elige el canal de Ribby:** `/ribby canal canal:#el-canal`.
   Ahí Ribby felicita cumpleaños, celebra aniversarios, anuncia los eventos de temporada, avisa de capítulos nuevos y saluda a la gente por su cuenta. **Sin canal configurado, nada de esto se publica.**
2. **Comprueba la biblioteca:** `/biblioteca recomendar`. Ribby carga sola la lista de Wattpad *"Historias de nuestro servidor"* al arrancar y la actualiza cada 6 horas. Si sale vacía, usa `/biblioteca sincronizar`.
3. **Anuncia las novedades** a la comunidad con el texto de `NOVEDADES_RIBBY.md`.

---

## 🏆 2. Cambios en los retos literarios

### Registro
`/participante_registrar` tiene tres campos nuevos **opcionales**: `etiquetas`, `descripcion` y `wattpad` (enlace a la historia o al perfil del autor). Con ellos, la historia entra en la biblioteca de Ribby lista para recomendarse.
- Si el autor pone el enlace de su **historia** de Wattpad, Ribby la vincula al reto y guarda sus datos.
- Si pone el de su **perfil**, Ribby aprende qué cuenta de Wattpad es suya.
- Volver a registrarse ya **no borra** el documento, la portada ni la fecha de registro.

### Votación y antifraude (cambio importante)
- El sistema antifraude secreto **funcionaba mal**: con descargar un solo documento, el voto ya contaba como válido. Ahora está corregido.
- La lista de habilitados se calcula **solo al usar `/evento iniciar_votacion`** y se rehace entera cada vez.
- **Las descargas cuentan únicamente si se hacen antes de iniciar la votación.**
- Los umbrales siguen siendo el 70 % del tiempo de narración en voz **o** el 50 % de los documentos descargados.

### Otros arreglos
- `/votar` admite más de 25 historias (hasta 125), y el menú desaparece después de cada voto para que nadie lo reutilice.
- Si cierras un evento con `/evento cerrar` en mitad de una narración, la narración también se cierra correctamente.
- Si Ribby se reinicia durante una narración, al volver revisa quién sigue en el canal de voz y ajusta la asistencia.
- `/admin_help` responde siempre en privado.
- Los enlaces de documentos y portadas ya no caducan.

---

## 📚 3. Biblioteca de recomendaciones

**Fuentes:** la lista de Wattpad de La Comarca, todas las historias de los retos (las antiguas también), y los enlaces que añada la comunidad.

**Quién puede hacer qué:**
| Acción | Quién |
|---|---|
| Añadir historias sueltas (enlace o `/biblioteca agregar`) | Cualquiera, al instante |
| Completar etiquetas y resúmenes | Cualquiera, al instante |
| Escribir o corregir el resumen de una historia propia | Solo el autor (su versión manda sobre la de los demás) |
| Importar listas de lectura completas | Solo staff: `/biblioteca sincronizar lista:<enlace>` |
| Quitar una historia | Solo staff: `/biblioteca eliminar` |

- Las historias de los retos no se pueden quitar de la biblioteca, para no perder el registro del reto.
- **Contenido maduro:** las historias marcadas como maduras en Wattpad se recomiendan con un aviso visible de "+18".
- **Reseñas:** son públicas, etiquetan al autor, y nadie puede reseñar su propia historia.
- **Avisos de capítulos:** Ribby revisa Wattpad cada 6 horas. Si una historia publica capítulos nuevos, avisa en su canal a quien la siga o la tenga como misión de lectura. Sin canal configurado, avisa por mensaje privado.

---

## 💞 4. La relación con Ribby (información reservada)

Cada usuario tiene de 0 a 100 corazones. Según los corazones, Ribby le ve como:

| Nivel | Corazones | Notas |
|---|---|---|
| Desconocido | 0–14 | |
| Amigo | 15–44 | |
| Mejor amigo | 45–74 | Sin coquetear, nadie pasa de aquí |
| Algo más que amigos | 75–99 | Hay que haberle coqueteado varias veces |
| *Enamorada* (secreto) | 100 | Da pistas, pero **nunca se declara ella** |
| Pareja | — | Solo si el usuario se declara estando en 100 |

**Reglas que conviene conocer:**
- **Hay un tope diario** de corazones charlando. Llegar al máximo solo hablando lleva unas 6 semanas; con regalos, citas y misiones diarias, unas 3–4.
- Ser grosero resta corazones.
- **Si llega a 100 y el usuario no se declara en 7 días**, el interés se enfría y vuelve a "amigo".
- Si se declara antes de tiempo, Ribby le rechaza con cariño y tiene que esperar 24 h para volver a intentarlo.
- **Ribby solo puede tener una pareja en todo el servidor.** Mientras la tenga, los demás no pasan de "algo más", y ella rechaza sus coqueteos con amabilidad.
- Cuando acepta a alguien, lo anuncia en el canal. Los niveles de los demás son privados.
- Si su pareja desaparece 30 días, la relación termina en buenos términos y Ribby queda libre. La pareja también puede terminar con `/ribby terminar`.
- Después de 14 días sin hablarle se pierde 1 corazón al día, pero un amigo nunca vuelve a ser desconocido.
- **Todo es tierno y apto para todo público.** Ribby corta cualquier contenido sexual y nunca usa culpa ni celos.

**Tainy (su creador):** Ribby le ve como a su padre. Siempre tiene los corazones al máximo, nunca puede ser su pareja (si lo intenta, Ribby reacciona como una hija avergonzada), y solo le cuenta los capítulos "familiares" de su historia.

**Moderación:** `/ribby reiniciar usuario:@alguien` borra la relación de esa persona con Ribby (por ejemplo, si alguien abusa del sistema o se quiere liberar el puesto de pareja).

---

## 🎉 5. Vida social de Ribby

| Función | Cómo funciona |
|---|---|
| **Misiones de lectura** (`/ribby mision`) | Ribby elige una historia según los gustos del usuario. Al reseñarla gana 2 corazones (la reseña no cuenta como misión si llega antes de 1 hora). Se puede pedir otra historia una vez al día. |
| **Cumpleaños** (`/ribby cumpleanos`) | Ese día, a partir de las 9:00 (hora de México), Ribby felicita en su canal y regala 3 corazones. |
| **Aniversarios** | Cada mes que cumple con su pareja, Ribby lo celebra en su canal. |
| **Eventos de temporada** (`/ribby evento`) | 💘 San Valentín (10–15 feb) · 📚 Día del Libro (20–24 abr) · 🎃 Halloween y Día de Muertos (25 oct – 2 nov) · 🎄 Navidad (15 dic – 6 ene). Ribby los anuncia el primer día y ofrece un regalo y una cita especiales, una vez por evento. |
| **Logros** (`/ribby logros`) | 22 insignias. Hay dos secretas: regalarle un escarabajo y declararse antes de tiempo. |
| **Su historia** (`/ribby historia`) | 4 capítulos que se desbloquean siendo amigo, mejor amigo, algo más y pareja. Cuentan su pasado (cómo llegó a la biblioteca, el incendio, una carta sin enviar y su gran secreto). |
| **Quiz** (`/ribby quiz`) | Una pregunta al día sobre Ribby o sobre lo que el usuario le contó. Las preguntas sobre su pasado solo salen si ya se leyó ese capítulo. |
| **Iniciativa** | Ribby saluda por su cuenta a sus mejores amigos o a su pareja. Como mucho 1 mensaje cada 6 horas en todo el servidor, entre las 11:00 y las 21:00, y a cada persona como máximo cada 4 días. Cualquiera puede desactivarlo con `/ribby avisos`. |

---

## 🧪 6. Modo de pruebas

Sirve para probar cualquier función sin ensuciar los datos reales de La Comarca. Solo pueden usarlo el staff y Tainy.

### Servidor de pruebas
En el **servidor de pruebas de Tainy** (ID `1489169806128185517`), **todo usa siempre la base de datos de pruebas**, para todo el mundo y sin activar nada. Ahí se pueden crear retos, votar o enamorar a Ribby sin miedo: nada de eso llega nunca a La Comarca. Para que funcione, Ribby tiene que estar invitada a ese servidor.

### Dentro de La Comarca
`/prueba activar`: desde ese momento, todo lo que hagas **tú** (comandos, botones, hablar con Ribby, el canal de voz) va a la base de datos de pruebas. Los demás siguen con los datos reales aunque estéis en el mismo canal. Ribby marca con 🧪 sus respuestas mientras estés en pruebas. Para volver: `/prueba desactivar`.

### Atajos
Funcionan en modo de pruebas o en el servidor de pruebas:

| Comando | Para qué |
|---|---|
| `/prueba sembrar` | Copia la biblioteca real a la de pruebas (empieza vacía) |
| `/prueba nivel` | Saltar a cualquier nivel de relación, incluida "pareja" |
| `/prueba diario` | Repetir regalo, cita, quiz, declaración y cambio de misión sin esperar |
| `/prueba tiempo días:N` | Simular que pasan días: enfriamiento, inactividad, misiones "ya leídas" |
| `/prueba evento` | Forzar San Valentín, Día del Libro, Halloween o Navidad |
| `/prueba celebrar` | Lanzar ya un cumpleaños, un aniversario o el anuncio de un evento |
| `/prueba iniciativa` | Que Ribby te escriba por su cuenta ahora mismo |
| `/prueba capitulo_nuevo` | Simular un capítulo nuevo de una historia que sigas |
| `/prueba reiniciar` | Borrar todos los datos de prueba |
| `/prueba estado` | Ver si estás en pruebas y quién más lo está |

En modo de pruebas, **Ribby trata a Tainy como a un usuario normal**, para que pueda probar todas las rutas de la relación.

**Probar un reto completo en solitario:** crea el evento, registra a otra persona con `/participante_registrar usuario:@alguien` (sus datos también van a pruebas, porque el comando lo lanzas tú) y vota por su historia.

---

## 🛠️ 7. Problemas frecuentes

| Problema | Qué hacer |
|---|---|
| No aparecen los comandos nuevos | Espera unos minutos tras el reinicio de Ribby; Discord tarda en actualizar. Si persiste, reinicia Discord. |
| Ribby no felicita cumpleaños, ni anuncia eventos, ni saluda | Falta `/ribby canal`. |
| La biblioteca está vacía | `/biblioteca sincronizar`. |
| Ribby responde con frases fijas en vez de conversar | Su IA no está disponible en ese momento (cuota o caída del servicio); vuelve sola. |
| Alguien abusa del sistema de corazones | `/ribby reiniciar usuario:@alguien`. |
| Una historia no debería estar en la biblioteca | `/biblioteca eliminar`. |
| Un autor no puede corregir el resumen de su historia | Tiene que vincular su cuenta con `/biblioteca vincular_wattpad`. |
