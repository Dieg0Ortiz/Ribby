import google.generativeai as genai
import config
genai.configure(api_key=config.GEMINI_API_KEY)

models_to_test = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.5-flash", "gemma-4-26b-a4b-it"]

for m in models_to_test:
    try:
        model = genai.GenerativeModel(m)
        res = model.generate_content("Hola")
        print(f"{m} SUCCESS: {res.text}")
    except Exception as e:
        print(f"{m} ERROR: {e}")
