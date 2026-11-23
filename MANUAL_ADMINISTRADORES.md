# 🔒 Manual para Administradores: Ribby (Secretos y Antifraude)

Este manual es **estrictamente confidencial** para el equipo de líderes y administradores de La Comarca. Detalla el verdadero funcionamiento del bot por debajo de la mesa, incluyendo los mecanismos antifraude secretos.

---

## 🕵️‍♂️ 1. El Verdadero Sistema Antifraude (Votos Nulos Silenciosos)
Para el usuario común, la votación parece estar abierta para todos sin restricciones. Sin embargo, Ribby implementa un **filtro silencioso** para evitar votos por amiguismo (gente que entra solo a votar sin participar).

Para que un voto sea considerado **Válido**, el usuario debe cumplir silenciosamente **al menos una** de estas dos condiciones:
1. **Condición de Voz:** Haber estado conectado en el canal de voz al menos el **70% del tiempo total** que duraron las narraciones.
2. **Condición de Lectura:** Haber descargado mediante el bot al menos el **50% de las historias** subidas.

**¿Qué pasa con los que no cumplen?**
El bot los deja votar y les envía un mensaje de "✅ ¡Voto Registrado!". Ellos creerán que su voto contó. Sin embargo, **Ribby marca su voto internamente como NULO** (`es_valido = False`) en la base de datos y no se suma al conteo final.

### Visibilidad de los Votos Nulos
- Al usar `/evento iniciar_votacion`, el administrador (y solo el administrador) recibirá un mensaje privado efímero detallando exactamente quiénes sí cumplieron los requisitos y son votos válidos.
- Al usar `/evento cerrar`, el bot publicará los ganadores contando solo los votos válidos. Al administrador le llegará un **reporte privado** indicando cuántos votos nulos hubo, a quiénes se les anuló y por qué.

---

## 🔄 2. Flujo del Evento (Resumen de Admin)
1. `/evento crear`: Abre inscripciones.
2. `/evento iniciar_narracion` / `/evento cerrar_narracion`: Abre/Cierra sesiones de voz. El bot rastrea los minutos automáticamente de fondo. Se pueden hacer múltiples sesiones.
3. `/evento iniciar_votacion`: Inicia el engaño. Todos pueden votar, pero el bot ya decidió quiénes son válidos y quiénes serán anulados en secreto. Las descargas cuentan solo si se hicieron **antes** de este comando.
4. `/evento cerrar`: Finaliza todo, anuncia al ganador y genera el reporte de nulos.

---

## 📋 3. Comandos Exclusivos de Staff

- `/evento crear [nombre]`: Inicia el evento.
- `/evento configurar [canal_voz] [canal_envio] [canal_respaldo]`: Indispensable para que el bot sepa qué canal de voz debe espiar para contar los minutos de asistencia. El canal de respaldo (opcional y privado) guarda una copia de cada archivo.
- `/evento configurar_votos [cantidad]`: Cuántos votos (1–10) puede emitir cada persona por historias distintas.
- `/admin_help`: Muestra este manual. Siempre responde en privado (solo lo ves tú).
- `/evento iniciar_narracion`: Inicia el cronómetro en el canal de voz configurado.
- `/evento cerrar_narracion`: Detiene el cronómetro del día.
- `/evento iniciar_votacion`: Filtra a los habilitados (en secreto) y abre las urnas.
- `/evento cerrar`: Publica resultados filtrados y te envía el reporte privado.

> [!WARNING]
> Recuerda no compartir este documento ni capturas del mismo en canales públicos, o la magia del sistema antifraude se perderá.

---

## 💞 4. Comandos de Staff de la Vida Social de Ribby
- `/ribby canal [canal]`: **Configúralo primero.** Es el canal donde Ribby felicita cumpleaños, celebra aniversarios, anuncia eventos de temporada y saluda por iniciativa propia. Sin canal, nada de eso se publica.
- `/ribby reiniciar [usuario]`: borra la relación de alguien con Ribby (corazones, pareja, etc.).
- `/biblioteca eliminar` y `/biblioteca sincronizar`: gestión de la biblioteca.

Límites de la iniciativa de Ribby (para que nunca sea spam): como mucho 1 mensaje cada 6 horas en todo el servidor, solo entre las 11:00 y las 21:00 (hora de México), a cada persona como mucho cada 4 días, y solo a mejores amigos o a su pareja. Cada usuario puede desactivarlo con `/ribby avisos`.

---

## 🧪 5. Modo de Pruebas
Para probar cualquier función sin tocar los datos reales.

- `/prueba activar`: pone a Ribby **entera** en modo de pruebas **para todo el mundo**: lo que haga cualquier usuario se guarda en una base de datos de pruebas aparte y no cuenta de verdad. Ribby lo anuncia en el canal y marca con 🧪 sus respuestas.
- `/prueba desactivar`: todo vuelve a la normalidad. · `/prueba estado`: ver si está activado y quién lo activó.
- En el **servidor de pruebas** (ID 1489169806128185517) todo usa siempre la base de pruebas, sin activar nada.
- `/prueba sembrar`: copia la biblioteca real a la de pruebas (empieza vacía).
- `/prueba reiniciar`: borra todos los datos de prueba.

**Atajos (solo en modo de pruebas):**
- `/prueba nivel`: salta a cualquier nivel con Ribby (amigo, mejor amigo, algo más, enamorada, pareja).
- `/prueba diario`: reinicia los límites diarios (regalo, cita, quiz, corazones, declaración, misión).
- `/prueba tiempo [días]`: viaja al futuro (enfriamiento del interés, inactividad, misión de lectura ya "leída").
- `/prueba evento`: fuerza San Valentín, Día del Libro, Halloween o Navidad solo para ti.
- `/prueba celebrar`: lanza ya un cumpleaños, un aniversario o el anuncio de un evento.
- `/prueba iniciativa`: Ribby te escribe por su cuenta ahora mismo.
- `/prueba capitulo_nuevo`: simula que una historia que sigues publicó un capítulo.

Para probar retos completos en solitario: crea el evento, registra a otra persona con `/participante_registrar usuario:@alguien` y vota por su historia.

**Nota sobre Tainy (creador de Ribby):** fuera de pruebas, Ribby le trata como a su padre (cariño de familia, corazones al máximo, nunca romance). En modo de pruebas le trata como a un usuario normal para que pueda probar todas las rutas.

