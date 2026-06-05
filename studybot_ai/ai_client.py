from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from studybot_ai.config import get_env, get_required_env


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("Gemini did not return JSON.")
        return json.loads(match.group(0))


def _validate_pack(data: dict) -> dict:
    if not isinstance(data.get("note_title"), str) or not data["note_title"].strip():
        raise ValueError("Gemini response does not contain note_title.")

    if not isinstance(data.get("note_content"), str) or not data["note_content"].strip():
        raise ValueError("Gemini response does not contain note_content.")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Gemini response does not contain questions.")

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

    for question in normalized_questions:
        if not all(question.values()):
            raise ValueError("Gemini returned an incomplete question.")

    return {
        "note_title": data["note_title"].strip(),
        "note_content": data["note_content"].strip(),
        "questions": normalized_questions,
    }


def generate_study_pack(subject_name: str, material: str, question_count: int) -> dict:
    api_key = get_env("GROQ_API_KEY", "").strip()
    model = get_env("GROQ_MODEL", "llama-3.3-70b-versatile")

    use_mock = False
    if not api_key or not api_key.startswith("gsk_"):
        use_mock = True

    if not use_mock:
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
            "response_format": {
                "type": "json_object"
            },
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
            with urllib.request.urlopen(request, timeout=60) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            text = response_data["choices"][0]["message"]["content"]
            return _validate_pack(_extract_json(text))
        except Exception as error:
            print(f"Groq API call failed, falling back to mock generator: {error}")
            use_mock = True

    if use_mock:
        import random
        # Heuristic sentences from material
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
