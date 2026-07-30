# DEPLOY.md

本文件記錄部署相關的細節與 checklist。從 `CLAUDE.md` 拆出,因為日常業務邏輯開發用不到這些內容,只有實際要部署或碰觸 deployment 設定時才需要讀。

## 目標環境

學校提供的 Linux VM＋PostgreSQL。現在只有 Django WSGI/ASGI entry 與 production security settings,**尚無正式 deployment artifacts**(無 Dockerfile、Gunicorn 設定、Nginx、systemd unit、CI/CD)。

此系統預計歸類為「校務行政系統及隸屬系所之行政資訊系統」,依目前取得的校方說明免收 VM 租賃費用;正式申請仍以學校審核結果為準。預估帳號規模 500 人以上,服務對外開放且需支援手機瀏覽。

### VM 申請規格建議

下列是目前申請階段的容量規劃,不是程式執行的最低門檻:

- 預載作業系統:`Ubuntu (64bit)`。
- CPU:`8 Core`。
- RAM:`16 GB`。
- 系統硬碟:`150 GB`(申請表可選上限)。
- 備份用 NFS:`120 GB`暫定;最終應依學校 NFS 備份機制與保留版本數確認。
- DNS:使用學校格式 `<自設主機名稱>.<單位英文縮寫>.ntnu.edu.tw`;主機名稱與單位縮寫尚待系辦/網管確認,不可在程式設定中先猜定。
- 預設系統管理帳號:填維運用 Linux 帳號,不要使用 `admin`、`root`、姓名、學號或與 Django Admin 相同的帳號;最終帳號名稱由申請人與校方規範確認。

### 硬體需求說明

申請表如要求說明超過 4 Core 或 8 GB RAM 的理由,可使用下列內容:

> 本系統預計提供 500 人以上使用,同一台虛擬伺服器需同時執行 Nginx、Django WSGI 應用服務、PostgreSQL 資料庫、背景排程及稽核紀錄。使用尖峰包含學期初名冊匯入與註冊、配對期間的名單查詢與邀請、排課與簽到,以及學期末大量時數統計、Excel 匯出與 PDF 證明產生。PDF 產生、Excel 匯出、檔案掃描/處理與資料庫查詢均會同時消耗 CPU 與記憶體,因此規劃 8 Core、16 GB RAM,以保留尖峰負載、系統更新與未來合作計畫擴充空間。
>
> 系統硬碟需存放 Ubuntu、應用程式、PostgreSQL 資料庫、靜態檔案、資格證明與可能的 PDF/JPG/PNG 上傳、產生的證明文件、系統與稽核 log 及更新暫存空間。使用者資料需跨學期保存,且後續可能增加合作計畫與附件,因此申請 150 GB 系統硬碟,避免正式上線後因容量不足重新申請搬遷。另規劃 NFS 備份空間保存資料庫與 media 備份;備份不可和正式資料只放在同一顆系統硬碟。

容量大不等於可以無限保存檔案。正式上線前仍須決定附件保存期限、log rotation、備份保留版本與定期容量告警。

## 正式部署至少需要

1. 設定 `.env.example` 中所有環境變數,使用長且隨機的 `DJANGO_SECRET_KEY`。
2. `DJANGO_DEBUG=0`、正確 `DJANGO_ALLOWED_HOSTS` 與 PostgreSQL 連線資訊。
3. `python manage.py migrate`、`python manage.py collectstatic`。
4. 用正式 WSGI/ASGI server,不使用 `runserver`。
5. 反向代理 HTTPS;`DEBUG=False` 時已啟用 Secure Cookie、SSL redirect、HSTS。
6. cron/systemd timer 定期執行 `python manage.py process_matching_state`(README 建議每分鐘)。
7. 另外設計 DB/media 備份、log rotation、監控與災難復原;RPO/RTO 尚待系辦決定。
8. 設定正式 DNS、TLS 憑證、`CSRF_TRUSTED_ORIGINS` 與 `SECURE_PROXY_SSL_HEADER`,並確認反向代理傳遞正確的 Host/HTTPS headers。
9. PostgreSQL 與 media 都要納入備份;至少完成一次「從備份還原到測試環境」演練,不能只確認備份檔有產生。
10. 建立容量、CPU、RAM、磁碟、HTTP 5xx、服務存活與備份失敗告警。

## 上線前仍待確認

- 正式 DNS 主機名稱與單位英文縮寫。
- 校方實際核配的 CPU、RAM、150 GB 系統碟與 NFS 容量。
- 正式系統管理帳號、SSH 金鑰與可登入來源限制。
- PostgreSQL 是同機安裝或由學校提供獨立服務。
- 正式 RPO、RTO、每日/每週備份頻率、備份保留週期與復原責任人。
- 資格文件、課堂紀錄附件、稽核 log 與對話紀錄的保存/刪除政策。異常回報目前不提供附件上傳,不列入附件保存範圍。
- TLS 憑證由學校自動提供、網管代管或由維運者申請。

## 本機常用指令

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

`.vscode/launch.json` 已改為與日常人工驗收一致的 8001;請勿同時啟動兩個不必要的 server(過去曾發生舊 server process 沒關掉、改完程式碼卻由舊 process 回應請求的情況,`ps aux | grep runserver` 確認後再啟動新的)。

## 部署前驗證

```bash
source .venv/bin/activate
python manage.py test --verbosity 1
python manage.py check
python manage.py makemigrations --check --dry-run
DJANGO_DEBUG=0 DJANGO_SECRET_KEY='deployment-check-only-secret-key-that-is-long-and-random-2026' \
  python manage.py check --deploy
```
