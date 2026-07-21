# CLAUDE.md

本文件供 Claude Code 與其他 AI coding agent 在專案啟動時快速取得正確脈絡。除非使用者明確改變需求,請以**目前程式碼、資料庫約束與測試**為準,不要只依 README 或歷史對話推測功能。

> 最後盤點日期:2026-07-21
> 專案路徑:`/Users/Qiangqiang/Desktop/CSL`
> 版本控制狀態:此目錄目前**不是 Git repository**,沒有 `.git`,因此無 commit history 可查。下列進度是由現有程式、migration 與測試整理,不是由 commit 推導。
>
> 本檔案只放**核心業務邏輯與慣例**(變動頻率低)。開發進度、已知缺口與部署細節(變動頻率高或非日常開發所需)已拆到:
> - `docs/PROGRESS.md` — 目前開發進度、已知缺口、尚未定案決策
> - `docs/DEPLOY.md` — 部署步驟與 checklist

## 1. 專案目的與背景

這是國立臺灣師範大學華語文教學系的「華語輔導系統 / Chinese Language Tutoring System」。主要服務情境是:

- 華語系研究所學生的畢業條件包含實習時數;未參與其他實習者可透過輔導外籍生累積時數。
- 大學部學生可因修課使用系統,博士生可累積輔導經驗;實際資格文件種類仍待系辦最後確認。
- 師大外籍生需要華語輔導;馬里蘭大學等合作計畫學生需要語言交換及時數證明。
- 舊流程以紙本管理,助教難以掌握名冊、配對、排課、雙方出席、課堂紀錄、補登與有效時數。

系統目標是讓約 300–600 名使用者在同一平台完成:名冊核對註冊、匿名配對、排課、簽到、雙方課堂紀錄與互認、補登審核、私訊、時數統計、證明下載,以及 Admin 的全系總覽與資料匯出。

## 2. 角色與功能

程式內角色定義於 `accounts.models.Role`。對使用者 UI 一律稱「老師 / Teacher」與「學生 / Student」;`Tutor`、`Tutee` 是程式內領域名稱。

### Admin(管理員)

- 不可由公開學生名冊註冊;用 `createsuperuser` 或 Django Admin 建立。
- 後台入口:`/system-admin/`。
- 管理學生名冊、帳號、帳號狀態、資格文件與稽核紀錄。
- 自訂 Admin dashboard 顯示名冊/註冊/角色/配對/邀請統計。
- 審核 Tutor 資格文件。
- 設定學期、修改學期、手動封存學期。
- 查看解除配對申請並核准/拒絕;查看歷史結果。
- 查看全系課程總覽、老師名單、各老師個人課表及未完成課程。
- 查看課堂通報;目前通報只能由原通報者取消,Admin 沒有「已處理」狀態。
- 查看課程雙方的簽到、紀錄、確認與補登詳情。
- 逐筆核准或拒絕補簽到/補課堂紀錄。
- 依全體或指定使用者、學期或自訂日期範圍匯出 Excel 2003 XML `.xls`。
- 可透過 Django Admin 手動修改密碼;目前沒有客製化 Admin 密碼重設頁。

### Tutor(老師;華語系學生)

- 名冊包含學制(大學、碩士、博士)與身分類別;一個學號只能建立一個角色。
- 兩階段註冊後建立教學 Profile,包含性別、母語、國籍、系所、聽說讀寫 1–5、簡介、時段及安全問題。
- 上傳資格文件(PDF/JPG/JPEG/PNG,最大 1 MB);註冊時可先略過,但**資格狀態必須為 APPROVED 才能配對**。
- 瀏覽匿名學生資料並發邀請;配對前看不到姓名、學號、電話或 Email。
- 同一學期最多同時輔導 2 位學生。
- 接受/拒絕收到的邀請,或取消自己尚未回覆的邀請。
- 配對成立後可查看完整學生資料、使用配對私訊、提出解除配對。
- 只有 Tutor 能建立、取消、修改課程及建立每週重複課程。
- 每堂課需簽到、填寫自己的課堂紀錄,並確認對方的簽到與紀錄。
- 查看已排/有效/累積時數、學期歷史及下載正式 PDF 證明。

### Tutee(學生)

共用能力:

- 名冊核對後註冊;建立華語程度、學習時間、聽說讀寫、加強項目、需求與可上課時段。
- 接收 Tutor 邀請並查看匿名 Tutor 資料;配對後查看完整資料與私訊。
- 查看 Tutor 安排的課程;目前由 Tutor 與本人線下協調,Tutee 不需在系統中接受排課。
- 每堂課與 Tutor 採相同機制:都要簽到、填寫自己的課堂紀錄、確認對方內容。
- 可提出解除配對;解除後可換新 Tutor,但同學期不可和原 Tutor 再配。

依 `RosterEntry.program_source` 有下列差異:

- `NTNU` 師大外籍生:不能主動邀請 Tutor;沒有時數需求,dashboard 不顯示時數總覽與證明下載。
- `MARYLAND` 馬里蘭學生:可瀏覽匿名 Tutor 並主動邀請;可統計與下載語言交換時數證明;目前無 32/64 小時上限。
- `OTHER` 其他合作計畫:可下載合作計畫證明,但目前 `_is_maryland_tutee()` 只允許 `MARYLAND` 主動邀請。擴充新合作計畫前必須先和系辦確認此差異。

## 3. 系統邊界(目前不做)

- 不串接 Google、OAuth、學校 SSO、校務系統或其他外部登入 API。
- 不寄 Email、簡訊、推播或外部行事曆通知。
- 不使用 GPS、地理圍欄、QR code 或裝置定位驗證簽到;簽到只是登入後按鈕。
- 不處理線上付款、費用、薪資、收費或帳務。
- 不提供視訊教室、線上教材、作業系統或影音儲存。
- 私訊為 Django request/response 頁面,不是 WebSocket 即時聊天,也沒有外部通知。
- 不讓使用者自行選擇或變更角色;角色完全由預載名冊決定。
- 不允許同一學號同時是 Tutor 與 Tutee。
- 不開放 Admin 公開註冊。
- 不讓 NTNU 外籍生主動邀請 Tutor。
- 不替使用者自動安排配對或推薦排序;候選名單目前只是匿名篩選。
- 不強迫 16 週每週都有課;有完成且有效才計時數,沒上課就沒有時數。
- 不要求達到 100 小時才下載證明;證明按有效紀錄的實際時數產生。
- 不限制上課在 09:00–19:00;可排 24 小時內任意時間,但分鐘須為 5 的倍數。
- 目前無 native mobile app;只做響應式 Web UI。
- 尚未完成學校 SSO、正式 VM 反向代理、Gunicorn/uWSGI、systemd、Nginx、備份/監控設定(見 `docs/DEPLOY.md`)。

## 4. 核心業務邏輯

### 4.1 名冊、註冊與帳號恢復

- `RosterEntry.student_id` 與 `User.username` 都代表學號;學號唯一。
- 公開註冊第一階段只接受 `is_enabled=True`、尚未 claimed、角色為 Tutor/Tutee 的名冊。
- 第一階段建立 `RegistrationDraft`,只保存 Django 密碼雜湊,30 分鐘到期。
- 第二階段依名冊角色進入 `/register/tutor/` 或 `/register/tutee/`;完整 Profile、安全問題與同意欄位成功後才建立正式 `User`,並設定 `claimed_at`。
- 預覽頁 `/preview/tutor/`、`/preview/tutee/` 只在 `DEBUG=True` 開放,不寫入資料庫。
- 密碼至少 10 字元,套用 Django similarity/common/numeric validators。
- 忘記密碼採「學號＋原本選定的三題＋三個答案」;答案正規化後只存 hash。
- 恢復驗證同 IP＋學號 15 分鐘最多 5 次;驗證成功後 10 分鐘內必須完成新密碼設定。
- `User.account_status=SUSPENDED` 時禁止登入。

### 4.2 學期

- 學期只有開始/結束日;已移除另外的配對開始/截止欄位,所以配對窗口就是整個學期。
- 啟用中學期日期不可重疊。
- 今天尚未結束的啟用學期最多 3 個(目前＋未來兩學期)。
- 學期結束超過 6 個月後,`archive_expired_semesters()` 只把 `is_active=False`;不刪學期、課程或時數。
- 學期結束後 active pairing 自動結束,pending release 也會被標為自動處理。
- `dashboard()` 會呼叫 `synchronize_matching_state()`;正式環境仍須排程 `python manage.py process_matching_state`,否則無流量時不會即時處理。

### 4.3 匿名資料與邀請

配對前不得顯示姓名、英文名、完整學號、電話、Email。程式目前匿名欄位如下:

- Tutee:性別、母語、國籍、整體華語程度、加強項目、學習時間、需求備註、可上課星期/時段。
- Tutor:性別、母語、國籍、四項教學能力、教學簡介、可上課星期/時段。

邀請規則:

- 邀請有效 5 天;過期後 `EXPIRED`。
- Tutor 必須有 APPROVED 資格文件且名額未滿。
- Tutor 可邀請可用 Tutee;只有 `MARYLAND` Tutee 可主動邀請 Tutor。
- 收件人接受後立即建立 Pairing,不需 Admin 核准。
- Tutee 同學期最多 1 個 active Tutor;Tutor 同學期最多 2 個 active Tutee。
- 接受某 Tutee 的邀請後,該 Tutee 其他 pending invitations 會自動取消。
- `Pairing` 對 `(semester, tutor, tutee)` 有永久唯一約束:同學期曾配對過,即使解除後也不能再配同一人。
- 解除後雙方只要各自仍有名額,可和不同對象重新配對。

### 4.4 解除配對

- Tutor 或 Tutee 都能提出;同一 pairing 同時只能有一筆 pending request。
- `NO_SHOW`、`UNREACHABLE`、`SCHEDULE_CONFLICT`:Admin 可先處理;若 3 天未處理,系統自動解除。
- `CONDUCT`、`OTHER`:必填補充說明且永不自動解除,只能由 Admin 決定。
- 核准/自動解除時:Pairing 變 `ENDED`,未來尚未取消的課程會取消並釋放額度;已結束的課程與時數紀錄保留。
- Admin 拒絕時 pairing 保持 active。

### 4.5 排課與額度

- 只有 active pairing 的 Tutor 可排課。
- 課程時數只能為 0.5、1、1.5、2 小時;正式時數依排課時數,不依實際簽到時間差。
- 開始時間可為全天任一時間,但分鐘只能是 00/05/10/.../55。
- 新課必須在未來且在 pairing 的 semester 範圍內。
- 可每週重複至指定日期;超過學期結束日會截到學期末。
- 週定義為星期一至星期日。
- 同一 pairing 每週已排時數上限 2 小時。
- 同一 pairing 每學期已排時數上限 32 小時。
- 同一 Tutor 每學期已排時數上限 64 小時。
- 額度按所有未取消課程計算,包含尚未上課、尚未簽到或尚未完成紀錄的課程;取消後才釋放。
- Maryland Tutee 本身沒有另外的時數上限,但與 Tutor 的課仍受 pairing 32 與 Tutor 64 小時限制,因目前 quota service 沒有 program 例外。
- 取消/修改只有 Tutor 可操作;已有任何簽到或課堂紀錄時不可自行改,需洽 Admin。
- 過去課程在結束後 21 天內仍可取消或改到未來;超過 21 天禁止。
- 修改後的課仍須在學期內並重新計算週/組/Tutor 額度。
- 重複課程可只改單堂或「本堂及後續」;若後續任何一堂已有活動紀錄,只能改單堂。

### 4.6 簽到、課堂紀錄、互認與有效時數

Tutor、NTNU Tutee、Maryland Tutee 現在採**完全相同流程**:

1. 雙方各自簽到。
2. 雙方各自填寫自己的課堂紀錄(地點、主題、內容、備註)。
3. 每人確認對方的簽到與課堂紀錄;可確認、要求修改或回報問題。
4. 一般課程滿足條件後自動成為有效時數;Admin 不逐筆核准一般課。

細節:

- 簽到於上課前 10 分鐘開放。
- 上課結束 30 分鐘後才簽到,視為補簽,必填原因。
- 課堂開始後才可提交紀錄;課程結束 24 小時後首次提交,視為補課堂紀錄,必填原因。
- 每位使用者每學期最多 5 次補簽到、5 次補課堂紀錄;兩種額度分開計算。
- 補簽/補登最後期限:學期結束後第 1 天 23:59:59。
- 任何一方修改自己的紀錄時,系統會刪除對方針對該作者的舊確認,必須重新確認。
- 有任一補簽/補紀錄時,雙方完成互認後才進入 `PENDING`,再由 Admin 逐筆核准;被拒絕不計有效時數。
- `class_is_valid()` 的唯一有效條件:課程未取消、剛好 2 筆 attendance、2 筆 class record、2 筆完整 CONFIRMED confirmation;若含 makeup,還要 `MakeupReview=APPROVED`。
- 「已排時數 / Reserved」與「有效時數 / Verified」是不同概念,不可混用。

### 4.7 課堂通報

- 只在該課程實際開始至結束之間開放,不提前開放。
- 原因:聯絡不到對方、對方未出席、時間/地點問題、其他緊急狀況;OTHER 必填說明。
- 同一通報者對同一堂課只能有一筆 active alert。
- Admin dashboard 可看到 active alerts;通報者取消後即不再顯示。

### 4.8 私訊

- 只有 pairing 雙方可開啟 `/matching/pairings/<id>/messages/`。
- Active pairing 可發送,ended pairing 只能讀歷史。
- 單則最多 2000 字;開啟對話時會標記對方未讀訊息為已讀。
- 目前沒有附件、即時推播、WebSocket 或內容審核。

### 4.9 時數、證明與匯出

- Tutor 可下載時數;Tutee 只有 `MARYLAND`/`OTHER` 可下載,NTNU Tutee 不顯示此功能。
- 本學期證明於學期結束後第 3 天 00:00 開放;已過去學期可隨時下載。
- 可選整學期或自訂日期;自訂範圍不可涵蓋任何尚未開放下載的學期。
- PDF 有摘要版與詳細版;詳細版欄位可選日期、學生國籍、學生程度、時數,輸出順序固定,每頁最多 8 筆並重複證明內文。
- PDF 底圖:`tutoring/resources/certificate_templates/`;字型:`assets/fonts/`。
- Tutor 使用 NTNU 輔導證明;`MARYLAND`/`OTHER` Tutee 使用合作計畫證明。
- PDF 產製位於 `tutoring/reporting.py`,使用 ReportLab 疊字後以 pypdf 合併底圖。
- Admin 匯出目前是 Excel 2003 XML 內容、`.xls` 副檔名,不是 `.xlsx`;UI 已預留未來增加格式的文案。
- 所有下載與匯出都寫入 `AuditLog`。

## 5. 技術架構

### Runtime

- Python 3.12(本機 `.venv`)
- Django 5.2.16
- PostgreSQL 18;本機預設 DB/USER 都是 `qiangqiang`
- psycopg 3.2、Pillow、ReportLab、pypdf
- 時區 `Asia/Taipei`、`USE_TZ=True`、介面語言 `zh-hant`
- Django server-rendered HTML;無 React/Vue、無 REST API、無 Node build step
- Vanilla JavaScript + 單一大型 `static/css/app.css`
- 全站中英並列、響應式版面

### 目錄責任

```text
config/                 Django settings、root URL、WSGI/ASGI
accounts/               User/名冊/註冊/登入/恢復/Profile/Admin dashboard
accounts/management/    本機 demo 帳號 seed
tutoring/               配對、排課、簽到、紀錄、互認、補登、報表
tutoring/services.py    核心業務規則;新規則優先放這裡而非 view/template
tutoring/reporting.py   PDF 證明與 Excel XML 匯出
tutoring/management/    狀態排程與 V1/V2 demo seed
templates/              Django templates;dashboard 依角色拆 partial
static/css/app.css      全站樣式
static/js/              dashboard、使用者選單、國家/語言下拉資料
media/                  使用者上傳,勿提交真實個資或資格文件
assets/fonts/           PDF 內嵌字型
tutoring/resources/     NTNU/Maryland PDF 底圖
output/pdf/             本機人工檢查用預覽,不是正式使用者資料來源
```

### 主要 URL

- `/` 登入
- `/register/` 名冊核對與密碼草稿
- `/register/tutor/`、`/register/tutee/` 第二階段 Profile
- `/dashboard/` 三角色 dashboard
- `/profile/` 個人資料(目前唯讀)
- `/handbook/` 角色使用手冊
- `/matching/...` 配對、排課、課程、訊息、匯出操作
- `/system-admin/` Django Admin

### 部署

目標環境、正式上線 checklist、本機啟動指令、部署前驗證指令,見 `docs/DEPLOY.md`。日常業務邏輯開發不需要讀這份,只有處理 deployment/infra 任務時才需要。

## 6. 目前開發進度

已完成項目、已知缺口、尚未定案決策已整理在 `docs/PROGRESS.md`,包含目前的 migration/測試數量快照。**這份快照只是盤點當下的結果,開發前建議先重新驗證(見下一節)。**

## 7. 程式碼慣例

### Python / Django

- Model/enum 使用英文 `snake_case`/`PascalCase`;資料庫選項集中用 `models.TextChoices`。
- 核心規則集中在 `tutoring/services.py`,view 負責權限、表單、message、redirect;不要把 quota 或狀態規則只寫在 template/JS。
- 多步驟狀態變更使用 `@transaction.atomic`、`select_for_update()`;牽涉競態的配對、名額、排課、審核必須維持此模式。
- 建立領域物件時使用 `full_clean()` 或表單驗證,並同時保留 DB constraint;不要只依前端驗證。
- 未授權的資源型操作多數回 404,角色頁面也可用 `role_required`;新增 endpoint 應延續相鄰程式的模式。
- 所有重要行為(登入、註冊、資格審核、解除、下載、匯出)應寫 `AuditLog`,metadata 不放密碼/安全問題答案。
- 日期時間使用 `django.utils.timezone`,不要建立 naive datetime;業務時區是 `Asia/Taipei`。
- 時數用 `Decimal`,不可改用 float 做 quota 加總。
- 檔案刪除/帳號刪除需保守;多數關聯使用 `PROTECT` 是為保留稽核與時數紀錄。

### UI / 文字

- 所有可見 UI、錯誤、按鈕與說明維持中英並列;使用者術語用「老師/學生」,不要直接顯示 Tutor/Tutee。
- 中文通常為主標,英文用較小副標;長雙語句使用換行,不用斜線硬擠在同一行。
- 必填錯誤統一為「此欄位為必填欄位」。
- 使用現有色票與元件 class;新增樣式優先擴充 `static/css/app.css`,不要在 template 寫大量 inline style。
- JS 使用原生 DOM API 與 `data-*` hooks;不要加入前端框架或外部 CDN。
- 修改靜態資源後更新 template 的 cache-busting query string,並在本機瀏覽器實際 reload。
- 配對前資料必須維持最小揭露;不得因 UI 方便把姓名、學號或電話加入匿名 card/API context。

### Models / migrations

- 改 model 後必須:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py makemigrations --check --dry-run
```

- 不可直接手改既有 migration 來掩蓋 schema 差異;新增 migration。
- PostgreSQL 是唯一正式支援 DB,不要依 SQLite 特性設計測試或 constraint。

### 測試與驗證

完整測試與部署前驗證指令見 `docs/DEPLOY.md`。

- 新規則需在 `accounts/tests.py` 或 `tutoring/tests.py` 新增回歸測試。
- 業務規則測試優先直接呼叫 service;權限、template、redirect、下載再用 Django test client。
- PDF 改動除測試 `%PDF`/page count 外,必須重新產生 `output/pdf/` 預覽、以 Poppler render 成圖片並人工檢查單頁、續頁、最後一頁;暫存圖片放 `tmp/pdfs/` 並在完成後刪除。
- Demo seed 僅限 `DEBUG=True`。常用命令:

```bash
python manage.py seed_matching_demo --password '<local-only-password>'
python manage.py seed_v2_demo
python manage.py seed_v2_time_demo
python manage.py process_matching_state
```

## 8. 文件維護與同步機制

這份文件(以及 `docs/PROGRESS.md`、`docs/DEPLOY.md`)只有在被持續更新的情況下才有價值。以下是具體的同步規則,不是選項:

1. **何時必須更新本文件**
   - 新增/修改角色權限、配對規則、額度計算、簽到與互認流程、時數/證明規則 → 更新對應的第 2–4 節。
   - 新增/修改 model、目錄結構、URL 路由 → 更新第 5 節。
   - 任何 migration 或新增測試 → 更新 `docs/PROGRESS.md` 的數字快照。
   - 部署流程、環境變數、正式 server 設定變更 → 更新 `docs/DEPLOY.md`。

2. **每次開發 session 開始前(尤其是換 agent 或隔了一段時間再開發時)**
   - 先實際跑 `python manage.py test --verbosity 1` 與確認 migration 檔案數,和 `docs/PROGRESS.md` 記錄的快照核對;不一致就先更新快照,不要假設文件是對的。
   - 若使用者的新指示和本文件衝突,以使用者最新明確指示為準,並**在同一個 session 內**同步修改本文件與測試,不要留到之後才補。

3. **commit / PR 層級的提醒(待 Git 初始化後啟用)**
   - 建議在 PR 說明或 commit message 固定加一行檢查:「是否涉及業務規則變更?是否已同步更新 CLAUDE.md / docs/PROGRESS.md?」
   - 之後若補上 CI,可以考慮加一個簡單檢查:當 `tutoring/services.py`、`accounts/models.py` 等核心檔案有 diff,而 `CLAUDE.md` 沒有對應 diff 時,在 CI 顯示提醒(非強制擋 merge,先從提醒開始)。

4. **版本節點稽核**
   - 每次要開新的大版本(例如未來 V3)之前,重新完整盤點一次本文件全部三個檔案的準確性,而不是只增量修改,避免小修小補堆疊出不一致。

## 9. Agent 接手原則

1. 先讀相關 model/service/form/view/test,再改 template;不要只按畫面猜資料狀態。
2. 使用者提出的新規則若和本文件衝突,以使用者最新明確指示為準,並同步更新本文件與測試(見第 8 節)。
3. 不要把 demo 帳密、真實學生名冊、資格文件、`.env` 或 DB dump 寫入版本控制。
4. 保留現有使用者修改與資料;不要用 `git reset --hard`、刪 DB、重建 migrations 或清空 media。
5. 交付前說明實作、測試、migration、已知限制;若只完成 UI mock,必須明確標示沒有後端行為。
