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
3. `/evento iniciar_votacion`: Inicia el engaño. Todos pueden votar, pero el bot ya decidió quiénes son válidos y quiénes serán anulados en secreto.
4. `/evento cerrar`: Finaliza todo, anuncia al ganador y genera el reporte de nulos.

---

## 📋 3. Comandos Exclusivos de Staff

- `/evento crear [nombre]`: Inicia el evento.
- `/evento configurar [canal_voz] [canal_envio]`: Indispensable para que el bot sepa qué canal de voz debe espiar para contar los minutos de asistencia.
- `/evento iniciar_narracion`: Inicia el cronómetro en el canal de voz configurado.
- `/evento cerrar_narracion`: Detiene el cronómetro del día.
- `/evento iniciar_votacion`: Filtra a los habilitados (en secreto) y abre las urnas.
- `/evento cerrar`: Publica resultados filtrados y te envía el reporte privado.

> [!WARNING]
> Recuerda no compartir este documento ni capturas del mismo en canales públicos, o la magia del sistema antifraude se perderá.
