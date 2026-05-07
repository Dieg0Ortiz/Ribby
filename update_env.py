import re

env_file = ".env"
try:
    with open(env_file, "r") as f:
        content = f.read()
except FileNotFoundError:
    content = ""

# Update or add GEMINI_API_KEY
gemini_keys = "AIzaSyBPcjtWfPpHlSFDwsC84EExwUt_qwur28Y,AIzaSyCPl_KNLFcDoCke5eq2TkFR4cq50khrkWk,AIzaSyCXpVnxjwJFNiltaSezOkjWW-OwMSBqG1g,AIzaSyA0wIXjOP-8kOuIFkUzNDPX5C_OmTXiE_o,AIzaSyADFje4qAD9Sl_svK6jZI7g03fOcKrg2ag"
if "GEMINI_API_KEY=" in content:
    content = re.sub(r'GEMINI_API_KEY=.*', f'GEMINI_API_KEY={gemini_keys}', content)
else:
    content += f'\nGEMINI_API_KEY={gemini_keys}\n'

if "GROQ_API_KEY=" in content:
    content = re.sub(r'GROQ_API_KEY=.*', 'GROQ_API_KEY=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', content)
else:
    content += '\nGROQ_API_KEY=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\n'

if "OPENROUTER_API_KEY=" in content:
    content = re.sub(r'OPENROUTER_API_KEY=.*', 'OPENROUTER_API_KEY=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', content)
else:
    content += '\nOPENROUTER_API_KEY=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\n'

with open(env_file, "w") as f:
    f.write(content)
