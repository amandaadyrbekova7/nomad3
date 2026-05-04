import os
import sqlite3
import secrets
import io
import base64
from datetime import datetime
from functools import wraps

import qrcode
from flask import (
    Flask, g, render_template, request, redirect, url_for,
    session, flash, abort, jsonify, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash

# ----------------------------------------------------------------------------
# App setup
# ----------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "festkg.db")

app = Flask(__name__)
app.secret_key = os.environ.get("FESTKG_SECRET", secrets.token_hex(32))

# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'user', -- 'user' | 'business'
    phone TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT,
    city TEXT,
    phone TEXT,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS festivals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    duration_days INTEGER NOT NULL DEFAULT 1,
    duration_label TEXT,
    categories TEXT NOT NULL,
    description TEXT,
    cover_emoji TEXT NOT NULL DEFAULT '🎪'
);

CREATE TABLE IF NOT EXISTS tariffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    festival_id INTEGER NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    seats_left INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS schedule_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    festival_id INTEGER NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
    day_label TEXT NOT NULL,
    day_index INTEGER NOT NULL DEFAULT 1,
    time TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    stage TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    festival_id INTEGER NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
    tariff_id INTEGER NOT NULL REFERENCES tariffs(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1,
    total_price INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'paid',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    festival_id INTEGER NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
    booth_type TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# ----------------------------------------------------------------------------
# Seed data
# ----------------------------------------------------------------------------
FESTIVALS_SEED = [
    {
        "slug": "bishkek-food-fest",
        "name": "Bishkek Food Fest",
        "city": "Бишкек",
        "start_date": "2026-06-12",
        "end_date": "2026-06-13",
        "duration_days": 2,
        "duration_label": "12–13 июня · 2 дня",
        "categories": "Гастро,Семья",
        "description": "Главный гастрономический фестиваль столицы: национальная кухня, шеф-повара, стрит-фуд, дегустации.",
        "cover_emoji": "🍜",
        "tariffs": [
            ("Вход", 0, "Свободный вход на территорию", 5000),
            ("Дегустация шефов", 1500, "Сет из 6 авторских блюд", 200),
            ("VIP-зона", 4500, "Лаунж, напитки и встреча с шефами", 80),
        ],
        "schedule": [
            ("День 1 · 12 июня", 1, "11:00", "Открытие фестиваля", "Парад шефов и приветствие", "Главная сцена"),
            ("День 1 · 12 июня", 1, "12:30", "Бешбармак-челлендж", "Соревнование по приготовлению", "Зона Гастро"),
            ("День 1 · 12 июня", 1, "15:00", "Мастер-класс: лагман", "Шеф Алмаз Турдубеков", "Кулинарная студия"),
            ("День 1 · 12 июня", 1, "18:00", "Дегустационный сет", "6 блюд от 6 шефов", "Гастро-холл"),
            ("День 1 · 12 июня", 1, "20:30", "Музыкальный вечер", "Live-band и DJ-сет", "Главная сцена"),
            ("День 2 · 13 июня", 2, "11:00", "Семейный бранч", "Завтраки народов мира", "Семейная зона"),
            ("День 2 · 13 июня", 2, "13:00", "Битва бариста", "Чемпионат по латте-арту", "Кофе-корт"),
            ("День 2 · 13 июня", 2, "16:00", "Десерт-баттл", "Кондитеры Бишкека", "Гастро-холл"),
            ("День 2 · 13 июня", 2, "19:00", "Закрытие и награждение", "Гала-ужин и розыгрыш", "Главная сцена"),
        ],
    },
    {
        "slug": "nomad-music-festival",
        "name": "Nomad Music Festival",
        "city": "Чолпон-Ата",
        "start_date": "2026-07-18",
        "end_date": "2026-07-20",
        "duration_days": 3,
        "duration_label": "18–20 июля · 3 дня",
        "categories": "Музыка,Культура",
        "description": "Этно-электроника на берегу Иссык-Куля: комуз, варганы, диджеи и опен-эйр под звёздами.",
        "cover_emoji": "🎵",
        "tariffs": [
            ("1 день", 1200, "Любой день фестиваля", 1500),
            ("Абонемент 3 дня", 3000, "Полный доступ", 800),
            ("VIP-кемпинг", 8500, "Палатка + питание + бэкстейдж", 120),
        ],
        "schedule": [
            ("День 1 · 18 июля", 1, "16:00", "Открытие · Юрточный городок", "Заселение и регистрация", "Кемпинг"),
            ("День 1 · 18 июля", 1, "18:00", "Этно-сейшн", "Комузисты Кыргызстана", "Малая сцена"),
            ("День 1 · 18 июля", 1, "21:00", "Headliner: Ordo Sakhna", "Этно-фолк концерт", "Главная сцена"),
            ("День 1 · 18 июля", 1, "23:30", "DJ-сет на пляже", "Электроника до утра", "Beach Stage"),
            ("День 2 · 19 июля", 2, "10:00", "Йога на рассвете", "Открытое занятие", "Пляж"),
            ("День 2 · 19 июля", 2, "14:00", "Мастер-класс: варган", "Школа этно-инструментов", "Шатёр культуры"),
            ("День 2 · 19 июля", 2, "20:00", "Headliner: Nomad Beat", "Этно-электроника", "Главная сцена"),
            ("День 2 · 19 июля", 2, "00:00", "Звёздная вечеринка", "Open-air rave", "Beach Stage"),
            ("День 3 · 20 июля", 3, "12:00", "Ярмарка ремёсел", "Войлок, серебро, кожа", "Аллея мастеров"),
            ("День 3 · 20 июля", 3, "18:00", "Гала-концерт", "Все артисты вместе", "Главная сцена"),
            ("День 3 · 20 июля", 3, "22:00", "Закрытие: фаер-шоу", "Прощальная церемония", "Пляж"),
        ],
    },
    {
        "slug": "osh-art-street",
        "name": "Osh Art Street",
        "city": "Ош",
        "start_date": "2026-05-22",
        "end_date": "2026-05-24",
        "duration_days": 3,
        "duration_label": "22–24 мая · 3 дня",
        "categories": "Искусство,Культура",
        "description": "Уличное искусство Оша: муралы, инсталляции, перформансы и живая роспись.",
        "cover_emoji": "🎨",
        "tariffs": [
            ("Вход", 0, "Свободный вход", 8000),
            ("Тур с куратором", 800, "Экскурсия 2 часа", 150),
            ("Воркшоп художника", 2200, "Создай свой постер", 60),
        ],
        "schedule": [
            ("День 1 · 22 мая", 1, "10:00", "Открытие галереи под небом", "Презентация проекта", "Площадь Ала-Тоо"),
            ("День 1 · 22 мая", 1, "12:00", "Создание мурала", "Live-painting от 5 художников", "ул. Курманжан Датка"),
            ("День 1 · 22 мая", 1, "16:00", "Перформанс «Шёлковый путь»", "Танец и проекция", "Центр города"),
            ("День 1 · 22 мая", 1, "19:00", "Кинопоказ под открытым небом", "Документалка о стрит-арте", "Парк Навои"),
            ("День 2 · 23 мая", 2, "11:00", "Воркшоп: трафарет", "Для всех желающих", "Арт-зона"),
            ("День 2 · 23 мая", 2, "14:00", "Дискуссия художников", "Будущее уличного искусства", "Лекторий"),
            ("День 2 · 23 мая", 2, "18:00", "Аукцион работ", "Поддержка молодых авторов", "Галерея"),
            ("День 3 · 24 мая", 3, "12:00", "Семейный день", "Раскраски и квесты", "Парк Навои"),
            ("День 3 · 24 мая", 3, "17:00", "Финальный тур", "Все муралы фестиваля", "Старт у Ала-Тоо"),
            ("День 3 · 24 мая", 3, "20:00", "Закрытие · диджей-сет", "Прощальная вечеринка", "Главная сцена"),
        ],
    },
    {
        "slug": "kyrgyz-heritage-fair",
        "name": "Kyrgyz Heritage Fair",
        "city": "Бишкек",
        "start_date": "2026-08-08",
        "end_date": "2026-08-10",
        "duration_days": 3,
        "duration_label": "8–10 августа · 3 дня",
        "categories": "Культура,Семья",
        "description": "Ярмарка наследия: войлок, ювелирка, конные игры, эпос «Манас» и национальная кухня.",
        "cover_emoji": "🏺",
        "tariffs": [
            ("Семейный билет", 700, "До 4 человек", 1200),
            ("Взрослый", 300, "Один взрослый", 5000),
            ("Дети до 12", 0, "Бесплатно с родителем", 5000),
        ],
        "schedule": [
            ("День 1 · 8 августа", 1, "10:00", "Открытие · парад в национальных костюмах", "Шествие участников", "Центральная аллея"),
            ("День 1 · 8 августа", 1, "12:00", "Эпос «Манас»", "Выступление манасчи", "Юрта-театр"),
            ("День 1 · 8 августа", 1, "15:00", "Войлоковаляние", "Мастер-класс", "Зона ремёсел"),
            ("День 1 · 8 августа", 1, "18:00", "Конные игры: кок-бору", "Демонстрационный матч", "Ипподром"),
            ("День 2 · 9 августа", 2, "11:00", "Ювелирная мастерская", "Серебро вручную", "Зона ремёсел"),
            ("День 2 · 9 августа", 2, "14:00", "Дегустация: бешбармак", "Национальное блюдо", "Гастро-юрта"),
            ("День 2 · 9 августа", 2, "17:00", "Музыка комуза", "Концерт фольклорного ансамбля", "Главная сцена"),
            ("День 3 · 10 августа", 3, "12:00", "Детский день", "Игры и сказки", "Семейная зона"),
            ("День 3 · 10 августа", 3, "16:00", "Финальные конные игры", "Соревнование команд", "Ипподром"),
            ("День 3 · 10 августа", 3, "19:00", "Закрытие · гала-концерт", "Звёзды кыргызской эстрады", "Главная сцена"),
        ],
    },
    {
        "slug": "lake-song-kol-fest",
        "name": "Lake Song-Köl Fest",
        "city": "Сон-Куль",
        "start_date": "2026-07-25",
        "end_date": "2026-07-27",
        "duration_days": 3,
        "duration_label": "25–27 июля · 3 дня",
        "categories": "Эко,Спорт",
        "description": "Высокогорный фестиваль на озере Сон-Куль: треккинг, конные туры, юрты и звёздное небо.",
        "cover_emoji": "🏔️",
        "tariffs": [
            ("Дневной билет", 500, "Доступ на территорию", 800),
            ("Юрта на 2 ночи", 6500, "Питание включено", 60),
            ("Конный тур", 3500, "Прогулка 4 часа", 100),
        ],
        "schedule": [
            ("День 1 · 25 июля", 1, "12:00", "Заселение в юрты", "Встреча гостей", "Юрточный лагерь"),
            ("День 1 · 25 июля", 1, "15:00", "Треккинг к водопаду", "Лёгкий маршрут 5 км", "Берег озера"),
            ("День 1 · 25 июля", 1, "19:00", "Ужин у костра", "Национальная кухня", "Костровая зона"),
            ("День 1 · 25 июля", 1, "22:00", "Астро-наблюдение", "Млечный путь и планеты", "Обсерватория"),
            ("День 2 · 26 июля", 2, "08:00", "Конный тур", "Прогулка вокруг озера", "Конюшня"),
            ("День 2 · 26 июля", 2, "13:00", "Эко-лекция", "Биосфера Сон-Куля", "Лекторий"),
            ("День 2 · 26 июля", 2, "17:00", "Игры кочевников", "Стрельба из лука, тогуз коргол", "Игровая поляна"),
            ("День 2 · 26 июля", 2, "21:00", "Этно-концерт", "Живая музыка у костра", "Главная сцена"),
            ("День 3 · 27 июля", 3, "09:00", "Йога у воды", "Открытое занятие", "Берег"),
            ("День 3 · 27 июля", 3, "13:00", "Закрытие · обед", "Прощальный плов", "Гастро-зона"),
        ],
    },
    {
        "slug": "osh-cultural-week",
        "name": "Osh Cultural Week",
        "city": "Ош",
        "start_date": "2026-09-10",
        "end_date": "2026-09-16",
        "duration_days": 7,
        "duration_label": "10–16 сентября · 7 дней",
        "categories": "Культура,Музыка,Искусство",
        "description": "Неделя культуры в Оше: театры, выставки, концерты и кинопоказы по всему городу.",
        "cover_emoji": "🎭",
        "tariffs": [
            ("Дневной проход", 250, "На все события дня", 3000),
            ("Абонемент 7 дней", 1500, "Полный доступ к программе", 500),
            ("VIP-pass", 5500, "Лаунж + встречи с артистами", 80),
        ],
        "schedule": [
            ("День 1 · 10 сентября", 1, "18:00", "Церемония открытия", "Парад театров", "Центральная площадь"),
            ("День 2 · 11 сентября", 2, "19:00", "Спектакль «Манас»", "Государственный театр", "Театр им. Бабура"),
            ("День 3 · 12 сентября", 3, "16:00", "Выставка живописи", "Современные художники Оша", "Галерея"),
            ("День 4 · 13 сентября", 4, "20:00", "Симфонический концерт", "Камерный оркестр", "Филармония"),
            ("День 5 · 14 сентября", 5, "18:30", "Кинопоказ: ретроспектива", "Фильмы Боконбаева", "Кинотеатр Манас"),
            ("День 6 · 15 сентября", 6, "17:00", "Поэтический вечер", "Молодые поэты КР", "Литкафе"),
            ("День 7 · 16 сентября", 7, "20:00", "Гала-закрытие", "Все артисты + фейерверк", "Площадь Ала-Тоо"),
        ],
    },
]


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)

    # Migrations: add columns if missing
    cols = [r["name"] for r in db.execute("PRAGMA table_info(festivals)")]
    if "duration_days" not in cols:
        db.execute("ALTER TABLE festivals ADD COLUMN duration_days INTEGER NOT NULL DEFAULT 1")
    if "duration_label" not in cols:
        db.execute("ALTER TABLE festivals ADD COLUMN duration_label TEXT")

    # Seed festivals if empty
    count = db.execute("SELECT COUNT(*) c FROM festivals").fetchone()["c"]
    if count == 0:
        for f in FESTIVALS_SEED:
            cur = db.execute(
                """INSERT INTO festivals
                   (slug,name,city,start_date,end_date,duration_days,duration_label,categories,description,cover_emoji)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (f["slug"], f["name"], f["city"], f["start_date"], f["end_date"],
                 f["duration_days"], f["duration_label"], f["categories"],
                 f["description"], f["cover_emoji"])
            )
            fid = cur.lastrowid
            for t in f["tariffs"]:
                db.execute(
                    "INSERT INTO tariffs (festival_id,name,price,description,seats_left) VALUES (?,?,?,?,?)",
                    (fid, t[0], t[1], t[2], t[3])
                )
            for s in f["schedule"]:
                db.execute(
                    """INSERT INTO schedule_items
                       (festival_id,day_label,day_index,time,title,description,stage)
                       VALUES (?,?,?,?,?,?,?)""",
                    (fid, s[0], s[1], s[2], s[3], s[4], s[5])
                )

    db.commit()
    db.close()


# ----------------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("user_id"):
            flash("Войдите, чтобы продолжить", "warn")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w


def business_required(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u:
            return redirect(url_for("login"))
        if u["role"] != "business":
            flash("Только для бизнес-аккаунтов", "warn")
            return redirect(url_for("festivals"))
        return f(*a, **kw)
    return w


@app.context_processor
def inject_globals():
    def fmt_money(v):
        try:
            return f"{int(v):,}".replace(",", " ")
        except Exception:
            return str(v)
    return {"current_user": current_user(), "fmt_money": fmt_money}


# ----------------------------------------------------------------------------
# Routes: Auth
# ----------------------------------------------------------------------------
@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("festivals"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Неверный email или пароль", "error")
            return render_template("login.html", email=email)
        session["user_id"] = user["id"]
        flash("Добро пожаловать!", "success")
        nxt = request.args.get("next") or url_for("festivals")
        return redirect(nxt)
    return render_template("login.html", email="")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        if not email or not password or len(password) < 6:
            flash("Email и пароль обязательны (мин. 6 символов)", "error")
            return render_template("register.html", **request.form)
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            flash("Такой email уже зарегистрирован", "error")
            return render_template("register.html", **request.form)
        cur = db.execute(
            "INSERT INTO users (email,password_hash,full_name,phone,role) VALUES (?,?,?,?, 'user')",
            (email, generate_password_hash(password), full_name, phone)
        )
        db.commit()
        session["user_id"] = cur.lastrowid
        flash("Регистрация успешна!", "success")
        return redirect(url_for("festivals"))
    return render_template("register.html")


@app.route("/register-business", methods=["GET", "POST"])
def register_business():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        biz_name = request.form.get("biz_name", "").strip()
        category = request.form.get("category", "").strip()
        city = request.form.get("city", "").strip()
        description = request.form.get("description", "").strip()
        if not email or not password or len(password) < 6 or not biz_name:
            flash("Заполните email, пароль (мин. 6) и название компании", "error")
            return render_template("register_business.html", **request.form)
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            flash("Такой email уже зарегистрирован", "error")
            return render_template("register_business.html", **request.form)
        cur = db.execute(
            "INSERT INTO users (email,password_hash,full_name,phone,role) VALUES (?,?,?,?, 'business')",
            (email, generate_password_hash(password), full_name, phone)
        )
        uid = cur.lastrowid
        db.execute(
            "INSERT INTO businesses (user_id,name,category,city,phone,description) VALUES (?,?,?,?,?,?)",
            (uid, biz_name, category, city, phone, description)
        )
        db.commit()
        session["user_id"] = uid
        flash("Бизнес-аккаунт создан!", "success")
        return redirect(url_for("business_dashboard"))
    return render_template("register_business.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------------------------
# Routes: Festivals
# ----------------------------------------------------------------------------
@app.route("/festivals")
@login_required
def festivals():
    db = get_db()
    rows = db.execute("SELECT * FROM festivals ORDER BY start_date").fetchall()
    items = []
    for f in rows:
        min_price = db.execute(
            "SELECT MIN(price) p FROM tariffs WHERE festival_id=?", (f["id"],)
        ).fetchone()["p"]
        items.append({**dict(f), "min_price": min_price})
    cat = request.args.get("cat", "Все")
    if cat != "Все":
        items = [x for x in items if cat in x["categories"].split(",")]
    cats = ["Все", "Музыка", "Гастро", "Искусство", "Культура", "Эко", "Спорт", "Семья"]
    return render_template("festivals.html", items=items, cats=cats, current_cat=cat)


@app.route("/festival/<slug>")
@login_required
def festival_detail(slug):
    db = get_db()
    f = db.execute("SELECT * FROM festivals WHERE slug=?", (slug,)).fetchone()
    if not f:
        abort(404)
    tariffs = db.execute(
        "SELECT * FROM tariffs WHERE festival_id=? ORDER BY price", (f["id"],)
    ).fetchall()
    sched_rows = db.execute(
        "SELECT * FROM schedule_items WHERE festival_id=? ORDER BY day_index, time",
        (f["id"],)
    ).fetchall()
    schedule = {}
    for s in sched_rows:
        schedule.setdefault(s["day_label"], []).append(s)
    return render_template("festival_detail.html", f=f, tariffs=tariffs, schedule=schedule)


@app.route("/buy/<int:tariff_id>", methods=["GET", "POST"])
@login_required
def buy(tariff_id):
    db = get_db()
    t = db.execute("SELECT * FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
    if not t:
        abort(404)
    f = db.execute("SELECT * FROM festivals WHERE id=?", (t["festival_id"],)).fetchone()
    if request.method == "POST":
        try:
            qty = max(1, int(request.form.get("quantity", "1")))
        except ValueError:
            qty = 1
        if qty > t["seats_left"]:
            flash(f"Доступно только {t['seats_left']} мест", "error")
            return redirect(url_for("buy", tariff_id=tariff_id))
        total = qty * t["price"]
        code = "FK-" + secrets.token_hex(4).upper()
        cur = db.execute(
            """INSERT INTO tickets (code,user_id,festival_id,tariff_id,quantity,total_price,status)
               VALUES (?,?,?,?,?,?, 'paid')""",
            (code, session["user_id"], f["id"], t["id"], qty, total)
        )
        db.execute("UPDATE tariffs SET seats_left = seats_left - ? WHERE id=?", (qty, t["id"]))
        db.commit()
        flash("Билет успешно оформлен!", "success")
        return redirect(url_for("ticket_view", ticket_id=cur.lastrowid))
    return render_template("buy.html", t=t, f=f)


@app.route("/ticket/<int:ticket_id>")
@login_required
def ticket_view(ticket_id):
    db = get_db()
    tk = db.execute("SELECT * FROM tickets WHERE id=? AND user_id=?",
                    (ticket_id, session["user_id"])).fetchone()
    if not tk:
        abort(404)
    f = db.execute("SELECT * FROM festivals WHERE id=?", (tk["festival_id"],)).fetchone()
    t = db.execute("SELECT * FROM tariffs WHERE id=?", (tk["tariff_id"],)).fetchone()
    return render_template("ticket.html", tk=tk, f=f, t=t)


@app.route("/ticket/<int:ticket_id>/qr.png")
@login_required
def ticket_qr(ticket_id):
    db = get_db()
    tk = db.execute("SELECT * FROM tickets WHERE id=? AND user_id=?",
                    (ticket_id, session["user_id"])).fetchone()
    if not tk:
        abort(404)
    img = qrcode.make(f"FESTKG|{tk['code']}|user:{tk['user_id']}|fest:{tk['festival_id']}")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/my-tickets")
@login_required
def my_tickets():
    db = get_db()
    rows = db.execute("""
        SELECT tk.*, f.name fname, f.city fcity, f.start_date fstart,
               f.cover_emoji emoji, t.name tname, t.price tprice
        FROM tickets tk
        JOIN festivals f ON f.id=tk.festival_id
        JOIN tariffs t ON t.id=tk.tariff_id
        WHERE tk.user_id=?
        ORDER BY tk.created_at DESC
    """, (session["user_id"],)).fetchall()
    return render_template("my_tickets.html", tickets=rows)


# ----------------------------------------------------------------------------
# Routes: Business cabinet
# ----------------------------------------------------------------------------
@app.route("/business")
@business_required
def business_dashboard():
    db = get_db()
    u = current_user()
    biz = db.execute("SELECT * FROM businesses WHERE user_id=?", (u["id"],)).fetchone()
    apps_rows = db.execute("""
        SELECT a.*, f.name fname FROM applications a
        JOIN festivals f ON f.id=a.festival_id
        WHERE a.business_id=? ORDER BY a.created_at DESC
    """, (biz["id"],)).fetchall()

    total_apps = len(apps_rows)
    approved = sum(1 for a in apps_rows if a["status"] == "approved")
    pending = sum(1 for a in apps_rows if a["status"] == "pending")
    rejected = sum(1 for a in apps_rows if a["status"] == "rejected")

    # Demo financial metrics derived from approved applications
    revenue = approved * 45000
    commission = int(revenue * 0.10)
    net = revenue - commission

    festivals_list = db.execute("SELECT id,name FROM festivals ORDER BY start_date").fetchall()

    return render_template(
        "business_dashboard.html",
        biz=biz, apps=apps_rows, festivals_list=festivals_list,
        total_apps=total_apps, approved=approved, pending=pending,
        rejected=rejected, revenue=revenue, commission=commission, net=net
    )


@app.route("/business/apply", methods=["POST"])
@business_required
def business_apply():
    db = get_db()
    u = current_user()
    biz = db.execute("SELECT * FROM businesses WHERE user_id=?", (u["id"],)).fetchone()
    fid = request.form.get("festival_id")
    booth = request.form.get("booth_type", "Стандарт")
    note = request.form.get("note", "")
    if not fid:
        flash("Выберите фестиваль", "error")
        return redirect(url_for("business_dashboard"))
    db.execute(
        "INSERT INTO applications (business_id,festival_id,booth_type,note,status) VALUES (?,?,?,?, 'pending')",
        (biz["id"], int(fid), booth, note)
    )
    db.commit()
    flash("Заявка отправлена!", "success")
    return redirect(url_for("business_dashboard"))


@app.route("/business/profile", methods=["POST"])
@business_required
def business_profile():
    db = get_db()
    u = current_user()
    biz = db.execute("SELECT * FROM businesses WHERE user_id=?", (u["id"],)).fetchone()
    db.execute(
        """UPDATE businesses SET name=?, category=?, city=?, phone=?, description=?
           WHERE id=?""",
        (
            request.form.get("name", "").strip(),
            request.form.get("category", "").strip(),
            request.form.get("city", "").strip(),
            request.form.get("phone", "").strip(),
            request.form.get("description", "").strip(),
            biz["id"]
        )
    )
    db.commit()
    flash("Профиль обновлён", "success")
    return redirect(url_for("business_dashboard") + "#profile")


# Demo helper: approve/reject your own applications (for full-cycle demo)
@app.route("/business/app/<int:app_id>/<action>", methods=["POST"])
@business_required
def business_app_action(app_id, action):
    if action not in ("approve", "reject"):
        abort(400)
    db = get_db()
    u = current_user()
    biz = db.execute("SELECT * FROM businesses WHERE user_id=?", (u["id"],)).fetchone()
    new_status = "approved" if action == "approve" else "rejected"
    db.execute("UPDATE applications SET status=? WHERE id=? AND business_id=?",
               (new_status, app_id, biz["id"]))
    db.commit()
    return redirect(url_for("business_dashboard"))


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


# ----------------------------------------------------------------------------
# Boot
# ----------------------------------------------------------------------------
with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
