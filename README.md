# 華語實習暨輔導系統 MPTS / Mandarin Practicum and Tutoring System

國立臺灣師範大學華語文教學系的師生配對與輔導管理系統。

## 目前進度

完整的功能範圍、角色權限與業務規則以 **`CLAUDE.md`** 為準;目前開發進度、已知缺口與版本規劃見 **`docs/PROGRESS.md`**。本檔案只放技術棧與本機啟動步驟,避免重複維護兩份容易失準的功能清單。

## 技術架構

- Python 3.12
- Django 5.2 LTS
- PostgreSQL 18
- psycopg 3、Pillow、ReportLab、pypdf、openpyxl
- Django server-rendered responsive UI,無前端框架、無 REST API
- 全站中英並列介面

## 本機啟動

1. 啟動 Postgres.app,確認 `qiangqiang` 資料庫存在。
2. 在專案根目錄執行:

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

3. 開啟 <http://127.0.0.1:8001/>。

## 建立正式 Admin

```bash
source .venv/bin/activate
python manage.py createsuperuser
```

公開註冊頁不會建立 Admin;後續 Admin 由既有 Admin 建立。

## 測試

```bash
source .venv/bin/activate
python manage.py test
DJANGO_DEBUG=0 DJANGO_SECRET_KEY='use-a-real-secret' python manage.py check --deploy
```

## 程式碼檢查

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
```

GitHub Actions(`.github/workflows/ci.yml`)在每次 push 到 `main` 與每個 PR 都會自動跑 lint、migration 檢查與完整測試。

## 環境變數

複製 `.env.example` 的欄位到部署環境。正式部署不可沿用開發用 `DJANGO_SECRET_KEY`,也不可將密碼或真實學生資料提交到 Git。

## 配對狀態排程

正式環境需由 cron 或 systemd timer 定期執行下列指令(建議每分鐘一次),以處理邀請逾期、學期結束及自動解除配對等狀態轉換:

```bash
python manage.py process_matching_state
```

## 部署

完整上線 checklist、環境設定與部署前驗證指令見 `docs/DEPLOY.md`。
