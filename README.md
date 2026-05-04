# FestKG — Фестивали Кыргызстана (Flask)

Полноценный веб-портал на Flask + SQLite:
- 6 фестивалей с программой по дням и длительностью
- Регистрация пользователя и регистрация бизнеса (отдельные формы)
- Авторизация (email + пароль, Werkzeug-хэш)
- Покупка билетов с QR-кодом и тарифами
- Кабинет бизнеса: метрики, заявки, профиль

## Запуск локально

```bash
pip install -r requirements.txt
python app.py
```

Откройте http://localhost:5000 — увидите форму входа.
- Регистрация пользователя: /register
- Регистрация бизнеса: /register-business

## Деплой
Render / Railway / PythonAnywhere — добавьте `gunicorn app:app` как стартовую команду
(`pip install gunicorn` в requirements).

## Структура
- `app.py` — приложение, БД, роуты
- `templates/` — Jinja2-шаблоны
- `static/styles.css` — стили (темы светлая/тёмная)
