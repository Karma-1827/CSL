# DEPLOY.md

本文件記錄部署相關的細節與 checklist。從 `CLAUDE.md` 拆出,因為日常業務邏輯開發用不到這些內容,只有實際要部署或碰觸 deployment 設定時才需要讀。

## 目標環境

學校提供的 Linux VM＋PostgreSQL。現在只有 Django WSGI/ASGI entry 與 production security settings,**尚無正式 deployment artifacts**(無 Dockerfile、Gunicorn 設定、Nginx、systemd unit、CI/CD)。

## 正式部署至少需要

1. 設定 `.env.example` 中所有環境變數,使用長且隨機的 `DJANGO_SECRET_KEY`。
2. `DJANGO_DEBUG=0`、正確 `DJANGO_ALLOWED_HOSTS` 與 PostgreSQL 連線資訊。
3. `python manage.py migrate`、`python manage.py collectstatic`。
4. 用正式 WSGI/ASGI server,不使用 `runserver`。
5. 反向代理 HTTPS;`DEBUG=False` 時已啟用 Secure Cookie、SSL redirect、HSTS。
6. cron/systemd timer 定期執行 `python manage.py process_matching_state`(README 建議每分鐘)。
7. 另外設計 DB/media 備份、log rotation、監控與災難復原;RPO/RTO 尚待系辦決定。

## 本機常用指令

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

`.vscode/launch.json` 目前仍使用 8000;日常人工驗收多使用 8001,請勿同時啟動兩個不必要的 server。

## 部署前驗證

```bash
source .venv/bin/activate
python manage.py test --verbosity 1
python manage.py check
python manage.py makemigrations --check --dry-run
DJANGO_DEBUG=0 DJANGO_SECRET_KEY='deployment-check-only-secret-key-that-is-long-and-random-2026' \
  python manage.py check --deploy
```
