from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


# Путь к локальному файлу базы данных SQLite
DB_PATH = Path(os.getenv("STUDYBOT_AI_DB", "data/studybot_ai.db"))


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    """
    Преобразует кортеж результатов SQL-запроса в ассоциативный словарь (словарь ключ-значение),
    где ключами являются названия колонок таблицы.
    """
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """
    Контекстный менеджер для управления соединениями с СУБД SQLite.
    - Автоматически создает папку базы данных, если она отсутствует.
    - Принудительно включает поддержку ограничений внешних ключей (PRAGMA foreign_keys = ON).
    - При успешном выполнении автоматически фиксирует изменения (commit), при ошибке — закрывает соединение.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = _row_factory
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    """
    Инициализирует реляционную схему данных.
    Создает все необходимые таблицы, индексы и ограничения внешних ключей, если они не существуют.
    """
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                teacher_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
                UNIQUE(name, teacher_id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                full_name TEXT,
                group_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_id INTEGER NOT NULL,
                FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE,
                UNIQUE(name, group_id)
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_answer TEXT NOT NULL CHECK(correct_answer IN ('A', 'B', 'C', 'D')),
                FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                date TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS generated_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                source_material TEXT NOT NULL,
                generated_note TEXT NOT NULL,
                questions_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
            );
            """
        )


# === Функции для работы с преподавателями (Teacher Functions) ===

def create_teacher(email: str, password_hash: str) -> int:
    """
    Записывает учетную запись преподавателя в БД.
    Пароль сохраняется исключительно в захешированном виде.
    """
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO teachers (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.strip().lower(), password_hash, datetime.now().isoformat(timespec="seconds")),
        )
        return cursor.lastrowid


def get_teacher_by_email(email: str) -> dict | None:
    """
    Выбирает запись преподавателя по его электронной почте (для входа в админку).
    """
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM teachers WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()


def get_teacher_by_id(teacher_id: int) -> dict | None:
    """
    Выбирает запись преподавателя по его первичному ключу (для валидации куки/сессии).
    """
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM teachers WHERE id = ?",
            (teacher_id,),
        ).fetchone()


# === Функции для работы с группами (Group Functions) ===

def create_group(name: str, teacher_id: int) -> int:
    """
    Создает новую учебную группу, привязанную к аккаунту преподавателя.
    """
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO groups (name, teacher_id, created_at) VALUES (?, ?, ?)",
            (name.strip(), teacher_id, datetime.now().isoformat(timespec="seconds")),
        )
        return cursor.lastrowid


def list_groups(teacher_id: int) -> list[dict]:
    """
    Возвращает список всех групп, созданных данным преподавателем.
    """
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM groups WHERE teacher_id = ? ORDER BY name",
            (teacher_id,),
        ).fetchall()


def list_all_groups() -> list[dict]:
    """
    Возвращает список вообще всех групп в БД (используется студентами при регистрации в боте).
    """
    with get_connection() as connection:
        return connection.execute("SELECT * FROM groups ORDER BY name").fetchall()


def get_group(group_id: int) -> dict | None:
    """
    Выбирает информацию о группе по её первичному ключу.
    """
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM groups WHERE id = ?",
            (group_id,),
        ).fetchone()


# === Функции для работы со студентами (Student User Functions) ===

def get_or_create_user(telegram_id: int, username: str | None) -> dict:
    """
    Ищет запись студента по его Telegram ID. 
    Если студент не найден — создает новую запись с пустыми полями группы и ФИО.
    """
    with get_connection() as connection:
        user = connection.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if user:
            return user

        connection.execute(
            "INSERT INTO users (telegram_id, username, created_at) VALUES (?, ?, ?)",
            (telegram_id, username or "Без username", datetime.now().isoformat(timespec="seconds")),
        )
        return connection.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()


def update_user_group_and_name(telegram_id: int, group_id: int, full_name: str) -> None:
    """
    Сохраняет выбор учебной группы и ФИО студента при прохождении регистрации в Telegram-боте.
    """
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET group_id = ?, full_name = ? WHERE telegram_id = ?",
            (group_id, full_name.strip(), telegram_id),
        )


def clear_user_group(telegram_id: int) -> None:
    """
    Сбрасывает привязку студента к группе и его имя (выход из группы или сброс при удалении группы).
    """
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET group_id = NULL, full_name = NULL WHERE telegram_id = ?",
            (telegram_id,),
        )



# === Функции для работы с предметами (Subject Functions) ===

def list_subjects(group_id: int | None = None) -> list[dict]:
    """
    Возвращает список предметов. Если передан group_id, фильтрует по учебной группе.
    """
    query = "SELECT * FROM subjects"
    params = []
    if group_id is not None:
        query += " WHERE group_id = ?"
        params.append(group_id)
    query += " ORDER BY name"
    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def get_subject(subject_id: int) -> dict | None:
    """
    Выбирает предмет по его уникальному ID.
    """
    with get_connection() as connection:
        return connection.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()


def add_subject(name: str, group_id: int) -> None:
    """
    Добавляет новый предмет в базу данных с привязкой к конкретной группе.
    Игнорирует добавление, если предмет с таким именем в группе уже существует.
    """
    with get_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO subjects (name, group_id) VALUES (?, ?)",
            (name.strip(), group_id),
        )


# === Функции для работы с вопросами (Question Functions) ===

def list_questions(subject_id: int | None = None, group_id: int | None = None, limit: int | None = None) -> list[dict]:
    """
    Выбирает список тестовых вопросов. Поддерживает фильтрацию по предмету, группе и лимит записей.
    """
    query = """
        SELECT questions.*, subjects.name AS subject_name
        FROM questions
        JOIN subjects ON subjects.id = questions.subject_id
    """
    conditions = []
    params = []

    if subject_id is not None:
        conditions.append("questions.subject_id = ?")
        params.append(subject_id)
    if group_id is not None:
        conditions.append("subjects.group_id = ?")
        params.append(group_id)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY questions.id"

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def add_question(
    subject_id: int,
    question: str,
    option_a: str,
    option_b: str,
    option_c: str,
    option_d: str,
    correct_answer: str,
) -> None:
    """
    Сохраняет новый сгенерированный ИИ вопрос с 4 вариантами ответов и указанием верного в БД.
    """
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO questions (
                subject_id, question, option_a, option_b, option_c, option_d, correct_answer
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject_id,
                question.strip(),
                option_a.strip(),
                option_b.strip(),
                option_c.strip(),
                option_d.strip(),
                correct_answer.strip().upper(),
            ),
        )


# === Функции для работы с конспектами (Notes Functions) ===

def list_notes(subject_id: int | None = None, group_id: int | None = None) -> list[dict]:
    """
    Выбирает конспекты лекций для предмета или группы, сортируя по новизне.
    """
    query = """
        SELECT notes.*, subjects.name AS subject_name
        FROM notes
        JOIN subjects ON subjects.id = notes.subject_id
    """
    conditions = []
    params = []

    if subject_id is not None:
        conditions.append("notes.subject_id = ?")
        params.append(subject_id)
    if group_id is not None:
        conditions.append("subjects.group_id = ?")
        params.append(group_id)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY notes.id DESC"

    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def add_note(subject_id: int, title: str, content: str) -> None:
    """
    Добавляет сгенерированный конспект лекции в БД.
    """
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO notes (subject_id, title, content) VALUES (?, ?, ?)",
            (subject_id, title.strip(), content.strip()),
        )


# === Функции результатов и статистики (Results / Stats Functions) ===

def save_result(telegram_id: int, subject_id: int, score: int, total_questions: int) -> None:
    """
    Сохраняет результаты тестирования студента.
    """
    with get_connection() as connection:
        user = connection.execute(
            "SELECT id FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not user:
            return

        connection.execute(
            """
            INSERT INTO results (user_id, subject_id, score, total_questions, date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user["id"], subject_id, score, total_questions, datetime.now().isoformat(timespec="seconds")),
        )


def get_user_stats(telegram_id: int) -> dict:
    """
    Агрегирует статистику тестов конкретного студента по его текущей группе.
    Возвращает количество попыток, средний и лучший процент прохождения.
    """
    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, group_id FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not user or not user["group_id"]:
            return {"total_tests": 0, "average_percent": 0, "best_percent": 0}

        rows = connection.execute(
            """
            SELECT results.score, results.total_questions 
            FROM results 
            JOIN subjects ON subjects.id = results.subject_id
            WHERE results.user_id = ? AND subjects.group_id = ?
            """,
            (user["id"], user["group_id"]),
        ).fetchall()

    if not rows:
        return {"total_tests": 0, "average_percent": 0, "best_percent": 0}

    percents = [round(row["score"] / row["total_questions"] * 100) for row in rows]
    return {
        "total_tests": len(rows),
        "average_percent": round(sum(percents) / len(percents)),
        "best_percent": max(percents),
    }


# === Функции для сводки дашборда (Dashboard Counts) ===

def dashboard_counts(group_id: int | None = None) -> dict:
    """
    Считает количество сущностей в рамках группы для отображения на панелях статистики.
    """
    if group_id is None:
        return {"subjects": 0, "questions": 0, "notes": 0, "users": 0, "results": 0, "generated_tests": 0}

    with get_connection() as connection:
        return {
            "subjects": connection.execute("SELECT COUNT(*) AS count FROM subjects WHERE group_id = ?", (group_id,)).fetchone()["count"],
            "questions": connection.execute(
                """
                SELECT COUNT(*) AS count 
                FROM questions 
                JOIN subjects ON subjects.id = questions.subject_id 
                WHERE subjects.group_id = ?
                """, (group_id,)).fetchone()["count"],
            "notes": connection.execute(
                """
                SELECT COUNT(*) AS count 
                FROM notes 
                JOIN subjects ON subjects.id = notes.subject_id 
                WHERE subjects.group_id = ?
                """, (group_id,)).fetchone()["count"],
            "users": connection.execute("SELECT COUNT(*) AS count FROM users WHERE group_id = ?", (group_id,)).fetchone()["count"],
            "results": connection.execute(
                """
                SELECT COUNT(*) AS count 
                FROM results 
                JOIN subjects ON subjects.id = results.subject_id 
                WHERE subjects.group_id = ?
                """, (group_id,)).fetchone()["count"],
            "generated_tests": connection.execute(
                """
                SELECT COUNT(*) AS count 
                FROM generated_tests 
                JOIN subjects ON subjects.id = generated_tests.subject_id 
                WHERE subjects.group_id = ?
                """, (group_id,)).fetchone()["count"],
        }


# === Функции логов генераций ИИ (Generated Tests) ===

def save_generated_test(
    subject_id: int,
    title: str,
    source_material: str,
    generated_note: str,
    questions_json: str,
) -> int:
    """
    Сохраняет историю генерации теста ИИ (для последующего просмотра преподавателем).
    """
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO generated_tests (
                subject_id, title, source_material, generated_note, questions_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                subject_id,
                title.strip(),
                source_material.strip(),
                generated_note.strip(),
                questions_json,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cursor.lastrowid


def list_generated_tests(group_id: int | None = None) -> list[dict]:
    """
    Возвращает список всех когда-либо сгенерированных ИИ тестов для группы.
    """
    query = """
        SELECT generated_tests.*, subjects.name AS subject_name
        FROM generated_tests
        JOIN subjects ON subjects.id = generated_tests.subject_id
    """
    params = []
    if group_id is not None:
        query += " WHERE subjects.group_id = ?"
        params.append(group_id)
    query += " ORDER BY generated_tests.id DESC"

    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def get_generated_test(generated_test_id: int) -> dict | None:
    """
    Возвращает детальные данные генерации теста ИИ по ID.
    """
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT generated_tests.*, subjects.name AS subject_name
            FROM generated_tests
            JOIN subjects ON subjects.id = generated_tests.subject_id
            WHERE generated_tests.id = ?
            """,
            (generated_test_id,),
        ).fetchone()


# === Функции удаления (Delete Handlers) ===

def delete_generated_test(test_id: int) -> None:
    """Удаляет запись лога генерации теста."""
    with get_connection() as connection:
        connection.execute("DELETE FROM generated_tests WHERE id = ?", (test_id,))


def delete_question(question_id: int) -> None:
    """Удаляет тестовый вопрос."""
    with get_connection() as connection:
        connection.execute("DELETE FROM questions WHERE id = ?", (question_id,))


def delete_subject(subject_id: int) -> None:
    """Удаляет предмет. Включает каскадное удаление конспектов/тестов на уровне СУБД."""
    with get_connection() as connection:
        connection.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))


def delete_group(group_id: int) -> None:
    """Удаляет учебную группу. Включает каскадные удаления и сбросы связей студентов."""
    with get_connection() as connection:
        connection.execute("DELETE FROM groups WHERE id = ?", (group_id,))


def list_group_users(group_id: int) -> list[dict]:
    """
    Возвращает список студентов группы для вывода на веб-панель преподавателя.
    """
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE group_id = ? ORDER BY full_name",
            (group_id,),
        ).fetchall()

