# 華語輔導系統 / Chinese Language Tutoring System

國立臺灣師範大學華語文教學系的師生配對與輔導管理系統。

## 技術架構

- Python 3.12
- Django 5.2 LTS
- PostgreSQL 18
- Django server-rendered responsive UI
- 全站中英並列介面

## 已完成（V0）

- 預載學生名冊與學號唯一註冊
- 兩階段註冊：登入資料 → Tutor／Tutee 專屬 Profile Setup
- 註冊草稿只保存密碼雜湊、30 分鐘到期；完成 Profile 後才建立正式帳號
- Admin、Tutor、Tutee 三種角色
- 登入、登出與三安全問題密碼恢復
- Tutor 資格證明上傳（PDF/JPG/PNG，1 MB）
- Admin 名冊管理、資格審核與稽核紀錄
- 三角色雙語響應式儀表板
- 正式環境 HTTPS、Secure Cookie、HSTS 設定

## 本機啟動

1. 啟動 Postgres.app，確認 `qiangqiang` 資料庫存在。
2. 在專案根目錄執行：

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py runserver
```

3. 開啟 <http://127.0.0.1:8000/>。

## 建立正式 Admin

```bash
source .venv/bin/activate
python manage.py createsuperuser
```

公開註冊頁不會建立 Admin；後續 Admin 由既有 Admin 建立。

## 測試

```bash
source .venv/bin/activate
python manage.py test
DJANGO_DEBUG=0 DJANGO_SECRET_KEY='use-a-real-secret' python manage.py check --deploy
```

## 環境變數

複製 `.env.example` 的欄位到部署環境。正式部署不可沿用開發用 `DJANGO_SECRET_KEY`，也不可將密碼或真實學生資料提交到 Git。

## 已完成（V1）

- 學期與可配對時間設定
- Tutor/Tutee 資料卡與最小揭露欄位
- 雙向邀請、五日逾期、接受與拒絕
- Tutor 同時上限 2 位，Tutee 同時上限 1 位
- 解除後同學期不得與原對象重新配對
- 自動／人工解除配對流程

## 配對狀態排程

正式環境需由 cron 或 systemd timer 定期執行下列指令（建議每分鐘一次），以處理五日邀請逾期、學期結束及三日後自動解除：

```bash
python manage.py process_matching_state
```
