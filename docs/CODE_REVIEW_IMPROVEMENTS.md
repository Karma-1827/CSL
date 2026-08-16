# CSL 華語輔導系統 Code Review 改善清單

> 盤點日期：2026-07-30  
> 目的：提供後續 AI coding agent／工程師接手整改使用。  
> 狀態：**歷史盤點文件，已併入 `docs/VULNERABILITY_SCAN_IMPROVEMENTS.md` 與 `docs/PROGRESS.md`。** 本文件保留原始發現與設計理由，不再作為目前完成狀態的判斷依據；附件權限、production fail-closed、共享節流、可信 proxy、上傳驗證、Admin 業務資料唯讀等項目均已完成。最新弱掃狀態以 `docs/VULNERABILITY_SCAN_IMPROVEMENTS.md` 為準。

## 1. 執行原則

1. 先處理 P0 上線阻斷項目，再處理資料一致性、效能與 UX。
2. 修改前先閱讀 `CLAUDE.md`、`docs/PROGRESS.md`、`docs/SECURITY_CHECKLIST.md` 與 `docs/DEPLOY.md`。
3. 不得清除或重建既有 PostgreSQL 資料庫、migration、media 或使用者資料。
4. 不得直接修改使用者尚未提交的既有變更。
5. 每個整改項目都應補測試；完成後至少執行：

   ```bash
   python manage.py test --verbosity 1
   python manage.py check
   python manage.py makemigrations --check --dry-run
   DJANGO_DEBUG=0 DJANGO_SECRET_KEY='deployment-check-only-secret-key-that-is-long-and-random-2026' \
     python manage.py check --deploy
   ruff check .
   ```

6. 涉及業務規則但尚未定案的項目，不可自行假設，應先詢問使用者或系辦。

## 2. 歷史品質基準

以下是 2026-07-30 整改前的盤點結果，不代表目前狀態；2026-08-10 最新基準為 Django 273 項測試、Ruff、migration、`check --deploy`、`pip check`、`pip-audit` 全數通過。

- Django 測試：134 項全數通過。
- `manage.py check`：通過。
- `manage.py check --deploy`：通過。
- migration 檢查：沒有遺漏。
- Ruff：通過。
- `pip check`：沒有相依性衝突。
- 手機版登入頁在 390 × 844 viewport 下沒有水平溢出。
- Tutor 註冊資料頁在 390px 寬度下約 4,941px 高，共有約 29 個必填欄位，仍有明顯的填寫負擔。

上述結果只表示現有測試涵蓋的功能正常，不代表已符合正式環境的安全、效能與維運要求。

## 3. 優先級總覽

| 優先級 | 項目 | 性質 | 是否阻擋正式上線 |
| --- | --- | --- | --- |
| P0 | 使用者上傳附件改為受權限保護的下載 | 資安／個資 | 是 |
| P0 | 正式環境缺少 `SECRET_KEY` 時拒絕啟動 | 資安／部署 | 是 |
| P0 | 登入與忘記密碼節流改為共享且可信 | 資安 | 是 |
| P1 | 驗證上傳檔案的真實內容並處理舊檔 | 資安／儲存 | 建議是 |
| P1 | 保存歷史證明所需的資料快照 | 行政資料一致性 | 是 |
| P1 | 學期日期修改加入既有資料防呆 | 業務資料一致性 | 是 |
| P1 | 防止 Django Admin 繞過配對人數限制 | 業務資料一致性 | 建議是 |
| P2 | 移除時數計算與 Admin dashboard 的 N+1／全量載入 | 效能 | 否 |
| P2 | 確認正常簽到與課堂紀錄的寬限時間 | 產品規則 | 待確認 |
| P2 | Tutor 註冊流程分步化 | UX | 否 |
| P2 | 強化 AuditLog 寫入失敗時的告警 | 稽核／維運 | 建議是 |
| P3 | 清理死欄位、過大檔案與 PDF 模板警告 | 技術債 | 否 |
| P3 | 修正部署文件與實際設定不一致 | 文件／部署 | 否 |

---

## 4. P0：正式上線阻斷項目

### 4.1 使用者附件目前採直接 media URL

#### 現況

資格證明與課堂附件直接輸出 `FileField.url`：

- `templates/accounts/admin_user_profile.html`
- `templates/dashboard/index.html`
- `templates/tutoring/class_detail.html`
- `templates/tutoring/admin_record_card.html`
- `config/settings.py` 的 `MEDIA_URL`／`MEDIA_ROOT`
- `config/urls.py` 在 DEBUG 模式下直接提供 media

正式部署若由 Nginx 直接提供 `/media/`，請求不會經過 Django 的登入、角色或配對關係檢查。取得附件網址的人可能繞過介面直接下載資格文件或課堂附件。

#### 建議方案

1. `/media/` 不作為公開 static location。
2. 建立受保護的下載 view：
   - 資格文件：只允許文件本人及 Admin。
   - 課堂附件：只允許該堂課的 Tutor、Tutee 及 Admin。
3. Django 完成權限判斷後：
   - 開發環境可使用 `FileResponse`。
   - 正式環境建議使用 Nginx `X-Accel-Redirect` 傳輸。
4. 儲存檔名使用隨機 UUID；原始檔名只保留在資料庫供畫面顯示。
5. 設定：
   - 禁止 directory listing。
   - 適當的 `Content-Disposition`。
   - `X-Content-Type-Options: nosniff`。
   - 私有附件不使用公開快取。

#### 驗收標準

- 未登入者即使知道附件網址也無法下載。
- 非配對成員無法下載其他課堂附件。
- Tutor 無法下載其他 Tutor 的資格文件。
- Admin 可以從原本介面正常開啟文件。
- DEBUG 與正式 Nginx 環境都能通過測試。

### 4.2 正式環境仍可能使用公開的預設 SECRET_KEY

#### 現況

`config/settings.py` 在沒有 `DJANGO_SECRET_KEY` 時使用固定字串：

```python
dev-only-change-before-deployment-csl-tutoring-system
```

實測在 `DJANGO_DEBUG=0` 且沒有設定密鑰時，系統仍可啟動。

#### 建議方案

- 只有開發模式可以使用開發用預設值。
- `DEBUG=False` 且未設定正式密鑰，或仍等於開發預設值時，拋出 `ImproperlyConfigured` 並拒絕啟動。
- 增加 deployment test 驗證：
  - 缺密鑰必須啟動失敗。
  - 有長且隨機的密鑰才可通過。

#### 驗收標準

- `DJANGO_DEBUG=0` 且缺少 `DJANGO_SECRET_KEY` 時，`manage.py check --deploy` 或應用啟動會失敗並顯示清楚原因。
- 開發模式仍能依 README 指令啟動。
- `.env.example` 與 `docs/DEPLOY.md` 的說明同步。

### 4.3 登入與帳號恢復節流不適合多 worker 正式環境

#### 現況

- `accounts/forms.py::BilingualAuthenticationForm` 使用 Django `cache` 記錄登入失敗次數。
- `accounts/views.py::recover_account` 使用相同方式限制安全問題嘗試。
- 專案沒有設定正式共享 cache，目前實際後端是 `LocMemCache`。
- 多個 Gunicorn worker 不共享計數，服務重啟也會清空。
- `accounts/forms.py::client_ip()` 直接採用外部傳入的 `X-Forwarded-For` 第一個值。實測使用者可以自行指定此值，進而切換節流 key。

#### 建議方案

可選一種：

1. 使用 Redis 作為 Django cache；或
2. 使用 PostgreSQL 保存登入節流紀錄。

另外：

- 由 Nginx 覆寫可信 IP header，不接受用戶端自行指定的第一個 `X-Forwarded-For`。
- 清楚定義可信 proxy 數量。
- 同時考慮「IP＋學號」與「單一學號」的限制，避免攻擊者持續更換 IP。
- 對登入成功、被鎖定、恢復失敗寫入適量 AuditLog，但不可記錄密碼或安全問題答案。

#### 驗收標準

- 不同 worker 看到相同嘗試次數。
- 重啟其中一個 worker 不會重置限制。
- 偽造 `X-Forwarded-For` 不能繞過限制。
- 多位使用者經同一校園 NAT 登入時，不會因只看 IP 而互相誤鎖。
- 第 5 次／第 6 次的實際行為與提示訊息有明確測試。

---

## 5. P1：資安與資料一致性

### 5.1 上傳驗證只檢查副檔名及大小

#### 現況

`tutoring/models.py::_validate_upload()` 只檢查：

- `.pdf`、`.jpg`、`.jpeg`、`.png`
- 檔案大小

實測將 HTML／script 內容命名為 `.pdf` 後，驗證仍會通過。

`docs/SECURITY_CHECKLIST.md` 目前寫 Pillow 用於圖片附件驗證，但實際程式碼沒有使用 Pillow，文件與實作不一致。

#### 建議方案

- JPG／PNG：使用 Pillow `Image.open()` 與 `verify()`。
- PDF：使用 pypdf 嘗試解析，限制合理頁數，拒絕損壞檔案。
- 檢查檔頭／magic bytes，不只看副檔名及瀏覽器傳來的 MIME。
- 上傳後使用安全的伺服器端檔名。
- 替換 `QualificationDocument.file` 或 `ClassRecord.attachment` 時，明確刪除、封存或排程清除舊檔。
- 系辦確認是否需要防毒掃描；若需要，可在正式環境串 ClamAV，但這不是目前既有需求，不應擅自加入外部 SaaS。

#### 驗收標準

- 假 PDF、損壞圖片、內容與副檔名不符的檔案會被拒絕。
- 合法 PDF/JPG/PNG 仍可上傳。
- 錯誤訊息使用一般使用者可理解的中英文。
- 替換附件後不會留下無人引用且含個資的舊檔。
- `SECURITY_CHECKLIST.md` 與實際驗證行為一致。

### 5.2 歷史時數證明會讀取學生目前的 Profile

#### 現況

`tutoring/reporting.py::hour_report_data()` 產生證明時，直接讀取 TuteeProfile 目前的：

- 國籍
- 華語程度

若學生上課時為 A2，之後修改為 B2，再下載同一期間的詳細證明，歷史證明會變成 B2，無法重現當時資料。

#### 建議方案

需要先決定快照時點，建議選項：

- 配對成立時保存配對快照；或
- 每堂課第一次有效成立時保存課程證明快照。

至少保存：

- 學生國籍
- 學生華語程度
- 合作計畫名稱／代碼
- 必要時保存雙方顯示姓名與學號

建議以「課程層級快照」產生詳細證明，才能正確反映不同日期的程度或計畫變化。

#### 驗收標準

- 修改 Profile 前後，過去已成立課程的證明內容保持一致。
- 新課程使用修改後的新資料。
- 舊資料 migration 有明確回填策略，不能靜默填入錯誤歷史值。

### 5.3 Admin 修改學期日期會回溯改變既有規則

#### 現況

`SemesterSettingsForm` 允許修改開始日、結束日及啟用狀態。儲存時只驗證學期彼此不重疊，沒有檢查既有 Pairing、ClassSession、補登截止日或證明開放時間。

修改結束日期會立即改變：

- 哪個學期被視為目前學期。
- 自動解除配對的時間。
- 補簽／補紀錄截止時間。
- 時數證明開放時間。
- 既有課程是否仍落在學期範圍。

#### 建議方案

- 尚無配對／課程的學期可自由編輯。
- 已有資料時：
  - 禁止把日期縮到既有課程之外；或
  - 先顯示受影響配對、課程與截止日，再要求 Admin 二次確認。
- 日期修改寫入 AuditLog，metadata 應包含修改前後的日期。
- 若學期已結束且已有時數證明，建議只允許特殊修正流程，不提供一般編輯。

#### 驗收標準

- 不可將學期日期改到排除既有課程。
- 受影響時畫面說明具體原因及資料筆數。
- 無資料的未來學期仍可正常修改。
- AuditLog 可查到修改前後值。

### 5.4 Django Admin 可繞過 Tutor 同時最多兩位學生的限制

#### 現況

一般配對流程在 service 層檢查 Tutor 上限，但：

- DB constraint 只保障每位 Tutee 同學期最多一位 active Tutor。
- `PairingAdmin` 仍允許直接新增及修改。
- Admin 可能直接建立第三筆 active pairing。

#### 建議方案

- 優先方案：禁止 Django Admin 直接新增 Pairing，只允許唯讀或有限修正。
- 若仍需 Admin 手動配對，建立正式的「管理員建立配對」服務，重用完整業務驗證與 transaction locking。
- Model `clean()` 可增加防呆，但不能把它視為唯一的競態保護。

#### 驗收標準

- 所有入口都不能讓 Tutor 同學期同時有超過兩位 active Tutee。
- Admin 手動操作也必須遵守限制。
- 兩個併發接受邀請的情況有測試。

---

## 6. P2：效能、產品規則與 UX

### 6.1 時數計算及 Admin dashboard 查詢量會隨課程筆數線性增加

#### 現況

`tutoring/services.py::class_is_valid()` 會對 Attendance、ClassRecord、ClassConfirmation 與 MakeupReview 執行多次 relation 查詢。

即使 caller 已 `prefetch_related()`，帶條件的 `.filter()`／`.exists()` 仍可能重新查 DB。本次以 Demo Tutor 5 堂課執行 `valid_sessions_for_user()`，共產生 22 次 SQL query。

`accounts/views.py::dashboard()` 的 Admin 分支會：

1. 先載入選定學期全部課程。
2. 在 Python 計算全部老師的課程與時數。
3. 最後才將老師清單分頁。

500 位使用者、數千堂課時會拖慢 Admin dashboard、匯出及 PDF 產生。

#### 建議方案

- 將有效課程判定改為：
  - queryset annotation (`Count`、`Exists`)；或
  - 明確使用已 prefetch 的 list，不在迴圈內重新 filter。
- Admin 老師名單先在 DB 分頁，再只抓當頁老師所需課程統計。
- 大型 Excel／PDF 匯出評估背景工作，但 500 人規模可先完成 query 優化及壓力測試，再決定是否加入 queue。
- 加入 query-count regression tests。

#### 驗收標準

- 5 堂與 500 堂課的 query 數不應按每堂增加 3～4 次。
- Admin dashboard 只載入當頁所需老師的詳細資料。
- 500 位使用者／合理課程量的測試資料下，主要頁面回應時間有量測紀錄。

### 6.2 正常簽到與課堂紀錄的寬限時間待系辦確認

#### 現況

目前程式規則：

- 上課前 10 分鐘開放簽到。
- 課程結束後 30 分鐘內簽到仍算正常簽到。
- 課程結束後 24 小時內提交課堂紀錄仍算正常紀錄。
- 超過上述時間才算補登並進入 Admin 審核。

#### 必須確認

1. 課後正常簽到是否真的允許 30 分鐘？
2. 課堂紀錄是否允許課後 24 小時免審核？
3. 如果課堂尚未結束，是否可先提交課堂紀錄？
4. 使用者第一次在期限內提交、期限後修改，是否應轉成補登？

在系辦確認前，不要自行修改數值。

### 6.3 Tutor 註冊頁在手機上過長

#### 現況

390px 寬度下：

- 頁面高度約 4,941px。
- 約 29 個必填欄位。
- 基本資料、教學能力、資格文件、上課時間與安全問題集中在同一頁。

#### 建議方案

沿用既有 `RegistrationDraft`，拆成三步：

1. 基本與聯絡資料。
2. 教學履歷、能力評分與資格文件。
3. 上課時間、安全問題與送出確認。

介面應提供：

- 明確的進度指示。
- 上一步／下一步。
- 每一步獨立驗證。
- 回到前一步不遺失已填資料。
- 最後送出前的摘要確認。

#### 驗收標準

- 手機上每一步不超過合理的欄位量。
- 使用者返回上一頁時資料仍保留。
- 任一步錯誤會自動定位並清楚顯示。
- 重新整理、逾時與直接輸入步驟網址的行為有測試。

### 6.4 AuditLog 採 fail-open，重要操作可能成功但沒有稽核紀錄

#### 現況

`accounts/models.py::AuditLog.record()` 捕捉所有例外後回傳 `None`，主要業務操作仍成功。這能避免 logging failure 破壞業務交易，但資格審核、時數調整、資料匯出等敏感動作可能沒有稽核軌跡。

#### 建議方案

- 保留一般事件 fail-open，但必須加入正式告警與監控。
- 對高風險事件評估：
  - fail-closed；或
  - transaction outbox／待補寫稽核事件。
- 至少監控 `csl.audit` logger，不能只寫到無人查看的本機 log。

#### 驗收標準

- 模擬 AuditLog 寫入失敗時，監控能收到明確告警。
- 高風險操作的預期行為有文件與測試。
- 不記錄密碼、安全問題答案或附件內容。

---

## 7. P3：技術債與文件

### 7.1 `ClassRecord.reflection` 是未使用欄位

- Model 有 `reflection`。
- `ClassRecordForm` 已不包含此欄位。
- UI 也已移除「學習成果與回饋」。

需要確認歷史資料是否有內容；若沒有用途，建立 migration 移除。不可只從 model 刪除而不做 migration。

### 7.2 核心檔案過大

目前約略狀況：

- `accounts/views.py` 超過 1,100 行。
- `tutoring/services.py` 接近 1,000 行。
- `static/css/app.css` 超過 3,500 行。

建議功能穩定後按領域拆分：

- accounts：registration、profiles、admin dashboard、recovery、roster。
- tutoring：matching、schedule、attendance、records、reports、exports。
- CSS：foundation、auth、dashboard、forms、schedule、admin、responsive。

這是可維護性改善，不應和 P0 修正混在同一個巨大 commit。

### 7.3 PDF 模板存在 pypdf 物件參照警告

完整測試雖然通過，但 PDF 產生時多次出現：

```text
Ignoring wrong pointing object ...
```

目前仍能產生 PDF，但未來 pypdf 升級可能轉為錯誤。建議使用可靠 PDF 工具重新另存學校模板，並重新跑：

- 摘要版。
- 詳細版。
- 多頁詳細版。
- NTNU 與 Maryland 模板。

需要做視覺比對，不能只檢查 `PdfReader` 能否開啟。

### 7.4 部署文件與實際 settings 不一致

`docs/DEPLOY.md` 要求設定 `CSRF_TRUSTED_ORIGINS`，但：

- `config/settings.py` 沒有讀取對應環境變數。
- `.env.example` 沒有該欄位。

需要選擇：

- 實作 `DJANGO_CSRF_TRUSTED_ORIGINS` 解析並加入範例；或
- 若正式部署確定同源且不需要，修正文案，避免維運人員以為已生效。

### 7.5 依賴漏洞掃描沒有排程

`.github/workflows/ci.yml` 只在 push／pull request 執行。若數月沒有 push，新 CVE 不會主動被發現。

建議加入每週一次的 GitHub Actions schedule，並確認失敗通知由誰接收。

---

## 8. 建議實作批次

為避免一次修改過大，建議拆成：

### 批次 A：上線安全邊界

- 私有附件下載。
- 真實檔案內容驗證。
- 舊附件清理政策。
- 正式環境 SECRET_KEY fail-fast。

### 批次 B：登入安全與部署設定

- 共享節流儲存。
- 可信 proxy IP。
- `CSRF_TRUSTED_ORIGINS` 與 `.env.example`。
- 補安全回歸測試。

### 批次 C：行政資料一致性

- 歷史證明快照。
- 學期日期修改防呆。
- Admin 配對限制。

### 批次 D：效能

- `class_is_valid()` 查詢優化。
- Admin dashboard DB 分頁／統計。
- 匯出與 PDF 壓力測試。

### 批次 E：UX 與技術債

- 註冊分步。
- 移除 dead field。
- 拆分過大檔案。
- 清理 PDF 模板。

每個批次應獨立 commit，避免資安修正、schema migration、UI 大改和重構全部混在一起。

## 9. 需要使用者／系辦先確認的問題

1. 課後 30 分鐘內簽到是否仍屬正常簽到？
2. 課後 24 小時內填寫課堂紀錄是否免 Admin 審核？
3. 歷史證明應保存「配對成立時」還是「每堂課成立時」的國籍與程度？
4. 已有課程的學期日期是否允許 Admin 修改？若允許，哪些情況可修改？
5. AuditLog 寫入失敗時，重要 Admin 操作應阻擋，還是允許成功後告警補寫？
6. 資格證明與課堂附件的保存期限、刪除責任人及備份保留期限。
7. Tutor 註冊是否接受改成三步式流程？
8. 是否需要使用 ClamAV 做附件防毒，或先以格式驗證及私有下載完成第一階段？

## 10. 完成定義

不能只把程式改到「測試通過」。一項整改只有同時符合以下條件才算完成：

- 功能行為符合已確認規則。
- 有成功、拒絕、越權與異常情境測試。
- DB constraint／transaction 與前端驗證相互配合。
- 中英文提示清楚。
- 手機與桌面主要流程完成實際瀏覽器驗證。
- `CLAUDE.md`、`docs/PROGRESS.md`、`docs/SECURITY_CHECKLIST.md`、`docs/DEPLOY.md` 中受影響的內容同步更新。
- 不引入真實個資、附件、`.env` 或測試密碼至 Git。
