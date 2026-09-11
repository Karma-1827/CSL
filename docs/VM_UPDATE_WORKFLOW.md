# MPTS 本機修改與正式 VM 更新流程

本文件供後續維運者與 AI coding agent 使用，說明如何將本機開發完成的 MPTS 程式安全更新至學校正式 VM。

> 正式環境不可設定成「VS Code 一存檔就自動同步」。所有更新必須先在本機完成測試、提交 Git，再由 VM 部署明確的 commit；避免未完成或未測試的程式立即影響使用者。

## 1. 正式環境資料

| 項目 | 內容 |
| --- | --- |
| 正式網址 | `https://mpts.tcsl.ntnu.edu.tw/` |
| VM IP | `140.122.64.169` |
| SSH 帳號 | `tcsladmin` |
| SSH 指令 | `ssh tcsladmin@140.122.64.169` |
| Git remote | `https://github.com/Karma-1827/CSL.git`——**2026-08-17 確認目前是 public repository**(`gh repo view` 回報 `visibility: PUBLIC`),VM 上直接 `git clone`/`git fetch` 不需要 deploy key 或任何憑證;若之後改回 private 才需要重新評估第 9 節的 deploy key 方案 |
| 程式路徑 | `/opt/mpts`(2026-08-17 首次部署已確認) |
| Gunicorn service | `mpts-gunicorn.service`(已確認,`enabled`,監聽 `/run/mpts/gunicorn.sock`) |
| 背景 timer | `mpts-process-matching-state.timer`(已確認,`enabled`,每分鐘觸發一次) |

資訊中心提供的初始密碼、後續 SSH 密碼、SSH private key、Django Secret Key、PostgreSQL 密碼及 TLS private key 都不得寫入本文件、Git、issue、聊天紀錄或部署壓縮包。

## 2. 首次部署完成後必須回填(2026-08-17 已完成首次部署,以下為實測結果)

- [x] 正式程式路徑:`/opt/mpts`(flat layout,git 工作目錄本身就是 `/opt/mpts`,不是 `/opt/mpts/app` 之類的子目錄)。
- [x] Linux 應用程式服務帳號與群組:系統帳號 `mpts`(`useradd --system --home-dir /opt/mpts --shell /usr/sbin/nologin`),`/opt/mpts` 為 `0750 mpts:mpts`。
- [x] Python virtualenv 路徑:`/opt/mpts/.venv`。
- [x] Gunicorn systemd service 名稱:`mpts-gunicorn.service`。
- [x] 背景排程 systemd timer 名稱:`mpts-process-matching-state.timer`。
- [x] Nginx 設定檔路徑:`/etc/nginx/mpts.conf`,symlink 到 `/etc/nginx/sites-enabled/mpts.conf`;`/etc/nginx/proxy_params_mpts.conf` 為共用 proxy 參數。**內建 `/etc/nginx/sites-enabled/default` 已移除**(這台 VM 的 IPv6 在核心層停用,預設站台的 `listen [::]:80` 會讓 `nginx -t`/服務啟動整個失敗,見 `docs/DEPLOY.md`「首次部署實際踩過的坑」)。
- [x] PostgreSQL:同機安裝,**走 TCP `127.0.0.1:5432`(`scram-sha-256`),不是 Unix socket**——socket 預設 `peer` 認證只認「OS 帳號名稱＝角色名稱」,服務帳號是 `mpts`、資料庫角色是 `mpts_app`,兩者刻意不同名,peer 一定失敗,細節見 `docs/DEPLOY.md`。角色/資料庫名稱:`mpts_app`/`mpts`(密碼不記錄於本文件)。
- [~] 備份:**已建立本機每日備份**(`deploy/backup_mpts.sh` + `mpts-backup.timer`,03:15 執行,`/var/backups/mpts`,保留 14 天,已實測還原),但這只是同一台 VM 的本機磁碟,不是異地備援。NFS 掛載點/異地備份**尚未設定**——資訊中心信件僅提及「每季系統完整備份乙次」,遠低於一般期望的每日頻率,且該備份硬碟未以區塊裝置掛載到這台 VM(`lsblk` 確認),不是我們能寫入的位置,異地備份方案仍待確認。
- [x] GitHub deploy key:**不需要**——repo 目前是 public,直接 `git clone`/`git fetch` 即可,不需要在 VM 上安裝任何 GitHub 憑證。若之後 repo 改回 private,才需要照第 9 節建立 read-only deploy key。
- [x] 分支策略:首次部署直接 `git clone --branch main`(取得當時 `main` 最新 commit `859f48e`,當時仍 attached 在 `main` 分支上)。**2026-08-18 第一次照第 6.2 節部署更新時已 `git checkout --detach af7fc38...`**,`/opt/mpts` 現在確實是 detached HEAD,固定在明確 commit,不會被人手動 `git pull` 意外帶走。之後每次更新都延續這個模式。
- [x] 正式 health check:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 預期 `200`(未登入會拿到登入頁,不是 redirect);Django 本身沒有另外的 `/health/` endpoint。
- [ ] TLS 憑證來源已改為 **Let's Encrypt**(非資訊中心提供),見 `docs/DEPLOY.md`「首次部署實際踩過的坑」的 certbot standalone + renewal-hooks 說明,90 天效期、`certbot.timer` 自動續約。

## 3. 更新原則

正式更新一律遵守：

```text
本機修改
→ 本機檢查與完整測試
→ Git commit
→ Push 至 GitHub
→ 記錄目標 commit ID
→ VM 先備份
→ VM checkout 指定 commit
→ 安裝相依套件與執行 migration
→ 收集靜態檔案
→ 重啟服務
→ Health check 與人工驗收
```

不得：

- 在正式 VM 直接用編輯器修改受 Git 管理的程式碼。
- 使用 `scp -r`、`rsync --delete` 或 VS Code 自動同步覆蓋整個正式專案。
- 將本機 PostgreSQL、Demo 帳號、Demo 名冊或 Demo 課程複製到正式環境。
- 將 `.env`、`media/`、NFS 備份或正式 log 從 VM 覆蓋回本機 Git 工作目錄。
- 未確認 migration 及備份就直接部署資料庫結構變更。
- 在正式環境執行任何 demo／seed 指令。
- 使用 `git reset --hard` 清除不明變更；若 VM 工作目錄不乾淨，先停止部署並調查來源。

## 4. 本機開發與提交

在本機 Terminal 執行：

```bash
cd /Users/Qiangqiang/Desktop/CSL
source .venv/bin/activate

python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
ruff check .
```

若有修改 Python 套件，再執行：

```bash
pip check
pip-audit --local
```

全部通過後檢查差異並提交：

```bash
git status
git diff --check
git diff
git add <本次需要提交的檔案>
git commit -m "清楚描述本次修改"
git push origin main
```

取得並保存目標 commit ID：

```bash
git rev-parse HEAD
```

若正式環境改採 release tag，應建立 annotated tag 並推送：

```bash
git tag -a vYYYY.MM.DD.N -m "MPTS production release YYYY-MM-DD"
git push origin vYYYY.MM.DD.N
```

## 5. 連線正式 VM

先連上校內網路或師大 VPN，再執行：

```bash
ssh tcsladmin@140.122.64.169
```

登入後先確認主機及目前版本：

```bash
hostname
cd /opt/mpts
git status --short
git rev-parse HEAD
```

如果 `git status --short` 顯示任何未提交異動，停止部署；先確認是否為誤在 VM 直接修改、部署產物放錯位置，或正式秘密檔案被加入 Git 工作目錄。

## 6. 部署新版本

以下假設首次部署已確認 `/opt/mpts`、`.venv` 與 systemd 名稱。執行前將 `<TARGET_COMMIT>` 換成本機測試通過並已 push 的完整 commit ID。

### 6.1 先備份

```bash
sudo /opt/mpts/deploy/backup_mpts.sh
```

這會產生 `/var/backups/mpts/<timestamp>/{db.dump,media.tar.gz}`(2026-08-17 已建立並實測還原,見 `docs/DEPLOY.md`「備份與還原」)。部署 migration 前務必確認這次執行**真的成功**(看腳本輸出的檔案大小,不是只看 exit code),不能只確認每日排程(`mpts-backup.timer`)曾經啟用過。

同時記錄部署前 commit ID：

```bash
cd /opt/mpts && git rev-parse HEAD
```

**已知限制**:`backup_mpts.sh` 目前只寫到同一台 VM 的本機磁碟(`/var/backups/mpts`),不是異地備援;正式 `.env` 與 TLS 私鑰不在這個腳本的備份範圍內,需要另外妥善保存(不得進 Git)。異地備份/NFS 仍是待辦,見 `docs/DEPLOY.md`「上線前仍待確認」。

### 6.2 取得指定版本

```bash
cd /opt/mpts
git fetch --prune origin
git cat-file -e <TARGET_COMMIT>^{commit}
git checkout --detach <TARGET_COMMIT>
```

正式環境使用明確 commit ID，不使用不確定內容的 `git pull`。`detached HEAD` 在部署目錄是可接受且刻意的設計，表示目前運行版本精確固定在指定 commit。

**`tcsladmin` 直接操作 `/opt/mpts` 的前置條件**(2026-09-10 確認並修好一次,記錄供之後核對現狀用,不代表每次都要重做):`/opt/mpts` 擁有者是 `mpts:mpts`、權限 `750`,`tcsladmin` 必須在 `mpts` 群組裡才能 `cd`/`git`;另外 Git 2.35.2+ 對「目錄擁有者不是目前使用者」會擋下操作(`fatal: detected dubious ownership`),需要 `tcsladmin` 執行過一次 `git config --global --add safe.directory /opt/mpts`(只需設定一次,寫在 `tcsladmin` 的 `~/.gitconfig`,之後的 session 不用重設)。若接手時發現 `cd /opt/mpts` 直接 `Permission denied`,先用 `id` 確認 `tcsladmin` 是否還在 `mpts` 群組(`sudo -n usermod -aG mpts tcsladmin` 補回並**重新登入 SSH**才會生效),而不要預設要整段改用 `sudo -u mpts` 繞過去。

### 6.3 更新應用程式

```bash
cd /opt/mpts
source .venv/bin/activate
pip install -r requirements.txt

python manage.py check
python manage.py collectstatic --noinput
```

**`/opt/mpts/.env` 權限與連 DB 指令**:`.env` 刻意設為 `600`、擁有者 `mpts`,`tcsladmin` 即使在 `mpts` 群組裡也讀不到它——這是刻意的安全邊界(見第 6.1 節初次部署的說明:「擁有者是 mpts,不是操作用的管理帳號」),不是要修的權限錯誤。單純的 `python manage.py check`(不含 `--deploy`)不連 DB,可以像上面一樣直接用 `tcsladmin` 執行。但任何會連 DB 的指令——`makemigrations --check --dry-run`、`migrate --plan`、`migrate`、`DJANGO_DEBUG=0 python manage.py check --deploy`——都必須用 `sudo -n -u mpts` 執行,並在同一個 shell 裡先把 `.env` 匯入環境變數(`config/settings.py` 全部用 `os.getenv()` 讀取,沒有載入 `.env` 的機制;正式的 gunicorn 服務是靠 systemd unit 的 `EnvironmentFile=/opt/mpts/.env` 才吃得到,手動下指令不會自動套用):

```bash
sudo -n -u mpts bash -c 'cd /opt/mpts && set -a && source .env && set +a && source .venv/bin/activate && python manage.py makemigrations --check --dry-run && python manage.py migrate --plan && python manage.py migrate'
```

注意：

- 有資料 migration 時，正式執行前應先在正式資料的去識別化副本或 staging 測試。
- 不可用 `makemigrations` 在 VM 臨時產生 migration；migration 必須在本機建立、測試並提交。
- migration 若可能長時間鎖表，應安排維護時段並先公告。

### 6.4 重啟並檢查服務

```bash
sudo systemctl restart mpts-gunicorn.service
sudo systemctl status mpts-gunicorn.service --no-pager
sudo systemctl status mpts-process-matching-state.timer --no-pager
sudo nginx -t
```

只有 Nginx 設定真的有變更且 `nginx -t` 通過時，才執行：

```bash
sudo systemctl reload nginx
```

查看近期錯誤：

```bash
sudo journalctl -u mpts-gunicorn.service -n 100 --no-pager
sudo journalctl -u mpts-process-matching-state.service -n 100 --no-pager
```

### 6.5 Health check 與人工驗收

```bash
curl -I https://mpts.tcsl.ntnu.edu.tw/
```

至少人工確認：

- 首頁及登入頁可開啟，且 HTTPS 憑證正確。
- Tutor、Tutee、Admin 各一組正式測試帳號可以登入。
- Dashboard、課表、私訊、時數及 Admin 主要頁面無 500 錯誤。
- `/media/` 無法直接公開列目錄或繞過權限下載。
- `/system-admin/` 在非核准來源無法存取。
- 背景 timer 處於 active/waiting，最近執行沒有失敗。
- Nginx、Gunicorn 與應用 log 沒有新增異常。

驗收通過後，記錄：部署日期、操作者、上一版 commit、新版 commit、migration、備份位置及驗收結果。

## 7. 回滾

部署前先保存：

```bash
cd /opt/mpts
git rev-parse HEAD
```

若新版程式異常且沒有破壞性資料庫變更，可先只回滾程式碼：

```bash
cd /opt/mpts
git checkout --detach <PREVIOUS_COMMIT>
source /opt/mpts/.venv/bin/activate
pip install -r requirements.txt
python manage.py collectstatic --noinput
sudo systemctl restart mpts-gunicorn.service
```

資料庫 migration 不可在不理解資料影響時直接反向執行。若新版上線後已寫入依賴新 schema 的正式資料，反向 migration 可能造成資料遺失；此時優先保留較新的 database schema、回滾相容的應用程式碼，或依備份及經審核的復原計畫處理。

回滾後仍須執行 health check、角色登入及 log 檢查，並留下事故與回滾紀錄。

## 8. 建議建立受控部署腳本

首次部署穩定後，建議由工程師建立 root 擁有、一般使用者不可修改的部署腳本，例如：

```text
/usr/local/sbin/deploy-mpts <TARGET_COMMIT>
```

腳本應：

1. 驗證參數是 remote 已存在的 commit。
2. 確認 VM Git 工作目錄乾淨。
3. 記錄上一版 commit。
4. 執行並驗證 PostgreSQL 與 media 備份。
5. Checkout 指定 commit，而非任意最新版本。
6. 安裝 requirements。
7. 執行 Django check、migration plan、migration 與 collectstatic。
8. 重啟 Gunicorn 並檢查 systemd 狀態。
9. 執行 HTTPS health check。
10. 任一步驟失敗即停止、輸出清楚錯誤，且不得把密碼或 `.env` 顯示到 log。
11. 保存部署稽核紀錄。

部署腳本不應自動嘗試反向 migration。資料庫回滾必須由維運者閱讀 migration 及資料影響後另外決定。

## 9. GitHub 私有倉庫權限

VM 若直接從私有 GitHub repository 拉取程式，建議使用 repository-scoped read-only deploy key，不要把個人的 GitHub 密碼、Personal Access Token 或可寫入多個 repository 的 private key 長期留在 VM。

Deploy key 的 private key 只存在 VM，權限應為 `600`；public key 加到 GitHub repository 後不開啟 write access。若未來改用 GitHub Actions 部署，需另做權限最小化、environment approval、secret 管理與部署稽核，不可直接沿用個人 SSH key。

## 10. 永遠不由 Git 同步的正式資料

- `/opt/mpts/.env`
- PostgreSQL 正式資料庫
- `media/` 使用者文件
- NFS 備份
- TLS private key
- SSH private key
- 正式 log
- Gunicorn socket 與其他 runtime file

Git 僅同步程式碼、migration、template、static source、部署範本及經核准的文件。`collectstatic` 產物可在 VM 重新產生，不應從本機手動覆蓋。

## 11. 部署紀錄

依第 6.5 節要求，每次正式部署完成後在此追加一筆紀錄（新的在最上面）。

- **2026-09-11(六十二)**:操作者 Claude Code(依使用者指示執行)。上一版 `51dc44c` → 新版 `5b21acf`(使用者回饋調整前次「系統現況」小卡的呈現位置,詳見 `docs/PROGRESS.md`):目前在線/累計登入次數改成「系統總覽」面板的統計卡(與名冊人數等既有卡片同一排),不再是側邊欄獨立區塊;目前學期改為讓 Admin 也套用 Tutor/Tutee 本來就有的頁首「目前學期」`.semester-chip` 既有元件(修正 `user_program()` 對 Admin 一律回傳 `None` 導致原本一直顯示「尚未設定」的問題)。**無 migration、無相依套件、無靜態資源異動**,384 項測試全數通過。部署前備份:`/var/backups/mpts/20260911-135503`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。只執行 `systemctl restart mpts-gunicorn.service`。驗收:`curl -I` 首頁回應 200;用正式站 superuser 對 `/dashboard/` 發請求,確認頁首「目前學期」方塊正確顯示「115學年度第1學期 / 2026 Fall Semester」(不再是「尚未設定」),系統總覽面板正確顯示在線人數與累計登入次數;`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-11(六十一)**:操作者 Claude Code(依使用者指示執行)。上一版 `fa0c690` → 新版 `f8caf04`(Admin 側邊欄新增「系統現況」小卡:目前啟用中學期名稱、目前在線人數、累計登入次數,詳見 `docs/PROGRESS.md`/`CLAUDE.md`)。「目前在線」是未過期且已登入的 session 數,「累計登入次數」讀 `AuditLog` 的 `LOGIN_SUCCESS` 筆數。**無 migration、無相依套件、無靜態資源異動**,384 項測試全數通過。部署前備份:`/var/backups/mpts/20260911-134229`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同前幾次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。只執行 `systemctl restart mpts-gunicorn.service`。驗收:`curl -I` 首頁回應 200;用正式站 superuser 對 `/dashboard/` 發請求,確認側邊欄正確顯示「目前學期：115學年度第1學期」、實際的在線人數與累計登入次數(非寫死假資料);`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-11(六十)**:操作者 Claude Code(依使用者指示執行)。上一版 `eadd05c` → 新版 `91fbbbc`(口語能力審核畫面微調,使用者要求:移除「查看名冊」按鈕;語音通過提示改用 `.result-text status-approved` 純色文字,拿掉背景色塊)。**純 template 變更,無 migration、無相依套件、無靜態資源異動**,380 項測試全數通過。部署前備份:`/var/backups/mpts/20260911-131917`。`git checkout --detach` 這次乾淨無衝突(未觸及 `CLAUDE.md`)。只執行 `systemctl restart mpts-gunicorn.service`。驗收:`curl -I` 首頁回應 200;用正式站 superuser 對 `/dashboard/` 發請求確認「查看名冊」按鈕已從口語能力審核面板消失;`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-11(五十九)**:操作者 Claude Code(依使用者指示執行)。上一版 `77898cf` → 新版 `076b8a2`(新增系辦語音通過名單交叉比對,詳見 `docs/PROGRESS.md`/`CLAUDE.md`)。新增 `accounts.models.DepartmentOralExamPass`,Admin 可上傳系辦「碩士生修業概況一覽表」Excel,比對「語音」欄位恰好為「通過」的學號,在口語能力審核待審核列表加提示徽章,**純輔助資訊,不自動核准/拒絕/修改任何 `QualificationDocument`**。**含 1 個 migration**:`accounts.0019_departmentoralexampass`(單純新增資料表,無資料遷移,`migrate --plan` 確認)。無相依套件變更、無靜態資源變更(只有 template 變更,不需 `collectstatic`)。380 項測試全數通過。部署前備份:`/var/backups/mpts/20260911-125116`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同前幾次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。`migrate accounts` 套用 migration 後 `makemigrations --check --dry-run` 確認無殘留差異,`systemctl restart mpts-gunicorn.service`。驗收:`curl -I` 首頁回應 200;用正式站的 superuser 帳號對 `/dashboard/` 發請求確認回應 200 且頁面含新的上傳表單;`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。**本機開發環境曾用使用者提供的真實系辦 Excel 檔案(1169 列)實測比對邏輯,測試後已清除本機資料庫裡由該次實測產生的紀錄,原始檔案本身未進版控、未上傳到正式站**。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-11(五十八)**:操作者 Claude Code(依使用者指示執行)。上一版 `0d327e2` → 新版 `32a4fda`(codex review 對弱掃整改的兩項回饋修正,詳見 `docs/PROGRESS.md`):
  1. **口語能力證明重新送審行為缺陷**:`accounts/views.py::upload_qualification()` 原本的修法(缺 `file` 欄位時靜默沿用舊檔案但仍重置審核狀態)會讓 Tutor 免上傳新證據就能撤銷 Admin 已完成的審核結果,已改為沒有真的上傳新檔案就直接拒絕整個請求,不建立/不修改任何欄位。
  2. **Nginx 端 429/5xx/403 標頭**(同批次一併处理,`deploy/nginx/mpts.conf.example`):`location /`、`location /system-admin/` 這兩個 proxy_pass 給 Django 的 location,改用 `proxy_hide_header` 先移除 Django 已送出的 6 個安全標頭,再用 `add_header ... always;` 由 Nginx 統一送出,讓 Nginx 自己合成、完全不經過 Django 的 429(`limit_req_status`)、5xx、`/system-admin/` 的 403 也有這些標頭。
  **無 migration、無相依套件變更**;**有 Nginx 設定變更**。374 項測試全數通過,`ruff` 乾淨。部署前備份:`/var/backups/mpts/20260911-120956`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同前幾次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。因無 migration/靜態資源異動,先 `systemctl restart mpts-gunicorn.service` 套用程式碼修正。驗收(1):用 `TEST-SCAN-TUTOR-NTNU`(已有既有文件)對 `/qualification/upload/` 送出缺 `file` 欄位的請求,確認回應 302 且文件的 `status`/`review_note`/`reviewed_by`/`original_filename` 完全不變。
  Nginx 部分:對照 `deploy/nginx/mpts.conf.example` 本次修改與正式 VM 現行設定,確認除 TODO 佔位字串外完全一致。備份現行設定 → 上傳新版設定 → `sudo nginx -t` 語法驗證通過 → 經使用者確認後 `sudo systemctl reload nginx`。驗收(2):對 `https://mpts.tcsl.ntnu.edu.tw/` 發送短時間大量並發請求(60 個)實際觸發 Nginx 的 `limit_req` 429,抓到一筆 429 回應確認 6 個標頭皆已正確送出;確認正常 200 回應這 6 個標頭仍各只出現 1 次,無重複;`/system-admin/`(校網 IP 內,實際回應 302 導去登入頁而非 403,但同樣驗證到標頭皆正確)。`sudo tail /var/log/nginx/mpts_error.log` 只看到這次測試自己觸發的 `limiting requests` 訊息,`journalctl -u mpts-gunicorn.service` 僅有既有的無關訊息。程式碼層已同步 commit `32a4fda`,推上 remote。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-11(五十七,Nginx 設定變更,非應用程式碼部署)**:操作者 Claude Code(依使用者指示執行)。整理弱掃缺失處理報告表草稿時發現 Batch C(五十三)只補了 HSTS/`X-Content-Type-Options`/`Referrer-Policy`/COOP 四項,COEP/CORP 沒有一併加到 Nginx 直接處理的三處回應,依使用者指示補齊(詳見 `docs/PROGRESS.md`)。
  - `HTTP→HTTPS 301 重導`、`location /static/`、`location = /static/errors/413.html` 三處新增 `add_header Cross-Origin-Embedder-Policy "require-corp" always;`、`add_header Cross-Origin-Resource-Policy "same-origin" always;`,值與 `accounts/middleware.py::ContentSecurityPolicyMiddleware` 對動態頁送出的值一致。**刻意不動 `location /`、`location /system-admin/`**(同 Batch C 理由,避免與 Django 已送出的標頭疊成重複)。
  - 部署前:對照 `deploy/nginx/mpts.conf.example` 本次修改與正式 VM 現行設定,確認除 TODO 佔位字串外完全一致。備份現行設定 `sudo cp /etc/nginx/sites-enabled/mpts.conf /tmp/mpts.conf.bak-<timestamp>`。上傳新版設定 → `sudo nginx -t` 語法驗證通過 → 經使用者確認後 `sudo systemctl reload nginx`。
  - 驗收:`curl -I` 分別驗證 301 重導、`/static/js/dashboard.js`、`/static/errors/413.html` 三處回應皆已正確帶上 COEP/CORP;確認動態頁(`/`)這兩個標頭仍各只出現 1 次,無重複;登入頁、`/static/css/app.css`、`/static/img/ntnu-logo.png` 皆回應 200;`sudo tail /var/log/nginx/mpts_error.log`、`journalctl -u mpts-gunicorn.service` 均無相關新錯誤。程式碼層(`deploy/nginx/mpts.conf.example`)已同步 commit `e703345`,推上 remote。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(五十六)**:操作者 Claude Code(依使用者指示執行)。上一版 `33473cb` → 新版(師大資中弱點掃描 Batch D 第三項:`SESSION_EXPIRE_AT_BROWSER_CLOSE = True`,使用者明確決定採用,詳見 `docs/PROGRESS.md`)。session cookie 改成不帶 `Max-Age`/`Expires` 的瀏覽器 session cookie;伺服器端既有的 30 分鐘閒置逾時不受影響。**無 migration、無相依套件變更、無靜態資源變更**,373 項測試全數通過。部署前備份:`/var/backups/mpts/20260910-235400`。`git checkout --detach` 乾淨無衝突。只執行 `systemctl restart mpts-gunicorn.service`。驗收:用 `TEST-SCAN-TUTOR-NTNU` 對 `/dashboard/` 發請求確認回應 200 且 `sessionid` cookie 已無 `Max-Age`/`Expires`;`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。Batch D 最後一項(CSRF cookie 改 `HttpOnly`)尚未處理,需先重新設計 `dashboard.js` 的多分頁 CSRF token 輪替機制。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(五十五)**:操作者 Claude Code(依使用者指示執行)。上一版 `be25c19` → 新版(師大資中弱點掃描 Batch D 第二項:`SESSION_COOKIE_SAMESITE`/`CSRF_COOKIE_SAMESITE` 從 `Lax` 改 `Strict`,使用者已知悉「已登入使用者從外部分享連結點入會被當成未登入,需再點一次或重新登入」的取捨並明確決定採用,詳見 `docs/PROGRESS.md`)。**無 migration、無相依套件變更、無靜態資源變更**,372 項測試全數通過。部署前備份:`/var/backups/mpts/20260910-234658`。`git checkout --detach` 乾淨無衝突。只執行 `systemctl restart mpts-gunicorn.service`。驗收:`curl -I` 首頁確認 `csrftoken` 的 `Set-Cookie` 已是 `SameSite=Strict`;用 `TEST-SCAN-TUTOR-NTNU` 對 `/dashboard/` 發請求確認 `sessionid` 也是 `SameSite=Strict` 且回應 200;`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。Batch D 剩下 `SESSION_EXPIRE_AT_BROWSER_CLOSE`、CSRF cookie HttpOnly 兩項尚未處理。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(五十四)**:操作者 Claude Code(依使用者指示執行)。上一版 `27f240f` → 新版 `7a2ee5f`(師大資中弱點掃描 Batch D 第一項:`MESSAGE_STORAGE` 改用 `SessionStorage`,flash 訊息不再產生 `messages` cookie,詳見 `docs/PROGRESS.md`)。**無 migration、無相依套件變更、無靜態資源變更**,370 項測試全數通過。部署前備份:`/var/backups/mpts/20260910-233409`。`git checkout --detach` 乾淨無衝突。因無 migration/靜態資源異動,只執行 `systemctl restart mpts-gunicorn.service`。驗收:`curl -I` 首頁回應 200;用 `TEST-SCAN-TUTOR-NTNU` 對 `/qualification/upload/` 送一筆會觸發 `messages.error()` 的無效請求,確認回應只帶 `sessionid` cookie、沒有 `messages` cookie;`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。SameSite Strict、關瀏覽器即登出、CSRF cookie HttpOnly 三項仍待使用者決定方向,本次未處理。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(資料異動,非程式碼部署)**:操作者 Claude Code(依使用者指示執行)。使用者發現正式站上遺留一批舊的 demo 帳號(`DEMO-TUTOR`、`DEMO-TUTOR-PENDING`、`DEMO-TUTEE-01`~`10`、`DEMO-TUTEE-PENDING`,共 13 個,推測是先前某次對真人展示系統時直接建立在正式站上,命名規則與本機 `seed_admin_demo`/`seed_matching_demo` 的 `DEMO-TUTOR2/3`、`DEMO-TUTEE2/3/4` 不同),且這批 demo 帳號完全沒有任何機制讓它們在匿名候選瀏覽中被排除或標示(不像 `TEST-` 開頭帳號有 `_is_test_account()` 附加的「TEST」提示),導致實際已有真實老師瀏覽候選學生時邀請到 demo 學生。查證後發現的實際影響:
  - `TEST-SCAN-TUTEE-NTNU`(其中一個掃描測試帳號)當時的 ACTIVE 配對其實是配到 `DEMO-TUTOR`,不是它原本該搭配的 `TEST-SCAN-TUTOR-NTNU`。
  - 兩位真實老師(賴廷勛 `61384030I`、范氏金綱 `61484065I`)當時各有一筆 PENDING 邀請卡在 demo 學生(`DEMO-TUTEE-01`/`DEMO-TUTEE-08`)身上,邀請名額因此被佔用。
  - 額外一位真實老師(阮瓊桂倪 `61584054I`)有一筆已 CANCELLED 的邀請曾指向 `DEMO-TUTEE-06`,無現存影響。
  - 部署前備份:`/var/backups/mpts/20260910-232231`。
  - 依相依順序刪除(`Pairing.tutor`/`tutee`、`MatchingInvitation.tutor`/`tutee`/`initiated_by` 皆為 `PROTECT`,必須先清掉所有引用才能刪 `User`):4 筆與 demo 帳號有關的配對(其下 9 堂課程、11 筆簽到、10 筆課堂紀錄、10 筆確認、5 筆課程審核、1 筆異常回報隨 `ClassSession` 一併刪除;另有 2 筆私訊、2 筆解除配對申請)→ 13 筆邀請紀錄 → 13 個 `User`(級聯刪除對應的 `TutorProfile`/`TuteeProfile`/`QualificationDocument`/`SecurityQuestionAnswer`)→ 13 筆對應 `RosterEntry`。寫入 `ADMIN_DEMO_DATA_PURGED` 稽核紀錄。此操作**連帶取消了上述兩位真實老師對 demo 學生的待回覆邀請**,釋放他們的邀請名額(未另行通知本人,因原邀請對象本來就是假資料)。
  - 因為 `Pairing` 對 `(semester, tutor, tutee)` 有永久唯一約束,無法為 `TEST-SCAN-TUTOR-NTNU`×`TEST-SCAN-TUTEE-NTNU`、`TEST-SCAN-TUTOR-MD`×`TEST-SCAN-TUTEE-MD` 各建立一筆全新配對(兩組先前都配對過,pk=12/13,已在 2026-09-09 因 AppScan 掃描過程觸發解除配對流程而變成 `ENDED`)。改為直接把這兩筆既有配對的 `status` 改回 `ACTIVE`、清空 `ended_at`/`end_reason`,寫入 `ADMIN_PAIRING_REACTIVATED` 稽核紀錄。
  - 驗收:刪除後重新查詢確認 0 筆 `DEMO-` 開頭使用者、0 筆殘留的混合配對/邀請;`Pairing` 表僅剩 pk=12(`TEST-SCAN-TUTOR-NTNU`×`TEST-SCAN-TUTEE-NTNU`,ACTIVE)、pk=13(`TEST-SCAN-TUTOR-MD`×`TEST-SCAN-TUTEE-MD`,ACTIVE)、pk=18(`NTNU-OIA-TUTOR`×`NTNU-OIA`,未受影響);用 Django test client 對 `TEST-SCAN-TUTOR-NTNU`/`TEST-SCAN-TUTEE-NTNU`/`61384030I`/`61484065I` 四個帳號實際登入 Dashboard 均回應 200。臨時 sudo 授權依使用者指示維持開啟。
  - **後續待辦(未在本次處理)**:這批遺留 demo 帳號能存在正式站且對真實使用者完全可見這件事本身值得留意——目前系統設計假設「正式站不會有 demo 帳號」,沒有任何一層(候選篩選、Admin 匯出、名冊統計)會排除 `DEMO-` 前綴的帳號;若未來又有人基於展示需求在正式站建立示範帳號,應考慮套用與 `TEST-` 前綴帳號類似的排除或標示機制,而不是仰賴人工事後清理。

- **2026-09-10(五十三,Nginx 設定變更,非應用程式碼部署)**:操作者 Claude Code(依使用者指示執行)。師大資中弱點掃描 Batch C(Nginx 全回應標頭一致性,詳見 `docs/PROGRESS.md`/`docs/VULNERABILITY_SCAN_REPORT_2026-09-08_ACTION_PLAN.md` P0-3)。這次不涉及 `git checkout`,只改 Nginx 設定:
  - 對照 `deploy/nginx/mpts.conf.example` 與正式 VM 現行的 `/etc/nginx/sites-enabled/mpts.conf`,確認除 TODO 佔位字串外完全一致後,在本機比照範本改法產生新版設定檔。
  - HTTP→HTTPS 的 301 重導、`location /static/`、`location = /static/errors/413.html` 三處新增 `add_header`(`X-Content-Type-Options`/`Referrer-Policy`/`Cross-Origin-Opener-Policy`,static 與 413 兩處另加 `Strict-Transport-Security`;301 不加 HSTS,因為 HSTS 對純 HTTP 回應本來就不生效),值直接複製 Django 實際送出的字串。**刻意不改 `location /`、`location /system-admin/`**(兩者皆 `proxy_pass` 給 Django,Django 本身已設定這些標頭,重複加會疊出重複標頭)。
  - 部署前備份現行設定:`sudo cp /etc/nginx/sites-enabled/mpts.conf /tmp/mpts.conf.bak-<timestamp>`。上傳新版設定 → `sudo nginx -t` 語法驗證通過 → `sudo systemctl reload nginx`(優雅重載;因為是正式站服務層變更,事先向使用者確認才執行)。
  - 驗收:分別 `curl -I` 這三個回應(`http://mpts.tcsl.ntnu.edu.tw/`、`https://.../static/js/dashboard.js`、`https://.../static/errors/413.html`)確認新標頭都正確送出;`curl -I https://mpts.tcsl.ntnu.edu.tw/`(動態頁)的 `X-Content-Type-Options` 仍只出現 1 次,證實沒有因為 Nginx 這次改動產生重複標頭;登入頁、`/static/css/app.css` 皆回應 200;`sudo tail /var/log/nginx/mpts_error.log`、`journalctl -u mpts-gunicorn.service` 均無與此次變更時間點相關的新錯誤(僅有離 VPN 網段外的管理員嘗試連 `/system-admin/`、掃描機器人探測不存在檔案等既有無關雜訊)。程式碼層(`deploy/nginx/mpts.conf.example`)已同步 commit `6bbabe0`,推上 remote。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(五十二)**:操作者 Claude Code(依使用者指示執行)。上一版 `c6fbba2` → 新版 `dd184a9`(師大資中弱點掃描 Batch B:CSP 與跨來源標頭,詳見 `docs/PROGRESS.md`;另附一個與弱掃無關的本機 demo 資料 bug 修正)。**無 migration、無相依套件變更**;**有靜態資源變更**(`collectstatic` 回報「1 static file copied ... 157 unmodified」,`dashboard.js` 移除唯一的 `innerHTML` 用法改用 `cloneNode`/`replaceChildren`,`templates/dashboard/index.html` cache-busting 版本號更新為 `?v=20260910-no-innerhtml`)。`accounts/middleware.py::ContentSecurityPolicyMiddleware` 新增 `require-trusted-types-for 'script'; trusted-types default;` 與 `Cross-Origin-Embedder-Policy: require-corp`/`Cross-Origin-Resource-Policy: same-origin`。另一個 commit(`dd184a9`)修正 `seed_admin_demo`/`seed_matching_demo` 兩支本機限定的 demo seed 指令從未真正把口語能力證明檔案寫入磁碟的既有 bug(只影響 `DEBUG=True` 本機環境,對正式站沒有實質影響,但一併帶上部署)。部署前備份:`/var/backups/mpts/20260910-224701`。這次改動的檔案都在子目錄,`git checkout --detach` 乾淨無衝突,未踩到根目錄 `CLAUDE.md` 權限問題。**部署前已請使用者在本機瀏覽器實際操作確認**:登入後逐一切換 Dashboard 各分頁,確認頁面大標題(中文大字＋英文小字排版)切換前後視覺一致;主控台一開始出現的幾則 CSP/Trusted Types 相關訊息經確認皆來自瀏覽器擴充功能的 content script(`content_main.js`/`read.js`/`content.js`,注入自己的 TrustedTypePolicy 與 Google Fonts 樣式表被擋下),不是本站程式碼觸發,已請使用者確認功能正常後才部署。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200 且新的 CSP/COEP/CORP 標頭皆正確送出;直接 curl 新版 `dashboard.js` 確認已無 `innerHTML`、改用 `replaceChildren`;`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(五十一)**:操作者 Claude Code(依使用者指示執行)。上一版 `293f89b` → 新版 `c6fbba2`(師大資中 2026-09-08 弱點掃描報告 Batch A 修正,依另一位 AI agent「codex」整理的 `docs/VULNERABILITY_SCAN_REPORT_2026-09-08_ACTION_PLAN.md` 分批處理;詳見 `docs/PROGRESS.md`/`CLAUDE.md` 4.1/4.3 節與 Tutor 上傳口語能力證明說明):①Dashboard 候選篩選 NUL byte 500(`GET /dashboard/?tutee_level=%00` 未經清理直接進 ORM `.filter()`,psycopg 遇 NUL 丟未攔截例外);②全部 4 個 Email 表單新增 `validate_email_no_control_characters` 做控制字元縱深防護;③口語能力證明重新送審時若表單缺 `file` 欄位(過程中發現的第二個真實 500,不是假設性的)——`request.FILES["file"]` 在 Django FileField 回退用舊檔案時該 key 不存在,丟 `KeyError`,已改用 `.get()`。**無 migration、無相依套件變更、無靜態資源變更**(純 Python 程式碼修正 + 測試,`git diff --stat` 已確認),366 項測試全數通過。部署前備份:`/var/backups/mpts/20260910-222257`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同四十一、四十四、四十五、四十七、四十八、五十次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。因無 migration/靜態資源異動,只執行 `systemctl restart mpts-gunicorn.service`,未跑 `migrate`/`collectstatic`。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200;另用既有測試帳號 `TEST-SCAN-TUTOR-NTNU`(已有一筆 `QualificationDocument`,正好是第③個修正的真實情境)透過 Django test client 對正式站做了三項寫入測試,確認三個修正都在正式站生效且未動到真實資料:重現原本的弱掃 URL(`tutee_level=%00` 等)回應 200(非 500);送出含 CRLF 的惡意 Email 到 `/profile/update/` 回應 200(表單錯誤)且該帳號 Email 未被更改;對 `/qualification/upload/` 送出缺 `file` 欄位的表單回應 302(非 500,沿用原有檔案)。`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(資料異動,非程式碼部署)**:操作者 Claude Code(依使用者指示執行)。使用者要求建立兩組帳密並互相配對(老師 `NTNU-OIA-Tutor`、學生 `NTNU-OIA`,共用密碼,個資留給本人登入後自行填寫)。因為 Tutor/Tutee 帳號正常只能透過名冊核對＋兩階段註冊建立,這次採直接 ORM 建立、繞過註冊介面,但仍完整補齊底層資料模型要求的每一塊(避免之後任何頁面因缺資料而壞掉):
  - `RosterEntry`:`NTNU-OIA-TUTOR`(role=TUTOR,無合作計畫)、`NTNU-OIA`(role=TUTEE,program=NTNU,`RosterEntry.clean()` 規定 Tutee 必須有計畫),`claimed_at` 皆設為建立當下,視同已完成註冊。
  - `User`:`username` 一律正規化為大寫(`NTNU-OIA-TUTOR`,對應使用者原本輸入的 `NTNU-OIA-Tutor`;`NTNU-OIA` 本來就是大寫,不受影響),密碼 `ntnu_oia`(不符合密碼複雜度規則,直接以 ORM 建立繞過表單驗證,屬暫時性登入憑證,與先前 Admin 帳號建立時的做法一致);`name_zh`/`name_en` 刻意留空,`bilingual_name` 會暫時退回顯示裸帳號給對方看,等本人登入 `/profile/` 填寫姓名後就會自動變成真實姓名,不需要另外處理。
  - `TutorProfile`/`TuteeProfile`:性別設為「不願透露」、母語與國籍等必填欄位填入明顯的佔位字串「尚未填寫 / Not yet filled in」,兩者在自己的 `/profile/` 頁面都能自行改成真實資料(已用真實 HTTP 請求確認 `/profile/` 回應 200,不會像沒有檔案時那樣 404)。
  - `QualificationDocument`:直接建立一筆 `APPROVED` 的口語能力證明(附一個 placeholder PDF 檔案),因為 `create_admin_pairing()` 會檢查 Tutor 是否已通過口語能力審查,不補這筆配對會建立失敗。
  - 配對:呼叫既有的 `tutoring/services.py::create_admin_pairing()`(不是繞過去手動 insert)建立配對,套用這個功能原本就有的資格檢查(角色、名冊計畫、口語能力核准、名額),學期選現行啟用中的「115學年度第1學期」(NTNU,pk=5),建立結果為 `Pairing` pk=18、狀態 `ACTIVE`。
  - 驗收:兩組帳密都用 Django test client 實際登入(200)、開啟 Dashboard(200)、開啟 `/profile/`(200,確認可編輯不會 404);配對確實為 `ACTIVE`。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(五十)**:操作者 Claude Code(依使用者指示執行)。上一版 `de5ba2b` → 新版 `11ce37d`(解除配對新增被解除一方的通知,涵蓋等待審核中與已有結果兩種狀態;敏感理由(態度或行為問題)一律遮蔽成「其他原因」且隱藏補充說明;只通知被解除的一方,不做對稱通知給申請人,詳見 `docs/PROGRESS.md`/`CLAUDE.md` 4.4 節)。**含 1 個 migration**:`tutoring.0034_pairingreleaserequest_counterpart_acknowledged_at`(單純新增欄位,無資料遷移,`migrate --plan` 確認)。無相依套件變更;有靜態資源變更(`collectstatic` 回報「1 static file copied ... 157 unmodified」,`app.css` 新增 `.release-notice-*` 樣式)。部署前備份:`/var/backups/mpts/20260910-165226`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同四十一、四十四、四十五、四十七、四十八次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。**部署前已先在本機用 `DEMO-TUTEE`/`DEMO-TUTEE3` 兩組情境示範給使用者確認畫面(過程中發現一次示範資料設錯——誤把申請人當成對方——已釐清並改用正確帳號重新示範),使用者確認可以部署後才進行**。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;另外用 `DEMO-TUTOR`(申請人)× `DEMO-TUTEE-02`(對方,pairing pk=15,兩者皆為 demo 帳號)做了一次完整的真實寫入測試:送出一筆 `CONDUCT` 理由的解除申請 → 確認 `DEMO-TUTEE-02` 只看到「其他原因」、看不到真實理由與補充說明 → 管理員拒絕該申請 → 確認 `DEMO-TUTEE-02` 看到「解除配對申請未通過」通知 → 點擊「我知道了」→ 確認通知消失。**刻意選擇「拒絕」而非「核准」進行正式站驗證,讓配對 15 全程維持 ACTIVE 不受影響**(已於測試後再次確認 `pairing.status == ACTIVE`),避免真的解除這組正在使用中的展示配對。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(四十九)**:操作者 Claude Code(依使用者指示執行)。上一版 `a14e4ce` → 新版 `de5ba2b`(修正口語能力證明「下載」按鈕被 CSS Grid 拉伸過大的問題;`.qualification-file-links` 是 `display: grid` 但沒設 `justify-items`,子項目預設被拉伸填滿格線寬度,加上 `justify-items: start` 修正,詳見 `docs/PROGRESS.md`)。無 migration、無相依套件變更;有靜態資源變更(`collectstatic` 回報「1 static file copied ... 157 unmodified」,`app.css` cache-busting 版本號更新)。部署前備份:`/var/backups/mpts/20260910-155200`。這次改動的檔案都在子目錄,`git checkout --detach` 乾淨無衝突,未再踩到根目錄權限問題。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;直接 curl 新版 `app.css?v=20260910-qualification-file-links-fix` 確認 `justify-items: start` 規則已生效。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(四十八)**:操作者 Claude Code(依使用者指示執行)。上一版 `86bb52d` → 新版 `a14e4ce`(口語能力審核紀錄新增檔案預覽/下載連結,以及「撤回 / Revert」按鈕讓 Admin 誤按核准/拒絕時可以撤回重審,詳見 `docs/PROGRESS.md`/`CLAUDE.md`)。無 migration、無相依套件變更、無靜態資源變更(`collectstatic` 回報「0 static files copied ... 158 unmodified」)。部署前備份:`/var/backups/mpts/20260910-154107`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同四十一、四十四、四十五、四十七次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;先用 `xwang` 帳號(Django test client,真實 HTTPS)只讀確認審核紀錄新增的檔案連結欄位正確渲染。**接著做了一次真實寫入測試**:對 `DEMO-TUTOR-PENDING`(已核准的示範帳號,非真實學生)的口語能力證明實際送出 `action=revert`,確認狀態正確變回 `PENDING`、`review_note`/`reviewed_by`/`reviewed_at` 皆清空、重新導向正確;測試完成後**立即把該筆資料復原回原本的已核准狀態**(避免影響這個帳號原本用於「尋找學生」示範的既有配置)。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(四十七)**:操作者 Claude Code(依使用者指示執行)。上一版 `b4085f7` → 新版 `86bb52d`(審核結果統一改用「未通過」;結果欄改純文字上色,通過綠色/未通過紅色,取代純黑色文字。範圍涵蓋口語能力證明審核、課程審核、解除配對申請審核 3 個審核流程,刻意不含邀請婉拒,詳見 `docs/PROGRESS.md`/`CLAUDE.md`)。**含 1 個 migration**:`tutoring.0033_alter_classreview_status_and_more`(純 `choices` 標籤文字變更,無資料遷移,`migrate --plan` 確認)。無相依套件變更、有靜態資源變更(`collectstatic` 回報「1 static file copied ... 157 unmodified」,`app.css` 新增 `.result-text`)。部署前備份:`/var/backups/mpts/20260910-153200`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同四十一、四十四、四十五次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;用 `xwang` 帳號(Django test client,真實 HTTPS,只讀不寫)確認正式站真實審核紀錄已顯示新的 `result-text status-approved` 樣式與「已通過」文字,頁面上找不到任何殘留的舊文字(「已拒絕」/「未核准」);另外直接 curl `app.css` 確認 `.result-text` 規則已生效。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(四十六)**:操作者 Claude Code(依使用者指示執行)。上一版 `3a8ee49` → 新版 `b4085f7`(審核紀錄「結果 / Result」欄拿掉 `.status-badge` 背景色塊,改純文字,使用者反映色塊「有點醜」)。純模板改動,無 migration、無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-143042`。這次改動的檔案都在子目錄,`git checkout --detach` 乾淨無衝突,未再踩到根目錄權限問題。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;用 `xwang` 帳號(Django test client,真實 HTTPS,只讀不寫)確認正式站真實審核紀錄已改成純文字顯示。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(四十五)**:操作者 Claude Code(依使用者指示執行)。上一版 `ff52863` → 新版 `3a8ee49`(①口語能力證明上傳表單「選擇檔案」下方新增選填留言欄位;②Admin 審核區「待審核」表格下方新增「審核紀錄」區塊,顯示已審核文件的結果、留言、審核備註與審核人員,詳見 `docs/PROGRESS.md`/`CLAUDE.md`)。**含 1 個 migration**:`tutoring.0032_qualificationdocument_tutor_note`(單純新增欄位,無資料遷移,`migrate --plan` 確認)。無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-142035`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同四十一、四十四次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;另外用 Django test client(真實 HTTPS、只讀不寫)分別以 `DEMO-TUTOR` 確認上傳表單新增的留言欄位已渲染、以 `xwang` 確認 Admin 審核區的「審核紀錄」區塊已渲染且正確顯示**正式站真實資料**(兩筆真實學生的審核紀錄,審核人員正確顯示為 `高阮陳線 / Jimmy`,即先前建立的 `jimmy` 帳號自行填寫的中文姓名)。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(四十四)**:操作者 Claude Code(依使用者指示執行)。上一版 `1ca6a5d` → 新版 `ff52863`(新增前台「學生名冊」瀏覽頁籤,解決非 superuser 管理員(如下方建立的 7 個助教/老師帳號)點系統總覽名冊卡片會被導去 Django Admin 登入頁卡住的問題,詳見 `docs/PROGRESS.md`/`CLAUDE.md`)。無 migration、無相依套件變更、無靜態資源變更(`collectstatic` 回報「0 static files copied ... 158 unmodified」)。部署前備份:`/var/backups/mpts/20260910-140936`。`git checkout --detach` 再次卡在根目錄下的 `CLAUDE.md`(同四十一次記錄的既有落差),已用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 補救。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;另外直接用 `xwang`(下方新建的非 superuser 管理員帳號之一,Django test client、真實 HTTPS、只讀不寫)實測:Dashboard 含新的「學生名冊」頁籤內容、完全不再出現 `/system-admin/accounts/rosterentry/` 這類 Django Admin 連結、統計卡正確帶入 `roster_role=TUTOR` 等篩選查詢字串、套用篩選後正確篩出老師名單。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(資料異動,非程式碼部署,補記)**:操作者 Claude Code(依使用者指示執行)。使用者要求「這是助教和老師們的帳號，請幫我建立」,建立 7 個一般管理員帳號(`role=ADMIN`、`is_staff=False`、`is_superuser=False`,與 `fangchi0623`/`jimmy` 同類型):`xwang`、`zoe`、`venneasreal`、`hsinrong`、`fpchang`、`jiafeihong`、`sw.chyu`。共用臨時密碼(使用者指定沿用與 `fangchi0623`/`jimmy` 相同的密碼,不記錄於此;同樣不符合密碼複雜度規則,直接以 ORM 建立繞過表單驗證,使用者已知悉且接受,屬暫時性登入憑證)。已用 `xwang` 實測登入自訂 dashboard(200)、確認無法進入 `/system-admin/`(302 導回登入頁)。這次操作本身沒有變更任何檔案或 commit,記錄在此供之後的 session 知道正式站多了這 7 個帳號;隨後就是因為這 7 個帳號實際使用時發現名冊卡片連結卡住,才有上面(四十四)那次部署。

- **2026-09-10(四十三)**:操作者 Claude Code(依使用者指示執行)。上一版 `12d57b8` → 新版 `1ca6a5d`(修正口語能力證明「選擇檔案」按鈕下方無故出現的警告三角形圖示:`static/js/file-size-check.js` 插入的隱藏 `.field-error` 元素被 `app.css` 的 `.field-error{display:flex}` 因特異度打平蓋掉 `[hidden]` 效果,新增 `.field-error[hidden]{display:none!important}` 修正,沿用既有的 `.dashboard-view[hidden]` 寫法,詳見 `docs/PROGRESS.md`)。無 migration、無相依套件變更;新增靜態資源改動(`app.css` cache-busting 版本號更新)。部署前備份:`/var/backups/mpts/20260910-112727`。`collectstatic` 回報「1 static file copied ... 157 unmodified」。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;直接 curl 新版 `app.css?v=20260910-field-error-hidden-fix` 確認 `.field-error[hidden]` 規則已生效。`git checkout --detach` 乾淨無衝突(這次改動的檔案都在子目錄,未再踩到四十一次記錄的根目錄權限問題)。**此次修正未經瀏覽器實際畫面驗證**(本 session 沒有連接瀏覽器自動化工具),只透過檢視伺服器端渲染的原始 HTML 確認 `.field-error` 元素完全由前端 JS 插入、CSS 特異度分析確認修法方向正確;若之後有瀏覽器工具可用,建議補一次視覺複查。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(資料異動,非程式碼部署)**:操作者 Claude Code(依使用者指示執行)。使用者要求「demo-tutor 幫我新增幾筆完成時數，我要測試下載功能」。正式站目前只有一個尚在進行中的學期(115學年度第1學期,2026-09-07～12-31),依 4.9 節規則「本學期證明於學期結束後第 3 天才開放下載」,這個學期的時數要到 2027-01-03 才能下載,無法直接拿現有配對測試。因此比照 `seed_admin_demo` 本機示範資料的既有作法,額外建立一個**已結束**的示範學期:`Semester`(pk=7,`114學年度第2學期`,`program=NTNU`,2026-02-16～06-30,`is_active=False`)、`Pairing`(pk=16,`DEMO-TUTOR`×`DEMO-TUTEE-01`,重用既有帳號)、4 堂已完成課程(pk 63–66,共 6 小時,時長混合 1/1.5/2 小時)。四堂皆直接以 ORM 建立 `Attendance`/`ClassRecord`/`ClassConfirmation`(雙方 CONFIRMED)並附上一筆 `ClassReview(status=APPROVED)`(2026-09-10 新規則要求每堂課都要核准,見第四十一次部署紀錄),而非透過 `check_in()`/`submit_class_record()` 服務函式(避免處理簽到/補登時間窗驗證,做法與 `tutoring/tests.py::_make_verified_session()` 測試輔助函式相同)。已用 Django test client(`force_login(DEMO-TUTOR)`,只讀不寫,真實 HTTP POST 到 `tutoring:download_hours`)確認：`tutor_available_programs()` 正確列出 NTNU、新學期正確出現在可下載清單、實際下載回應 `200 application/pdf`(615968 bytes),PDF 內文確認「總計授課 6 小時」。**這不是程式碼部署,沒有變更任何檔案或 commit**,純粹是這次規則變更後在正式站補建示範資料,記錄在此供之後的 session 知道正式站多了 `Semester`(pk=7)/`Pairing`(pk=16)/`ClassSession`(pk 63–66)這幾筆展示用資料,不要誤以為是真實課程紀錄。

- **2026-09-10(四十二)**:操作者 Claude Code(依使用者指示執行)。上一版 `32e3bc9` → 新版 `12d57b8`(口語能力證明可上傳文件清單移除第 4 項「華語師資養成班招生入學口試通過證明（限當學期）」,使用者要求刪掉,詳見 `docs/PROGRESS.md`)。純模板文字改動,無 migration、無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-102809`。驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error` 無關訊息;另外用 Django test client(`force_login(DEMO-TUTOR)`,只讀不寫)確認 Dashboard 口語能力證明上傳說明已不含「華語師資養成班」文字、其餘 3 項清單保留。`git checkout --detach` 乾淨無衝突。**查詢帳號清單時注意到正式站已出現真實學號格式的 Tutor 帳號(`61284066I`/`61384055I`),非先前的 `DEMO-`/`TEST-SCAN-` 測試帳號**——代表真實名冊/註冊已經開始使用,之後任何驗證動作都要避免對這類帳號做寫入操作,一律改用 `DEMO-`/`TEST-SCAN-` 帳號測試。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10(四十一)**:操作者 Claude Code(依使用者指示執行)。上一版 `0578fdb` → 新版 `32e3bc9`(①所有課堂時數改為都須經 Admin 逐筆核准才生效,不再區分是否為補登;`MakeupReview`/`MakeupReviewStatus` model 更名為 `ClassReview`/`ClassReviewStatus`,`tutoring:makeup_review` URL 更名 `tutoring:review_class`,Admin dashboard 頁籤「補登審核」更名「課程審核」——使用者原話:「現在所有輔導時數除了雙方確認，都要管理員審查才能變成有效，不管是在期限內或逾期」;②學生使用手冊依合作計畫隱藏用不到的功能說明(5.2 尋找老師、十一、合作計畫上課文件僅 Maryland 帳號顯示),詳見 `docs/PROGRESS.md`/`CLAUDE.md` 4.6 節)。**含 2 個 migration**:`tutoring.0030_rename_makeupreview_classreview`(`RenameModel`+2 個 `related_name` 的 `AlterField`,純 schema 變更、保留原始資料)、`tutoring.0031_grandfather_valid_classes_into_class_review`(資料遷移,把規則生效前已符合舊版有效條件但尚無審核紀錄的課程自動核准,避免不溯及既往)。無相依套件變更、無靜態資源變更(`collectstatic` 回報「0 static files copied ... 158 unmodified」)。部署前備份:`/var/backups/mpts/20260910-075459`。
  - 部署前先查詢正式資料庫規模(`ClassSession` 共 8 筆、`SCHEDULED` 5 筆),確認資料量小、風險可控才執行 migration。`0031` 執行後複查:資料庫裡 3 筆既有的 `ClassReview`(舊 `MakeupReview`)全部是弱掃測試帳號與展示帳號原本就有的真實人工核准紀錄(`review_note` 內容分別是「弱點掃描測試帳號，核准以利頁面測試」與「示範帳號，核准以利展示」),**沒有任何一筆是這次遷移新建立的**——代表正式站目前沒有「規則生效前已完成雙方互認但尚無審核紀錄」的課程,這次規則變更對正式站既有資料是零影響的乾淨情況。
  - 驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 僅有既有的 gunicorn `Control server error: Read-only file system` 無關訊息。另外用 Django test client(`Client(SERVER_NAME=...)`,`secure=True`,`force_login` 正式站現有 Admin 帳號,只讀不寫)對正式站實際渲染驗證:Dashboard 含「課程審核」頁籤文字、不再含「補登審核」;既有已核准課程的 `class_detail` 頁面正確顯示「課程審核詳情」與「已核准」;舊網址 `/matching/classes/57/makeup-review/` 正確回應 404。`git checkout --detach` 途中遇到下方記錄的目錄權限問題,已修正後確認乾淨。**臨時 sudo 授權依使用者指示維持開啟**。
  - **本次部署發現並修正另一個操作面問題,是上一則(四十)「已解決 tcsladmin 群組問題」的後續補充,而非新問題**:上次把 `tcsladmin` 加回 `mpts` 群組後,`cd /opt/mpts` 與大部分子目錄下的檔案更新都恢復正常,但這次 `git checkout --detach` 卡在 `error: unable to unlink old 'CLAUDE.md': Permission denied`——查明原因是 `/opt/mpts` **這個最上層目錄本身**的權限是 `drwxr-x--- mpts:mpts`(只有 owner 可寫,群組只有讀+執行),而多數異動檔案所在的子目錄(`tutoring/`、`templates/`、`accounts/`、`docs/`)顯然權限更寬鬆,允許群組寫入。Unix 底下「能否刪除/取代一個檔案」看的是**該檔案所在目錄**的寫入權限,不是檔案本身的權限,所以受影響的只有直接放在 `/opt/mpts` 根目錄下的檔案(這次是 `CLAUDE.md`;`README.md`、`requirements.txt`、`manage.py` 等同層級檔案理論上也會有一樣的問題)。修法:用 `sudo -n -u mpts git checkout HEAD -- CLAUDE.md` 以檔案真正擁有者身分補救這一個檔案,而不是放寬 `/opt/mpts` 本身的目錄權限——放寬根目錄權限會讓同在 `mpts` 群組裡的其他帳號(目前 `getent group mpts` 顯示還有 `www-data`)也一併取得寫入權限,是比單純「把 tcsladmin 加回群組」更大幅度的權限變更,不在使用者當初核准的範圍內,留給使用者之後自行決定是否要一併調整。**之後若 `git checkout`/`pull` 卡在更新根目錄下的檔案,先用這個 `sudo -u mpts git checkout HEAD -- <檔案>` 補救單一檔案，不要因此誤判群組修復失效或走回全程 `sudo -u mpts` 的舊模式**（子目錄內的檔案這次確認完全不受影響）。

- **2026-09-10(四十)**:操作者 Claude Code(依使用者指示執行)。上一版 `ae65d58` → 新版 `0578fdb`(尋找學生:發出邀請後鎖定該 Tutee,阻擋其他 Tutor 同時送出邀請;使用者反映「現在是只要學生還沒配對,每個 tutor 都可以送出邀請」,要求改成一發出邀請就鎖定,詳見 `docs/PROGRESS.md`/`CLAUDE.md` 4.3 節)。無 migration(`makemigrations --check --dry-run`/`migrate --plan` 皆確認無異動)、無相依套件變更、無靜態資源變更(`collectstatic` 回報「0 static files copied ... 158 unmodified」)。部署前備份:`/var/backups/mpts/20260910-030625`。
  - **本次部署發現一個操作面的環境落差,記錄供之後交接參考**:`tcsladmin` 這次已不在 `mpts` 系統群組內(`id` 確認 `groups=tcsladmin,sudo,users`,不含 `mpts`),導致原本文件裡的 `cd /opt/mpts`(以 `tcsladmin` 直接操作)會直接 `Permission denied`(`/opt/mpts` 是 `drwxr-x--- mpts:mpts`)。本次全程改用 `sudo -n -u mpts bash -c '...'` 以 `mpts` 身分執行所有 `git`/`python manage.py` 指令,順利完成部署;之後若 `tcsladmin` 群組權限沒有復原,應延續這個模式,不要假設可以直接 `cd /opt/mpts`。
  - **同時確認並修正一個一直存在、只是先前沒踩到的既有落差**:`config/settings.py` 讀取 `POSTGRES_*`/`DJANGO_*` 一律用 `os.getenv()`,完全沒有載入 `.env` 的機制(不是 `python-dotenv`/`django-environ`)——正式站 gunicorn 服務靠 systemd unit 的 `EnvironmentFile=/opt/mpts/.env` 才能吃到這些變數,但手動執行 `python manage.py check`/`migrate` 等指令**不會**自動讀到 `.env`,直接執行會 fallback 到程式碼寫死的本機開發預設值(`POSTGRES_USER` 預設 `qiangqiang`,對正式 DB 直接回報 `Peer authentication failed for user "qiangqiang"`)。修法是在每次手動執行 `manage.py` 前先 `set -a && source .env && set +a`,再 `source .venv/bin/activate`。這個步驟本來就該做,只是這次是第一次由 `sudo -u mpts` 這條路徑執行才真正被踩到(先前用 `tcsladmin` 直接操作的 session 顯然也做過這個步驟,只是沒有明確寫進 `docs/DEPLOY.md`/本文件第 6.3 節——已列為待補文件的項目,見下方)。
  - 驗收:`curl -I https://mpts.tcsl.ntnu.edu.tw/` 回應 `HTTP/2 200`;`sudo systemctl restart mpts-gunicorn.service` 後 `journalctl` 僅有既有的 gunicorn `Control server error: Read-only file system` 無關訊息,無新增 error/traceback。另外直接用 Django shell 呼叫 `tutoring/services.py` 的 `send_invitation()`/`anonymous_tutee_candidates()`(與畫面走同一套 service 函式,未新增任何測試資料)對正式資料實測:`DEMO-TUTOR` 已對 `DEMO-TUTEE-03` 有一筆待回覆邀請;讓另一個 Tutor 帳號 `DEMO-TUTOR-PENDING` 嘗試邀請同一位 `DEMO-TUTEE-03`,確認①候選清單裡看不到她、②直接呼叫 `send_invitation()` 正確拋出 `ValidationError`(訊息為新規則的雙語錯誤文字);同時確認 `DEMO-TUTOR`(原邀請人)自己的候選清單仍看得到 `DEMO-TUTEE-03`。三項行為皆符合預期。`git checkout --detach` 乾淨無衝突。**臨時 sudo 授權依使用者指示維持開啟**。
  - **2026-09-10 事後修正(使用者要求處理這兩個落差)**:①以 `sudo -n usermod -aG mpts tcsladmin` 把 `tcsladmin` 加回 `mpts` 群組,並確認新的 SSH 連線 `id` 已含 `mpts`;`git` 因 2.35.2+ 的 dubious-ownership 保護仍擋下操作,額外執行一次 `git config --global --add safe.directory /opt/mpts`(寫入 `tcsladmin` 的 `~/.gitconfig`,一次性,之後不用重設)後,`cd /opt/mpts`、`git status`/`fetch`/`checkout`、`collectstatic`、不連 DB 的 `python manage.py check` 都恢復可用 `tcsladmin` 直接操作,不需要 `sudo -u mpts`。②確認 `.env` 讀不到是**刻意的安全邊界**(`.env` 是 `600`、擁有者 `mpts`,連 `tcsladmin` 加入 `mpts` 群組後也讀不到——群組權限對 owner-only 的檔案沒有幫助),使用者決定**不修改程式**(不加 `python-dotenv` 之類的自動載入機制),維持「連 DB 的指令一律走 `sudo -n -u mpts` 並手動 `source .env`」這個模式;已把正確的指令序列與判斷原則(哪些指令連 DB、哪些不用)寫進本文件第 6.3 節,取代這裡原本指向 `docs/DEPLOY.md` 的錯誤文件參照(該節其實在本文件,不在 `docs/DEPLOY.md`)。

- **2026-09-10（三十七～三十九）**：操作者 Claude Code(依使用者指示執行)。連續三個小型部署,合併記錄:
  - `40be728`(配對後不顯示彼此學號;佐證連結範例「上課畫面截圖」改「實際授課照片」)
  - `4836aca`(發現排課下拉選單用 `Pairing.__str__()` 間接洩漏雙方學號,新增 `PairingChoiceField` 修正)
  - `ae65d58`(發現異常回報下拉選單用 `ClassSession.__str__()` 同樣間接洩漏,新增 `_OwnSessionChoiceField` 修正)
  三次皆無 migration、無相依套件變更、無靜態資源變更,部署前依序備份:`/var/backups/mpts/20260910-023533`、`20260910-024147`、`20260910-024656`。每次部署後皆以 `curl` 確認首頁 200、`journalctl` 無新增錯誤,並實際用 `demo-tutor` 帳號登入正式站驗證:個人資料頁與 Dashboard 配對卡片不再顯示對方學號、排課表單與異常回報表單的下拉選單皆改顯示姓名而非學號。三次 `git checkout --detach` 皆乾淨無衝突。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10（三十六）**：操作者 Claude Code(依使用者指示執行)。上一版 `cd2af49` → 新版 `c6ec727`(Tutor 側邊欄重新排序,Tutee 同步調整;異常回報從課程詳情頁拉出獨立成 Dashboard 頁籤,新增 `StandaloneIncidentReportForm` 讓使用者從下拉選單挑選自己的任一堂課,不必先點進特定課程,詳見 `docs/PROGRESS.md`)。無 migration、無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-020125`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 無新增錯誤;實際用明天demo要用的 `demo-tutor` 帳號驗證側邊欄新順序、開啟「異常回報」頁籤、從下拉選單選課程並成功送出一筆回報(順便留一筆真實紀錄供明日展示)。`git checkout --detach` 乾淨無衝突。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10（三十五）**：操作者 Claude Code(依使用者指示執行)。上一版 `51ee004` → 新版 `f469db3`(密碼等欄位錯誤改顯示在該欄位下方,不再只靠頁面訊息:使用者詢問「密碼錯誤提醒可以放在密碼欄位下方嗎」後,把 `update_profile()` 驗證失敗的處理方式從「導向 + flash message」改成「直接 render 個人資料頁並帶回失效表單」,讓既有的 `components/form_field.html` 逐欄位錯誤顯示生效;成功時仍維持 redirect 避免重整表單重複送出。詳見 commit message)。無 migration、無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-005456`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 無新增錯誤;另外用 `jimmy` 帳號實際送出密碼不一致的表單,確認錯誤文字直接出現在「再次輸入新密碼」欄位下方(`<div class="form-group has-error">`內),而非頁面上方的通用訊息。`git checkout --detach` 乾淨無衝突。**附帶發現**:核對 `AuditLog` 時確認 `fang.chii` 已在稍早(9/9 16:46)自行改好中文姓名、Email 並設定新密碼(`password_changed: True`),原臨時密碼已失效——這是預期中的正常使用,不是異常。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10（三十四）**：操作者 Claude Code(依使用者指示執行)。上一版 `e4d0951` → 新版 `51ee004`(個人資料頁的 `messages.html` 從 `<main>` 開頭移到 `#edit-profile` 區塊內:`update_profile()` 一律導回 `/profile/#edit-profile`,瀏覽器直接捲到編輯區塊,但訊息原本放在頁面最上方,使用者捲下去後完全看不到剛才顯示過的錯誤/成功提示——是使用者實際測試後回報「error 都只出現在頁首,使用者不會發現」才發現的後續問題)。無 migration、無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-004131`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 無新增錯誤。`git checkout --detach` 乾淨無衝突。部署完成後將帳號 `fangchi0623` 改名為 `fang.chii`(直接改 `User.username`,Django FK 皆以 `id` 關聯、不受影響),已用真實登入確認密碼未變、可正常登入並開啟個人資料頁。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10（三十三）**：操作者 Claude Code(依使用者指示執行)。上一版 `5c4fe84` → 新版 `e4d0951`(修正真實回報的「無法編輯個人資料」問題:`templates/accounts/profile.html` 從未 include `components/messages.html`,導致 `update_profile()` 的所有 `messages.error()`/`messages.success()` 一律被靜默吞掉,欄位驗證失敗時頁面只是重新整理、沒有任何提示。這個缺口本來就存在,影響 Tutor/Tutee 皆然,只是 Admin 的 `name_zh` 從空白開始且為必填,新管理員(`fangchi0623`/`jimmy`)一用就踩到。詳見 commit message)。無 migration、無相依套件變更、無靜態資源變更。**問題發現過程**:查 nginx `mpts_access.log` 確認真人瀏覽器(`123.193.235.61`/`140.122.20.177`)確實對 `/profile/update/` 送出多次 POST 且都收到 302(非 500),但 `AuditLog` 完全沒有對應的 `PROFILE_UPDATED` 紀錄、三個 Admin 帳號的 `name_zh` 也都仍是空字串,判斷是表單驗證失敗但頁面沒有顯示原因。部署前備份:`/var/backups/mpts/20260910-002947`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 排除既有雜訊後無 traceback/critical;另外用 `jimmy` 帳號實際登入,先故意送出空白姓名確認畫面現在會顯示「此欄位為必填欄位」,再送出正確姓名確認顯示「個人資料已更新」且姓名確實生效(`jimmy` 的中文姓名已設為「吉米」/English name「Jimmy」)。`git checkout --detach` 乾淨無衝突。臨時 sudo 授權依使用者指示維持開啟。

- **2026-09-10（三十二）**：操作者 Claude Code(依使用者指示執行)。上一版 `69802be` → 新版 `5c4fe84`（Admin 個人資料頁文字精簡:學號/Student ID 標籤含頁面上方個人資訊列改為 ID、拿掉不適用 Admin 的兩段說明文字、編輯區塊編號改 02、拿掉重複的密碼提示,詳見 commit message）。無 migration、無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-002242`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`journalctl` 排除既有雜訊後無 traceback/critical,並實際以 `jimmy` 帳號登入 `/profile/` 逐項核對六處文字改動皆已生效。`git checkout --detach` 乾淨無衝突。**依使用者指示,本次部署後臨時 sudo 授權維持開啟**(接下來還會連續修改與部署),待使用者明確表示結束後才移除,下一次記錄若沒有「已移除臨時 sudo」的敘述,代表授權仍持續有效中,交接時務必先確認目前狀態而非假設已關閉。

- **2026-09-10（三十一）**：操作者 Claude Code(依使用者指示執行)。上一版 `bf9f3bc` → 新版 `69802be`（Admin 個人資料自行編輯功能、密碼複雜度驗證缺口修補、Admin 基本資料改顯示簡化 ID 欄位，三個 commit 一次部署，詳見 `docs/PROGRESS.md`）。無 migration(`makemigrations --check --dry-run`/`migrate --plan` 皆確認無異動)、無相依套件變更、無靜態資源變更。部署前備份:`/var/backups/mpts/20260910-000800`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`journalctl` 排除既有雜訊後無 traceback/critical。`git checkout --detach` 乾淨無衝突。部署完成後緊接著建立 2 個一般管理員帳號(`fangchi0623`、`jimmy`,`role=ADMIN`/`is_staff=False`/`is_superuser=False`,共用臨時密碼,密碼不記錄於此),已用真實登入驗證兩者皆可進自訂 Admin dashboard、皆無法進 `/system-admin/` Django 後台(302 導回登入頁,確認權限範圍正確),`jimmy` 的 `/profile/` 頁面正確顯示新的「ID」欄位與編輯表單。臨時 sudo 授權已移除並確認恢復需要密碼。

- **2026-09-08（三十）**：操作者 Claude Code(依使用者指示執行)。上一版 `a5a62e1` → 新版 `bf9f3bc`（Admin dashboard 新增「上課文件」上傳/管理頁籤，取代原本只能在 Django Admin 操作的設計，詳見 `docs/PROGRESS.md`/`CLAUDE.md` 4.10 節）。無 migration(`makemigrations --check --dry-run`/`migrate --plan` 皆確認無異動)、無相依套件變更、無靜態資源變更(`collectstatic` 回報「0 static files copied ... 158 unmodified」，符合預期，這次純屬 Python/模板改動)。部署前備份:`/var/backups/mpts/20260908-134123`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200，未登入直接開 `/dashboard/` 正確回應 302 導回登入頁。`journalctl` 無新增 error(既有 gunicorn `Control server error` 訊息無關)。`git checkout --detach` 乾淨無衝突。此功能已在本機用 curl 對 dev server 做過真實登入→上傳→下載→編輯→刪除的端到端驗證(見 `docs/PROGRESS.md`)，正式站因目前只有 `admin` 一個帳號、尚無已開放「上課文件」功能的正式資料，暫未在正式站重複這輪端到端操作，之後有需要上傳正式課程文件時再實際使用並確認。

- **2026-09-08（二十九）**：操作者 Claude Code(依使用者指示執行)。上一版 `8b5e1f8` → 新版 `a5a62e1`（`/handbook/` 使用手冊改版:依使用者提供的自撰操作手冊原稿改成完整章節文件(老師 13 章、學生 12 章),沿用既有 `.profile-layout` 元件並新增 `.manual-section` 排版樣式,新增 15 張截圖靜態資源;全文依全站雙語慣例補上英文,詳見 `docs/PROGRESS.md`）。無 migration(`makemigrations --check --dry-run`/`migrate --plan` 皆確認無異動)、無相依套件變更;新增 15 個靜態圖片檔。部署前備份:`/var/backups/mpts/20260908-131840`。`collectstatic` 回報「16 static files copied ... 142 unmodified」(15 張圖 + 更新後的 `app.css`)。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200;`app.css`(`?v=20260908-handbook-manual-en`)、新截圖(`static/img/handbook/teacher/register.png`、`static/img/handbook/student/certificate.png`)皆用 curl 確認 200 且檔案大小正常;未登入直接開 `/handbook/` 正確回應 302 導回登入頁。正式站目前只有一個 `admin` 帳號(封測資料已清空,尚未匯入正式名冊,見 `docs/PROGRESS.md`),沒有 Tutor/Tutee 帳號可在正式站做角色渲染的端到端登入驗證;手冊三種角色(Tutor/Tutee/Admin)的實際渲染已在本機用 Django test client 完整驗證(皆 200,內容大小合理)。`journalctl` 無新增 error(既有 gunicorn `Control server error` 訊息無關)。`git checkout --detach` 乾淨無衝突。

- **2026-09-08（二十八）**：操作者 Claude Code(依使用者指示執行)。上一版 `8d42330` → 新版 `8b5e1f8`（修正彩色頭圖區塊配色 regression:`.app-shell` 把 `--navy`/`--deep-ink` 改黑那輪沒注意到這兩個變數也被拿來當品牌強調色背景/漸層用,`.profile-hero` 等 5 處由另一位 AI agent「codex」發現並先修(局部釘回 `#68152f`、h1 強制白色),本次複查再補上 `.stat-card:nth-child(4n+1)::before`、`.invitation-teacher-mark` 兩處同病根,詳見 `docs/PROGRESS.md`）。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260908-110357`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200;`app.css` 已用 curl 確認 `.stat-card`/`.invitation-teacher-mark` 的 `--navy: #68152f` 局部釘值都已生效。`journalctl` 無新增 error(既有 gunicorn `Control server error` 訊息無關)。`git checkout --detach` 乾淨無衝突。

- **2026-09-06（二十七）**：操作者 Claude Code(依使用者指示執行)。上一版 `2f37a63` → 新版 `8d42330`（另一位 AI agent「codex」review 抓到:`.stack-form p` 因特異度較高蓋掉 `.field-error` 的顏色/字級/排版/margin,正式站錯誤文字實際顯示酒紅色而非設定的錯誤紅;改成 `.stack-form p:not(.field-error)` 排除。同時補上單選/複選(`.choice-field.has-error ul`)與評分欄位(`.rating-field.has-error`,模板早就會加這個 class 但完全沒有對應 CSS)的 2px 紅框+淡紅底,詳見 `docs/PROGRESS.md`）。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260906-163214`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200;`app.css` 已用 curl 確認兩處 `.stack-form p:not(.field-error)` 與新增的 `.rating-field.has-error` 規則都已生效;另外對正式站再次觸發真實註冊密碼驗證錯誤,確認 markup 正常。`journalctl` 無新增 error(既有 gunicorn `Control server error` 訊息無關)。`git checkout --detach` 乾淨無衝突。

- **2026-09-06（二十六）**：操作者 Claude Code(依使用者指示執行)。上一版 `31ddfd2` → 新版 `2f37a63`（P1-02 補做：先前只做了雙語訊息跟密碼規則，紅框與錯誤文字本身的醒目程度沒有實質調整，使用者指出後這次補上——`.has-error .form-control` 邊框加粗到 2px 加淡紅底色，`.field-error` 改成有底色的提示框加 `⚠` 前綴，詳見 `docs/PROGRESS.md`）。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260906-155440`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200；另外直接對正式站觸發一次真實的註冊密碼驗證錯誤（常見密碼），確認 `form-group has-error` 與新樣式的 `field-error` 都正確渲染。`journalctl` 無新增 error(既有 gunicorn `Control server error` 訊息無關)。`git checkout --detach` 乾淨無衝突。

- **2026-09-06（二十五）**：操作者 Claude Code(依使用者指示執行)。上一版 `cc7a370` → 新版 `31ddfd2`（P1-03：新增 `static/js/password-toggle.js`，全站對每個 `input[type=password]` 自動加上顯示/隱藏按鈕；D-01：`static/js/profile-options.js` 母語選單新增粵語，詳見 `docs/PROGRESS.md`）。無 migration、無相依套件變更；新增一個靜態檔案。部署前備份:`/var/backups/mpts/20260906-032920`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200，`app.css`/`password-toggle.js`/`profile-options.js`（含 `yue: "粵語 (Cantonese)"`）皆已用 curl 對正式站確認，`journalctl` 無新增 error(既有 gunicorn `Control server error` 訊息無關)。`git checkout --detach` 乾淨無衝突。

- **2026-09-06（二十四）**：操作者 Claude Code(依使用者指示執行)。上一版 `f333466` → 新版 `cc7a370`（P2-05 補完：課程詳情頁「目前確認結果」`.review-result` 依 `ClassConfirmation.status` 分別上綠/黃/紅，與 `.class-status` 共用同一組色碼，詳見 `docs/PROGRESS.md`）。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260906-032044`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200，`app.css` 版本號與 `.review-result-confirmed` 規則皆已用 curl 對正式站確認，`journalctl` 無新增 error(既有 gunicorn `Control server error` 訊息無關)。`git checkout --detach` 乾淨無衝突。

- **2026-09-06（二十三）**：操作者 Claude Code(依使用者指示執行)。上一版 `7f98da5` → 新版 `f333466`（老師端封測回饋 P1-02 色彩對比後續調整 + P2-02/P2-04：一般文字酒紅色改黑色只限登入後頁面`.app-shell`、逐一修正多處寫死酒紅色元件、課程收合符號改箭頭、側欄文字放大、私訊按鈕與個人資料編輯區塊調整、課程卡片新增「修改/取消」內嵌標籤，詳見 `docs/PROGRESS.md`)。無 migration、無相依套件變更；新增一個靜態檔案 `static/js/open-details-from-hash.js`。部署前備份:`/var/backups/mpts/20260906-030746`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200，`app.css` 版本號、新 JS 檔案、`.sidebar-link b`/`.class-row-tag` 的最終數值皆已用 curl 直接對正式站確認與本機一致，`journalctl` 無新增 error(既有的 gunicorn `Control server error: Read-only file system` 為既存無關訊息)。`git checkout --detach` 乾淨無衝突。**此次部署一併帶上先前已 push 但未部署的 `07bcf4a`(僅文件與 Nginx 註解，無程式碼異動)**，VM 與遠端不再有 commit 落差。

- **2026-09-06（二十二）**：操作者 Claude Code(依使用者指示執行)。上一版 `6b32712` → 新版 `7f98da5`(老師端封測回饋 P1-01/P1-02:超大口語能力證明上傳新增瀏覽器端即時檔案大小檢查與 Nginx 413 自訂錯誤頁;密碼驗證錯誤訊息改為雙語並列出完整規則;移除死程式碼 `RegistrationForm`,詳見 `docs/PROGRESS.md` 與 commit message)。無 migration、無相依套件變更。**含 Nginx 設定變更**:`error_page 413 /static/errors/413.html;`。部署後第一次用 `curl -F` 實際送出超大檔案測試,發現自訂 413 頁沒有生效、仍是 nginx 內建醜頁面——查明是真實的 nginx bug([trac.nginx.org/nginx/ticket/1152](https://trac.nginx.org/nginx/ticket/1152)):HTTP/2(這個 server block 是 `listen 443 ssl http2`)底下,nginx 內部重導向到 `error_page` 時沒有正確清空原始請求的 `Content-Length`,導致重導向後的請求又被同一個 `client_max_body_size` 擋一次而失敗退回內建頁面。修法是幫錯誤頁那個路徑另外開一個 `location = /static/errors/413.html { client_max_body_size 0; ... }`(exact match 優先於 `/static/` 的 prefix match),只放寬這一個 GET-only 的靜態頁面,其餘路徑的 12m 限制不受影響。修正後重新用 `curl -F` 送 15MB 檔案確認收到完整雙語錯誤頁(`status=413`,內容含正確標題與品牌樣式),`app.css`/logo 等被引用的靜態資源也都正常載入。另外用未註冊學號+常見密碼直接對正式站送出註冊表單,確認雙語密碼錯誤訊息確實出現。部署前備份:`/var/backups/mpts/20260906-012854`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-gunicorn.service` 運作正常,`journalctl` 無新增 error(既有的 gunicorn `Control server error: Read-only file system` 訊息為既存、與本次改動無關的既知現象)。`git checkout --detach` 乾淨無衝突。

- **2026-09-04（二十一）**：操作者 Claude Code(依使用者指示執行)。上一版 `db0de7a` → 新版 `6b32712`(上線前最後檢查時發現並修正:①`pip-audit` 掃出 `pypdf 6.15.0` 有 3 個新公開 CVE(CVE-2026-84309/84310/84311),升級到 `6.16.1`;②`seed_admin_demo.py`/`load_testing/isolated_vm_loadtest.py` 殘留課堂紀錄改版已移除的 `skills_practiced` 欄位,改用現行的 `materials_used`/`individual_progress`,詳見 `docs/PROGRESS.md` 與 commit message)。無 migration(`makemigrations --check --dry-run`/`migrate --plan` 皆確認無異動);有相依套件變更,已在 VM 上以 `pip install -r requirements.txt` 更新並用 `python -c "import pypdf; print(pypdf.__version__)"` 確認為 `6.16.1`。部署前備份:`/var/backups/mpts/20260904-130048`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-gunicorn.service`/`mpts-process-matching-state.timer` 運作正常,`journalctl` 近期無 error 等級日誌。`git checkout --detach` 乾淨無衝突。**此次部署後緊接著執行第 12 節的封測資料清理,詳見該節。**

- **2026-09-03（二十）**：操作者 Claude Code。上一版 `10122e5` → 新版 `db0de7a`（移除課堂紀錄新欄位的回填 placeholder 文字:`materials_used`/`individual_progress` 不該把畫面提示文字直接存進資料庫,改清回空字串,由 `class_detail.html`/`admin_record_card.html` 在值為空時顯示「未提供(此紀錄建立於欄位新增前)」)。**含 migration**:`tutoring.0028_alter_classrecord_individual_progress_and_more`(`AlterField` 調整欄位預設值 + `RunPython` 資料遷移,把 41 筆既有紀錄的 placeholder 文字清回空字串,已於部署後直接查詢正式資料庫確認全部清除、`total=41, with old placeholder=0, now empty=41`)。部署前備份:`/var/backups/mpts/20260903-033222`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-process-matching-state.timer` 運作正常。`git checkout --detach` 乾淨無衝突。

- **2026-09-03（十九）**：操作者 Claude Code。上一版 `a28e0c7` → 新版 `10122e5`（課堂紀錄欄位改版：`topic`/`content`/`remarks` 沿用原欄位只改標籤；移除選填的多選標籤欄位 `skills_practiced` 及對應的 Django Admin 篩選器,改為兩個新的必填文字欄位 `materials_used`「使用之教材、教具及設備」(200字內)與 `individual_progress`「個別學習情形」(500字內);另外新增管理員操作手冊、封測相關文件等素材,詳見 commit message)。**含 migration**:`tutoring.0027_remove_classrecord_skills_practiced_and_more`(移除欄位、新增 2 個必填欄位並回填既有 41 筆紀錄為明確的「舊紀錄無資料」提示文字,已於部署後直接查詢正式資料庫確認全部正確回填、`skills_practiced` 欄位已移除)。部署前備份:`/var/backups/mpts/20260903-015221`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-process-matching-state.timer` 運作正常。`git checkout --detach` 乾淨無衝突。

- **2026-08-25（十八）**：操作者 Codex。上一版 `8ed33d1` → 新版 `a28e0c7`（補上 `.class-status.rejected` 的淡紅色膠囊底色，並更新 `app.css` 快取版本，修正正式站只有紅字、沒有紅色底的問題）。無 migration、無相依套件變更。部署前備份：`/var/backups/mpts/20260825-030135`。Gunicorn 重啟後第一次立即檢查曾短暫回應 502，約 24 秒後恢復 HTTP 200；後續確認 `mpts-gunicorn.service` 與 `mpts-process-matching-state.timer` 均為 active、近期無 error 等級日誌，正式 `staticfiles/css/app.css` 已包含 `background: #f8e2e2`，VM 固定於 commit `a28e0c7b037e752d33c4cb8a53f968dca0541864`。

- **2026-08-25（十七）**：操作者 Codex。上一版 `bd61b92` → 新版 `8ed33d1`（補時數申請遭管理員拒絕後，老師／學生課表與時數歷史卡片的「未核准 / Rejected」徽章改用既有紅色拒絕樣式，不再顯示黃色等待樣式；同時補上回歸測試）。無 migration、無相依套件變更。本機 316 項測試全部通過。部署前備份：`/var/backups/mpts/20260825-025650`。驗收：`https://mpts.tcsl.ntnu.edu.tw/` 回應 HTTP 200，`mpts-gunicorn.service` 與 `mpts-process-matching-state.timer` 均為 active，Gunicorn 近期無 error 等級日誌，VM 固定於 commit `8ed33d1daa6b714d0325311f323470d1f9f6940b`。

- **2026-08-25（十六）**：操作者 Claude Code。上一版 `0495101` → 新版 `bd61b92`（修正老師/學生自己的課表與時數歷史卡片:補時數雙方確認後應進入「等待管理員核准」,但 `class_schedule_group.html`／`class_history_list.html` 只看 `is_official`/`my_record`/`my_attendance`,從未讀取實際 `MakeupReview` 狀態,導致核准前(甚至被拒絕後)永遠卡在通用的「等待雙方完成 / Waiting」文字;改為有 `makeup_review` 且非 WAITING 時直接顯示真實狀態文字,詳見 commit message)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260825-024206`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-process-matching-state.timer` 運作正常。`git checkout --detach` 乾淨無衝突。

- **2026-08-25（十五）**：操作者 Claude Code。上一版 `77cb767` → 新版 `0495101`（補時數審核狀態標籤「待管理員審核」改成「等待管理員核准」,與「等待雙方確認」的用詞風格統一,詳見 CLAUDE.md 4.6 節與 commit message)。**含 migration**:`tutoring.0026_alter_makeupreview_status`(僅 choices 顯示文字變更,無資料表結構變動)。部署前備份:`/var/backups/mpts/20260825-022653`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-process-matching-state.timer` 運作正常,並直接查詢正式資料庫確認現有補時數審核紀錄(session 16)`get_status_display()` 已顯示新文字。`git checkout --detach` 乾淨無衝突。

- **2026-08-25（十四）**：操作者 Claude Code。上一版 `d402573` → 新版 `77cb767`（Tutee 課堂紀錄佐證連結改為選填、Tutor 維持必填；連帶修正課程詳情頁/Admin 課程詳情卡在雙方都缺連結與附件時的顯示文字，避免 Tutee 合法跳過選填欄位卻顯示暗示忘記上傳的「未上傳」字樣，詳見 CLAUDE.md 4.6 節與 commit message)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260825-020153`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-process-matching-state.timer` 運作正常。`git checkout --detach` 乾淨無衝突。

- **2026-08-25（十三）**：操作者 Claude Code。上一版 `990ea70` → 新版 `d402573`（課程詳情頁簽到/課堂紀錄按鈕文字：逾時補簽/補登時分別改顯示「補簽到 / Makeup check-in」「補填課堂紀錄 / Makeup record」,不再永遠顯示一般的「確認簽到」「送出紀錄」,詳見 commit message)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260825-014455`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,`mpts-process-matching-state.timer` 運作正常。`git checkout --detach` 乾淨無衝突。

- **2026-08-22（十二）**：操作者 Claude Code。上一版 `28e4e2a` → 新版 `990ea70`（兩項調整一併部署:①NTNU 學生不可主動邀請,Dashboard「邀請管理」的「已發送的邀請 Sent」卡片對他們永遠是空的,比照既有 `is_maryland` 判斷整張隱藏,Maryland 學生不受影響,`678ae3f`；②「已發送的邀請」與「歷史紀錄」兩張卡片黏在一起,原因是 `.dashboard-view > .panel + .panel` 選擇器只認相鄰的 `.panel` 手足,但歷史紀錄前面接的是 `div.invitation-stack` 不是 `.panel`,吃不到規則,補上對應選擇器沿用同樣 18px 間距,`990ea70`)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260822-185340`。驗收:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200,新版 `app.css`(`?v=20260822-invitation-stack-history-gap`)確認可正常存取。`git checkout --detach` 乾淨無衝突。
- **2026-08-22（十一）**：操作者 Claude Code。上一版 `43e03ef` → 新版 `28e4e2a`（沒有中文姓名的使用者(如國際生)在首頁問候語/側欄/帳號選單/個人資料頁不再顯示學號,改用 `User.bilingual_name` 正確 fallback 到英文姓名,詳見 commit message)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260822-181536`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200。`git checkout --detach` 乾淨無衝突。
- **2026-08-22（十）**：操作者 Claude Code。上一版 `047fd3d` → 新版 `43e03ef`（邀請補上稽核紀錄與 Dashboard 歷史區塊、候選卡片/邀請列表新增 TEST 帳號標籤,詳見 CLAUDE.md 與 commit message)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260822-173337`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`app.css` 內容確認含新的 `.test-account-badge` 規則。`git checkout --detach` 乾淨無衝突。另外這次部署前先在正式 VM 建立了 2 筆 Maryland Tutor 測試帳號(`TEST-MARYTUTOR1`/`TEST-MARYTUTOR2`,透過真實 `TutorRegistrationForm` 建立,非 seed 指令),部署前備份:`/var/backups/mpts/20260822-173002`。：操作者 Claude Code。上一版 `6ce210d` → 新版 `047fd3d`（修正真實 bug:`user_program()` 對一般 NTNU Tutor 回傳 `None` 導致 `active_semester()` 誤查舊版共用期間,使 Tutor 與 Tutee 在 Admin 建立 NTNU 專屬學期後看到不同期間;詳見 CLAUDE.md 4.2 節與 commit message)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260821-234444`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200。`git checkout --detach` 乾淨無衝突。
- **2026-08-21（八）**：操作者 Claude Code。上一版 `f44fd29` → 新版 `6ce210d`（移除 `Semester.applicable_users`,原因與討論見 `docs/PROGRESS.md`「尚未定案的產品/維運決策」)。**含 migration**:`tutoring.0025_remove_semester_applicable_users`(刪除 M2M 關聯表)。**部署前額外用 `manage.py dbshell` 查詢 `tutoring_semester_applicable_users` 資料表確認為 0 筆**,才執行 migration,避免萬一有未預期資料被靜默刪除。部署前備份:`/var/backups/mpts/20260821-233118`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 與 `/system-admin/login/` 皆回應 200。`git checkout --detach` 乾淨無衝突。
- **2026-08-21（七）**：操作者 Claude Code。上一版 `55e61b4` → 新版 `f44fd29`（口語能力審核區塊版面調整：下載連結移到預覽下方、審核備註移到通過/拒絕按鈕下方，`6233ecc`；「下載」連結改為小按鈕樣式，`f44fd29`)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260821-184434`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200,`app.css` 內容確認含新的 `.qualification-review-form` 規則。`git checkout --detach` 乾淨無衝突。
- **2026-08-21（六）**：操作者 Claude Code。上一版 `a8c8a24` → 新版 `55e61b4`（此次一併帶上先前已 push 但尚未部署的 `b014afc` 口語能力證明預覽功能,以及 `55e61b4` 本身:「補件」改為「拒絕」+ 補上審核備註輸入欄位)。**含 migration**:`tutoring.0024_alter_qualificationdocument_status`(純 choices 顯示文字變更,無資料異動)。部署前備份:`/var/backups/mpts/20260821-183137`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 與 `/system-admin/login/` 皆回應 200。`git checkout --detach` 乾淨無衝突。
- **2026-08-21（五）**：操作者 Claude Code。上一版 `5f0d19f` → 新版 `a8c8a24`（修正 10 處 view 完成動作後一律 redirect 回 dashboard 首頁分頁、而非留在原本操作分頁的問題:口語能力證明上傳/審核、邀請學生/老師、接受/拒絕/取消邀請、排課、取消課程、補登審核,詳見 commit message)。無 migration、無相依套件變更。部署前備份:`/var/backups/mpts/20260821-180358`。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 回應 200。`git checkout --detach` 乾淨無衝突。
- **2026-08-21（四）**：操作者 Claude Code。上一版 `dfe1a4b` → 新版 `5f0d19f`（修正個人資料編輯頁/老師註冊頁/學生註冊頁「可配合時段」下方雙語提示文字與勾選格緊貼的間距問題，純 CSS/template 改動）。無 migration、無相依套件變更。部署前備份：`/var/backups/mpts/20260821-172632`。驗收：`https://mpts.tcsl.ntnu.edu.tw/` 回應 200，`app.css` 內容確認含新的 `.choice-field > .form-note` 規則。`git checkout --detach` 乾淨無衝突。
- **2026-08-21（三）**：操作者 Claude Code。上一版 `f016833` → 新版 `dfe1a4b`（安全性套件升級:`Django` 5.2.16→5.2.17 修復 `PYSEC-2026-3717`,`sqlparse` 0.5.5→0.6.0 修復 4 個 DoS CVE 並首次明確鎖版本,詳見 `docs/SECURITY_CHECKLIST.md`)。無 migration,但**有相依套件變更,`pip install` 步驟確實需要重新安裝**(已用 `python -c "import django; print(django.VERSION)"` 與 `pip show sqlparse` 確認 VM 上裝的版本正確,不能只看 `pip install` 沒報錯就假設版本真的換了)。部署前備份:`/var/backups/mpts/20260821-171646`。`collectstatic` 這次因 Django 版本更新,`django.contrib.admin` 內建靜態檔案本身有異動,127 個檔案被更新(遠多於平常只有 0-1 個檔案變動的情況),屬預期行為。驗收:`https://mpts.tcsl.ntnu.edu.tw/` 與 `/system-admin/login/` 皆回應 200。`git checkout --detach` 乾淨無衝突。
- **2026-08-21（二）**：操作者 Claude Code。上一版 `6e5ec53` → 新版 `f016833`（老師註冊表單「學制 / Degree level」下拉選單補上 `("", "請選擇 / Select")` 佔位選項，與 gender/native_language/nationality 等欄位一致，修正原本瀏覽器會預設選中「大學」造成使用者誤以為系統已代為選擇的問題）。無 migration。部署前備份：`/var/backups/mpts/20260821-162856`。驗收：`https://mpts.tcsl.ntnu.edu.tw/` 回應 200。`git checkout --detach` 乾淨無衝突。同日稍早也處理了系統碟被 iptables drop log 灌爆的事件（見 `docs/DEPLOY.md`「事件紀錄」，屬 VM 系統層面修復,非本次應用程式部署範圍,不計入 commit 版本號）。
- **2026-08-21（一）**：操作者 Claude Code。上一版 `af7fc38` → 新版 `6e5ec53`（`188b7c3`：`/system-admin/` 白名單改為整個師大網段 `140.122.0.0/16`（先前逐一加 `/24` 白名單追不上實際觀察到的多個不同校內來源網段，這次未含在本次程式部署內，屬 Nginx 設定變更，已於當天先行套用；`6e5ec53`：註冊安全問題三選單改為即時互斥選取，選過的題目自動從其他兩個選單停用，伺服器端重複檢查不變）。無 migration。部署前備份：`/var/backups/mpts/20260821-154707`。驗收：`https://mpts.tcsl.ntnu.edu.tw/` 回應 200、新增的 `static/js/security-questions.js` 回應 200。這次 `git checkout --detach` 乾淨無衝突。
- **2026-08-18**：操作者 Claude Code。上一版 `859f48e` → 新版 `af7fc38`（配色改為師大酒紅/金色系 + 頁首並列師大校徽與華語系 logo，`603eace`/`af7fc38`）。無 migration。部署前備份：`/var/backups/mpts/20260818-171119`。驗收：`https://mpts.tcsl.ntnu.edu.tw/` 回應 200，`app.css` 內容確認為新色票、`ntnu-logo.png` 回應 200，`link` 標籤 cache-busting 版本正確更新。過程中發現 `deploy/backup_mpts.sh` 先前是用 `scp`/`install` 手動佈署到 VM 上（在該檔案真正進入 git 歷史之前），與這次 `git checkout --detach` 的目標 commit 衝突（unmerged untracked file）；核對兩者內容位元組相同後刪除未追蹤版本再重試，之後的部署不會再遇到這個特定衝突。

## 12. 封測結束資料清理紀錄

正式上線前的資料庫/media 清理不是「部署新程式」，獨立於第 11 節的部署紀錄之外記錄於此。

- **2026-09-04**：操作者 Claude Code(依使用者指示執行)。使用者確認正式站封測已結束、準備開放真實使用者註冊，要求清空所有封測資料。清理前唯讀盤點確認**正式資料庫裡完全沒有任何真實名冊、學期或配對**(全部 35 筆名冊皆為 `MPTSBT*`/`TEST-*` 測試學號,4 個學期皆命名為「封測時數測試期間」/`test`/`test2`),因此採全面重置而非逐筆篩選。緊接在第 11 節「二十一」部署(`6b32712`,pypdf CVE 修復)之後執行。
  - 清理前備份:`/var/backups/mpts/20260904-130623`(部署後、清理前的獨立備份;另有部署本身觸發的 `/var/backups/mpts/20260904-130048`)。
  - 清理範圍(使用者明確決定):刪除全部 `RosterEntry`(35)、除 `admin` 外的全部 `User`(33,含 5 個來源不明、2026-08-25 同一秒建立的 `admin1`~`admin5` superuser 帳號——使用者確認不需要保留)、全部 `Semester`(4)、`Pairing`(11)、`MatchingInvitation`(46)、`ClassSession`(54,cascade 帶走 41 筆 `ClassRecord`、39 筆 `Attendance`、37 筆 `ClassConfirmation`、10 筆 `MakeupReview`、7 筆 `ClassAlert`、5 筆 `IncidentReport`)、`PairingMessage`(17)、`PairingReleaseRequest`(9)、`HourAdjustment`(2)、`ClassDocument`(2)、`QualificationDocument`(12,含 cascade)、`AuditLog`(412,使用者明確選擇整批清空作為封測期間紀錄的收尾,而非保留)。**保留**:`PartnerProgram` 三筆設定(NTNU/MARYLAND/OTHER)與 `admin` 帳號本身。刪除順序需符合 model 的 `PROTECT`/`CASCADE` 依賴(先刪 `ClassSession`/`PairingMessage`/`PairingReleaseRequest`/`HourAdjustment`/`ClassDocument`,再刪 `Pairing`,再刪 `MatchingInvitation`,再刪 `Semester`,再刪 `User`,最後才能刪 `RosterEntry`),先在本機開發資料庫實際跑過一次確認無 `ProtectedError` 才對正式站執行,整個刪除包在單一 `transaction.atomic()`。清理腳本為一次性用途,**不進 repo**(避免之後被誤用在有真實資料的資料庫上)。
  - 清理後另外移除 `media/qualifications/`、`media/class_documents/` 內的孤兒測試檔案(對應 DB 紀錄已刪;內容已包含在上述備份的 `media.tar.gz`)。`media/class_record_attachments/` 目錄本身不存在(封測期間課堂紀錄皆使用佐證連結,無人使用舊版附件上傳)。
  - 清理後驗證:`https://mpts.tcsl.ntnu.edu.tw/`、`/system-admin/login/` 皆回應 200;`User.objects.all()` 僅剩 `admin`;`PartnerProgram` 三筆設定未受影響;`mpts-gunicorn.service`/`mpts-process-matching-state.timer` 皆正常運作。
  - 清理過程使用的臨時 `sudoers.d/90-mpts-deploy-tmp` NOPASSWD 授權(使用者於清理前在自己的終端機開設)已於清理完成後移除,`sudo -n -l` 確認已恢復需要密碼。
  - **下一步(留給系辦/使用者操作,不在本次清理範圍內)**:匯入真實名冊、建立真實學期,才能真正開放使用者註冊。

## 13. 弱點掃描專用帳號建立紀錄

依 `docs/VULNERABILITY_SCAN_ACCOUNT_SETUP.md` 建立僅供師大資訊中心 HCL AppScan 使用的隔離帳號,不是部署,獨立於第 11 節之外記錄於此;依該文件第九節規定,此處不記錄任何密碼。

- **2026-09-08**：操作者 Claude Code(依使用者指示執行)。建立前唯讀盤點確認正式站無任何 `TEST-SCAN-*` 帳號/名冊,且**正式站目前沒有任何 `Semester`(0 筆)**——封測資料已於 2026-09-04 全數清空(見第 12 節),真實學期尚未建立。
  - 備份:`/var/backups/mpts/20260908-144321`。
  - 建立 4 筆 `RosterEntry` 與對應 `User`/`TutorProfile`/`TuteeProfile`/`SecurityQuestionAnswer`(經真實 HTTPS 註冊流程,非直接寫入資料庫):`TEST-SCAN-TUTOR-NTNU`(TUTOR/MASTER)、`TEST-SCAN-TUTEE-NTNU`(TUTEE/NTNU)、`TEST-SCAN-TUTOR-MD`(TUTOR/BACHELOR)、`TEST-SCAN-TUTEE-MD`(TUTEE/MARYLAND)。兩位老師各上傳一份標明「僅供網站弱點掃描，非正式證明」的測試 PDF 並由管理員(`admin`)核准。
  - **與設定文件表格的一處刻意偏離**:`TEST-SCAN-TUTOR-MD` 的「所屬計畫」依現行 `tutor_can_serve_program()` 規則設為 `MARYLAND`(文件表格原寫「留空」;若真的留空,該 Tutor 依規則只能服務 NTNU,無法與馬里蘭 Tutee 配對,會讓文件自己要求的「Maryland 配對均成立」驗收項目在規則上不可能達成)。已於執行時以程式註解記錄原因,細節見完成回報。
  - **因無可用學期而中止**:依文件 5.3.3「如果某計畫沒有可用學期,停止建立配對並回報,不可擅自新增會影響正式規則的學期」,NTNU 與 MARYLAND 配對均未建立,5.4 節的課程/課堂紀錄/私訊/佐證連結/附件測試資料亦連帶未建立(皆依賴配對存在)。未新增任何 `Semester`。
  - 密碼由本機 Python 腳本產生,全程未輸入為 shell 參數、未寫入 VM、未印出於任何輸出,僅存於使用者本機一個 600 權限的暫存檔(路徑於完成回報中告知,不在此記錄),供填入資訊中心表單後由使用者自行刪除。
  - 已完成的權限隔離驗證(帳號未登入時保護頁面導回登入頁、各帳號可開啟自己的首頁與個人資料頁、資格文件僅本人與 Admin 可下載、彼此虛構 Email 不互相外流)全數通過,細節見完成回報。
  - 過程使用的臨時 `sudoers.d/90-mpts-deploy-tmp` NOPASSWD 授權(使用者事先在自己的終端機開設)已於完成後移除,`sudo -n -l` 確認已恢復需要密碼。`git status`、`mpts-gunicorn.service`、`journalctl` 均無非預期變化。
  - **待辦(留給使用者)**:確認是否/何時建立正式 NTNU、MARYLAND 學期,學期到位後再繼續完成 5.3 配對與 5.4 測試資料;掃描完成後依文件第九節停用帳號、更換密碼,複掃確認不需要後再依外鍵順序清除。

- **2026-09-08(續)**：使用者確認正式學期期間為 2026-09-14～2026-12-31,並指示「直接用吧」——這同時是系辦真正要用的第一個正式學期,不是只為掃描建的假期間。操作者 Claude Code(依使用者指示執行)。
  - 備份:`/var/backups/mpts/20260908-145718`。
  - 建立 2 筆正式 `Semester`(id 5 NTNU、id 6 MARYLAND,皆 2026-09-14～2026-12-31、`is_active=True`),寫法比照 `save_semester()` 的建立路徑(`full_clean()` + `AuditLog.record(event_type="SEMESTER_CREATED")`,actor 為正式 `admin` 帳號)。
  - 用 `tutoring.services.create_admin_pairing()` 建立兩組配對:`TEST-SCAN-TUTOR-NTNU`×`TEST-SCAN-TUTEE-NTNU`(pairing 12,學期 5)、`TEST-SCAN-TUTOR-MD`×`TEST-SCAN-TUTEE-MD`(pairing 13,學期 6)。
  - 5.4 節最低限度可操作資料(改為集中建置,不逐項重複):兩組配對各排一堂未來課程(`schedule_classes()`);Maryland 配對一則不含個資的私訊;NTNU 配對一堂**已完成、經補登審核核准**的過去課程(session 57,2026-09-14 09:00),雙方簽到、雙方課堂紀錄(Tutor 端含 1 個 `https://example.com` 測試佐證連結;Tutee 端故意 0 個佐證連結、但附上一份標明「僅供網站弱點掃描測試附件」的合法 PDF 到舊版附件欄位)、雙方互相確認、管理員核准補登,`class_is_valid()` 已確認為 `True`。
  - **時間戳記特別說明**:選定的學期從 9/14 才開始,晚於執行當下的真實日期(9/8),因此排課用 `schedule_classes()` 本身的「必須排在未來」限制,天然只能排在 9/14 之後——這對兩堂「未來課程」沒有影響,但代表用同一個限制無法生出「已經發生」的過去課程可測。這堂過去課程改為直接以 ORM + `full_clean()` 建立 `ClassSession`(日期訂在學期第一天 9/14,略過的只是排課服務對「不可回填」的介面層限制,不是資格/配對/稽核規則),再對 `check_in()`/`submit_class_record()` 這兩個本來就支援 `now` 參數的服務函式,傳入一個模擬時鐘(2026-09-16 12:00)觸發補簽到/補課堂紀錄流程——所有補登門檻、次數上限與審核流程都是用這個模擬時鐘正常跑過,不是繞過規則。副作用是這堂課的 `signed_at`/`submitted_at` 時間戳記(2026-09-16)會早於本次操作的真實系統時間(2026-09-08),之後若有人查資料庫發現這點屬於已知、刻意的掃描測試資料特徵,不是資料異常。
  - 驗證:直接以四個帳號的真實登入 session 對 `/matching/classes/<id>/`、`/matching/pairings/<id>/messages/` 做過端到端存取測試——配對雙方可開啟、非配對方回應 404;Maryland 配對訊息內容只有配對雙方看得到。另發現且確認為**預期行為非缺陷**:因為 `active_semester()` 只回傳「今天落在起訖區間內」的學期,今天(9/8)還沒到 9/14,四個帳號的 Dashboard「目前配對／我的課表」卡片目前都還是空的(要等 9/14 才會顯示);但用直接連結開課程詳情頁、訊息頁都正常運作且權限隔離正確——**如果資訊中心排的正式掃描時間在 9/14 之前執行,爬蟲若只靠 Dashboard 導覽可能爬不到這些深層頁面,建議掃描排在 9/14(含)之後,或另外把這幾個直接連結交給資訊中心**。
  - 服務與日誌檢查:`git status` 僅有既存的 `.cache/`/`staticfiles/` 未追蹤目錄(非本次改動);`mpts-gunicorn.service`/`mpts-process-matching-state.timer` 皆 active;`journalctl` 排除既有的 gunicorn `Control server error` 訊息與外部機器人探測 `/logs/error.log` 的雜訊(與本次操作無關)後,沒有任何 traceback/critical 等級紀錄。臨時 sudo 授權已於完成後移除並確認恢復需要密碼。
