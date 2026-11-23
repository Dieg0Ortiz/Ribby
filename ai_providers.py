"""
ai_providers.py — Proveedores de IA con respaldo en cadena.

Orden: Claude → Hugging Face → Groq (Gemini y OpenRouter al final, si tienen clave).
Solo se usan los que tengan su API key configurada.
Todos reciben el mismo formato: un system prompt y un historial
[{"role": "user" | "ribby", "content": str}, ...].
"""

from __future__ import annotations

import logging
import re

import aiohttp
import anthropic
from google import genai
from google.genai import types

log = logging.getLogger("bot-literario.ai_providers")

# Límite de salida común. Discord admite 2000 caracteres por mensaje;
# ~500 tokens deja margen sin cortar las respuestas a media frase.
MAX_TOKENS_SALIDA = 500
TIMEOUT_HTTP = aiohttp.ClientTimeout(total=30)


class AIProvider:
    """Clase base para todos los proveedores de IA."""

    nombre = "AIProvider"

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        raise NotImplementedError


def _es_error_de_cuota(e: Exception) -> bool:
    texto = str(e).lower()
    codigo = getattr(e, "code", None)
    return codigo == 429 or "429" in texto or "quota" in texto or "rate limit" in texto or "resource_exhausted" in texto


class ClaudeProvider(AIProvider):
    """Claude (Anthropic) — por defecto Claude Haiku 5.5, el modelo más barato y rápido."""

    nombre = "Claude"

    def __init__(self, api_key: str, model_name: str):
        self.model_name = model_name
        # Un solo reintento automático (429/5xx/529) y timeout corto: si Claude
        # no responde rápido, es mejor pasar al siguiente proveedor.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0, max_retries=1)

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        messages = [
            {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
            for m in chat_history
        ]
        if not messages:
            raise ValueError("El historial no puede estar vacío.")

        try:
            resp = await self._client.messages.create(
                model=self.model_name,
                max_tokens=MAX_TOKENS_SALIDA,
                system=system_prompt,
                messages=messages,
                # Sin razonamiento interno y esfuerzo bajo: respuestas cortas de chat,
                # los tokens se gastan solo en el texto que ve el usuario.
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
            )
        except anthropic.AuthenticationError as e:
            raise RuntimeError("API key de Claude inválida (revisa ANTHROPIC_API_KEY)") from e
        except anthropic.RateLimitError as e:
            raise RuntimeError("Claude: límite de uso alcanzado (429)") from e
        except anthropic.OverloadedError as e:
            raise RuntimeError("Claude: servicio saturado (529)") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Claude error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"Claude: error de conexión ({e})") from e

        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude rechazó responder a este mensaje")

        texto = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not texto:
            raise RuntimeError("Respuesta vacía de Claude")
        return texto


class GeminiProvider(AIProvider):
    nombre = "Gemini"

    def __init__(self, api_keys: list[str], model_name: str):
        self.api_keys = api_keys
        self.model_name = model_name
        self.current_key_idx = 0
        self._clientes = [genai.Client(api_key=k) for k in api_keys]

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        if not self.api_keys:
            raise RuntimeError("No hay llaves de Gemini configuradas.")

        contents = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in chat_history
        ]
        if not contents:
            raise ValueError("El historial no puede estar vacío.")

        cfg = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=MAX_TOKENS_SALIDA,
            temperature=0.8,
            # Sin "thinking": respuestas cortas y rápidas, y no consume el límite de salida
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        # Probar TODAS las llaves empezando por la actual, dando la vuelta completa
        n = len(self.api_keys)
        for intento in range(n):
            idx = (self.current_key_idx + intento) % n
            try:
                resp = await self._clientes[idx].aio.models.generate_content(
                    model=self.model_name, contents=contents, config=cfg
                )
                texto = (resp.text or "").strip()
                if not texto:
                    raise RuntimeError("Respuesta vacía de Gemini")
                self.current_key_idx = idx  # Recordar la última llave que funcionó
                return texto
            except Exception as e:  # noqa: BLE001
                if _es_error_de_cuota(e):
                    log.info(f"Cuota excedida en la llave Gemini #{idx} (…{self.api_keys[idx][-4:]}); probando la siguiente")
                    continue
                raise  # Otro error (bloqueo de seguridad, modelo inexistente…)

        raise RuntimeError("Todas las llaves de Gemini excedieron su cuota.")


class OpenAICompatibleProvider(AIProvider):
    """Proveedor para APIs con formato OpenAI /chat/completions (Groq, OpenRouter)."""

    def __init__(self, nombre: str, api_key: str, model_name: str, url: str, extra_headers: dict | None = None):
        self.nombre = nombre
        self.api_key = api_key
        self.model_name = model_name
        self.url = url
        self.extra_headers = extra_headers or {}

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        if not self.api_key:
            raise RuntimeError(f"No hay llave de {self.nombre} configurada.")

        messages = [{"role": "system", "content": system_prompt}]
        messages += [
            {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
            for m in chat_history
        ]
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": MAX_TOKENS_SALIDA,
            "temperature": 0.7,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", **self.extra_headers}

        async with aiohttp.ClientSession(timeout=TIMEOUT_HTTP) as session:
            async with session.post(self.url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    texto = await resp.text()
                    raise RuntimeError(f"{self.nombre} error {resp.status}: {texto[:300]}")
                data = await resp.json()

        contenido = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        # Algunos modelos abiertos incluyen su razonamiento entre <think>...</think>: no se muestra
        contenido = re.sub(r"<think>.*?</think>", "", contenido, flags=re.S | re.I)
        if not contenido.strip():
            raise RuntimeError(f"Respuesta vacía de {self.nombre}")
        return contenido.strip()


class ProviderManager:
    """Prueba los proveedores en orden hasta que uno responda."""

    def __init__(self, config):
        self.providers: list[AIProvider] = []

        # Orden: Claude → Hugging Face → Groq. Gemini y OpenRouter van al final y
        # solo si siguen teniendo clave configurada.
        if config.ANTHROPIC_API_KEY:
            self.providers.append(ClaudeProvider(config.ANTHROPIC_API_KEY, config.CLAUDE_MODEL))
        if config.HF_TOKEN:
            self.providers.append(OpenAICompatibleProvider(
                "Hugging Face", config.HF_TOKEN, config.HF_CHAT_MODEL,
                "https://router.huggingface.co/v1/chat/completions",
            ))
        if config.GROQ_API_KEY:
            self.providers.append(OpenAICompatibleProvider(
                "Groq", config.GROQ_API_KEY, config.GROQ_MODEL,
                "https://api.groq.com/openai/v1/chat/completions",
            ))
        if config.GEMINI_API_KEYS:
            self.providers.append(GeminiProvider(config.GEMINI_API_KEYS, config.GEMINI_MODEL))
        if config.OPENROUTER_API_KEY:
            self.providers.append(OpenAICompatibleProvider(
                "OpenRouter", config.OPENROUTER_API_KEY, config.OPENROUTER_MODEL,
                "https://openrouter.ai/api/v1/chat/completions",
                {"HTTP-Referer": "https://github.com/ComarcaLit/Ribby", "X-Title": "Ribby Bot"},
            ))

        log.info(f"ProviderManager inicializado con {len(self.providers)} proveedor(es) de IA.")

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        if not self.providers:
            raise RuntimeError("No hay ningún proveedor de IA configurado.")

        ultimo_error: Exception | None = None
        for provider in self.providers:
            try:
                log.debug(f"Generando respuesta con {provider.nombre}...")
                return await provider.generate(system_prompt, chat_history)
            except Exception as e:  # noqa: BLE001
                ultimo_error = e
                log.warning(f"Fallo en {provider.nombre}: {e}")

        raise RuntimeError(f"Todos los proveedores de IA fallaron (último error: {ultimo_error})")
