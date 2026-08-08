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
8. 設定正式 DNS、TLS 憑證、`DJANGO_CSRF_TRUSTED_ORIGINS`(逗號分隔的 `scheme://host`,例如 `https://mpts.xxx.ntnu.edu.tw`)。`SECURE_PROXY_SSL_HEADER` 已在 `config/settings.py` 寫死信任 `X-Forwarded-Proto`,**部署前必須先確認反向代理(Nginx)一律清除用戶端自行帶入的 `X-Forwarded-Proto`/`X-Forwarded-For` 再重新設定**,否則等同讓外部請求自行宣稱是 HTTPS,繞過 `SECURE_SSL_REDIRECT`/Secure Cookie 的保護;Django 本身無法偵測反向代理是否確實清除。
9. `DJANGO_DEBUG=0` 啟動時,`config/settings.py` 會 fail closed:缺少或等於開發預設值的 `DJANGO_SECRET_KEY`、空白的 `POSTGRES_PASSWORD`,或 `DJANGO_ALLOWED_HOSTS` 為空/`*`/只有 localhost,都會讓應用程式直接拋出 `ImproperlyConfigured` 無法啟動。部署前務必確認這三項環境變數都已填入正式值,而不是等啟動失敗才發現。
10. PostgreSQL 與 media 都要納入備份;至少完成一次「從備份還原到測試環境」演練,不能只確認備份檔有產生。
11. 建立容量、CPU、RAM、磁碟、HTTP 5xx、服務存活與備份失敗告警。
12. `/media/` 不得設成 Nginx 可直接公開存取的 static location(口語能力證明、課堂紀錄附件、上課文件三種私人檔案都已改走受保護下載 view,見 `accounts:download_qualification`、`tutoring:download_class_record_attachment`、`accounts:download_class_document`,批次3)。目前開發環境用 Django `FileResponse` 直接讀檔案回應,正式環境應改用 Nginx `X-Accel-Redirect`(view 只驗證權限並回傳內部重導頭,實際傳檔交給 Nginx),減少 WSGI worker 花時間搬檔案;三個 view 目前的 `Cache-Control: private, no-store`、`X-Content-Type-Options: nosniff`、`Content-Disposition: attachment` 這三個回應標頭在改用 `X-Accel-Redirect` 後仍要保留。

## Django Admin(`/system-admin/`)存取限制

自製 Admin dashboard 尚未涵蓋合作計畫、上課文件、Admin 帳號、AuditLog 檢視、時數調整（單筆）、特殊資料修正等行政功能，因此**批次 4 完成後仍不能移除 `/system-admin/`**，只先做兩層防護,等自製功能補齊再評估是否完全不掛載這個 URL:

1. **核心業務 model 已在 Django Admin 改為唯讀**(`tutoring/admin.py::ReadOnlyAdminMixin`,套用於 `Pairing`、`MatchingInvitation`、`ClassSession`、`Attendance`、`ClassRecord`、`ClassConfirmation`、`MakeupReview`、`PairingReleaseRequest`):保留清單、篩選、搜尋與唯讀檢視,但新增/修改/刪除一律回傳 `False`(即使是 superuser),避免 Admin 登入被用來繞過 `tutoring/services.py` 的配對名額、狀態機與交易鎖規則。`ClassAlert`、`IncidentReport`、`HourAdjustment`、`ClassDocument` 等其餘 model 不在此範圍內,因為它們本來就是設計成透過 Django Admin 或 Admin dashboard 直接管理(見 `CLAUDE.md` 第 4.7/4.9/4.10 節)。
2. **`/system-admin/` 登入已套用與主站相同標準的共享節流**(`accounts/forms.py::ThrottledAdminAuthenticationForm`,經 `accounts/admin.py` 的 `admin.site.login_form` 掛載):同一 IP+帳號 15 分鐘內 5 次失敗即鎖定,使用獨立的 cache key 前綴(`admin_login:`)而非與主站共用計數,因為兩邊帳號池幾乎不重疊(只有 `is_staff` 帳號能通過 Admin 登入的 `confirm_login_allowed()`)。

**正式 VM 取得網段後,還需要在 Nginx 加上 IP／VPN 白名單**,把 `/system-admin/` 限制在校內或 VPN 來源,避免只靠登入節流面對整個公開網路。以下是範本,實際 IP／CIDR 待網管確認:

```nginx
location /system-admin/ {
    # 只允許校內網段／VPN 出口 IP,其餘一律拒絕。實際範圍待網管確認,
    # 不可用註解掉 deny all 的方式暫時放行。
    allow 140.122.0.0/16;       # 範例:師大校內網段(需網管確認實際範圍)
    allow 203.0.113.10;         # 範例:VPN 出口固定 IP(需網管確認實際位址)
    deny all;

    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

這段只是 `/system-admin/` 專屬的 location block 範本,不是完整的 Nginx server 設定(完整 server block、靜態檔案、`/media/` 的 `X-Accel-Redirect` location 留待批次 8 一併產出)。套用前務必:

- 用實際核配的校內網段/VPN 出口 IP 取代範例值,不可用 `0.0.0.0/0` 或留空等同開放。
- 確認 `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` 會**覆蓋**、而非附加用戶端自行帶入的 `X-Forwarded-For`,否則 Django 這端信任代理鏈時可能被偽造的標頭混淆。
- 若之後改用 Cloudflare 或其他 CDN/WAF,校內網段清單需要換成該服務的來源 IP 清單,不能直接沿用這份範本。

## 上線前仍待確認

- 正式 DNS 主機名稱與單位英文縮寫。
- 校方實際核配的 CPU、RAM、150 GB 系統碟與 NFS 容量。
- 正式系統管理帳號、SSH 金鑰與可登入來源限制。
- PostgreSQL 是同機安裝或由學校提供獨立服務。
- 正式 RPO、RTO、每日/每週備份頻率、備份保留週期與復原責任人(待系辦/資訊中心確認,見 `docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 20 項)。
- 個資、口語能力證明文件、課堂紀錄附件、稽核 log、對話紀錄與正式證明 PDF 的保存/刪除政策,同樣待系辦/資訊中心確認,系統不會自行寫死刪除年限。異常回報目前不提供附件上傳,不列入附件保存範圍。
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
