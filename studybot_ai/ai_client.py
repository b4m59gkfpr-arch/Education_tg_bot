from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from studybot_ai.config import get_env, get_required_env


def _extract_json(text: str) -> dict:
    """
    Извлекает JSON-строку из ответа нейросети.
    Очищает маркеры разметки markdown (```json ... ```) и парсит текст в словарь.
    """
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Резервный поиск первого вхождения фигурных скобок с помощью регулярного выражения
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("LLM did not return JSON.")
        return json.loads(match.group(0))


def _validate_pack(data: dict) -> dict:
    """
    Выполняет жесткую проверку структуры данных (Schema Validation).
    Проверяет наличие полей note_title, note_content и валидность структуры вопросов.
    """
    if not isinstance(data.get("note_title"), str) or not data["note_title"].strip():
        raise ValueError("LLM response does not contain note_title.")

    if not isinstance(data.get("note_content"), str) or not data["note_content"].strip():
        raise ValueError("LLM response does not contain note_content.")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("LLM response does not contain questions.")

    normalized_questions = []
    for item in questions:
        if not isinstance(item, dict):
            raise ValueError("Each question must be an object.")

        options = item.get("options")
        if not isinstance(options, dict):
            raise ValueError("Each question must contain options.")

        correct_answer = str(item.get("correct_answer", "")).upper().strip()
        if correct_answer not in {"A", "B", "C", "D"}:
            raise ValueError("correct_answer must be A, B, C, or D.")

        normalized_questions.append(
            {
                "question": str(item.get("question", "")).strip(),
                "option_a": str(options.get("A", "")).strip(),
                "option_b": str(options.get("B", "")).strip(),
                "option_c": str(options.get("C", "")).strip(),
                "option_d": str(options.get("D", "")).strip(),
                "correct_answer": correct_answer,
            }
        )

    # Убеждаемся, что ни одно поле не является пустым
    for question in normalized_questions:
        if not all(question.values()):
            raise ValueError("LLM returned an incomplete question structure.")

    return {
        "note_title": data["note_title"].strip(),
        "note_content": data["note_content"].strip(),
        "questions": normalized_questions,
    }


def generate_study_pack(subject_name: str, material: str, question_count: int) -> dict:
    """
    Генерирует конспект и тесты по заданной теме и лекции.
    Использует Groq Cloud API (Llama 3.3). 
    В случае отсутствия ключа или ошибки сети переключается на встроенный генератор-заглушку (Mock).
    """
    api_key = get_env("GROQ_API_KEY", "").strip()
    model = get_env("GROQ_MODEL", "llama-3.3-70b-versatile")

    use_mock = False
    # Проверка валидности API-ключа
    if not api_key or not api_key.startswith("gsk_"):
        use_mock = True

    if not use_mock:
        # Промпт-инжиниринг: заставляем ИИ отвечать только в JSON и отсеивать «мусорные» разделы лекций
        prompt = f"""
You are helping build an exam preparation Telegram bot.

Subject: {subject_name}
Question count: {question_count}

Create a concise study note and multiple-choice test from the material below.

Return only valid JSON in this exact structure:
{{
  "note_title": "short title",
  "note_content": "clear study note in Russian",
  "questions": [
    {{
      "question": "question in Russian",
      "options": {{
        "A": "answer A",
        "B": "answer B",
        "C": "answer C",
        "D": "answer D"
      }},
      "correct_answer": "A"
    }}
  ]
}}

Rules:
- Write in Russian.
- Make questions based only on the provided material.
- Use exactly {question_count} questions.
- correct_answer must be only A, B, C, or D.
- Do not add markdown or extra text outside the JSON.
- Игнорируй титульные листы, оглавления, введения, аннотации, благодарности и списки литературы (references), если они присутствуют. Фокусируйся исключительно на самом содержательном учебном материале.

Material:
{material}
""".strip()

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            # Требуем от API возвращать валидный JSON-объект
            "response_format": {
                "type": "json_object"
            },
            # Низкая температура 0.3 для снижения креативности модели и точного следования материалу
            "temperature": 0.3,
        }

        url = "https://api.groq.com/openai/v1/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            method="POST",
        )

        try:
            # Асинхронно-подобное синхронное чтение через urllib с таймаутом
            with urllib.request.urlopen(request, timeout=60) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            text = response_data["choices"][0]["message"]["content"]
            return _validate_pack(_extract_json(text))
        except Exception as error:
            print(f"Groq API call failed, falling back to mock generator: {error}")
            use_mock = True

    if use_mock:
        # Резервный эвристический генератор-заглушка на случай сбоя API
        import random
        # Разделяем исходный текст на отдельные предложения
        sentences = [s.strip() for s in re.split(r"[.!?\n]", material) if len(s.strip()) > 10]
        if not sentences:
            sentences = [material.strip()]

        questions = []
        for i in range(question_count):
            sent = sentences[i % len(sentences)]
            q_text = f"Опираясь на материал темы '{subject_name}': о чём говорится в предложении '{sent[:60]}...'?"
            if len(sent) < 80:
                q_text = f"К какому разделу темы '{subject_name}' относится утверждение: '{sent}'?"

            correct_val = f"Правильное суждение: {sent[:50]}"
            distractor_1 = f"Альтернативная гипотеза {i + 1}"
            distractor_2 = f"Второстепенный признак {i + 1}"
            distractor_3 = f"Общая концепция ({subject_name})"

            options_list = [correct_val, distractor_1, distractor_2, distractor_3]
            random.shuffle(options_list)

            correct_idx = options_list.index(correct_val)
            correct_letter = ["A", "B", "C", "D"][correct_idx]

            questions.append({
                "question": q_text,
                "option_a": options_list[0],
                "option_b": options_list[1],
                "option_c": options_list[2],
                "option_d": options_list[3],
                "correct_answer": correct_letter,
            })

        return {
            "note_title": f"Конспект по теме '{subject_name}' (Демо)",
            "note_content": f"Краткий обзор материала:\n\n{material[:800]}...",
            "questions": questions,
        }

