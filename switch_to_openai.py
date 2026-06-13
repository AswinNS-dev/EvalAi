import os

for f in os.listdir('backend/agents'):
    if f.endswith('.py') and f != '__init__.py':
        p = os.path.join('backend/agents', f)
        with open(p, 'r', encoding='utf-8') as file:
            c = file.read()
        c = c.replace('from groq import Groq', 'from openai import OpenAI')
        c = c.replace('Groq(api_key=settings.groq_api_key) if settings.groq_available', 'OpenAI(api_key=settings.openai_api_key) if settings.openai_available')
        c = c.replace('model="llama-3.3-70b-versatile"', 'model="gpt-4o-mini"')
        with open(p, 'w', encoding='utf-8') as file:
            file.write(c)
