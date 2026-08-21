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

- **2026-08-21**：操作者 Claude Code。上一版 `af7fc38` → 新版 `6e5ec53`（`188b7c3`：`/system-admin/` 白名單改為整個師大網段 `140.122.0.0/16`（先前逐一加 `/24` 白名單追不上實際觀察到的多個不同校內來源網段，這次未含在本次程式部署內，屬 Nginx 設定變更，已於當天先行套用；`6e5ec53`：註冊安全問題三選單改為即時互斥選取，選過的題目自動從其他兩個選單停用，伺服器端重複檢查不變）。無 migration。部署前備份：`/var/backups/mpts/20260821-154707`。驗收：`https://mpts.tcsl.ntnu.edu.tw/` 回應 200、新增的 `static/js/security-questions.js` 回應 200。這次 `git checkout --detach` 乾淨無衝突。
- **2026-08-18**：操作者 Claude Code。上一版 `859f48e` → 新版 `af7fc38`（配色改為師大酒紅/金色系 + 頁首並列師大校徽與華語系 logo，`603eace`/`af7fc38`）。無 migration。部署前備份：`/var/backups/mpts/20260818-171119`。驗收：`https://mpts.tcsl.ntnu.edu.tw/` 回應 200，`app.css` 內容確認為新色票、`ntnu-logo.png` 回應 200，`link` 標籤 cache-busting 版本正確更新。過程中發現 `deploy/backup_mpts.sh` 先前是用 `scp`/`install` 手動佈署到 VM 上（在該檔案真正進入 git 歷史之前），與這次 `git checkout --detach` 的目標 commit 衝突（unmerged untracked file）；核對兩者內容位元組相同後刪除未追蹤版本再重試，之後的部署不會再遇到這個特定衝突。
