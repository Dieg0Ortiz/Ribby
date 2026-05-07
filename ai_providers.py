import logging
import random
import aiohttp
import google.generativeai as genai

log = logging.getLogger("bot-literario.ai_providers")

class AIProvider:
    """Clase base para todos los proveedores de IA."""
    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        raise NotImplementedError()

class GeminiProvider(AIProvider):
    def __init__(self, api_keys: list[str]):
        self.api_keys = api_keys
        self.current_key_idx = 0
        self.model_name = 'gemini-2.5-flash'
        self._configure_current_key()

    def _configure_current_key(self):
        if self.api_keys:
            key = self.api_keys[self.current_key_idx]
            genai.configure(api_key=key)
            self.model = genai.GenerativeModel(self.model_name)
            log.info(f"Usando Gemini API Key índice {self.current_key_idx} (Termina en ...{key[-4:]})")

    def _next_key(self) -> bool:
        """Rota a la siguiente llave. Devuelve True si rotó con éxito, False si ya probó todas."""
        if not self.api_keys:
            return False
        
        self.current_key_idx += 1
        if self.current_key_idx >= len(self.api_keys):
            self.current_key_idx = 0
            return False # Ya dimos la vuelta completa
            
        self._configure_current_key()
        return True

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        if not self.api_keys:
            raise Exception("No hay llaves de Gemini configuradas.")

        # Construir el formato nativo de historial para Gemini
        contents = []
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [msg["content"]]})
            
        # Inyectar el system prompt en el primer mensaje del usuario para simularlo
        if contents and contents[0]["role"] == "user":
            contents[0]["parts"][0] = f"{system_prompt}\n\n---\n\n{contents[0]['parts'][0]}"
        else:
            # Fallback por si acaso
            contents.insert(0, {"role": "user", "parts": [f"{system_prompt}\n\n---\n\nInicia la charla."]})
            contents.insert(1, {"role": "model", "parts": ["Entendido."]})

        # Intentar con la llave actual, si da 429, rotar
        keys_tried = 0
        while keys_tried < len(self.api_keys):
            try:
                response = await self.model.generate_content_async(contents)
                if response.text:
                    return response.text
                raise Exception("Respuesta vacía de Gemini")
            except Exception as e:
                error_msg = str(e)
                log.warning(f"Error con Gemini (Key {self.current_key_idx}): {error_msg}")
                # Si es un error de cuota o rate limit
                if "429" in error_msg or "Quota" in error_msg or "rate limit" in error_msg.lower():
                    log.info("Cuota excedida en la llave actual. Rotando a la siguiente...")
                    keys_tried += 1
                    if not self._next_key():
                        break # Ya probamos todas
                else:
                    raise # Otro tipo de error (ej. bloqueo de seguridad)
        
        raise Exception("Todas las llaves de Gemini fallaron o excedieron su cuota.")

class GroqProvider(AIProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Usamos Llama 3 8B por su tremenda velocidad
        self.model_name = "llama3-8b-8192"
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        if not self.api_key:
            raise Exception("No hay llave de Groq configurada.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Construir array de mensajes estilo OpenAI
        messages = [{"role": "system", "content": system_prompt}]
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "assistant"
            messages.append({"role": role, "content": msg["content"]})
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.7
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Groq error {resp.status}: {text}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

class OpenRouterProvider(AIProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Usamos un modelo gratuito de OpenRouter
        self.model_name = "meta-llama/llama-3-8b-instruct:free"
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        if not self.api_key:
            raise Exception("No hay llave de OpenRouter configurada.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ComarcaLit/Ribby",
            "X-Title": "Ribby Bot"
        }
        
        # Construir array de mensajes estilo OpenAI
        messages = [{"role": "system", "content": system_prompt}]
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "assistant"
            messages.append({"role": role, "content": msg["content"]})
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.7
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"OpenRouter error {resp.status}: {text}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

class ProviderManager:
    """Maneja la lógica de fallback entre proveedores."""
    def __init__(self, config):
        self.providers: list[AIProvider] = []
        
        # 1. Añadir Gemini (tiene soporte nativo de rotación)
        if config.GEMINI_API_KEYS:
            self.providers.append(GeminiProvider(config.GEMINI_API_KEYS))
            
        # 2. Añadir Groq como primer respaldo (es más rápido y estable que OR gratuito)
        if config.GROQ_API_KEY:
            self.providers.append(GroqProvider(config.GROQ_API_KEY))
            
        # 3. Añadir OpenRouter como segundo respaldo
        if config.OPENROUTER_API_KEY:
            self.providers.append(OpenRouterProvider(config.OPENROUTER_API_KEY))
            
        log.info(f"ProviderManager inicializado con {len(self.providers)} proveedores de IA.")

    async def generate(self, system_prompt: str, chat_history: list[dict]) -> str:
        if not self.providers:
            raise Exception("No hay ningún proveedor de IA configurado.")
            
        for i, provider in enumerate(self.providers):
            try:
                provider_name = provider.__class__.__name__
                log.info(f"Intentando generar respuesta con {provider_name}...")
                response = await provider.generate(system_prompt, chat_history)
                return response
            except Exception as e:
                log.warning(f"Fallo en {provider.__class__.__name__}: {e}")
                if i < len(self.providers) - 1:
                    log.info(f"Saltando al siguiente proveedor de IA...")
                else:
                    raise Exception("TODOS los proveedores de IA fallaron.")
                    
        raise Exception("Flujo inesperado en ProviderManager.")
