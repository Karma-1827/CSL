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

### 6.3 更新應用程式

```bash
source /opt/mpts/.venv/bin/activate
pip install -r requirements.txt

python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py collectstatic --noinput
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
