from studybot_ai.database import add_note, add_question, add_subject, init_db, list_subjects


def subject_id_by_name(name: str) -> int:
    for subject in list_subjects():
        if subject["name"] == name:
            return subject["id"]
    raise RuntimeError(f"Subject not found: {name}")


def main() -> None:
    init_db()

    for name in ["ООП", "Базы данных", "Алгоритмы"]:
        add_subject(name)

    oop_id = subject_id_by_name("ООП")
    db_id = subject_id_by_name("Базы данных")
    algo_id = subject_id_by_name("Алгоритмы")

    add_question(
        oop_id,
        "Что такое инкапсуляция?",
        "Создание новых классов на основе существующих",
        "Сокрытие внутренней реализации объекта",
        "Один интерфейс для разных типов",
        "Разделение программы на файлы",
        "B",
    )
    add_question(
        db_id,
        "Что означает SQL?",
        "Simple Query Language",
        "Structured Query Language",
        "System Queue Logic",
        "Stored Question List",
        "B",
    )
    add_question(
        algo_id,
        "Какая сложность у бинарного поиска?",
        "O(n)",
        "O(n^2)",
        "O(log n)",
        "O(1)",
        "C",
    )

    add_note(
        oop_id,
        "Основы ООП",
        "Инкапсуляция — сокрытие внутренней реализации объекта. Наследование — создание нового класса на основе существующего.",
    )

    print("Gemini demo data added.")


if __name__ == "__main__":
    main()
