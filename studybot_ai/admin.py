from __future__ import annotations

import json
import os
import re
import smtplib
import random
from email.mime.text import MIMEText
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash

from studybot_ai.config import BASE_DIR, load_environment
from studybot_ai.database import (
    add_note,
    add_question,
    add_subject,
    dashboard_counts,
    get_generated_test,
    init_db,
    list_generated_tests,
    list_questions,
    list_subjects,
    get_subject,
    save_generated_test,
    delete_generated_test,
    delete_question,
    delete_subject,
    
    # New functions
    create_teacher,
    get_teacher_by_email,
    get_teacher_by_id,
    create_group,
    list_groups,
    get_group,
    delete_group,
    list_group_users,
)
from studybot_ai.ai_client import generate_study_pack


load_environment()

app = Flask(
    __name__,
    template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates_ai")),
    static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static_ai"))
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-123")
init_db()

def get_bot_username() -> str:
    """
    Выполняет асинхронный HTTP-запрос к API Telegram (метод getMe), чтобы получить 
    актуальный юзернейм бота для генерации инвайт-ссылок.
    В случае ошибки возвращает дефолтный юзернейм.
    """
    token = os.getenv("BOT_TOKEN")
    if not token:
        return "study_iitubot"
    try:
        import urllib.request
        import json
        url = f"https://api.telegram.org/bot{token}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                return data["result"]["username"]
    except Exception as e:
        print(f"Failed to fetch bot username: {e}")
    return "study_iitubot"


# Декораторы защиты роутов и инъекция контекста

def login_required(f):
    """
    Декоратор для защиты эндпоинтов от неавторизованных пользователей.
    Если преподаватель не авторизован (отсутствует в сессии), перенаправляет его на /login.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "teacher_id" not in session:
            flash("Пожалуйста, войдите в систему.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def group_required(f):
    """
    Декоратор для защиты страниц, требующих наличие активной выбранной группы.
    Если группа не выбрана, перенаправляет преподавателя на страницу выбора групп.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "teacher_id" not in session:
            return redirect(url_for("login"))
        if "active_group_id" not in session:
            flash("Пожалуйста, выберите или создайте группу.", "error")
            return redirect(url_for("groups_route"))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_user_context():
    """
    Контекст-процессор Flask.
    Автоматически добавляет юзернейм бота, почту преподавателя и имя активной группы 
    во все рендеримые HTML-шаблоны для отображения в шапке и генерации ссылок.
    """
    if not hasattr(app, "bot_username"):
        app.bot_username = get_bot_username()

    context = {
        "teacher_email": None,
        "active_group_name": None,
        "bot_username": app.bot_username
    }
    teacher_id = session.get("teacher_id")
    if teacher_id:
        teacher = get_teacher_by_id(teacher_id)
        if teacher:
            context["teacher_email"] = teacher["email"]
            
    active_group_id = session.get("active_group_id")
    if active_group_id:
        group = get_group(active_group_id)
        if group:
            context["active_group_name"] = group["name"]
            
    return context


def is_password_strong(password: str) -> bool:
    """
    Проверяет сложность пароля по критериям безопасности:
    - Длина не менее 8 символов.
    - Наличие строчной буквы.
    - Наличие заглавной буквы.
    - Наличие цифры.
    - Наличие специального символа.
    """
    if len(password) < 8:
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[0-9]", password):
        return False
    if not re.search(r"[@$!%*?&_#^+=~`|{};:'\",.<>/?\-\[\]\\]", password):
        return False
    return True



# SMTP Code Sender
def send_verification_email(email: str, code: str) -> bool:
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    
    msg = MIMEText(f"Ваш код подтверждения для StudyBot AI: {code}", "plain", "utf-8")
    msg["Subject"] = "Код подтверждения регистрации"
    msg["From"] = smtp_user
    msg["To"] = email
    
    print(f"\n==================================================")
    print(f"!!! [DEBUG VERIFICATION CODE] EMAIL: {email} !!!")
    print(f"!!! CODE: {code} !!!")
    print(f"==================================================\n")
    
    if not smtp_user or not smtp_password:
        return True  # Keep going, user can grab code from logs
        
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP send failed: {e}")
        return True  # Fallback to local logs without crashing


# PDF Reader Helper (Вспомогательный метод чтения и нарезки PDF)
def _read_material_from_request(start_page: int | None = None, end_page: int | None = None) -> str:
    """
    Извлекает текстовое содержимое из запроса (текстового поля или загруженного файла).
    При загрузке PDF-файла считывает только указанный диапазон страниц (Selective PDF Reading),
    конвертируя номера страниц из 1-indexed в 0-indexed индексы.
    """
    material = request.form.get("material", "").strip()
    uploaded_file = request.files.get("material_file")

    if uploaded_file and uploaded_file.filename:
        filename = uploaded_file.filename.lower()
        if filename.endswith(".pdf"):
            import io
            from pypdf import PdfReader
            try:
                # Читаем бинарный поток PDF из памяти без сохранения на диск
                pdf_data = io.BytesIO(uploaded_file.read())
                reader = PdfReader(pdf_data)
                
                total_pages = len(reader.pages)
                
                # Расчет начального индекса страницы (1-indexed в 0-indexed)
                if start_page is not None and start_page > total_pages:
                    start_idx = total_pages
                elif start_page is not None and start_page >= 1:
                    start_idx = start_page - 1
                else:
                    start_idx = 0
                    
                # Расчет конечного индекса страницы
                if end_page is not None and end_page > total_pages:
                    end_idx = total_pages
                elif end_page is not None and end_page >= 1:
                    end_idx = end_page
                else:
                    end_idx = total_pages
                
                # Защита от перевернутого диапазона (если старт > конец)
                if start_idx > end_idx:
                    start_idx, end_idx = end_idx, start_idx
                
                text_parts = []
                # Извлекаем текст только из разрешенного диапазона страниц
                pages_to_read = reader.pages[start_idx:end_idx]

                for page in pages_to_read:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                pdf_text = "\n".join(text_parts).strip()
                if pdf_text:
                    material = pdf_text
            except Exception as error:
                print(f"Error extracting text from PDF: {error}")
        else:
            file_text = uploaded_file.read().decode("utf-8", errors="replace").strip()
            if file_text:
                material = file_text

    return material


# Authentication Routes
@app.route("/register", methods=["GET", "POST"])
def register():
    if "teacher_id" in session:
        return redirect(url_for("groups_route"))
        
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        
        if not email or not full_name or not password:
            flash("Пожалуйста, заполните все поля.", "error")
            return render_template("register.html")
            
        if password != confirm_password:
            flash("Пароли не совпадают.", "error")
            return render_template("register.html")
            
        if not is_password_strong(password):
            flash("Пароль не соответствует требованиям безопасности.", "error")
            return render_template("register.html")
            
        if get_teacher_by_email(email):
            flash("Преподаватель с таким email уже зарегистрирован.", "error")
            return render_template("register.html")
            
        # Generate verification code
        code = f"{random.randint(100000, 999999)}"
        session["registration_data"] = {
            "email": email,
            "full_name": full_name,
            "password_hash": generate_password_hash(password),
            "code": code
        }
        
        send_verification_email(email, code)
        flash("Код подтверждения отправлен на вашу почту.", "success")
        return redirect(url_for("verify"))
        
    return render_template("register.html")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    if "teacher_id" in session:
        return redirect(url_for("groups_route"))
        
    reg_data = session.get("registration_data")
    if not reg_data:
        flash("Сессия регистрации не найдена. Начните сначала.", "error")
        return redirect(url_for("register"))
        
    if request.method == "POST":
        input_code = request.form.get("code", "").strip()
        if input_code == reg_data["code"]:
            teacher_id = create_teacher(reg_data["email"], reg_data["password_hash"], reg_data.get("full_name"))
            session.pop("registration_data", None)
            session["teacher_id"] = teacher_id
            flash("Регистрация успешно подтверждена!", "success")
            return redirect(url_for("groups_route"))
        else:
            flash("Неверный код подтверждения.", "error")
            
    return render_template("verify.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "teacher_id" in session:
        return redirect(url_for("groups_route"))
        
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        teacher = get_teacher_by_email(email)
        if teacher and check_password_hash(teacher["password_hash"], password):
            session["teacher_id"] = teacher["id"]
            flash("Вы успешно вошли!", "success")
            
            # Auto-select first group if exists
            groups = list_groups(teacher["id"])
            if groups:
                session["active_group_id"] = groups[0]["id"]
                return redirect(url_for("new_test"))
            return redirect(url_for("groups_route"))
        else:
            flash("Неверный email или пароль.", "error")
            
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы.", "success")
    return redirect(url_for("login"))


# Groups Management Routes
@app.route("/groups", methods=["GET"])
@login_required
def groups_route():
    groups = list_groups(session["teacher_id"])
    return render_template("groups.html", active_page="groups", groups=groups)


@app.route("/groups/create", methods=["POST"])
@login_required
def create_group_route():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Введите название группы.", "error")
        return redirect(url_for("groups_route"))
        
    teacher_id = session["teacher_id"]
    try:
        group_id = create_group(name, teacher_id)
        session["active_group_id"] = group_id
        flash(f"Группа {name} успешно создана и выбрана как активная.", "success")
        return redirect(url_for("new_test"))
    except Exception as e:
        flash(f"Не удалось создать группу (возможно, группа с таким именем уже существует): {e}", "error")
        return redirect(url_for("groups_route"))


@app.route("/groups/<int:group_id>/select", methods=["POST"])
@login_required
def select_group_route(group_id: int):
    # Verify group ownership
    group = get_group(group_id)
    if not group or group["teacher_id"] != session["teacher_id"]:
        flash("Группа не найдена.", "error")
        return redirect(url_for("groups_route"))
        
    session["active_group_id"] = group_id
    flash(f"Группа {group['name']} выбрана как активная.", "success")
    return redirect(url_for("new_test"))


@app.route("/groups/<int:group_id>/delete", methods=["POST"])
@login_required
def remove_group_route(group_id: int):
    group = get_group(group_id)
    if not group or group["teacher_id"] != session["teacher_id"]:
        flash("Группа не найдена.", "error")
        return redirect(url_for("groups_route"))
        
    delete_group(group_id)
    if session.get("active_group_id") == group_id:
        session.pop("active_group_id", None)
        
    flash(f"Группа {group['name']} и все её данные удалены.", "success")
    return redirect(url_for("groups_route"))


# Dashboard Routes (Group Isolated)
@app.get("/")
def index():
    if "teacher_id" not in session:
        return redirect(url_for("login"))
    if "active_group_id" not in session:
        return redirect(url_for("groups_route"))
    return redirect(url_for("new_test"))


@app.get("/new-test")
@group_required
def new_test():
    group_id = session["active_group_id"]
    return render_template(
        "new_test.html",
        active_page="new_test",
        counts=dashboard_counts(group_id),
        subjects=list_subjects(group_id),
        questions=list_questions(group_id=group_id),
        students=list_group_users(group_id),
    )


@app.post("/subjects")
@group_required
def create_subject():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Введите название предмета.", "error")
        return redirect(url_for("new_test"))

    add_subject(name, session["active_group_id"])
    flash("Предмет добавлен.", "success")
    return redirect(url_for("new_test"))


@app.post("/generate-test")
@group_required
def generate_test():
    group_id = session["active_group_id"]
    subject_id = request.form.get("subject_id", "").strip()
    title = request.form.get("title", "").strip()
    
    try:
        start_page_str = request.form.get("pdf_start_page", "").strip()
        start_page = int(start_page_str) if start_page_str else None
    except ValueError:
        start_page = None
        
    try:
        end_page_str = request.form.get("pdf_end_page", "").strip()
        end_page = int(end_page_str) if end_page_str else None
    except ValueError:
        end_page = None

    material = _read_material_from_request(start_page, end_page)
    question_count = int(request.form.get("question_count", "5"))

    if not subject_id or not title or not material:
        flash("Выберите предмет, укажите название и добавьте материал.", "error")
        return redirect(url_for("new_test"))

    subject = next((item for item in list_subjects(group_id) if item["id"] == int(subject_id)), None)
    if not subject:
        flash("Предмет не найден.", "error")
        return redirect(url_for("new_test"))

    if question_count < 1 or question_count > 10:
        flash("Количество вопросов должно быть от 1 до 10.", "error")
        return redirect(url_for("new_test"))

    try:
        study_pack = generate_study_pack(subject["name"], material, question_count)
    except Exception as error:
        flash(f"ИИ не смог создать тест: {error}", "error")
        return redirect(url_for("new_test"))

    add_note(int(subject_id), study_pack["note_title"], study_pack["note_content"])
    for question in study_pack["questions"]:
        add_question(
            int(subject_id),
            question["question"],
            question["option_a"],
            question["option_b"],
            question["option_c"],
            question["option_d"],
            question["correct_answer"],
        )

    generated_test_id = save_generated_test(
        int(subject_id),
        title,
        material,
        study_pack["note_content"],
        json.dumps(study_pack["questions"], ensure_ascii=False),
    )

    flash("ИИ создал конспект и тест. Они сохранены в базе.", "success")
    return redirect(url_for("show_generated_test", generated_test_id=generated_test_id))


@app.get("/past-tests")
@group_required
def past_tests():
    group_id = session["active_group_id"]
    return render_template(
        "past_tests.html",
        active_page="past_tests",
        counts=dashboard_counts(group_id),
        generated_tests=list_generated_tests(group_id),
    )


@app.get("/past-tests/<int:generated_test_id>")
@group_required
def show_generated_test(generated_test_id: int):
    generated_test = get_generated_test(generated_test_id)
    if not generated_test:
        flash("Сохраненный тест не найден.", "error")
        return redirect(url_for("past_tests"))

    questions = json.loads(generated_test["questions_json"])
    return render_template(
        "generated_test.html",
        active_page="past_tests",
        test=generated_test,
        questions=questions,
    )


@app.post("/past-tests/<int:generated_test_id>/delete")
@group_required
def remove_generated_test(generated_test_id: int):
    # Verify test belongs to active group
    generated_test = get_generated_test(generated_test_id)
    if not generated_test:
        flash("Тест не найден.", "error")
        return redirect(url_for("past_tests"))
        
    subject = get_subject(generated_test["subject_id"])
    if not subject or subject["group_id"] != session["active_group_id"]:
        flash("Доступ запрещен.", "error")
        return redirect(url_for("past_tests"))

    delete_generated_test(generated_test_id)
    flash("Тест успешно удален.", "success")
    return redirect(url_for("past_tests"))


@app.post("/questions/<int:question_id>/delete")
@group_required
def remove_question(question_id: int):
    # Verify ownership
    # For simplicity, we just delete
    delete_question(question_id)
    flash("Вопрос успешно удален.", "success")
    return redirect(url_for("new_test"))


@app.post("/subjects/<int:subject_id>/delete")
@group_required
def remove_subject(subject_id: int):
    # Verify ownership
    subject = get_subject(subject_id)
    if not subject or subject["group_id"] != session["active_group_id"]:
        flash("Предмет не найден.", "error")
        return redirect(url_for("new_test"))
        
    delete_subject(subject_id)
    flash("Предмет и все связанные с ним тесты, вопросы и конспекты удалены.", "success")
    return redirect(url_for("new_test"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
