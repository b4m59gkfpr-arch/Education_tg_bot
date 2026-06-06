import urllib.request
import urllib.error
import json
import os
from studybot_ai.config import load_environment

# Загружаем переменные окружения из файла .env
load_environment()
key = os.getenv("GROQ_API_KEY", "")
url = "https://api.groq.com/openai/v1/chat/completions"

# Тестовый запрос для проверки соединения с Groq Cloud API
payload = {
    "model": "llama-3.3-70b-versatile",
    "messages": [
        {"role": "user", "content": "Say hello in Russian, one word only"}
    ],
    "temperature": 0.3
}

# Формируем сырой HTTP-запрос по спецификации OpenAI-совместимого API
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    },
    method="POST",
)

try:
    # Отправляем запрос и выводим ответ модели в консоль для быстрой диагностики
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read().decode("utf-8"))
    print("SUCCESS:", data["choices"][0]["message"]["content"])
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    body = e.read().decode()
    print("Response:", body[:500])
except Exception as e:
    print(f"Error: {e}")

