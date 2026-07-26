# CLAUDE.md

本文件供 Claude Code 與其他 AI coding agent 在專案啟動時快速取得正確脈絡。除非使用者明確改變需求,請以**目前程式碼、資料庫約束與測試**為準,不要只依 README 或歷史對話推測功能。

> 最後盤點日期:2026-07-26(V3/V3.1 完成,進入 V4)
> 專案路徑:`/Users/Qiangqiang/Desktop/CSL`
> 版本控制狀態:此目錄已是 **Git repository**,remote 為 `https://github.com/Karma-1827/CSL.git`(private)。目前僅有一個 initial commit,尚無多次 commit history 可供推導開發脈絡;下列進度仍是由現有程式、migration 與測試整理。
>
> 本檔案只放**核心業務邏輯與慣例**(變動頻率低)。開發進度、已知缺口與部署細節(變動頻率高或非日常開發所需)已拆到:
> - `docs/PROGRESS.md` — 目前開發進度、已知缺口、尚未定案決策
> - `docs/DEPLOY.md` — 部署步驟與 checklist
> - `docs/SECURITY_CHECKLIST.md` — 依師大資訊中心「資通系統防護基準檢核表」逐條對照 CSL 現況的資安盤點(V4 範圍),只有處理資安/合規相關任務時才需要讀

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
- 自訂 Admin dashboard「名冊匯入」頁籤預設是**分類卡片式快速匯入**(`accounts:roster_import_quick`):固定的「華語系學生」卡片(Tutor,無計畫)+ 每個啟用中 `PartnerProgram` 各一張卡片(Tutee,對應該計畫)+ 一張連到 Django Admin 新增計畫的「新增合作計畫」卡片;每張卡片只接受**單欄學號清單**(容忍標題列、中文表頭列等雜訊,`accounts/services.py::_read_single_column_values()`/`import_roster_ids()`),角色與計畫完全由**上傳到哪張卡片**決定,不看檔案內容,對應系辦「每種身分分開一份學號檔案」的實際流程。姓名、學制、身份別等欄位不在此匯入,由使用者註冊時自行填寫(見第 4.1 節)。
- 舊版「完整欄位」CSV/Excel(.xlsx)匯入(含姓名、學制、身份別、計畫代碼等欄位)保留在同頁籤的「進階匯入」摺疊區塊(`accounts:roster_import`),仍提供範本下載。
- 兩種匯入方式**皆改為**:只新增不覆蓋既有學號,學號已存在(或檔案內重複)則靜默略過(保留系統內既有資料),只匯入真正新的學號。快速匯入本來就只有「學號格式是否合法」一種檢查,不合法的列略過並提示警告,不擋下整批。進階完整欄位匯入仍對**逐列必填/合法性驗證**(姓名、role、學制、身份別、計畫代碼等)維持 all-or-nothing:只要有任一列驗證失敗,整批都不寫入;只有「學號重複/已存在」這件事從「整批擋下」改成「該列靜默略過」。
- 自訂 Admin dashboard 顯示名冊/註冊/角色/配對/邀請統計。
- 審核 Tutor 資格文件。
- 設定學期、修改學期、手動封存學期。
- 查看解除配對申請並核准/拒絕;查看歷史結果。
- 查看全系課程總覽、老師名單、各老師個人課表及未完成課程。
- 查看單一 Tutor/Tutee 的「行政檔案」整合頁(`accounts:admin_user_profile`,`accounts/admin_user_profile.html`):唯讀彙整基本資料、Profile(教學/學習資料)、資格狀態(僅 Tutor)、全部學期的配對紀錄、依學期分組的課程與時數、課堂通報與異常回報紀錄(各取最近 20 筆)。入口在 Django Admin 的學生名冊(`RosterEntry`)清單多一欄「查看檔案」連結。**刻意不做任何操作按鈕**(審核資格、核准解除、標記通報等仍在原本頁面做),只負責彙整顯示,避免與既有審核流程重複或衝突。
- 查看課堂通報與異常回報,可標記為「已紀錄」並留備註(見第 4.7 節)。
- 查看課程雙方的簽到、紀錄、確認與補登詳情。
- 逐筆核准或拒絕補簽到/補課堂紀錄。
- 依全體或指定使用者、學期或自訂日期範圍匯出資料,可選 `.xlsx`(建議)、`.csv` 或舊版相容用的 Excel 2003 XML `.xls`。
- 可透過 Django Admin 手動修改密碼;目前沒有客製化 Admin 密碼重設頁。
- 可透過 Django Admin 新增「時數調整紀錄」(`HourAdjustment`),補登系統上線前的舊紙本時數或更正資料;只能加不能扣,且只影響證明 PDF 總時數、不逐筆列出明細(見第 4.9 節)。可單筆新增,也可在 `HourAdjustment` 清單頁點「匯入 Excel / Import from Excel」批次匯入(兩欄 CSV/Excel:學號、時數;學期、合作計畫、原因在匯入表單上選一次,套用到整批;逐列驗證,任一列有問題整批都不寫入)。

### Tutor(老師;華語系學生)

- 一個學號只能建立一個角色;學制(大學部/碩士班/博士班)與身分類別(本地生/僑生/外籍生)由 Tutor 本人於註冊第二階段選擇,不是名冊匯入時預先設定(見第 4.1 節)。
- 兩階段註冊後建立教學 Profile,包含中英文姓名、身份別、學制、性別、母語、國籍、系所、聽說讀寫 1–5、簡介、時段及安全問題。
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

- 名冊核對後註冊;第二階段填寫中英文姓名、身份別(本地生/僑生/外籍生)、華語程度、學習時間、聽說讀寫、加強項目、需求與可上課時段(所屬計畫仍由名冊預先指定,不是自選)。
- 接收 Tutor 邀請並查看匿名 Tutor 資料;配對後查看完整資料與私訊。
- 查看 Tutor 安排的課程;目前由 Tutor 與本人線下協調,Tutee 不需在系統中接受排課。
- 每堂課與 Tutor 採相同機制:都要簽到、填寫自己的課堂紀錄、確認對方內容。
- 可提出解除配對;解除後可換新 Tutor,但同學期不可和原 Tutor 再配。

### 合作計畫(`accounts.models.PartnerProgram`)

Tutee 的所屬計畫不再是寫死的 enum,而是獨立資料表 `PartnerProgram`,`RosterEntry.program` 是指向它的 FK(可為空,Tutor 一律為空;Tutee 必填,見 `RosterEntry.clean()`)。新增合作計畫**不需要改程式、通常也不需要新的 PDF 底圖**,系辦直接在 Django Admin(`/system-admin/accounts/partnerprogram/`)新增一筆即可。每筆計畫可設定:

- `allow_tutee_initiate_invitation`:此計畫的 Tutee 能不能主動瀏覽並邀請 Tutor。
- `tutee_can_download_hours`:此計畫的 Tutee 能不能下載時數證明。
- `tutee_certificate_filename`/`tutee_certificate_title_zh`/`tutee_certificate_title_en`/`tutee_certificate_plan_name`/`tutee_certificate_activity_text`:Tutee 版證明的模板檔名、標題(中英)與內文文案。
- `tutor_certificate_filename`/`tutor_certificate_title_zh`/`tutor_certificate_title_en`/`tutor_certificate_plan_name`/`tutor_certificate_activity_text`:Tutor 版證明的模板檔名、標題與內文文案(Tutor 下載時依所選計畫套用,見第 4.9 節)。

**證明底圖是共用的**:`tutoring/resources/certificate_templates/csl_template.pdf` 只印有師大院徽、系所頭銜(中英)、浮水印與 logo,**沒有印標題或任何內文**;標題(標楷體+Times New Roman,粗體,兩行置中)與內文段落都是 `tutoring/reporting.py::build_hours_pdf()` 用 ReportLab 動態疊上去的,座標寫死在函式裡(標題約在 y=612–635,內文由 y=540 往下排列)。因此新增計畫預設**都指向同一份 `csl_template.pdf`**,只要在 Admin 填標題與文案文字就能生出一張新的證明,不需要美編另外設計底圖;`tutor_certificate_filename`/`tutee_certificate_filename` 欄位保留是為了極少數需要「真的不同底圖」的計畫留一個例外設定的空間,平常不需要動它。

目前(以資料遷移 `accounts/migrations/0005_...`、`0006_...` 建立)已設定三筆,Tutor/Tutee 兩種角色都已配好文案:

- `NTNU` 師大外籍生:不可主動邀請;可下載時數證明。Tutee 標題「受輔導證明 / Certificate of Tutoring Received」;Tutor 標題「實習證明 / Certificate of Counseling Practicum」。
- `MARYLAND` 馬里蘭大學:可主動邀請;可下載語言交換證明。Tutee 標題「語言交換證明 / Certificate of Language Exchange」;Tutor 標題「語言交換服務證明 / Certificate of Language Exchange Service」。
- `OTHER` 其他合作計畫:預設**不可**主動邀請(與 Maryland 不同,是刻意的預設值,可在 Admin 個別調整);Tutee/Tutor 標題暫用通用的「合作計畫證明」/「合作計畫服務證明」,實際接洽新計畫時應請系辦確認正式用詞再改。migration `accounts/0008` 已將此筆 `is_active` 設為 `False`(尚未有實際對接的合作計畫,先從 Admin dashboard「名冊匯入」卡片與其他 `is_active=True` 篩選清單中隱藏);資料本身還在,之後真的要接洽新計畫時,可直接在 Django Admin 把這筆改回啟用並調整名稱/文案,或另外新增一筆。
- 三筆的標題/文案文字都是首版草稿,系辦覺得用詞需要調整可直接在 Django Admin 改,不用找工程師改程式。
- `PartnerProgram.is_active=False` 目前只影響兩處:Admin dashboard 快速匯入卡片清單(`accounts:dashboard` 的 `quick_import_programs`)、以及該計畫的快速匯入網址本身(`roster_import_quick` 會 404)。**不影響**已有該計畫的 Tutee 既有功能(邀請權限、時數下載、證明產生都是直接看 `RosterEntry.program` 這個 FK,不檢查 `is_active`)。
- 新增計畫前務必和系辦確認邀請權限、時數上限是否需要例外(目前排課額度服務沒有 per-program 例外,32/64 小時上限對所有計畫一視同仁)。

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
- NTNU 外籍生預設不能主動邀請 Tutor(由 `PartnerProgram.allow_tutee_initiate_invitation` 控制,Admin 可調整,見第 2 節「合作計畫」)。
- 不替使用者自動安排配對或推薦排序;候選名單只依後端資格、名額與不可重配等規則排除不合格對象,不做排序演算法。Tutor 瀏覽外籍生候選人時可用性別、華語程度、母語關鍵字、加強項目、星期、時段做**使用者端複合篩選**(見第 4.3 節),但篩選只是縮小既有候選清單,不會改變配對前的最小揭露欄位範圍,也不會自動配對。
- 不強迫 16 週每週都有課;有完成且有效才計時數,沒上課就沒有時數。
- 不要求達到 100 小時才下載證明;證明按有效紀錄的實際時數產生。
- 不限制上課在 09:00–19:00;可排 24 小時內任意時間,但分鐘須為 5 的倍數。
- 目前無 native mobile app;只做響應式 Web UI。
- 尚未完成學校 SSO、正式 VM 反向代理、Gunicorn/uWSGI、systemd、Nginx、備份/監控設定(見 `docs/DEPLOY.md`)。

### 舊版系統的參考原則

舊版專案位於 `/Users/Qiangqiang/Desktop/CSL-system`,技術是 React/Vite＋Express＋直接 SQL,可用來確認早期產品概念與 UI,但**不可把舊 API、SQL 或大型 JSX 直接複製進本專案**。新版是 Django server-rendered 架構,且已加入交易鎖、model validation、DB constraint、角色權限與 AuditLog;沿用舊功能時必須依新版模型與 service layer 重新實作。

舊版盤點過的概念目前皆已排入範圍並完成(候選篩選、私訊摘要、輔導類型標籤、課堂紀錄附件、Admin 使用者總覽、時數調整帳,見 `docs/PROGRESS.md`「已完成」)。

明確不沿用舊版的內容:Email 驗證、100 小時才可申請證明、證明再次送 Admin 核發、09:00–19:00 排課限制、硬編碼檔案清單、未完成的 WebSocket「線上」狀態、用假課程補時數,以及異常回報附件(2026-07-26 已確認目前不需要;課堂紀錄附件仍保留,見第 4.6 節;若之後需求改變,做法可直接比照課堂紀錄附件)。

## 4. 核心業務邏輯

### 4.1 名冊、註冊與帳號恢復

- `RosterEntry.student_id` 與 `User.username` 都代表學號;學號唯一。`RosterEntry.clean()` 會將學號正規化為大寫,註冊第一階段的學號查找也是大小寫不敏感,所以系辦名冊與使用者輸入不論大小寫都能對上(登入本來就是大小寫不敏感,這裡是補齊匯入/註冊端的一致性)。
- 公開註冊第一階段只接受 `is_enabled=True`、尚未 claimed、角色為 Tutor/Tutee 的名冊。
- 第一階段建立 `RegistrationDraft`,只保存 Django 密碼雜湊,30 分鐘到期。
- 第二階段依名冊角色進入 `/register/tutor/` 或 `/register/tutee/`;完整 Profile、安全問題與同意欄位成功後才建立正式 `User`,並設定 `claimed_at`。
- 中文姓名、英文姓名(選填)、身份別(本地生/僑生/外籍生)由**使用者於第二階段註冊時自行填寫**,不再要求系辦於名冊匯入時預先提供;Tutor 另外還要在註冊時自行選擇學制(大學部/碩士班/博士班)下拉選單。`RosterEntry.name_zh`/`identity_category`/`education_level` 因此在匯入時允許留空(`blank=True`),送出註冊表單時才寫回 `RosterEntry` 並鎖定,之後只能透過 `/profile/` 以外的管道(聯絡系辦)修改,見下方唯讀規則。
- 預覽頁 `/preview/tutor/`、`/preview/tutee/` 只在 `DEBUG=True` 開放,不寫入資料庫。
- 密碼至少 10 字元,套用 Django similarity/common/numeric validators。
- 忘記密碼採「學號＋原本選定的三題＋三個答案」;答案正規化後只存 hash。
- 恢復驗證同 IP＋學號 15 分鐘最多 5 次;驗證成功後 10 分鐘內必須完成新密碼設定。
- `User.account_status=SUSPENDED` 時禁止登入。
- `/profile/` 可自行編輯:電話、性別、母語、國籍、系所、聽說讀寫程度、簡介/需求備註、可上課星期與時段(Tutee 另含整體程度、學習時間、加強項目),修改立即生效,不需 Admin 審核,寫入 `PROFILE_UPDATED` AuditLog。
- 姓名(`name_zh`/`name_en`)、學號(`User.username`/`RosterEntry.student_id`)、安全問題答案不開放使用者自行修改,有問題須聯絡系辦。
- 資格文件狀態不受 Profile 編輯影響,重新上傳沿用既有 `/qualification/upload/` 流程。
- Profile 欄位(尤其聽說讀寫程度、可上課時段)是配對候選卡片即時讀取的來源;配對成立後仍可編輯,對方看到的資料會跟著即時變動,系統目前沒有配對當下的快照機制。

### 4.2 學期

- 學期只有開始/結束日;已移除另外的配對開始/截止欄位,所以配對窗口就是整個學期。
- 啟用中學期日期不可重疊。
- 今天尚未結束的啟用學期最多 3 個(目前＋未來兩學期)。
- 學期結束超過 6 個月後,`archive_expired_semesters()` 只把 `is_active=False`;不刪學期、課程或時數。
- 學期結束後 active pairing 自動結束,pending release 也會被標為自動處理。
- `dashboard()` 會呼叫 `synchronize_matching_state()`;正式環境仍須排程 `python manage.py process_matching_state`,否則無流量時不會即時處理。
- Admin dashboard「學期時間設定」每張學期卡片右上角有一顆編輯筆 icon(`.semester-edit-icon-btn`,`<details>`/`<summary>` 實作,無 JS),點擊展開該學期的編輯表單(`tutoring:update_semester`,`SemesterSettingsForm`)可改名稱與日期;修改日期是**回溯性**的,`makeup_deadline_at`/`hours_download_at` 都是即時運算的 property 而非快照,改 `ends_on` 會立即影響補登期限與證明下載開放時間,且不會回頭檢查已排課程是否超出新範圍,UI 上有提示但無強制檢查。
- `SemesterSettingsForm`/`SemesterCreateForm` 的日期欄位 widget 需明確設定 `format="%Y-%m-%d"`(`DateInput(attrs={"type": "date"}, format="%Y-%m-%d")`),否則瀏覽器原生日期選擇器認不出 Django 預設 locale 格式,編輯既有學期時日期欄位會顯示空白而非目前值。
- 刪除分兩種:此學期底下**尚無 `Pairing`** 才能真刪除(`tutoring:delete_semester`,寫入 `SEMESTER_DELETED`,DB 靠 `Pairing.semester` 的 `PROTECT` 約束擋下有資料的情況);已有 `Pairing` 且**已結束**(`ends_on < today`)只能「封存」(`tutoring:archive_semester`,`is_active=False`,原有課程/時數保留);已有 `Pairing` 且尚未結束則兩者都不能用,只能編輯修正。

### 4.3 匿名資料與邀請

配對前不得顯示姓名、英文名、完整學號、電話、Email。程式目前匿名欄位如下:

- Tutee:性別、母語、國籍、整體華語程度、加強項目、學習時間、需求備註、可上課星期/時段。
- Tutor:性別、母語、國籍、四項教學能力、教學簡介、可上課星期/時段。

Tutor 瀏覽外籍生候選人清單時,可用性別、華語程度、母語、加強項目、星期、時段做複合篩選(`tutoring/services.py::anonymous_tutee_candidates()` 的 `filters` 參數;UI 見 `templates/dashboard/index.html` 的 `find-tutee` 分頁,GET 表單提交回 `accounts:dashboard`)。篩選邏輯:性別/華語程度/母語皆為精準比對(母語欄位是下拉選單,選項與註冊表單共用同一份 `static/js/profile-options.js` 產生的語言清單,值為 `Intl.DisplayNames` 產生的雙語字串,不是自由關鍵字);加強項目為「已選項目須全部命中」(AND);星期與時段各自為「命中任一已選值即算符合」(OR),兩者之間再取交集。篩選只是在既有候選清單上做子集過濾,不會新增可見欄位,也不做排序或推薦。篩選卡片預設收合,面板標題右上角的「搜尋條件 / Search filters」是 `<details>/<summary>` 原生收合元件(`.candidate-filter-disclosure`/`.candidate-filter-toggle`,無 JS),點擊才展開,取代原本常駐的「配對前不顯示姓名與學號」提示(該提示仍保留在側邊欄 `sidebar-note`)。Tutee(Maryland)瀏覽 Tutor 一側也已比照補上同一套機制(`anonymous_tutor_candidates()` 的 `filters` 參數,UI 見 `find-tutor` 分頁);差異是 Tutor 沒有對應「華語程度」與「加強項目」的欄位,所以只提供性別、母語、星期、時段四項,其餘篩選邏輯(精準比對/OR/收合式 UI)完全相同。

邀請規則:

- 邀請有效 5 天;過期後 `EXPIRED`。
- Tutor 必須有 APPROVED 資格文件且名額未滿。
- Tutor 可邀請可用 Tutee;Tutee 能否主動邀請 Tutor 由其 `RosterEntry.program.allow_tutee_initiate_invitation` 決定(目前只有 `MARYLAND` 為 True,`tutoring/services.py::_tutee_can_initiate_invitation()`)。
- 收件人接受後立即建立 Pairing,不需 Admin 核准。
- Tutee 同學期最多 1 個 active Tutor;Tutor 同學期最多 2 個 active Tutee。
- 每位使用者(Tutor 或 Tutee)同學期待回覆邀請(PENDING)總數上限 3 筆,不分是誰發起、雙向合計計算(`MAX_PENDING_INVITATIONS_PER_USER`,`tutoring/services.py`)。
- 接受某 Tutee 的邀請後,該 Tutee 其他 pending invitations 會自動取消(不分發起人)。
- Tutor 因此次接受而配對名額滿(達 2 位 active Tutee)時,該 Tutor 其餘 pending invitations 也會一併自動取消。
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
2. 雙方各自填寫自己的課堂紀錄(地點、主題、內容、授課類型、備註、附件)。
3. 每人確認對方的簽到與課堂紀錄;可確認、要求修改或回報問題。
4. 一般課程滿足條件後自動成為有效時數;Admin 不逐筆核准一般課。

細節:

- `ClassRecord.skills_practiced` 是選填的多選標籤(聽力/口說/閱讀/寫作,沿用 `accounts/forms.py::SKILL_CHOICES` 同一套分類,與 Tutor 教學能力、Tutee 加強項目共用同一詞彙),比照舊版「輔導類型」概念補回,方便 Admin 統計教學方式。不影響 `class_is_valid()` 的有效時數判定,單純是資料標籤。課程詳情頁(`class_detail.html`/`admin_record_card.html`)以標籤呈現;Django Admin 的 `ClassRecord` 清單另加 `SkillsPracticedFilter`(`tutoring/admin.py`),用 JSONField `contains` 查詢讓 Admin 依單一類型篩選/計數,沒有另外做自訂統計面板。
- `ClassRecord.attachment` 是選填附件(比照舊版概念,已於系辦確認後加入),限 PDF/JPG/PNG、最大 500 KB(`validate_class_record_attachment()`,與資格文件的 `validate_qualification_file()` 共用同一個 `_validate_upload()` 驗證邏輯,只有大小上限不同:資格文件 1 MB、課堂紀錄附件 500 KB)。不影響 `class_is_valid()` 的有效時數判定。表單用一般 `FileInput`(不是 `ClearableFileInput`),所以**沒有「清除附件」的介面**——重新提交但不選新檔案時會保留原本的附件,要移除只能換上傳新檔案覆蓋,或請 Admin 從 Django Admin 處理。課程詳情頁與 Django Admin 的課程詳情卡都會顯示附件下載連結(`ClassRecord.attachment_filename` property 取檔名)。
- 舊 model 上還有一個 `reflection`(學習成果與回饋)欄位,但 `ClassRecordForm` 沒有把它列進 `Meta.fields`,提交流程完全不會用到,等同已棄用的欄位;修改課堂紀錄相關程式時不要誤以為它是現行必填欄位。
- 簽到於上課前 10 分鐘開放。
- 上課結束 30 分鐘後才簽到,視為補簽,必填原因。
- 課堂開始後才可提交紀錄;課程結束 24 小時後首次提交,視為補課堂紀錄,必填原因。
- 每位使用者每學期最多 5 次補簽到、5 次補課堂紀錄;兩種額度分開計算。
- 補簽/補登最後期限:學期結束後第 1 天 23:59:59。
- 任何一方修改自己的紀錄時,系統會刪除對方針對該作者的舊確認,必須重新確認。
- 有任一補簽/補紀錄時,雙方完成互認後才進入 `PENDING`,再由 Admin 逐筆核准;被拒絕不計有效時數。
- `class_is_valid()` 的唯一有效條件:課程未取消、剛好 2 筆 attendance、2 筆 class record、2 筆完整 CONFIRMED confirmation;若含 makeup,還要 `MakeupReview=APPROVED`。
- 「已排時數 / Reserved」與「有效時數 / Verified」是不同概念,不可混用。

### 4.7 課堂通報與異常回報

課堂通報(`ClassAlert`)與異常回報(`IncidentReport`)是兩套獨立機制,定位不同,不要混用或合併:

**課堂通報**(即時、上課中的緊急通報):

- 只在該課程實際開始至結束之間開放,不提前開放。
- 原因:聯絡不到對方、對方未出席、時間/地點問題、其他緊急狀況;OTHER 必填說明。
- 同一通報者對同一堂課只能有一筆 active alert。
- Admin 可標記為已紀錄(內部狀態值仍是 `RESOLVED`,`resolve_class_alert`)並留備註;已紀錄與通報者自行取消(`CANCELLED`)都是終點狀態,已紀錄後不能再取消,已取消後也不能再標記已紀錄。
- 用詞刻意選「已紀錄」而非「已處理」:很多通報(尤其人身安全等)系辦不一定能真的解決,Admin 這個動作只代表「已知悉並留存記錄,後續再討論」,不代表問題已解決。
- Admin dashboard「課堂通報」頁籤有 PENDING 待處理 + HISTORY 已紀錄兩區塊,紀錄含紀錄人、紀錄時間、備註。

**異常回報**(事後、可分類的回報,`tutoring/services.py` 的 `submit_incident_report`/`resolve_incident_report`):

- 分類:學生缺席、老師缺席、場地問題、學習進度問題、人身安全、其他(`IncidentReportCategory`)。
- 不限上課時段,課程參與者(Tutor/Tutee)任何時候都能對自己參與的課程送出回報,可對同一堂課回報多次。
- 通報者送出後不能自行撤回,只有 Admin 能標記為已紀錄(內部狀態值仍是 `RESOLVED`)並留備註,同樣是「已知悉留存」而非「已解決」的語意。
- 無附件上傳。
- Admin dashboard「異常回報」頁籤有 PENDING 待處理 + HISTORY 已紀錄兩區塊,紀錄含紀錄人、紀錄時間、備註。

### 4.8 私訊

- 只有 pairing 雙方可開啟 `/matching/pairings/<id>/messages/`。
- Active pairing 可發送,ended pairing 只能讀歷史。
- 學期結束或解除配對只會把 Pairing 改為 `ENDED`,不刪除 `PairingMessage`;Tutor/Tutee dashboard 的「私訊」會把 ended pairing 保留在可展開的「過往對話紀錄」中,使用者可隨時重新開啟唯讀歷史。
- 單則最多 2000 字;開啟對話時會標記對方未讀訊息為已讀。
- Dashboard「私訊」的進行中／過往對話清單各自依「最近活動時間」排序(有訊息用最後一則訊息時間,完全沒訊息的配對 fallback 用 `Pairing.started_at`;`tutoring/services.py::annotate_conversation_summaries()`),並顯示未讀數 badge、最後一則訊息摘要(`truncatechars:36`)與時間;側邊欄「私訊」連結也會顯示總未讀數。未讀判定沿用既有邏輯:`read_at__isnull=True` 且非本人發送;開啟該配對訊息頁一樣會把訊息標記已讀,標記行為本身沒有改變,這次只是把既有資料呈現出來。
- 目前沒有附件、即時推播、WebSocket 或內容審核。

### 4.9 時數、證明與匯出

- Tutor 一律可下載時數;Tutee 能否下載由 `RosterEntry.program.tutee_can_download_hours` 決定(`reporting.user_has_hour_records()`)。目前 NTNU/MARYLAND/OTHER 三個計畫都是 True,即三種 Tutee 都能下載。
- Tutor 下載時數證明時,下載區多一個「合作計畫」下拉選單(`HoursDownloadForm.program`),只列出這位 Tutor**實際帶過學生的計畫**且**該計畫已設定 Tutor 版證明模板**(`tutoring.reporting.tutor_available_programs()`);未設定 Tutor 版模板的計畫不會出現,不算錯誤,是尚未配置。
- Tutor 選了哪個計畫,時數也只算該計畫底下的 Tutee(`hour_report_data()`/`valid_sessions_for_user()` 的 `program` 參數依 `pairing__tutee__roster_entry__program` 篩選),不會把其他計畫的時數混進同一張證明。
- Tutee 下載時一律使用自己 `roster_entry.program` 對應的 Tutee 版模板,不受表單傳入值影響(`build_hours_pdf()` 內對 Tutee 角色強制覆寫,防止竄改)。
- `NTNU` Tutor 版證明內文是特例寫死格式(`build_hours_pdf()` 內 `is_ntnu_tutor` 分支),不是走通用的 `plan_name`/`activity` 句型:「本系{學制}學生 XXX,學號 XXX,於民國 X 年 X 月-X 月,於本校擔任國際生華語輔導老師,總計授課 X 小時。特此證明」,學制文字依 `RosterEntry.education_level` 動態代入(大學部/碩士班/博士班);開始與結束若在同一年月,期間只顯示一次「民國 X 年 X 月」,不重複為「X 月-X 月」。姓名/學號首句不縮排、使用較大字級並固定獨立一行;摘要/詳細版其餘內文皆置上、左右對齊且不畫下方分隔線。其餘計畫(Maryland/OTHER)、Tutee 版仍走通用的 `plan_name`/`activity` 句型。
- 本學期證明於學期結束後第 3 天 00:00 開放;已過去學期可隨時下載。
- 可選整學期或自訂日期;自訂範圍不可涵蓋任何尚未開放下載的學期。
- PDF 有摘要版與詳細版;詳細版欄位可選日期、學生國籍、學生程度、時數,輸出順序固定,每頁最多 8 筆並重複證明內文。
- PDF 底圖:`tutoring/resources/certificate_templates/`;字型:`assets/fonts/`;模板檔名、計畫名稱、活動描述文字皆從對應 `PartnerProgram` 欄位讀取,不再寫死於程式碼。
- 若某計畫缺少對應角色(Tutor/Tutee)的證明模板檔名,下載時會擋下並顯示錯誤,而非產生壞掉的 PDF(`build_hours_pdf()` 開頭檢查)。
- PDF 產製位於 `tutoring/reporting.py`,使用 ReportLab 疊字後以 pypdf 合併底圖。
- 下載區同時提供「預覽」與「下載」兩個按鈕,共用同一份表單與驗證邏輯,靠 submit button 的 `name="intent"`(`preview`/`download`)區分:預覽回應 `Content-Disposition: inline` 並用 `formtarget="_blank"` 開新分頁,由瀏覽器內建 PDF 檢視器顯示;下載回應 `attachment`,強制下載。
- Admin 匯出(`tutoring:export_excel`)可選三種格式(`tutoring/reporting.py`):`.xlsx`(`build_excel_xlsx()`,用專案既有依賴 `openpyxl`,UI 預設勾選)、`.csv`(`build_export_csv()`,標準庫 `csv`,寫入 UTF-8 BOM 避免 Windows Excel 開啟中文表頭亂碼)、`.xls`(`build_excel_xml()`,舊版 Excel 2003 XML,供仍需要的舊流程相容)。三種格式的欄位與資料來源共用同一個 `_export_rows()`,只有輸出容器不同;選用格式會一併寫進 `ADMIN_EXCEL_EXPORTED` 的 `AuditLog.metadata`。
- 所有下載與匯出都寫入 `AuditLog`;預覽寫入 `HOURS_PDF_PREVIEWED`,下載寫入 `HOURS_PDF_DOWNLOADED`,事件分開方便區分「看過」與「實際下載」。
- `tutoring.models.HourAdjustment`(時數調整紀錄)用於補登系統上線前的舊紙本時數或更正資料,比照舊版概念但**刻意不沿用舊版建立無 Tutee 假課程的作法**——沒有假 `ClassSession`/`Pairing`,是獨立 model:使用者、學期、合作計畫、時數、原因、建立者(Admin)、時間戳記。設計上的關鍵限制(已與使用者確認):
  - **只能為正數**,只能加不能扣;若某筆時數算錯需要往下修正,必須用其他方式處理(例如取消對應課程),不透過這個功能扣時數。
  - **只影響證明 PDF 的「總時數」,不會在明細版逐筆列出**(`hour_report_data()` 把 `session_total` 與 `adjustment_total`分開算,加總後才是 `total`;`build_hours_pdf()` 只讀 `total`,明細列表 `sections`/`rows` 完全不受影響)。逐筆調整紀錄只在 Admin 內部彙整頁(`accounts:admin_user_profile`)可見,標明「僅內部稽核可見」。
  - 計入哪一次下載的判斷是「該筆調整的學期整個落在下載的日期範圍內」(`reporting.hour_adjustment_total()`,`semester.starts_on/ends_on` 需完全落在 `starts_on/ends_on` 區間),不是用調整紀錄本身的日期(它沒有日期,只有學期)。
  - Tutor 選特定合作計畫下載時,只會算該計畫的調整紀錄(`program` 外鍵);`tutor_available_programs()` 也一併更新,讓「只有調整紀錄、資料庫裡完全沒有真實課程」的計畫仍會出現在 Tutor 的下拉選單,避免補登的舊資料反而無法被看到或下載。
  - 建立/管理都**留在 Django Admin 裡**(`tutoring/admin.py::HourAdjustmentAdmin`),沒有另外開一個獨立於 Django Admin 之外的自訂前台頁面,符合這個功能低頻率使用的定位;單筆新增/修改時會寫入 `AuditLog`(`HOUR_ADJUSTMENT_CREATED`/`HOUR_ADJUSTMENT_UPDATED`)。model `clean()` 擋下時數 ≤ 0 與非 Tutor/Tutee 對象兩種情況,Django Admin 送出表單時會自動觸發。
  - 批次匯入:`HourAdjustment` 清單頁右上角「匯入 Excel / Import from Excel」連結(透過 `HourAdjustmentAdmin.get_urls()` 掛進去的自訂 admin view,不是獨立於 Django Admin 之外的頁面),對應 `tutoring/services.py::import_hour_adjustments()`。匯入表單先選一次學期、合作計畫、原因(套用到整批),再上傳一份兩欄 CSV/Excel(學號、時數;容忍標題列)。**逐列驗證、all-or-nothing**——任一列找不到學號、對象不是 Tutor/Tutee、時數不是正數或格式錯誤,整批都不寫入(跟「進階完整欄位」名冊匯入的驗證風格一致,而不是名冊快速匯入那種「靜默略過壞列」風格,因為這裡的資料會直接影響證明時數)。成功匯入寫一筆 `HOUR_ADJUSTMENT_IMPORTED` 的 `AuditLog`(不是每列各寫一筆,避免洗版)。

## 5. 技術架構

### Runtime

- Python 3.12(本機 `.venv`)
- Django 5.2.16
- PostgreSQL 18;本機預設 DB/USER 都是 `qiangqiang`
- psycopg 3.2、Pillow、ReportLab、pypdf、openpyxl
- 時區 `Asia/Taipei`、`USE_TZ=True`、介面語言 `zh-hant`
- Django server-rendered HTML;無 React/Vue、無 REST API、無 Node build step
- Vanilla JavaScript + 單一大型 `static/css/app.css`
- 全站中英並列、響應式版面

### 目錄責任

```text
config/                 Django settings、root URL、WSGI/ASGI
accounts/               User/名冊/註冊/登入/恢復/Profile/Admin dashboard
accounts/services.py    名冊匯入(分類卡片快速匯入 + 進階完整欄位匯入,CSV/Excel 解析、驗證、範本產生)
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
tutoring/resources/     各合作計畫的證明 PDF 底圖,檔名由 PartnerProgram 設定引用
output/pdf/             本機人工檢查用預覽,不是正式使用者資料來源
```

### 主要 URL

- `/` 登入
- `/register/` 名冊核對與密碼草稿
- `/register/tutor/`、`/register/tutee/` 第二階段 Profile
- `/dashboard/` 三角色 dashboard
- `/profile/` 個人資料;Tutor/Tutee 可自行編輯非名冊類欄位(見第 4.1 節),姓名/學號唯讀
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

- Lint(`ruff`,設定在 `pyproject.toml`):只開 `F`(pyflakes,抓未使用的 import/變數、未定義名稱等真的會出錯的問題)與 `E9`(語法錯誤),刻意不開 `E`(pycodestyle 風格規則,含行長)或 import 排序規則,因為既有程式碼從未套用過任何格式化工具,貿然開啟會逼出一次跟本次修改無關的全庫重排版大 diff。`.github/workflows/ci.yml` 的 CI 會跑 `ruff check .`;開發者本機可執行 `pip install -r requirements-dev.txt` 後跑同一指令。若之後真的要導入 `ruff format`(或其他 formatter)做全庫重排版,應該是一次獨立、刻意的決定與 PR,不要在功能改動裡順便夾帶。
- CI(GitHub Actions,`.github/workflows/ci.yml`):對 `main` 的 push 與所有 PR 觸發,跑一個用 Postgres service container 的 job,依序執行 `ruff check .`、`makemigrations --check --dry-run`、`python manage.py test`、`DJANGO_DEBUG=0 python manage.py check --deploy`。目前只做這幾項,沒有另外接部署或通知。

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
   - 每次要開新的大版本(例如未來 V4)之前,重新完整盤點一次本文件全部三個檔案的準確性,而不是只增量修改,避免小修小補堆疊出不一致。

## 9. Agent 接手原則

1. 先讀相關 model/service/form/view/test,再改 template;不要只按畫面猜資料狀態。
2. 使用者提出的新規則若和本文件衝突,以使用者最新明確指示為準,並同步更新本文件與測試(見第 8 節)。
3. 不要把 demo 帳密、真實學生名冊、資格文件、`.env` 或 DB dump 寫入版本控制。
4. 保留現有使用者修改與資料;不要用 `git reset --hard`、刪 DB、重建 migrations 或清空 media。
5. 交付前說明實作、測試、migration、已知限制;若只完成 UI mock,必須明確標示沒有後端行為。
