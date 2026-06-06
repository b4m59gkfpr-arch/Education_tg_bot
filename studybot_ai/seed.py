from werkzeug.security import generate_password_hash
from studybot_ai.database import (
    add_note,
    add_question,
    add_subject,
    init_db,
    list_subjects,
    create_teacher,
    create_group,
    get_teacher_by_email,
    list_groups,
)


def subject_id_by_name(name: str, group_id: int) -> int:
    """
    Вспомогательный метод для поиска ID предмета по его названию в рамках конкретной группы.
    """
    for subject in list_subjects(group_id):
        if subject["name"] == name:
            return subject["id"]
    raise RuntimeError(f"Subject not found: {name}")


def main() -> None:
    """
    Основной скрипт наполнения БД демонстрационными данными.
    Создает преподавателя, тестовую группу 2509 и добавляет базовые предметы/тесты.
    """
    init_db()

    # 1. Создание демонстрационного преподавателя
    email = "teacher@test.com"
    teacher = get_teacher_by_email(email)
    if not teacher:
        # Пароль соответствует требованиям сложности (Password123!)
        teacher_id = create_teacher(email, generate_password_hash("Password123!"), "Иван Иванов")
        print(f"Teacher created: {email} (Password: Password123!)")
    else:
        teacher_id = teacher["id"]

    # 2. Создание демонстрационной группы
    groups = list_groups(teacher_id)
    if not groups:
        group_id = create_group("2509", teacher_id)
        print("Demo group '2509' created.")
    else:
        group_id = groups[0]["id"]

    # 3. Добавление предметов с привязкой к группе
    existing_subjects = {s["name"] for s in list_subjects(group_id)}
    for name in ["ООП", "Базы данных", "Алгоритмы"]:
        if name not in existing_subjects:
            add_subject(name, group_id)

    oop_id = subject_id_by_name("ООП", group_id)
    db_id = subject_id_by_name("Базы данных", group_id)
    algo_id = subject_id_by_name("Алгоритмы", group_id)

    # 4. Добавление тестовых вопросов
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

    # 5. Добавление демонстрационного конспекта лекции
    add_note(
        oop_id,
        "Основы ООП",
        "Инкапсуляция — сокрытие внутренней реализации объекта. Наследование — создание нового класса на основе существующего.",
    )

    print("Demo data successfully populated in SQLite database.")


if __name__ == "__main__":
    main()

