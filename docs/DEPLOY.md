# DEPLOY.md

本文件記錄部署相關的細節與 checklist。從 `CLAUDE.md` 拆出,因為日常業務邏輯開發用不到這些內容,只有實際要部署或碰觸 deployment 設定時才需要讀。

## 目標環境

學校提供的 Linux VM＋PostgreSQL。`deploy/` 目錄(批次8)已提供 Gunicorn 設定、Nginx server block 範本、systemd unit/timer 與正式環境 `.env` 範本。**2026-08-17 已在資訊中心分配的正式 VM(`mpts.tcsl.ntnu.edu.tw`)套用過一次,套件安裝、DB、Gunicorn、Nginx、TLS(Let's Encrypt)、`/system-admin/` IP 白名單皆已驗證可正常運作**,細節與過程中修正的落差見下方「首次部署實際踩過的坑」;仍待確認的項目移到「上線前仍待確認」。尚無 Dockerfile 或 CI/CD 自動部署,目前每次部署仍是手動依 `docs/DEPLOY.md` 步驟操作。

此系統預計歸類為「校務行政系統及隸屬系所之行政資訊系統」,依目前取得的校方說明免收 VM 租賃費用;正式申請仍以學校審核結果為準。預估帳號規模 500 人以上,服務對外開放且需支援手機瀏覽。

### VM 申請規格建議

下列是目前申請階段的容量規劃,不是程式執行的最低門檻:

- 預載作業系統:`Ubuntu (64bit)`。
- CPU:`8 Core`。
- RAM:`32 GB`。
- 系統硬碟:`150 GB`(申請表可選上限)。
- 備份用 NFS:`600 GB`(申請表可選上限);實際備份保留版本數仍須依學校 NFS 機制確認。
- DNS:使用學校格式 `<自設主機名稱>.<單位英文縮寫>.ntnu.edu.tw`;主機名稱與單位縮寫尚待系辦/網管確認,不可在程式設定中先猜定。
- 預設系統管理帳號:填維運用 Linux 帳號,不要使用 `admin`、`root`、姓名、學號或與 Django Admin 相同的帳號;最終帳號名稱由申請人與校方規範確認。

### 硬體需求說明

申請表如要求說明超過 4 Core 或 8 GB RAM 的理由,可使用下列內容:

> 本系統預計提供 500 人以上使用,同一台虛擬伺服器需同時執行 Nginx、Django WSGI 應用服務、PostgreSQL 資料庫、背景排程及稽核紀錄。使用尖峰包含學期初名冊匯入與註冊、配對期間的名單查詢與邀請、排課與簽到,以及學期末大量時數統計、Excel 匯出與 PDF 證明產生。PDF 產生、Excel 匯出、檔案掃描/處理與資料庫查詢均會同時消耗 CPU 與記憶體,因此規劃 8 Core、32 GB RAM,以保留尖峰負載、資料庫快取、系統更新與未來合作計畫擴充空間。
>
> 系統硬碟需存放 Ubuntu、應用程式、PostgreSQL 資料庫、靜態檔案、資格證明與可能的 PDF/JPG/PNG 上傳、產生的證明文件、系統與稽核 log 及更新暫存空間。使用者資料需跨學期保存,且後續可能增加合作計畫與附件,因此申請 150 GB 系統硬碟,避免正式上線後因容量不足重新申請搬遷。另申請 600 GB NFS 備份空間保存 PostgreSQL、media 與必要設定的每日、每週及每月多版本備份;備份容量需大於主機實際資料量,才能保留多個歷史還原點,且不可和正式資料只放在同一顆系統硬碟。

容量大不等於可以無限保存檔案。正式上線前仍須決定附件保存期限、log rotation、備份保留版本與定期容量告警。

## 正式部署至少需要

1. 依 `deploy/.env.production.example` 填好 `/opt/mpts/.env`(路徑僅為範例,實際部署路徑待定),使用長且隨機的 `DJANGO_SECRET_KEY`,`chmod 600` 並確認擁有者是服務帳號。
2. `DJANGO_DEBUG=0`、正確 `DJANGO_ALLOWED_HOSTS` 與 PostgreSQL 連線資訊。
3. `python manage.py migrate`、`python manage.py collectstatic`。
4. 用 `deploy/gunicorn.conf.py` + `deploy/systemd/mpts-gunicorn.service` 啟動 Gunicorn,不使用 `runserver`;Gunicorn 只綁 Unix socket,不對外開任何 TCP port(見該 service 檔案的 `ReadWritePaths`/`ProtectSystem` 說明)。
5. 用 `deploy/nginx/mpts.conf.example` + `deploy/nginx/proxy_params_mpts.conf` 設定反向代理 HTTPS;`DEBUG=False` 時已啟用 Secure Cookie、SSL redirect、HSTS。
6. `deploy/systemd/mpts-process-matching-state.service` + `.timer` 每分鐘執行 `python manage.py process_matching_state`(啟用 `.timer`,不要直接啟用 `.service`)。
7. 另外設計 DB/media 備份、log rotation、監控與災難復原;RPO/RTO 尚待系辦決定。
8. 設定正式 DNS、TLS 憑證、`DJANGO_CSRF_TRUSTED_ORIGINS`(逗號分隔的 `scheme://host`,例如 `https://mpts.xxx.ntnu.edu.tw`)。`SECURE_PROXY_SSL_HEADER` 已在 `config/settings.py` 寫死信任 `X-Forwarded-Proto`,**部署前必須先確認反向代理(Nginx)一律清除用戶端自行帶入的 `X-Forwarded-Proto`/`X-Forwarded-For` 再重新設定**,否則等同讓外部請求自行宣稱是 HTTPS,繞過 `SECURE_SSL_REDIRECT`/Secure Cookie 的保護;Django 本身無法偵測反向代理是否確實清除。
9. `DJANGO_DEBUG=0` 啟動時,`config/settings.py` 會 fail closed:缺少或等於開發預設值的 `DJANGO_SECRET_KEY`、空白的 `POSTGRES_PASSWORD`,或 `DJANGO_ALLOWED_HOSTS` 為空/`*`/只有 localhost,都會讓應用程式直接拋出 `ImproperlyConfigured` 無法啟動。部署前務必確認這三項環境變數都已填入正式值,而不是等啟動失敗才發現。
10. PostgreSQL 與 media 都要納入備份;至少完成一次「從備份還原到測試環境」演練,不能只確認備份檔有產生。
11. 建立容量、CPU、RAM、磁碟、HTTP 5xx、服務存活與備份失敗告警。
12. `/media/` 不得設成 Nginx 可直接公開存取的 static location(口語能力證明、課堂紀錄附件、上課文件三種私人檔案都已改走受保護下載 view,見 `accounts:download_qualification`、`tutoring:download_class_record_attachment`、`accounts:download_class_document`,批次3)。目前開發環境用 Django `FileResponse` 直接讀檔案回應,正式環境應改用 Nginx `X-Accel-Redirect`(view 只驗證權限並回傳內部重導頭,實際傳檔交給 Nginx),減少 WSGI worker 花時間搬檔案;三個 view 目前的 `Cache-Control: private, no-store`、`X-Content-Type-Options: nosniff`、`Content-Disposition: attachment` 這三個回應標頭在改用 `X-Accel-Redirect` 後仍要保留。`deploy/nginx/mpts.conf.example` 已預留 `/protected-media/`(`internal`)location 對應這個用途,但**三個 view 尚未真的送出 `X-Accel-Redirect` 標頭**,目前這個 location 還沒有任何流量走到——這是刻意留給之後有真實 Nginx 環境可以整合測試時才實作與驗證的項目,不在批次 8(純文件/範本準備)範圍內。
13. `accounts/middleware.py::ContentSecurityPolicyMiddleware` 已於 2026-08-10 由 Report-Only 切換為正式強制 `Content-Security-Policy`,並加上 `Permissions-Policy`;政策刻意不含任何 `unsafe-inline`。每次新增或修改頁面後仍須以實際瀏覽器操作登入、註冊、Dashboard、排課、訊息、Admin、PDF 預覽等主要流程,確認主控台沒有 CSP violation。若頁面違規,應優先把 inline 內容搬到 `static/` 底下,不可直接放寬政策。CSP 由 Django 統一送出,Nginx 不應再設定第二套不同政策。
14. **`DJANGO_TRUSTED_PROXY_COUNT=1`**(批次5,`config/settings.py`/`accounts/forms.py::client_ip()`):預設是 `0`(完全不信任 `X-Forwarded-For`,一律用實際 socket 對端位址),只有在 `deploy/nginx/mpts.conf.example` 已經套用、且該設定確實把 `X-Forwarded-For` 整個覆蓋成真實用戶端 IP(而非附加)的前提下才能改成 `1`。忘記設定不會讓應用程式啟動失敗,但登入/名冊查詢/帳號恢復的節流計數與 `AuditLog` 的 IP 欄位會全部記錄成 Nginx 自己的位址,節流實質上會用同一把 key 把所有使用者混在一起計算,務必在部署後手動確認(例如用兩個不同來源 IP 各觸發一次失敗登入,檢查節流是否分別計算)。
15. 登入、名冊查詢、帳號恢復與 `/system-admin/` 的節流計數已改存在 PostgreSQL(`accounts/migrations/0016_create_cache_table.py` 建立的 `django_cache_table`,`config/settings.py` 的 `CACHES`,批次5),取代原本的 `LocMemCache`;`python manage.py migrate` 就會建表,不需要額外手動步驟。這代表節流計數會跨 Gunicorn worker 共享,重啟單一 worker 也不會解除鎖定。
16. 未登入的登入、註冊、名冊身分確認、Tutor/Tutee 個人檔案建立、帳號恢復及設定新密碼頁,與所有已登入頁面一樣,都由 `PrivateNoStoreMiddleware` 加上 `Cache-Control: private, no-store`、`Pragma: no-cache` 與 `Expires: 0`,避免共用電腦或代理伺服器保留學號、安全問題與個人資料頁面。
17. Nginx 範本已包含 `server_tokens off`、TLS 1.2/1.3、TLS 1.2 cipher allowlist、session ticket 關閉、一般請求/連線限制及 client/proxy timeout。這些是安全基準而非可直接照抄的正式值；取得 VM 後必須執行 `nginx -t`,再用實際 HTTPS 端點檢查 TLS、429 行為、PDF/Excel 產製與上傳不會被 timeout 或 rate limit 誤擋。資訊中心掃描若有固定來源 IP,可依校方指示暫時調整該來源的掃描速率,不得直接全站停用限制。

## Django Admin(`/system-admin/`)存取限制

自製 Admin dashboard 尚未涵蓋合作計畫、上課文件、Admin 帳號、AuditLog 檢視、時數調整（單筆）、特殊資料修正等行政功能，因此**批次 4 完成後仍不能移除 `/system-admin/`**，只先做兩層防護,等自製功能補齊再評估是否完全不掛載這個 URL:

1. **核心業務 model 已在 Django Admin 改為唯讀**(`tutoring/admin.py::ReadOnlyAdminMixin`,套用於 `Pairing`、`MatchingInvitation`、`ClassSession`、`Attendance`、`ClassRecord`、`ClassConfirmation`、`MakeupReview`、`PairingReleaseRequest`):保留清單、篩選、搜尋與唯讀檢視,但新增/修改/刪除一律回傳 `False`(即使是 superuser),避免 Admin 登入被用來繞過 `tutoring/services.py` 的配對名額、狀態機與交易鎖規則。`ClassAlert`、`IncidentReport`、`HourAdjustment`、`ClassDocument` 等其餘 model 不在此範圍內,因為它們本來就是設計成透過 Django Admin 或 Admin dashboard 直接管理(見 `CLAUDE.md` 第 4.7/4.9/4.10 節)。
2. **`/system-admin/` 登入已套用與主站相同標準的共享節流**(`accounts/forms.py::ThrottledAdminAuthenticationForm`,經 `accounts/admin.py` 的 `admin.site.login_form` 掛載):同一 IP+帳號 15 分鐘內 5 次失敗即鎖定,另外加上不分 IP、單一帳號 15 分鐘內 20 次失敗即鎖定的第二層(批次5,防範分散在多個來源 IP 的慢速攻擊),兩層都存在 PostgreSQL(見下方「正式部署至少需要」第 15 項),不會因為 Gunicorn 重啟或 worker 不同而重置或各算各的。使用獨立的 cache key 前綴(`admin_login:`/`admin_login_id:`)而非與主站共用計數,因為兩邊帳號池幾乎不重疊(只有 `is_staff` 帳號能通過 Admin 登入的 `confirm_login_allowed()`)。

**正式 VM 取得網段後,還需要在 Nginx 加上 IP／VPN 白名單**,把 `/system-admin/` 限制在校內或 VPN 來源,避免只靠登入節流面對整個公開網路。完整範本(含 `/system-admin/` 的 IP 白名單 location、靜態檔案、`/protected-media/` 的 `X-Accel-Redirect` 預留 location)已在批次 8 產出:`deploy/nginx/mpts.conf.example` + `deploy/nginx/proxy_params_mpts.conf`。套用前務必:

- 用實際核配的校內網段/VPN 出口 IP 取代範例值,不可用 `0.0.0.0/0` 或留空等同開放。
- `proxy_params_mpts.conf` 把 `X-Forwarded-For` 設為 `$remote_addr`(**覆蓋**,不是用 `$proxy_add_x_forwarded_for` 附加)——這點曾在本文件寫錯:`$proxy_add_x_forwarded_for` 實際上是「把 nginx 看到的來源 IP,接在用戶端原本送來的 `X-Forwarded-For` 值後面」,不是覆蓋;若用這個變數,惡意用戶端自行帶入的偽造值會留在第一個位置,而 `accounts/forms.py::client_ip()` 正是取第一個值,等於完全沒有防到偽造。因為 Nginx 是這個部署唯一、直接面對用戶端的一層(Gunicorn 只綁 Unix socket、不對外),沒有更前面的可信代理需要保留其標頭,所以直接覆蓋成 `$remote_addr` 是正確做法;之後如果在 Nginx 前面再加 Cloudflare 或其他 CDN/WAF,才需要改成信任並轉發那一層的標頭。
- 若之後改用 Cloudflare 或其他 CDN/WAF,校內網段清單需要換成該服務的來源 IP 清單,不能直接沿用這份範本。

## 上線前仍待確認

**2026-08-17 已由資訊中心分配並完成初次部署,下列已確認:**

- 正式 DNS 主機名稱:`mpts.tcsl.ntnu.edu.tw`(IP `140.122.64.169`),已可公開解析。
- VM 規格:Ubuntu 24.04.2 LTS、CPU*8、RAM*32 GB、系統碟 150 GB、備份碟 600 GB(依資訊中心信件為準,較 `docs/DEPLOY.md` 舊版申請規劃的 16 GB RAM 更高)。
- PostgreSQL:同機安裝(非獨立服務),見上方「首次部署實際踩過的坑」的 `POSTGRES_HOST` 說明。
- TLS 憑證:Let's Encrypt(`certbot certonly --standalone` 取得,已設定 renewal-hooks 搭配 Nginx 自動續約,90 天效期)。
- SSH 存取:資訊中心提供的預設帳號 `tcsladmin` 已改密碼;僅限師大 VPN 網段 `140.122.57.0/24` 才能從校外連線(SSH port 22、RDP port 3389),其餘防火牆規則需自行設定。`/system-admin/` 的 Nginx IP 白名單已套用同一個 VPN 網段。

**仍待確認:**

- `/system-admin/` 的一般校內網段(目前只有 VPN 網段 `140.122.57.0/24` 有資訊中心書面確認,`deploy/nginx/mpts.conf.example` 對應那行仍是刻意會讓 `nginx -t` 失敗的 TODO 佔位,取得後才能加回去)。
- 正式 RPO、RTO、每日/每週備份頻率、備份保留週期與復原責任人(待系辦/資訊中心確認,見 `docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 20 項;資訊中心信件僅提到「每季系統完整備份乙次」,遠低於本文件件先前規劃的每日備份,需另外確認是否需要自建更高頻率的 `pg_dump`/`media` 備份,不能只依賴資訊中心的季備份)。
- 個資、口語能力證明文件、課堂紀錄附件、稽核 log、對話紀錄與正式證明 PDF 的保存/刪除政策,同樣待系辦/資訊中心確認,系統不會自行寫死刪除年限。異常回報目前不提供附件上傳,不列入附件保存範圍。
- VM 目前有待套用的核心更新(需重開機),尚未安排維護窗口。
- `/protected-media/` 的 `X-Accel-Redirect` 尚未在三個受保護下載 view 中實際串接(見上方第 12 項),目前私人檔案下載仍全部經由 Django `FileResponse` 直接串流,不是本次部署的阻斷項,但正式上線後應找時間補上以降低 WSGI worker 負擔。

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

## 部署、升級、回滾、備份與故障排除(批次8)

以下流程假設 `deploy/` 目錄下的範本已經套用成正式設定(見上方各節),部署路徑以 `/opt/mpts` 為例,實際路徑、服務帳號名稱由正式環境決定時一併更新本節。**2026-08-17 已在師大資訊中心分配的正式 VM(`mpts.tcsl.ntnu.edu.tw`,140.122.64.169)完整演練過一次**,下方步驟與「首次部署實際踩過的坑」皆已依實測更新。

### 初次部署

1. 建立服務帳號(`useradd --system --home-dir /opt/mpts --shell /usr/sbin/nologin --create-home mpts`)、Python virtualenv(`python -m venv /opt/mpts/.venv`),`pip install -r requirements.txt`。repo 目前是 **public**,可直接 `git clone https://github.com/Karma-1827/CSL.git` 到 `/opt/mpts`,不需要 deploy key/PAT;若之後改回 private 才需要另外處理認證。
2. 依 `deploy/.env.production.example` 建立 `/opt/mpts/.env`,權限設為 `600`,擁有者是 `mpts`(不是操作用的管理帳號)。**機密值不要交給任何 agent 填進版控裡的範本檔**,應另外產生一份不進 git 的真實 `.env` 再用 `scp`/`install` 送上機,範本檔只留 `TODO` 佔位。
3. `python manage.py migrate`、`python manage.py collectstatic --noinput`。
4. 複製 `deploy/systemd/*.service`、`deploy/systemd/*.timer` 到 `/etc/systemd/system/`,`deploy/nginx/*.conf*` 到 `/etc/nginx/`(依上方各節填好 TODO)。
5. `systemctl daemon-reload`,`systemctl enable --now mpts-gunicorn.service mpts-process-matching-state.timer`。
6. `nginx -t` 通過後 `systemctl reload nginx`。
7. 用一組非正式人員帳號(見 `docs/VULNERABILITY_SCAN_IMPROVEMENTS.md` 第 8 節)實際跑過登入、Dashboard、排課、下載證明,確認整條路徑(Nginx → Gunicorn → PostgreSQL)正常。

### 首次部署實際踩過的坑(2026-08-17,真實 VM)

- **PostgreSQL Unix socket 預設用 `peer` 認證,`POSTGRES_HOST` 留空會失敗**:Ubuntu 預設 `pg_hba.conf` 對 `local`(Unix socket)連線一律用 `peer`——只認「作業系統帳號名稱與資料庫角色名稱相同」,不看密碼。服務用的作業系統帳號是 `mpts`,但 `.env.production.example` 建議的資料庫角色名稱是 `mpts_app`(兩者故意分開命名以求清楚),兩者對不上,`peer` 認證必定失敗(`FATAL: Peer authentication failed for user "mpts_app"`),與密碼是否正確無關。**修正:`POSTGRES_HOST=127.0.0.1`**(改用 TCP 連線,走 `pg_hba.conf` 裡 `host ... 127.0.0.1/32 scram-sha-256` 那條規則,才會真的檢查密碼)。`deploy/.env.production.example` 與本文件第 34 行附近的欄位說明已同步更新,不要再把 `POSTGRES_HOST` 留空。
- **這台 VM 的 IPv6 在核心層停用**(`ip -6 addr show` 空白、`/sys/module/ipv6/parameters/disable=1`):`deploy/nginx/mpts.conf.example` 原本每個 `listen` 都有對應的 `listen [::]:...`,套用後 nginx **完全無法啟動**(`socket() [::]:80 failed (97: Address family not supported by protocol)`,不是「忽略 IPv6 繼續用 IPv4」,是直接啟動失敗),連 `apt install nginx` 都會卡在 postinst 步驟導致 dpkg 整個回報錯誤。已把範本裡的 `listen [::]:...` 全部拿掉並加註解說明;若未來真的换到有 IPv6 的主機,需要自行加回來並重新用 `nginx -t` 驗證。
- **`apt install nginx` 失敗時,系統內建的預設 site 也要處理**:上述 IPv6 問題發生時,`/etc/nginx/sites-enabled/default`(Ubuntu 內建範例站台)也一起因為同一個原因無法通過 `nginx -t`,導致 postinst script 失敗、`dpkg` 整包標記為「未完全安裝」。要先 `rm -f /etc/nginx/sites-enabled/default`,確認 `nginx -t` 通過後再 `dpkg --configure -a` 補完安裝,才能繼續套用我們自己的 `mpts.conf`。
- **`/opt/mpts` 目錄權限與 Nginx 讀取靜態檔案的衝突**:服務帳號 `mpts` 的 home directory 預設是 `0750`(`useradd --create-home` 的預設 umask),擁有者/群組都是 `mpts`,other 完全沒有權限。Nginx 的 worker process 跑在 `www-data` 底下,預設連 `/opt/mpts/` 都無法 `cd` 進去,`/static/` location 一律 403/500。**修正:`usermod -aG mpts www-data`**——因為 `0750` 的 group 本來就有 `r-x`,把 `www-data` 加進 `mpts` 群組即可讀取,不需要放寬成 `0755`(避免其他系統帳號也能列出 `/opt/mpts` 內容)。
- **Let's Encrypt 用 `certbot certonly --standalone`,和 Nginx 搶 80 埠**:因為當時 Nginx 還沒有正式設定檔可用,用 `--standalone` 模式最簡單(certbot 自己臨時監聽 80 取得憑證,不需要先有能動的 Nginx)。但正式續約時 Nginx 已經在跑並占用 80 埠,`certbot renew` 會失敗或卡住。**修正:在 `/etc/letsencrypt/renewal-hooks/pre/`、`/post/` 各放一支腳本,續約前 `systemctl stop nginx`、續約後 `systemctl start nginx`**,`certbot renew --dry-run` 驗證過搭配這組 hook 可以正常運作,Nginx 續約完會自動起回來。
- **手動測試 `certbot renew --dry-run` 時,不要忘記加 `--no-random-sleep-on-renew`**:certbot 的 `renew` 指令預設會插入一段隨機延遲(有時長達數分鐘),用意是避免大量伺服器在同一時間(例如 systemd timer 觸發的整點)一起打 Let's Encrypt 的伺服器造成尖峰負載;`certbot.timer` 本身照預設保留這個延遲即可(不需要改),但**手動**驗證時如果沒加這個旗標,會誤以為指令「卡住」了,其實只是在等待隨機延遲跑完。
- 套件安裝過程中 `apt` 提示核心版本(`6.8.0-106-generic`)與目前執行中版本不一致,建議重開機套用新核心更新——**這次部署刻意沒有重開機**(避免中斷已經在跑的服務去驗證一個和這次部署無關的核心更新),留給之後找一個維護窗口再處理,重開機前記得確認 gunicorn/nginx/postgresql 三個服務都設定成開機自動啟動(`systemctl is-enabled` 三者皆為 `enabled`)。
- 部署過程中為了讓自動化流程能連進去跑 `sudo` 指令,曾**暫時**在 `/etc/sudoers.d/90-mpts-deploy-tmp` 開一條 `tcsladmin ALL=(ALL) NOPASSWD: ALL`,部署收尾後已刪除並用 `sudo -n true` 確認密碼再度變成必填。**這不是常態設定**,之後若要用自動化工具跑維運指令,應該改成只針對特定指令的最小權限 sudoers 規則,而不是整條解鎖。

### 事件紀錄:系統碟被 iptables drop log 灌爆(2026-08-21)

**現象**:使用者發現 `df -h /` 顯示使用率 80.4%,查明時已到 84%(148GB 系統碟)。

**根因**:VM 的防火牆規則是資訊中心提供的範本 `/etc/iptables.rule`(開機由 `/etc/rc.local` 載入,見信件「其餘防火牆敬請自行設定」),範本最後一條是無限速的全比對 LOG 規則:

```text
iptables -A INPUT -j LOG --log-level info --log-prefix "IPTABLES-DROP: "
```

INPUT chain 預設政策是 `DROP`,任何沒被前面規則放行的封包都會落到這條規則被**無限次數**寫進 `syslog`/`kern.log`,不論來源、不論協定。2026-08-16 00:00:02 起,師大校內 IP `140.122.196.254`(不在任何已知白名單網段,推測是校內某台設備誤把 syslog 轉發設定指向這個新分配的 IP,而不是真正的外部攻擊)開始持續對這台 VM 的 UDP port 514(syslog 協定埠)發送封包,防火牆正確擋下,但**每個被擋的封包都寫一行 log**,5 天下來 `syslog`+`kern.log`(含輪替的 `.1`)累積到近 110GB,把系統碟從正常水位推到 84%。整段期間應用程式服務(Gunicorn/Nginx/PostgreSQL/排程 timer)皆維持正常運作,未發生服務中斷。

**處置**(皆已在正式 VM 執行):

1. 立即釋放空間:`rm -f /var/log/kern.log.1 /var/log/syslog.1`(已輪替、非使用中,直接刪除)+ `truncate -s 0 /var/log/kern.log /var/log/syslog`(用 `truncate` 而非 `rm`,讓 rsyslog 沿用同一個已開啟的 file descriptor 繼續寫入,不需要重啟 rsyslog)。磁碟使用率由 84% 降回 8%。
2. 修正根因:把 `/etc/iptables.rule` 裡的 LOG 規則加上速率限制(`-m limit --limit 5/min --limit-burst 10`),並用 `iptables -R INPUT 10 ...` 立即套用到目前運行中的規則,同時修改 `/etc/iptables.rule` 本身(改前備份為 `/etc/iptables.rule.bak-20260821`)確保重開機後這條限速規則仍然生效。這樣往後不論是同一個來源再次來洪水式流量,還是任何其他掃描/誤設定流量,都不會再無限制地灌爆碟。
3. 加一層保險:`/etc/logrotate.d/rsyslog` 原本只有 `weekly`(以天為單位,沒有大小上限),已改成 `size 500M`(改前備份為 `/etc/logrotate.d/rsyslog.bak-20260821`)。**注意這台機器的 logrotate 3.21.0 版本,`size` 與 `weekly`/`daily` 等時間條件在同一個 stanza 裡是互斥的,以設定檔中「後面出現的那個」為準**(`logrotate -d` 會印出 `note: 'X' overrides previously specified 'Y'` 提示),不是像新版文件說的兩者可以同時生效,務必把 `size` 寫在 `weekly` **之後**才會是 size 優先;寫反了會像這次一樣完全不生效還不會報錯。logrotate 本身透過 `logrotate.timer` 每天執行一次,所以「500M 上限」實際上是「檢查當下超過 500M 就轉檔」,極端情況下一天內仍可能超過 500M 一些,但已足以避免重演這次 5 天灌 110GB 的規模。
4. **意外收穫**:`/etc/iptables.rule` 裡列出了資訊中心範本本身就有的幾個內部網段(僅用於 OS 層 SSH 存取控制,和 Nginx 的 `/system-admin/` HTTP 層白名單是兩回事,但很可能反映了同一批真實網段):`140.122.20.0/23`、`140.122.56.0/23`、`140.122.67.0/23`(SSH)、`140.122.66.0/23`(SSH,另一條)、`140.122.85.0/24`(TCP,用途不明)。`140.122.56.0/23` 涵蓋了資訊中心書面確認的 VPN 網段 `140.122.57.0/24`,兩者一致。**這不是資訊中心針對 `/system-admin/` HTTP 存取的書面確認**,不能直接拿來取代 `deploy/nginx/mpts.conf.example` 目前的 `140.122.0.0/16`,但如果之後要把 `/system-admin/` 的白名單收斂回更精確的範圍,這是一個值得先問資訊中心「這幾個範圍是否也涵蓋一般管理端上網存取」的線索,而不用整個從零開始猜。

**後續待辦**:應正式知會資訊中心或校內網管,`140.122.196.254` 這個來源持續對 `140.122.64.169:514/udp` 送出流量已超過 5 天,協助排查是否為某設備的 syslog 轉發設定殘留(這個 IP 是新分配給 MPTS 用的,舊用途的殘留設定是最可能的解釋)。

### 升級(部署新版本)

1. 部署前先確認 `docs/PROGRESS.md`/`CLAUDE.md` 是否有需要人工介入的 migration 或資料調整(例如新增必填欄位的資料回填)。
2. `git fetch` + `git checkout <目標版本>`(或直接 pull,依實際 branch 策略而定)。
3. `pip install -r requirements.txt`(套件版本可能變動)。
4. `python manage.py migrate`——**先在有正式資料副本的 staging 環境跑過一次**,確認沒有預期外的鎖表時間或資料遺失,再對正式環境執行。
5. `python manage.py collectstatic --noinput`。
6. `systemctl restart mpts-gunicorn.service`(Gunicorn 沒有做到 zero-downtime reload,重啟期間會有短暫無法回應;若之後要做到不中斷,需要改用多台 Gunicorn 輪替或加上 `--reload`/graceful worker 替換機制,目前規模與流量尚不需要這個複雜度)。
7. 用第 7 步同一組測試帳號跑一次關鍵流程,確認新版本正常後再宣告升級完成。

### 回滾

1. `git checkout <上一個正式版本的 tag/commit>`。
2. `pip install -r requirements.txt`(回滾到舊版套件)。
3. **Migration 回滾是本專案目前最大的風險點**:多數 migration 是新增欄位/資料表,直接 `python manage.py migrate <app> <上一個 migration 編號>` 理論上可行,但務必先確認新版本上線期間沒有寫入依賴新欄位/新資料表的資料——若已經有正式資料寫入新增的欄位或資料表,回滾 migration 會遺失那些資料。沒有把握時,優先只回滾應用程式碼、保留資料庫在新的 schema(新程式碼通常還是能讀舊 schema,但反過來不一定成立),而不是連 migration 一起回滾。
4. `systemctl restart mpts-gunicorn.service`。
5. 回滾後一樣跑一次關鍵流程確認,並在事後檢討記錄回滾原因。

### 備份與還原

**2026-08-17 已在正式 VM 建立並測試 `deploy/backup_mpts.sh`**(`deploy/systemd/mpts-backup.service`+`.timer`,每天 03:15 執行):

- PostgreSQL:`sudo -u postgres pg_dump -Fc` 自訂格式備份到 `/var/backups/mpts/<timestamp>/db.dump`。
- `media/`:同一次備份打包成 `media.tar.gz`。
- 備份目錄 `/var/backups/mpts` 為 `root:root 0700`,刻意與跑應用程式的 `mpts` 帳號分開(`mpts` 沒有 sudo,即使應用程式被入侵也碰不到備份檔案),符合「備份帳號與應用程式帳號分離」原則。
- 保留天數預設 14 天(`MPTS_BACKUP_RETENTION_DAYS` 環境變數可覆寫),正式保留週期待系辦/資訊中心確認後再調整。
- **這只是本機磁碟備份,不是異地備援**:這台 VM 只有一顆 150GB 系統碟(`lsblk` 確認),資訊中心信件提到的「600G 備份硬碟」並未以區塊裝置掛載到這台 VM,推測是資訊中心自己另外管理的每季全機備份,不是我們能寫入的位置。真正的異地/獨立備份(NFS 或其他)仍是「上線前仍待確認」的項目,在那之前這份本機備份只能防「程式改錯、誤刪資料、bad migration」,防不了整台 VM 或系統碟本身損毀。

**還原步驟**(2026-08-17 已在正式 VM 對一個一次性測試資料庫實際演練過,不只是空跑腳本):

```bash
sudo -u postgres createdb <測試用資料庫名稱>
# 注意重新導向必須由 root 讀取備份目錄(0700),不能讓 postgres 帳號自己開檔:
sudo cat /var/backups/mpts/<timestamp>/db.dump | sudo -u postgres pg_restore -d <測試用資料庫名稱>
# 用實際資料表核對筆數,不能只看指令有沒有噴錯:
sudo -u postgres psql -d <測試用資料庫名稱> -t -c "SELECT count(*) FROM accounts_user;"
sudo -u postgres dropdb <測試用資料庫名稱>
```

`pg_restore -d <db> <path>` 或 `< path` 重新導向這種寫法會因為呼叫的 shell 是 `tcsladmin`(沒有讀取 `/var/backups/mpts` 的權限)而失敗,即使前面加了 `sudo -u postgres` 也一樣——重新導向是呼叫端 shell 處理的,不是 `sudo -u postgres` 之後才處理,務必用 `sudo cat file | sudo -u postgres pg_restore ...` 這種管線寫法,讓「讀檔」這一步用 root 權限完成、「還原」這一步才切成 `postgres` 帳號。`media.tar.gz` 還原只是單純 `tar -xzf`,沒有這個問題。

- **正式上線前至少完成一次「從備份還原到一個獨立測試環境」的演練**,包含資料庫還原與 `media/` 還原後應用程式仍能正常提供下載——只確認備份檔案有產生、從未實際還原過,不能視為備份機制已經可用。目前只驗證過資料庫還原到一次性測試資料庫並核對筆數,**尚未**驗證還原後接上一份完整應用程式實例、`media/` 檔案下載是否正常,建議之後找時間補做這一步。

### 故障排除

- `systemctl status mpts-gunicorn.service`、`journalctl -u mpts-gunicorn.service -n 200` 查看應用程式是否啟動失敗;常見原因是 `.env` 缺漏必要變數觸發 `config/settings.py` 的 fail-closed 檢查(批次2),錯誤訊息會直接說明缺少哪個變數。
- `systemctl status mpts-process-matching-state.timer`、`journalctl -u mpts-process-matching-state.service` 確認排課狀態機是否確實每分鐘執行;長期沒有執行會導致配對/課程狀態(例如學期結束後自動解除配對)沒有即時更新。
- Nginx 502/504:先確認 Gunicorn 是否存活(`systemctl status mpts-gunicorn.service`)、Unix socket 是否存在(`ls -la /run/mpts/`)——`RuntimeDirectory=mpts` 只在服務執行期間存在,服務沒啟動時 socket 目錄也不會在。
- CSP 主控台出現非預期 violation:先確認是不是最近新增的頁面用了 inline `<script>`/`<style>` 或 event handler 屬性(批次6要求一律搬到 `static/`);修正後才考慮是否需要調整政策本身。
- 私人檔案下載出現 403/404 但使用者反映應該有權限:依序檢查——帳號角色是否正確、是否為該堂課/該筆文件的相關人員、`ClassDocument`/`PartnerProgram` 的 `is_active`/`class_documents_enabled` 是否仍為啟用中,這些都是既有受保護下載 view(批次3)判斷可見性的依據。
