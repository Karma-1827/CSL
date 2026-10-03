# CLAUDE.md

本文件供 Claude Code 與其他 AI coding agent 在專案啟動時快速取得正確脈絡。除非使用者明確改變需求,請以**目前程式碼、資料庫約束與測試**為準,不要只依 README 或歷史對話推測功能。

> 最後盤點日期:2026-08-10(V3/V3.1 完成,V4 進行中;最新調整包含港澳生、移除暱稱、雙方佐證連結及課堂紀錄 500 字限制,見 `docs/PROGRESS.md`)
> 專案路徑:`/Users/Qiangqiang/Desktop/CSL`
> 版本控制狀態:此目錄已是 **Git repository**,remote 為 `https://github.com/Karma-1827/CSL.git`(private),且已建立多次 commit history。精確數量請以 `git log`/`git rev-list --count HEAD` 為準,不要在文件內維護容易過期的固定數字;理解專案時仍應以目前程式碼、migration、測試及本文件為準。
>
> 本檔案只放**核心業務邏輯與慣例**(變動頻率低)。開發進度、已知缺口與部署細節(變動頻率高或非日常開發所需)已拆到:
> - `docs/PROGRESS.md` — 目前開發進度、已知缺口、尚未定案決策
> - `docs/DEPLOY.md` — 部署步驟與 checklist
> - `docs/SECURITY_CHECKLIST.md` — 依師大資訊中心「資通系統防護基準檢核表」逐條對照 CSL 現況的資安盤點(V4 範圍),只有處理資安/合規相關任務時才需要讀

## 1. 專案目的與背景

這是國立臺灣師範大學華語文教學系的「華語實習暨輔導系統 / Mandarin Practicum and Tutoring System」,簡稱 `MPTS`(2026-08 更名,舊名「華語輔導系統 / Chinese Language Tutoring System」)。主要服務情境是:

- 華語系研究所學生的畢業條件包含實習時數;未參與其他實習者可透過輔導外籍生累積時數。
- 大學部學生可因修課使用系統,博士生可累積輔導經驗;實際口語能力證明種類仍待系辦最後確認。
- 師大外籍生需要華語輔導;馬里蘭大學等合作計畫學生需要語言交換及時數證明。
- 舊流程以紙本管理,助教難以掌握名冊、配對、排課、雙方出席、課堂紀錄、補登與有效時數。

系統目標是讓約 300–600 名使用者在同一平台完成:名冊核對註冊、匿名配對、排課、簽到、雙方課堂紀錄與互認、補登審核、私訊、時數統計、證明下載,以及 Admin 的全系總覽與資料匯出。

## 2. 角色與功能

程式內角色定義於 `accounts.models.Role`。對使用者 UI 一律稱「老師 / Teacher」與「學生 / Student」;`Tutor`、`Tutee` 是程式內領域名稱。

### Admin(管理員)

- 不可由公開學生名冊註冊;用 `createsuperuser` 或 Django Admin 建立。
- 後台入口:`/system-admin/`。
- **2026-09-09 起 Admin 可在 `/profile/` 自行編輯個人資料**:因應多位管理員共用系統的情境(每人各自的帳號由其他管理員以 Django Admin/`createsuperuser` 建立),需要能自行填寫中文姓名,讓口語能力審核、解除配對、課堂通報、異常回報、補登審核、時數調整等各處既有的「審核人/處理人」顯示(皆讀取 `User.bilingual_name`,留空時會退回顯示裸學號)能正確顯示姓名,方便日後追蹤是哪位管理員處理過哪一筆。欄位:中文姓名(必填)、英文姓名(選填)、Email(選填)、新密碼(選填,`accounts/forms.py::AdminProfileEditForm`);「基本資料」唯讀區塊對 Admin 不顯示「學號 / Student ID」與電話(電話 Admin 從未使用),改顯示一欄簡化的「ID」(值同樣是 `request.user.username`,只是標籤不再套用 Tutor/Tutee 的「學號」措辭;頁面上方個人資訊列仍固定顯示「學號 / Student ID」,是所有角色共用、未受此次調整影響的既有區塊)。密碼欄位留空表示不修改,不會強迫每次編輯資料都要重設密碼;有填寫時走一般密碼驗證規則,`accounts/views.py::update_profile()` 呼叫 `set_password()` 後會呼叫 Django 的 `update_session_auth_hash()`,確保管理員改自己的密碼後目前的登入 session 不會被立即登出。學號一律不可透過此表單修改(與 Tutor/Tutee 既有規則一致)。**2026-09-10 修正兩個實際踩到的問題**:①`templates/accounts/profile.html` 原本完全沒有 include `components/messages.html`,`update_profile()` 的所有訊息一律被靜默吞掉,已補上(放在 `#edit-profile` 卡片內、表單上方,因為導向一律帶 `#edit-profile` 錨點,放在頁面最上方使用者捲下去後看不到);②`update_profile()` 驗證失敗時已改為直接 `render` 個人資料頁並帶回失效的 bound form(而非導向+flash message),讓 `components/form_field.html` 既有的逐欄位錯誤顯示生效——密碼不一致、必填姓名留空等錯誤現在會直接出現在該欄位下方,不是只有一則不知道對應哪個欄位的通用訊息。此模式(失敗時 render 帶錯誤的表單、成功時才 redirect)同時套用到 Tutor/Tutee 分支,`profile()`/`update_profile()` 共用的 context 建構已抽成 `_profile_context(user)`。
- 管理學生名冊、帳號、帳號狀態、口語能力證明與稽核紀錄。
- 自訂 Admin dashboard「名冊匯入」頁籤預設是**分類卡片式快速匯入**(`accounts:roster_import_quick`):**2026-08 起改為以合作計畫為單位的卡片**——每個啟用中 `PartnerProgram` 一張卡片,卡片內含該計畫的「Tutor 名單」與「學生名單」兩個上傳區塊,不再拆成獨立的卡片。`category_code` 的判斷規則不變:Tutee 名單用計畫代碼本身(如 `NTNU`、`MARYLAND`);Tutor 名單則依計畫而定——`NTNU` 卡片的 Tutor 區塊用 `category_code="TUTOR"`,其餘計畫用 `category_code="TUTOR:<程式碼>"`。快速匯入接受 Excel/CSV 前兩欄「學號＋身分別」,第二欄可使用本地生、僑生、港澳生、陸生、外國學生/外籍生等中英文別名;舊的單欄學號清單仍相容。角色與計畫由上傳區塊決定,身分別由第二欄寫入。重新匯入時可補上既有空白身分別,但不覆蓋既有非空白值;未知身分別的資料列會略過並提示。姓名與學制仍由使用者註冊時填寫。實作位於 `accounts/services.py::_read_quick_roster_rows()`/`import_roster_ids()`。目前(2026-08)系辦實際只有兩個計畫:`NTNU`(師大外籍生輔導)與 `MARYLAND`(馬里蘭大學語言學伴)。
- 舊版「完整欄位」CSV/Excel(.xlsx)匯入(含姓名、學制、身份別、計畫代碼等欄位)保留在同頁籤的「進階匯入」摺疊區塊(`accounts:roster_import`),仍提供範本下載。
- 進階完整欄位匯入仍是 only-new；快速匯入則是「新增學號，或只補既有空白身分別」。兩者都不覆蓋既有非空白資料。快速匯入遇到不合法學號或未知身分別時略過該列並提示，不擋下其他合法列；進階完整欄位匯入仍對逐列必填/合法性驗證維持 all-or-nothing。
- 自訂 Admin dashboard 顯示名冊/註冊/角色/配對/邀請統計。**2026-09-11 新增目前在線人數與累計登入次數**(使用者要求,`accounts/services.py::count_online_users()`,`dashboard()` ADMIN 分支):顯示在「系統總覽」面板的統計卡格線裡(與名冊人數等既有卡片同一排,純資訊卡,不是連結),不是獨立區塊。「目前在線」是**未過期且已登入的 Django session 數**(逐一解碼 session payload 檢查 `_auth_user_id`),沿用既有 30 分鐘閒置逾時(`SESSION_COOKIE_AGE`)當作「在線」的定義,不是即時頁面瀏覽或 WebSocket 在線狀態(本專案刻意不做這兩種,見第 3 節系統邊界)。「累計登入次數」是 `AuditLog` 裡 `LOGIN_SUCCESS` 事件的總筆數(每次登入都算一次,不去重),沿用既有的 `CSLLoginView` 登入紀錄。**目前學期則重用 Tutor/Tutee 本來就有的頁首「目前學期」小方塊**(`.semester-chip`,`templates/dashboard/index.html` 的 `page-heading` 區塊,所有角色共用同一個既有元件),不是新元件:因為 `tutoring/services.py::user_program()` 對 Admin 一律回傳 `None`(Admin 沒有唯一所屬計畫),原本共用的 `current_semester` 計算方式對 Admin 永遠查不到值而顯示「尚未設定」,`dashboard()` 的 ADMIN 分支因此另外覆寫 `context["current_semester"]` 為目前所有合作計畫裡最先開始的一筆啟用中學期(`Semester.objects.filter(is_active=True, starts_on__lte=today, ends_on__gte=today).order_by("starts_on").first()`),讓 Admin 也能透過同一個既有 UI 看到目前學期。**2026-09-16 起「配對管理」頁籤的配對列表改成搜尋＋分頁,不再只顯示最新 8 筆**(使用者實際回報「阮瓊桂倪的配對不見了？」後查明:原本 `recent_pairings` 寫死 `Pairing.objects...[:8]`,配對數量一多,較早建立但仍在輔導中的配對就會被擠出這份清單,讓 Admin 誤以為配對不見了,實際上資料庫裡完好無缺)。比照學生名冊瀏覽頁籤(見上)既有的搜尋＋分頁做法:`dashboard()` 新增 `pairing_q`(比對雙方學號/中英文姓名)、`pairing_status`(`ACTIVE`/`ENDED`)、`pairing_page` 查詢參數,`Paginator` 每頁 20 筆,面板標題從「近期配對 / Recent matches」改為「配對列表 / Matches」以反映不再只顯示最近幾筆。
- **2026-09-10 新增前台「學生名冊」瀏覽頁籤**(Admin dashboard `#roster`):使用者反映一般管理員(`is_staff=False`,如 §2 Admin 節下方提到的多位 TA/老師帳號)點「系統總覽」的名冊人數/已註冊/老師/學生統計卡或側邊欄「學生名冊」連結時,原本直接連到 Django Admin 的 `RosterEntry`/`User` changelist(`/system-admin/...`),沒有後台權限的帳號會被導去登入頁卡住。新增的 `#roster` 頁籤(`accounts/views.py::dashboard()` 的 ADMIN 分支新增 `roster_q`/`roster_role`/`roster_program`/`roster_claimed`/`roster_page` 查詢與分頁,`templates/dashboard/admin_v2_panels.html` 新增對應區塊)重現 Django Admin `RosterEntryAdmin` 的**查詢能力**(學號/中英文姓名關鍵字、身分、合作計畫、註冊狀態四個篩選條件,30 筆一頁),但刻意只做唯讀瀏覽,不含新增/編輯/刪除——這些仍留在 Django Admin(僅 `is_staff=True` 可用),避免在前台重新做一套獨立於既有 Admin 表單驗證之外的寫入邏輯。原本 4 張統計卡與側邊欄連結、「口語能力審核」頁籤裡的「管理名冊」按鈕都已改連到這個頁籤(側邊欄連結與按鈕用純前端頁籤切換,4 張統計卡因為需要帶入不同篩選查詢字串,改用真的重新整理頁面的連結,不是 `data-dashboard-target`)。已通過的口語能力/課程/配對細節仍照舊分別連到各自既有的頁面,這次只處理「名冊」這一塊的可見性落差。**2026-09-11 使用者回報「後台入口不見了」,已於帳號選單補上一個 superuser 專用的 Django 後台連結**(`templates/components/app_header.html`,`{% if request.user.is_superuser %}` 包住 `{% url 'admin:index' %}`,放在「使用手冊」下方):上述改動移除了最顯眼的幾處直接連結後,superuser 反而完全沒有入口能回到 Django Admin 處理只有後台才能做的事(`PartnerProgram`、`HourAdjustment`、`DepartmentOralExamPass` 訂正等)。**這跟儀表板裡另外幾處既有的、未特別限制身分的 Django Admin 連結是兩回事**(例如「待回覆邀請」面板的「管理全部」按鈕連到 `admin:tutoring_matchinginvitation_changelist`、合作計畫相關的空狀態提示連到 `admin:accounts_partnerprogram_add`/`changelist`)——這些連結目前對所有 Admin 角色都會顯示,包含沒有 `is_staff` 的一般管理員帳號,點下去會卡在 Django Admin 自己的登入頁,是先前就存在、這次沒有一併處理的既有落差,留意未來若要收斂請一併調整,不要跟這次新增的 superuser 專用連結混為一談。
- 審核 Tutor 口語能力證明;審核區「待審核」表格下方新增「審核紀錄 / Review history」區塊(2026-09-10 使用者要求),列出最近 30 筆已審核(通過/拒絕)的文件,含該筆的通過/拒絕結果、Tutor 上傳時留的說明(見下方 `tutor_note`)、審核備註,以及**是哪位管理員審核的**(`QualificationDocument.reviewed_by`)。因為 `QualificationDocument` 是每位 Tutor 一筆(`OneToOneField`,重新上傳會覆蓋同一筆,不是新增一筆歷史紀錄),這份「審核紀錄」呈現的是每位 Tutor 目前這筆文件的最新審核結果,不是逐次重新上傳/重審的完整歷程。「結果 / Result」欄位原本用 `.status-badge` 背景色塊呈現,使用者覺得色塊不好看,改成純文字並用 `.result-text`(`static/css/app.css`)套用既有的 `.status-approved`/`.status-rejected` 顏色但拿掉背景,通過綠色、未通過紅色。**2026-09-10 起,`QualificationStatus.REJECTED`/`ClassReviewStatus.REJECTED`/`PairingReleaseStatus.REJECTED` 的中文標籤統一從「已拒絕」/「未核准」改為「未通過」**(對應的 `APPROVED` 標籤也同步從「已核准」改為「已通過」以維持對稱,英文標籤不變),讓所有「審核」性質的通過/未通過狀態用詞一致;`MatchingInvitation.REJECTED`(邀請被婉拒,「已拒絕 / Declined」)刻意不在此範圍內,因為那是雙方自己選擇接受/婉拒,不是審核結果。**審核紀錄每一列也新增檔案連結(預覽/下載,與待審核表格同一套 `qualification-file-links` 樣式)與「撤回 / Revert」按鈕**(`accounts:review_qualification` 新增 `action=revert`,把該筆文件的 `status` 改回 `PENDING`、清空 `review_note`/`reviewed_by`/`reviewed_at`,寫入 `QUALIFICATION_REVIEW_REVERTED` `AuditLog`),讓 Admin 誤按核准/拒絕時能撤回重新審核;沒有審核人員身分限制,任何 Admin 都可以撤回任一筆(與本檔案其餘審核類操作的既有慣例一致,不做逐筆歸屬限制)。**2026-09-11 新增系辦語音通過名單交叉比對(使用者要求)**:「待審核」表格上方新增一個收合式上傳區塊(`accounts:import_oral_exam_pass_list`,`accounts/forms.py::OralExamPassListImportForm`),讓 Admin 上傳系辦的「碩士生修業概況一覽表」Excel。這份表格是系辦內部畢業條件追蹤表,不是專門匯出的口語通過名單:標題列不固定在第一列、可能有多個工作表(部分工作表沒有「語音」欄位)、且「語音」欄位的值並不一致(通過/完成/有皆曾出現於同一份真實檔案中)。`accounts/services.py::import_department_oral_exam_pass_list()` 因此逐一工作表掃描前幾列找出同時含「學號」與「語音」的標題列,且**只認值恰好等於「通過」的儲存格**,其餘一律不算通過,比對結果寫入新增的 `accounts.models.DepartmentOralExamPass`(累加式,比照 `import_roster_ids()` 慣例只新增/更新、不刪除,訂正錯誤資料由 Admin 在 Django Admin 手動刪除該筆)。**這個比對純粹是待審核列表上的輔助提示**(`dashboard()` 在 ADMIN 分支對 `pending_qualifications` 附加 `oral_exam_pass_hint_type` 屬性,模板依此顯示對應徽章),**完全不會自動核准/拒絕/修改任何 `QualificationDocument`**——最終核准/拒絕永遠是 Admin 手動點擊決定,與這份名冊比對結果無關。**2026-09-24 新增 `list_type` 區分兩種完全不同語意的名單來源(使用者要求)**:使用者指出「馬里蘭是修課名單通過」——馬里蘭計畫的口語能力資格依據不是語音考試,而是系辦提供的修課名單(例如「115-1課程學生名單」),語意跟 NTNU 的「語音通過」完全不同,不能共用同一句提示文字。`accounts.models.DepartmentOralExamPassListType`(`ORAL_EXAM_PASS`/`MARYLAND_COURSE_ROSTER`)新增在 `DepartmentOralExamPass.list_type` 欄位(`accounts/migrations/0020`,預設 `ORAL_EXAM_PASS`,既有 309 筆語音通過紀錄不受影響)。`import_department_oral_exam_pass_list()` 新增 `list_type` 參數(預設 `ORAL_EXAM_PASS`,不影響既有呼叫端),寫入比對到的每一筆紀錄;`OralExamPassListImportForm` 新增「名單類型」下拉選單,Admin 上傳時自行選擇。**目前系辦提供的馬里蘭檔案沿用跟語音名單相同的「學號＋語音＝通過」欄位格式**(可能是既有匯入介面沒有其他選項下的權宜格式),因此解析邏輯完全沿用不需要改寫,只是把選定的 `list_type` 存進去。畫面上依 `list_type` 顯示「系辦名冊：語音通過」或「系辦名冊：修課名單」兩種徽章文字。**2026-09-23 晚間使用者透過既有介面上傳了一份馬里蘭「115-1課程學生名單」(153 筆比對成功,誤用 `list_type=ORAL_EXAM_PASS` 的預設值),已於 2026-09-24 用一次性腳本依 `imported_at` 時間戳記(該批次全部集中在 2026-09-23 23:41:11–12,與 2026-09-11 那批完全不重疊,已交叉核對確認)訂正回 `MARYLAND_COURSE_ROSTER`**,不影響原有的 309 筆語音通過紀錄。
- 設定學期、修改學期、手動封存學期。
- 查看解除配對申請並核准/拒絕;查看歷史結果。
- 查看全系課程總覽、老師名單、各老師個人課表及未完成課程。
- 查看單一 Tutor/Tutee 的「行政檔案」整合頁(`accounts:admin_user_profile`,`accounts/admin_user_profile.html`):唯讀彙整基本資料、Profile(教學/學習資料)、口語能力狀態(僅 Tutor)、全部學期的配對紀錄、依學期分組的課程與時數、課堂通報與異常回報紀錄(各取最近 20 筆)。入口在 Django Admin 的學生名冊(`RosterEntry`)清單多一欄「查看檔案」連結。**刻意不做任何操作按鈕**(審核口語能力、核准解除、標記通報等仍在原本頁面做),只負責彙整顯示,避免與既有審核流程重複或衝突。
- 查看課堂通報與異常回報,可標記為「已紀錄」並留備註(見第 4.7 節)。
- 查看課程雙方的簽到、紀錄、確認與補登詳情。
- 逐筆核准或拒絕補簽到/補課堂紀錄。
- Admin 資料匯出依序選擇「合作計畫 → 老師/學生/特定使用者 → 該計畫學期或自訂日期 → 欄位 → 格式」,可選 `.xlsx`(建議)、`.csv` 或 `.pdf`。選老師或學生時,下方名單只顯示該身分且整類納入匯出;選特定使用者時則可在計畫內跨身分勾選一位或多位使用者(2026-08 移除舊版 Excel 2003 XML `.xls`,新增 `.pdf` 行政報表格式,見第 4.9 節)。
- 可透過 Django Admin 手動修改密碼;目前沒有客製化 Admin 密碼重設頁。
- 可透過 Django Admin 新增「行政更正」紀錄(`HourAdjustment`),補登系統紀錄以外的時數或更正資料;只能加不能扣,且只影響證明 PDF 總時數、不逐筆列出明細(見第 4.9 節)。只能單筆新增(2026-08 移除批次 Excel 匯入入口,不再用於補登系統上線前的舊紙本時數,見第 4.9 節)。

### Tutor(老師;華語系學生)

- 一個學號只能建立一個角色;學制(大學部/碩士班/博士班)由 Tutor 本人於註冊第二階段選擇。身分類別(本地生/僑生/港澳生/陸生/外籍生)由 Admin 名冊第二欄預先設定,使用者在註冊第一階段選擇相符身分以驗證,第二階段只能查看且不可覆寫;需更正時聯絡系辦。
- 兩階段註冊後建立教學 Profile,包含中英文姓名、身份別、學制、性別、母語、國籍、系所、聽說讀寫 1–5、簡介、時段及安全問題。
- 上傳口語能力證明(PDF/JPG/JPEG/PNG,最大 1 MB);註冊時可先略過,但**口語能力狀態必須為 APPROVED 才能配對**。**2026-09-10 起上傳表單在「選擇檔案」下方新增一個選填的留言欄位**(`QualificationDocument.tutor_note`,最多 300 字,`accounts/forms.py::QualificationUploadForm`),讓 Tutor 可以補充說明(例如證明文件的取得時間),Admin 審核時(待審核表格與審核紀錄皆會顯示)與 Tutor 自己查看目前狀態時都看得到這則留言;重新上傳會覆蓋這個欄位(與其餘欄位一樣,因為是同一筆 `QualificationDocument`)。**2026-09-08 師大資中弱點掃描發現一個真實 500,2026-09-11 codex review 再指出修法本身還有行為缺陷,已一併修正**:重新送審時若送出的表單完全沒有 `file` 這個欄位(例如殘缺的 multipart 送出 `file[]=...` 而非 `file=...`),Django `FileField.clean()` 會依既有慣例回退使用 instance 上的舊檔案讓 `form.is_valid()` 仍為 `True`,但 `accounts/views.py::upload_qualification()` 原本直接用 `request.FILES["file"]` 取檔名,此時該 key 根本不存在,丟出未攔截的 `KeyError` → 500。第一輪修法(改用 `request.FILES.get("file")`,沒有新檔案時保留原檔名)雖然不再 500,但會**靜默接受**這次送出並照常把狀態重置回 `PENDING`、清空審核備註與審核人員——等於讓 Tutor 免上傳任何新證據就能撤銷 Admin 已完成的審核結果。已改為:在建構表單前先檢查 `"file" not in request.FILES`,沒有真的上傳新檔案就直接拒絕(顯示「此欄位為必填欄位」),不建立、不修改任何欄位,原檔案/審核狀態/審核備註/審核人員一律維持原樣。見 `docs/VULNERABILITY_SCAN_REPORT_2026-09-08_ACTION_PLAN.md`、`docs/VULNERABILITY_SCAN_DEFICIENCY_REPORT_2026-09-08.md`。
- 瀏覽匿名學生資料並發邀請;配對前看不到姓名、學號、電話或 Email。
- 同一學期最多同時輔導 2 位學生。
- 接受/拒絕收到的邀請,或取消自己尚未回覆的邀請。
- 配對成立後可查看完整學生資料、使用配對私訊、提出解除配對。
- 只有 Tutor 能建立、取消、修改課程及建立每週重複課程。
- 每堂課需簽到、填寫自己的課堂紀錄,並確認對方的簽到與紀錄。
- 查看已排/有效/累積時數、學期歷史及下載正式 PDF 證明。

### Tutee(學生)

共用能力:

- 名冊核對後註冊;第二階段填寫中英文姓名、華語程度、學習時間、聽說讀寫、加強項目、需求與可上課時段。身分別與所屬計畫皆由名冊預先指定,不是使用者自選。
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

**證明底圖是共用的**:`tutoring/resources/certificate_templates/csl_template.pdf` 只印有師大院徽、系所頭銜(中英)、浮水印與底部 logo,**沒有印動態標題或內文**;標題、內文、表格、下方日期與右下系戳都是 `tutoring/reporting.py::build_hours_pdf()` 用 ReportLab 動態疊上去。2026-08-11 起,部署環境若有提供本機私有素材,中文使用華康儷宋 W3/W7、英文使用 Helvetica Neue Condensed Bold,並疊加 `assets/certificates/CSL stamp.png`;這些素材因授權與內部圖章性質由 `.gitignore` 排除,缺少時會回退到 `TW-Kai.ttf`/Liberation Serif 且不顯示系戳。詳細版每頁最多 6 筆,為底部日期、logo 與放大後的系戳保留空間。因此新增計畫預設**都指向同一份 `csl_template.pdf`**,只要在 Admin 填標題與文案文字就能生出一張新的證明,不需要美編另外設計底圖;`tutor_certificate_filename`/`tutee_certificate_filename` 欄位保留是為了極少數需要「真的不同底圖」的計畫留一個例外設定的空間,平常不需要動它。

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
- 不串接學校 SSO；Gunicorn、systemd、Nginx 與 production env 範本已完成，但尚未在學校正式 VM 套用與驗證，DNS、TLS、防火牆、備份/監控及還原演練仍待 VM 到位後處理(見 `docs/DEPLOY.md`)。

### 舊版系統的參考原則

舊版專案位於 `/Users/Qiangqiang/Desktop/CSL-system`,技術是 React/Vite＋Express＋直接 SQL,可用來確認早期產品概念與 UI,但**不可把舊 API、SQL 或大型 JSX 直接複製進本專案**。新版是 Django server-rendered 架構,且已加入交易鎖、model validation、DB constraint、角色權限與 AuditLog;沿用舊功能時必須依新版模型與 service layer 重新實作。

舊版盤點過的概念目前皆已排入範圍並完成(候選篩選、私訊摘要、輔導類型標籤、課堂紀錄附件、Admin 使用者總覽、時數調整帳,見 `docs/PROGRESS.md`「已完成」)。

明確不沿用舊版的內容:Email 驗證、100 小時才可申請證明、證明再次送 Admin 核發、09:00–19:00 排課限制、硬編碼檔案清單、未完成的 WebSocket「線上」狀態、用假課程補時數,以及異常回報附件(2026-07-26 已確認目前不需要;課堂紀錄附件仍保留,見第 4.6 節;若之後需求改變,做法可直接比照課堂紀錄附件)。

## 4. 核心業務邏輯

### 4.1 名冊、註冊與帳號恢復

- `RosterEntry.student_id` 與 `User.username` 都代表學號;學號唯一。`RosterEntry.clean()` 會將學號正規化為大寫,註冊第一階段的學號查找也是大小寫不敏感,所以系辦名冊與使用者輸入不論大小寫都能對上(登入本來就是大小寫不敏感,這裡是補齊匯入/註冊端的一致性)。
- 公開註冊第一階段只接受 `is_enabled=True`、尚未 claimed、角色為 Tutor/Tutee 的名冊。
- 第一階段建立 `RegistrationDraft`,只保存 Django 密碼雜湊,30 分鐘到期。
- **2026-08 新增「確認學號」中間步驟**(`docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 7 項):第一階段成功後不會直接進入第二階段個人檔案表單,而是先導向 `/register/confirm/`(`accounts:register_confirm`),清楚列出學號並要求按「確認學號正確」才會被導向 `/register/tutor/`/`/register/tutee/`;按「返回修改」則回到第一階段。確認狀態只是 session 裡的一個布林旗標(`registration_confirmed`),完全不會動到 `RegistrationDraft.expires_at`,所以原本 30 分鐘的時效不受影響。直接用網址列開啟第二階段網址、或重新整理/返回確認頁都不會建立帳號:第二階段 view(`_role_registration()`)會先檢查這個旗標,沒確認就導回確認頁;任何時候重新整理或用瀏覽器返回鍵回到第一階段的 `/register/`(GET)都會清掉目前的草稿與確認旗標(既有的「GET 時清掉舊草稿」邏輯,`register()`),確保「返回」永遠是乾淨重來,不會意外殘留一個已確認但使用者其實想改的草稿。
- 第二階段依名冊角色進入 `/register/tutor/` 或 `/register/tutee/`;完整 Profile、安全問題與同意欄位成功後才建立正式 `User`,並設定 `claimed_at`。
- 中文姓名與英文姓名由使用者於第二階段註冊時填寫;Tutor 另選學制。身分別改由快速名冊第二欄預先匯入,註冊第一階段必須以「學號＋身分別」核對。第二階段顯示名冊身分但欄位為 disabled,使用者不可覆寫,需要更正時聯絡系辦。馬里蘭學生仍由名冊所屬計畫判定。`RosterEntry.name_zh`/`education_level` 在匯入時可留空,姓名送出註冊表單時寫回並鎖定。
- 第二階段要求 Email(`AbstractUser.email`,必填,僅檢查基本格式,不寄驗證信)。2026-08-10 已全面移除暱稱欄位及 `User.nickname` model 欄位(`accounts/0017`),畫面與配對資料均不再使用暱稱。**2026-09-08 起所有接受 Email 的表單(註冊、Tutor/Tutee/Admin 個人資料編輯)都額外套用 `accounts/forms.py::validate_email_no_control_characters`**,明確拒絕 `\r`、`\n`、NUL 與其餘 ASCII 控制字元,再交給 Django 內建的 `EmailField` 驗證。這是師大資中弱點掃描報告列出的 SMTP MX 注入疑似項目(`docs/VULNERABILITY_SCAN_REPORT_2026-09-08_ACTION_PLAN.md`)的縱深防護:Django 內建的 `EmailValidator` 正則與 `ProhibitNullCharactersValidator` 其實已經擋掉大部分注入嘗試,這個 validator 讓「拒絕控制字元」成為程式碼裡看得到、測得到的明確規則。
- 安全問題題庫(`accounts.models.SecurityQuestionAnswer`)分成兩份清單:`QUESTION_CHOICES` 含全部題目(含已停用題目,回復密碼流程用,確保舊帳號的安全問題 key 與文字都還能正確顯示與比對)、`ACTIVE_QUESTION_CHOICES` 排除已停用題目(新註冊表單只從這份清單選)。2026-08 停用 3 題(自訂秘密短語、第一位導師姓氏、童年最喜歡的遊戲)、改了 2 題文字移除「童年」字樣、新增 1 題(最喜歡的一首歌)。三題必須互不相同:表單會逐欄顯示錯誤,資料庫另有 `three_distinct_security_questions` check constraint 防止繞過表單寫入重複題目。
- 預覽頁 `/preview/tutor/`、`/preview/tutee/` 只在 `DEBUG=True` 開放,不寫入資料庫。
- 密碼至少 10 字元,套用 Django similarity/common/numeric validators,並套用 `accounts/password_validation.py::BilingualPasswordComplexityValidator`(2026-09-09 新增)強制混合大寫字母、小寫字母、數字與特殊符號——在此之前純小寫的密碼(如全小寫英文單字組成的長字串)可以通過既有全部驗證器,是在幫 Admin 個人資料頁新增密碼變更功能時測試發現的缺口。
- 忘記密碼採「學號＋原本選定的三題＋三個答案」;答案正規化後只存 hash。
- 恢復驗證同 IP＋學號 15 分鐘最多 5 次;驗證成功後 10 分鐘內必須完成新密碼設定。
- `User.account_status=SUSPENDED` 時禁止登入。
- `/profile/` 可自行編輯:電話、Email、性別、母語、國籍、系所、聽說讀寫程度、簡介/需求備註、可上課星期與時段(Tutee 另含整體程度、學習時間、加強項目),修改立即生效,不需 Admin 審核,寫入 `PROFILE_UPDATED` AuditLog。
- 姓名(`name_zh`/`name_en`)、學號(`User.username`/`RosterEntry.student_id`)、安全問題答案不開放使用者自行修改,有問題須聯絡系辦。
- 口語能力證明狀態不受 Profile 編輯影響,重新上傳沿用既有 `/qualification/upload/` 流程。
- Profile 欄位(尤其聽說讀寫程度、可上課時段)是配對候選卡片即時讀取的來源;配對成立後仍可編輯,對方看到的資料會跟著即時變動,系統目前沒有配對當下的快照機制。

### 4.2 學期

- 學期只有開始/結束日;已移除另外的配對開始/截止欄位,所以配對窗口就是整個學期。
- **2026-08 起學期(`Semester`)改為可依合作計畫分別設定期間**(`docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 15 項):
  - `Semester.program`(可為空的 FK 到 `PartnerProgram`):`None` 代表**舊版共用期間**,是這次改版前唯一存在過的形式,保留是為了讓既有 `Semester` 資料與已連結的 `Pairing`/`ClassSession` 不需要 migration 就能繼續運作。新建立的期間**表單一律要求選計畫**(`SemesterCreateForm.program.required=True`),但編輯既有期間的表單(`SemesterSettingsForm`)刻意讓 `program` 維持選填,避免逼使用者為舊期間回填計畫才能改名稱或日期。
  - 啟用期間的重疊檢查改成**同一 `program` 值內才擋重疊**(`None` 自己也算一種值,即所有舊版共用期間彼此之間仍不可重疊);不同計畫(含一個是 `None`、一個是實際計畫)的期間可以互相重疊,不再有全域筆數上限。
  - `tutoring/services.py::active_semester(program=None)` 取代原本無參數版本:`program=None` 查「目前啟用中的舊版共用期間」;傳入實際計畫時優先找該計畫專屬且目前啟用中的期間,找不到才退回舊版共用期間,確保還沒建立專屬期間的計畫不會突然無法使用。`user_program(user)` 取得使用者對應的計畫。`send_invitation()`、`dashboard()` 的 `matching_open` 判斷都已改用這個工具,依當事人所屬計畫決定要看哪個期間,而不是永遠只取資料庫裡第一筆「目前學期」。
  - **2026-08-21 修正一個 `user_program()` 的真實 bug**:一般 NTNU Tutor(`roster_entry.program` 為空)原本回傳 `None`,但 `active_semester(program=None)` 的意思是「查舊版共用期間」,不是「查 NTNU 專屬期間」——導致 Admin 建立一個指定 NTNU 計畫的新學期後,NTNU 學生(`roster_entry.program` 明確是 NTNU)正確套用新學期,一般 NTNU Tutor 卻仍停留在舊的共用學期,雙方看到不同期間。修正為:一般 Tutor(`roster_entry.program` 為空)改回傳實際的 NTNU `PartnerProgram` 物件而非 `None`,讓「留空隱含代表 NTNU」這個既有慣例在往下傳遞時被正確解析成具體物件。`dashboard()` 裡原本針對「Tutor 找學生用的計畫」已經手動 `if ... is None: fallback to NTNU` 補丁過同一個問題,但學期判斷那處漏補,這次順便移除該處的手動補丁(`user_program()` 本身已經處理好,不需要呼叫端各自補)。
  - **2026-08-21 已移除 `Semester.applicable_users`**(原本是選填的 M2M 到 `User`,留空代表「該計畫所有帳號都適用」,可複選特定使用者限縮適用對象):這個欄位從加入以來實際上一直沒有真正被用過,且它想解決的「一人同時適用多個計畫」問題其實解決錯了層次——它是掛在「學期」上的名單,不是「使用者屬於哪些計畫」這個身分屬性,就算在學期名單上勾了兩個計畫,`tutor_can_serve_program()` 這個真正決定配對/瀏覽權限的函式也完全不會看這個名單,兩者對不上。同時這也是使用者主動發現的一個既有不對稱:目前 `RosterEntry.program` 是單一可空欄位,NTNU Tutor 用「留空」隱含代表,Maryland Tutor 用明確值代表,若真的要支援「一人同時屬於多個計畫」,更根本的做法是把 `RosterEntry.program` 改成多對多,而不是在學期這層加名單;這個多對多改造牽涉 migration、資料回填與重新檢查所有假設「一人一計畫」的地方,列為獨立的未來任務,不與這次移除混在一起。移除後 `SemesterCreateForm`/`SemesterSettingsForm` 不再有這個欄位,`semester_applies_to_user()` 函式與其呼叫端(`send_invitation()`、`dashboard()` 的 `matching_open`)也一併移除,回歸「只要在啟用期間內,該計畫所有帳號都適用」的單純規則。
  - 尚未涵蓋:排課、時數統計、證明下載目前仍主要透過 `Pairing.semester` 直接拿學期物件,不會另外重新判斷「這個配對此刻該用哪個期間」,因為配對成立當下就已經鎖定 `semester`。
  - **2026-09-16 修正:Tutor/Tutee 自己 dashboard 的「目前配對」不再要求「當下日期落在學期起訖區間內」**(使用者實際回報:登入 `NTNU-OIA-TUTOR` 卻看不到已成立的配對)。根本原因:`accounts/views.py::dashboard()` 的 `current_semester = active_semester(program=user_program(request.user))` 只有在今天落在該學期 `starts_on`～`ends_on` 之間才會非 `None`;原本 TUTOR/TUTEE 分支的「目前配對」查詢要求 `Pairing.semester=current_semester`,一旦 Admin 把某計畫學期的 `starts_on` 改成未來日期(例如新學期正式開課日),當天到開課日之間,該計畫**所有已成立的 ACTIVE 配對**都會從當事人自己的 dashboard 消失,即使配對本身完全正常——這次事件正好是使用者在 115 學年度第 1 學期(NTNU/MARYLAND)開課前先讓幾組配對成立時發現的。使用者確認的正確行為:「已配對的要能先看到,但排課要等學期開始」——**這兩件事本來就是分開判斷的**:`tutoring/services.py::schedule_classes()` 檢查的是 `class_date` 是否在 `pairing.semester.starts_on`～`ends_on` 之間(配對自己鎖定的學期,不是「目前是否為進行中學期」這個判斷),所以拿掉「目前配對」顯示的日期限制,並不會連帶允許提早排課。修法:TUTOR/TUTEE 分支的 `pairings` 查詢改成單純 `Pairing.objects.filter(tutor=request.user, status=ACTIVE)`(或 `tutee=`),不再要求 `semester=current_semester`;瀏覽候選人/送邀請(`matching_open` 相關邏輯)刻意維持不動,學期開始前仍不能發起新配對。
- 學期結束超過 6 個月後,`archive_expired_semesters()` 只把 `is_active=False`;不刪學期、課程或時數。
- 學期結束後 active pairing 自動結束,pending release 也會被標為自動處理。
- `dashboard()` 會呼叫 `synchronize_matching_state()`;正式環境仍須排程 `python manage.py process_matching_state`,否則無流量時不會即時處理。
- Admin dashboard「學期時間設定」每張學期卡片右上角有一顆編輯筆 icon(`.semester-edit-icon-btn`,`<details>`/`<summary>` 實作,無 JS),點擊展開該學期的編輯表單(`tutoring:update_semester`,`SemesterSettingsForm`)可改名稱與日期;修改日期是**回溯性**的,`makeup_deadline_at`/`hours_download_at` 都是即時運算的 property 而非快照,改 `ends_on` 會立即影響補登期限與證明下載開放時間,且不會回頭檢查已排課程是否超出新範圍,UI 上有提示但無強制檢查。
- `SemesterSettingsForm`/`SemesterCreateForm` 的日期欄位 widget 需明確設定 `format="%Y-%m-%d"`(`DateInput(attrs={"type": "date"}, format="%Y-%m-%d")`),否則瀏覽器原生日期選擇器認不出 Django 預設 locale 格式,編輯既有學期時日期欄位會顯示空白而非目前值。
- 刪除分兩種:此學期底下**尚無 `Pairing`** 才能真刪除(`tutoring:delete_semester`,寫入 `SEMESTER_DELETED`,DB 靠 `Pairing.semester` 的 `PROTECT` 約束擋下有資料的情況);已有 `Pairing` 且**已結束**(`ends_on < today`)只能「封存」(`tutoring:archive_semester`,`is_active=False`,原有課程/時數保留);已有 `Pairing` 且尚未結束則兩者都不能用,只能編輯修正。

### 4.3 匿名資料與邀請

配對前不得顯示姓名、英文名、完整學號、電話或 Email。程式目前匿名欄位如下:

- Tutee:性別、母語、國籍、整體華語程度、加強項目、學習時間、需求備註、可上課星期/時段。
- Tutor:性別、母語、國籍、四項教學能力、教學簡介、可上課星期/時段。

**配對成立後才顯示雙方正式姓名及 Email**:`accounts:matched_profile`(配對後完整個人資料頁)與私訊頁(`templates/tutoring/messages.html`,對方名稱區)會顯示對方 Email。這些頁面本身已有配對存取控制:`matched_profile()` 只認 `ACTIVE` 配對,查無則 `Http404`;私訊頁允許曾經配對過的雙方開啟,`ACTIVE` 可發送、`ENDED` 唯讀(見第 4.8 節)。因此配對結束後完整 Profile 會收回,歷史對話仍保留當時雙方的正式姓名與 Email。Email 只作聯絡資訊顯示,系統不寄信、不整合 Gmail、Google 登入或校內 SSO。**2026-09-10 起配對雙方一律看不到彼此的學號/帳號 ID**(使用者明確要求,即使配對成立也不例外):`templates/accounts/matched_profile.html` 的「基本資料」不再列學號欄位,`templates/dashboard/index.html`「目前配對」卡片也拿掉對方 `username` 的顯示,只留姓名(中英)與 Email。這條隱藏只針對 Tutor/Tutee 互看對方,不影響 Admin 的行政檔案、配對管理列表、課程總覽等既有畫面(Admin 本來就需要看真實學號才能核對名冊與處理業務,未變動)。

Tutor 瀏覽外籍生候選人清單時,可用性別、華語程度、母語、加強項目、星期、時段做複合篩選(`tutoring/services.py::anonymous_tutee_candidates()` 的 `filters` 參數;UI 見 `templates/dashboard/index.html` 的 `find-tutee` 分頁,GET 表單提交回 `accounts:dashboard`)。篩選邏輯:性別/華語程度/母語皆為精準比對(母語欄位是下拉選單,選項與註冊表單共用同一份 `static/js/profile-options.js` 產生的語言清單,值為 `Intl.DisplayNames` 產生的雙語字串,不是自由關鍵字);加強項目為「已選項目須全部命中」(AND);星期與時段各自為「命中任一已選值即算符合」(OR),兩者之間再取交集。篩選只是在既有候選清單上做子集過濾,不會新增可見欄位,也不做排序或推薦。篩選卡片預設收合,面板標題右上角的「搜尋條件 / Search filters」是 `<details>/<summary>` 原生收合元件(`.candidate-filter-disclosure`/`.candidate-filter-toggle`,無 JS),點擊才展開,取代原本常駐的「配對前不顯示姓名與學號」提示(該提示仍保留在側邊欄 `sidebar-note`)。Tutee(Maryland)瀏覽 Tutor 一側也已比照補上同一套機制(`anonymous_tutor_candidates()` 的 `filters` 參數,UI 見 `find-tutor` 分頁);差異是 Tutor 沒有對應「華語程度」與「加強項目」的欄位,所以只提供性別、母語、星期、時段四項,其餘篩選邏輯(精準比對/OR/收合式 UI)完全相同。**2026-09-08 師大資中弱點掃描發現一個真實 500**:`GET /dashboard/?tutee_level=%00` 這類請求裡的 NUL byte,原本從 `request.GET` 未經清理就直接進 `queryset.filter(overall_level=...)`,psycopg 遇到含 NUL 的字串會直接丟例外,變成未攔截的 500。`accounts/views.py::dashboard()` 已在建構 `candidate_filters`/`tutor_candidate_filters` 前,對有固定選項的欄位(性別、華語程度、加強項目、星期、時段)一律白名單比對(`_sanitize_choice_value`/`_sanitize_choice_list`,不在白名單內的值一律當成「沒有篩選」,不是擋下請求或顯示錯誤);母語沒有固定後端選項清單,改用 `_sanitize_free_text_filter` 拒絕控制字元並限制長度。

**2026-08-22 候選卡片/邀請列表新增 `is_test` 提示**(`tutoring/services.py::_is_test_account()`,`anonymous_tutee_profile()`/`anonymous_tutor_profile()` 皆會附上):學號以 `TEST-` 開頭(`seed_test_roster.py` 早就在用的同一套測試學號慣例,見 `docs/SECURITY_CHECKLIST.md`)的帳號,在候選卡片、收到/已發送邀請、邀請歷史紀錄上都會多顯示一個「TEST」小標籤,方便系辦/測試人員在正式環境上肉眼分辨測試帳號與真實學生。**這不違反配對前最小揭露原則**:回傳的是伺服器端算好的布林值,不會把實際學號傳到前端,前端本來就看不到、也不需要知道實際學號是什麼。**2026-10-03 修正真實 bug:TEST- 帳號原本只有徽章提示,沒有真的從候選名單排除(使用者回報「馬里蘭還有學生送出邀請給測試/非真人帳好...谭清玥/Madilyn Tribbitt邀請掃描老師乙/Scan Tutor Maryland」)**:查正式站發現同一個弱點掃描測試帳號 `TEST-SCAN-TUTOR-MD`(掃描老師乙,見 `docs/VULNERABILITY_SCAN_ACCOUNT_SETUP.md`)已經被 3 位不同的真實 Maryland 學生(M0024/M0052/M0027)誤送出配對邀請——`is_test` 這個布林值從加入以來就只用來在候選卡片/邀請列表上顯示「TEST」提示標籤,`anonymous_tutee_candidates()`/`anonymous_tutor_candidates()` 從來沒有真的把 TEST- 帳號從候選名單排除,真實使用者一直都看得到、邀得到這些帳號。已修正為:①兩個候選清單函式都新增 `.exclude(...roster_entry__student_id__startswith="TEST-")`,TEST- 帳號不會再出現在任何真實使用者的候選名單裡;②`send_invitation()` 服務函式本身也補上同一道檢查(`_is_test_account(tutor) or _is_test_account(tutee)` 任一方為真就拒絕),避免有人繞過候選畫面直接呼叫這個函式建立邀請,跟 `tutor_can_serve_program()` 等既有「候選名單與送出邀請都要各自檢查一次」的慣例一致。**只擋「測試帳號與真實使用者」的配對,不影響測試帳號彼此之間既有的配對**:`TEST-SCAN-TUTOR-NTNU`↔`TEST-SCAN-TUTEE-NTNU`、`TEST-SCAN-TUTOR-MD`↔`TEST-SCAN-TUTEE-MD` 這兩組是透過 `create_admin_pairing()` 建立(不經過 `send_invitation()`),完全不受這次修正影響,掃描帳號仍可正常使用。**一次性正式站資料訂正**:查到的 3 筆邀請中,2 筆(M0052、M0027)申請人自己已經取消,維持原樣;唯一 1 筆仍是 `PENDING` 的(M0024/谭清玥→TEST-SCAN-TUTOR-MD)已用 `cancel_invitation(invitation_id=369, actor=該名學生)` 取消(以申請人本人身分呼叫既有服務函式,比照 `docs/VULNERABILITY_SCAN_ACCOUNT_SETUP.md` 一貫的「優先呼叫現行服務,不要裸 SQL 繞過規則」原則),寫入正常的 `INVITATION_CANCELLED` AuditLog。**同時檢查師大外籍生(NTNU)計畫**:`TEST-SCAN-TUTOR-NTNU`/`TEST-SCAN-TUTEE-NTNU` 目前沒有任何真實使用者誤發的邀請,不需要訂正。新增回歸測試(`tutoring/tests.py::MatchingTests` 新增 3 項、改寫 1 項既有測試),482 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 service/測試調整,無 model/migration/CSS 變更。

**2026-08 起 Tutor 與 Tutee 的可見/可配對範圍改依計畫分流**(`docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 4 項,馬里蘭大學語言學伴計畫):Admin 可在名冊匯入頁籤該計畫卡片的「Tutor 名單」區塊匯入修課 Tutor 學號(`accounts:roster_import_quick` 的 `category_code` 用 `TUTOR:<程式碼>`,例如 `TUTOR:MARYLAND`),把特定 Tutor 學號的 `RosterEntry.program` 設成該計畫(沿用 Tutee 早已使用的同一個欄位,只是這次允許 Tutor 也設定;`RosterEntry.clean()` 本來就沒有禁止 Tutor 有 `program`,只是先前的名冊匯入流程沒有入口可以這樣做)。`tutoring/services.py::tutor_can_serve_program(tutor, program)` 是唯一的判斷依據:沒有被列入任何計畫名單的一般 Tutor(`roster_entry.program` 為空)只能看到/配對 NTNU 的 Tutee;被列入某計畫修課名單的 Tutor 只能看到/配對「同一個計畫」的 Tutee,且**馬里蘭計畫額外要求該 Tutor 的 `education_level` 必須是大學部**(語言學伴課程限大學部,即使名單意外收錄了非大學部學號也會被這條規則擋下,不是只靠學制單獨判斷,因為不是所有大學部生都修這門課)。這條規則同時套用在:`anonymous_tutee_candidates()`(Tutor 瀏覽學生候選人清單)、`anonymous_tutor_candidates()`(Tutee 瀏覽老師候選人清單)、`send_invitation()`(不論是誰發起邀請都會檢查,不能繞過畫面直接呼叫 API 建立不符資格的邀請)。`tutoring/services.py::user_program(user)`(item 15 引入)也已同步更新,讓有修課名單的 Tutor 能正確對應到該計畫的期間,不再永遠被當成沒有計畫的一般 Tutor。

**2026-09-22 馬里蘭計畫課程安排建議(使用者提問後確認採用「提醒」而非硬性規則)**:使用者提出馬里蘭計畫的課程安排建議「每位學生以30分鐘中文，可以自由額外跟對方練30分鐘英文，一週一次」,並詢問是否要寫死在排課功能。討論後定案**只做提醒,不寫成強制規則**:排課時數本身沒有問題(30 分鐘本來就是既有合法排課時長之一,見上方 4.5 節),但「額外自由練習英文」明確是選填、彈性的,系統也沒有「課程類型/語言」欄位可以區分中文輔導與英文練習,硬性寫死等於要新增一套只給馬里蘭用的排課例外規則,違背系統既有「排課邏輯全計畫共用,不做 per-program 例外」的設計原則(時數上限就是刻意所有計畫一致,見系統邊界一節)。實作:`templates/dashboard/schedule_panel.html`「安排課程」面板依 `tutee_matching_program.code == 'MARYLAND'` 二選一顯示提示文字,純顯示層級,不影響 `schedule_classes()` 的任何驗證規則(排課時數上限本身仍是所有計畫一致,只是文字說明不同)。**2026-09-22 當天再調整一次(使用者要求)**:拿掉 NTNU 那句通用的「每組每週最多 2 小時」提示不再對馬里蘭顯示;馬里蘭專屬提示也拿掉「馬里蘭計畫建議：每位學生」這段前綴,直接以建議內容開頭。

邀請規則:

- **2026-09-16 起,配對(瀏覽候選人、送出/接受邀請)提前 7 天開放**(使用者轉達助教需求:「學期設定前一週可以先瀏覽tutee名單以及配對，但還不能安排課程」)。`tutoring/services.py::MATCHING_EARLY_OPEN_DAYS = 7`;`active_semester(program, early_days=0)` 新增選用參數,只有傳入非 0 值時才把「起始日」判斷提前該天數(預設值 0 完全不影響既有呼叫端,例如 `admin_tutor_schedule()`)。用到 `early_days=MATCHING_EARLY_OPEN_DAYS` 的呼叫點:`accounts/views.py::dashboard()` 的 `current_semester`/`matching_open`(含 Admin 自己看到的「目前學期」小方塊,理由是配對已提前開放時,Admin 畫面卻還顯示「尚未設定」會不一致)、`tutoring/services.py::send_invitation()` 取得的 `current` 學期、`_validate_matching_window()`(`send_invitation()`/`respond_to_invitation()` 接受邀請共用同一個檢查)。**排課完全不受影響**:`schedule_classes()` 檢查的是 `class_date` 是否在 `pairing.semester.starts_on`～`ends_on` 之間(配對自己鎖定的學期起訖日,不是「現在是否為進行中學期」這個判斷),跟這裡的提前開窗是兩套獨立邏輯,所以配對可以提前一週成立,但實際課程日期仍然只能落在學期正式起訖範圍內,一堂都排不進提前的這幾天。`create_admin_pairing()`(Admin 手動配對)完全不呼叫 `_validate_matching_window()`,本來就不受任何學期日期限制,不受此次調整影響。
- 邀請有效 5 天;過期後 `EXPIRED`。
- Tutor 必須有 APPROVED 口語能力證明且名額未滿,且必須在該 Tutee 所屬計畫的修課名單範圍內(見上)。
- Tutor 可邀請可用 Tutee;Tutee 能否主動邀請 Tutor 由其 `RosterEntry.program.allow_tutee_initiate_invitation` 決定(目前只有 `MARYLAND` 為 True,`tutoring/services.py::_tutee_can_initiate_invitation()`)。
- 收件人接受後立即建立 Pairing,不需 Admin 核准。
- Tutee 同學期最多 1 個 active Tutor;Tutor 同學期最多 2 個 active Tutee。
- **2026-09-10 起,Tutee 只要已有一筆待回覆邀請(PENDING,不分是誰發起),就會被鎖定**:`send_invitation()` 在既有的完全重複邀請檢查之後,多一道檢查——只要該 Tutee 在該學期已有其他 Tutor 送出的 PENDING 邀請,任何「別的」Tutor(`exclude(tutor=tutor)`)再次對同一 Tutee 送出邀請都會被 `ValidationError` 擋下,直到那筆邀請被接受、拒絕、取消或過期為止(先前的行為是:只要 Tutee 尚未配對成功,任何數量的 Tutor 都能同時對同一 Tutee 送出待回覆邀請)。`anonymous_tutee_candidates()` 也會把「已被別的 Tutor 鎖定」的 Tutee 從候選清單排除,但**對已送出該邀請的 Tutor 本人仍會顯示**(该 Tutor 看得到自己邀請中的對象,只有其他 Tutor 看不到)。這條規則**只套用在 Tutee 一側**,不對稱套用到 Tutor 身上——因為 Tutee 名額上限本來就是 1,鎖定與最終結果一致;但 Tutor 名額上限是 2,若對 Tutor-as-recipient(Maryland Tutee 主動邀請 Tutor 的情境)套用同樣的「一筆 PENDING 就鎖」規則,會誤擋合法的、還沒滿額的第二筆邀請,所以刻意不做。判斷條件只看 `tutee=tutee` 這個 FK,不管 `initiated_by`,因此不論是 Tutor 主動邀 Tutee、還是 Maryland Tutee 主動邀 Tutor(兩者都會建立一筆以該 Tutee 為 `tutee` 的邀請),都會正確觸發鎖定。此變更讓 `respond_to_invitation()` 接受分支裡「取消 Tutee 其他 pending 邀請」的 `_auto_cancel_pending_invitations` 呼叫,以及 `send_invitation()` 裡原本對 Tutee 也會檢查的 `MAX_PENDING_INVITATIONS_PER_USER` 3 筆上限,在 Tutee 一側實質上永遠不會再被觸發(Tutee 現在最多只可能有 1 筆 PENDING),但程式碼刻意保留未刪除,避免在同一次改動裡夾帶非必要的重構;這兩段邏輯對 Tutor 一側仍然有效、仍是活的。
- 每位使用者(Tutor 或 Tutee)同學期待回覆邀請(PENDING)總數上限 3 筆,不分是誰發起、雙向合計計算(`MAX_PENDING_INVITATIONS_PER_USER`,`tutoring/services.py`)。
- 接受某 Tutee 的邀請後,該 Tutee 其他 pending invitations 會自動取消(不分發起人)。
- Tutor 因此次接受而配對名額滿(達 2 位 active Tutee)時,該 Tutor 其餘 pending invitations 也會一併自動取消。
- `Pairing` 對 `(semester, tutor, tutee)` 有永久唯一約束:同學期曾配對過,即使解除後也不能再配同一人。
- 解除後雙方只要各自仍有名額,可和不同對象重新配對。
- **2026-08-22 起邀請的送出/接受/婉拒/取消/自動取消/自動過期都寫入 `AuditLog`**(`INVITATION_SENT`/`INVITATION_ACCEPTED`/`INVITATION_REJECTED`/`INVITATION_CANCELLED`/`INVITATION_AUTO_CANCELLED`/`INVITATION_EXPIRED`):在此之前邀請完全沒有稽核紀錄,且一旦轉成非 `PENDING`(不論是被拒絕、取消或過期)就會從 Dashboard「邀請管理」分頁的收到/已發送清單消失、沒有任何地方看得到,是使用者實測時發現的落差。Dashboard「邀請管理」分頁新增「歷史紀錄」區塊(`invitation_history`,依匿名資料呈現,最近 20 筆),讓已結束的邀請仍可查閱,但**維持配對前最小揭露原則**:歷史紀錄一樣只顯示匿名資訊(性別/母語/國籍等),不會因為邀請已經結束就額外顯示對方姓名或學號。系統自動觸發的事件(過期、因另一筆邀請成立而自動取消)`actor` 為 `None`,比照既有的 `PAIRING_RELEASE_AUTO_APPROVED`/學期自動結束等系統事件慣例。

**Admin 手動配對**(`docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 12 項,2026-08 新增):Admin 可在 Dashboard「配對管理」頁籤的「Admin 手動配對」表單直接選 Tutor、Tutee、期間建立配對,跳過雙方邀請/接受的流程(`tutoring/services.py::create_admin_pairing()`,`tutoring:create_pairing` URL,一般使用者呼叫會被擋下)。除了「不需要邀請」以外,其餘資格檢查(角色、帳號啟用、`tutor_can_serve_program()` 計畫名單、Tutee 是否已有 active Tutor、是否重複配對)與一般邀請流程完全相同,不會因為走這條路就繞過第 4 項的計畫限制。**唯一的例外是名額**:一般自行配對(邀請流程)每位 Tutor 同學期上限固定 2 位 active Tutee;透過這個功能,Admin 可以讓非 NTNU 合作計畫的 Tutor 額外多帶 1 位(同學期總量上限 3 位,`ADMIN_PAIRING_EXTRA_CAPACITY`/`tutor_has_admin_pairing_capacity()`),但 NTNU 一律維持 2 位上限,Admin 無法用這個功能讓 NTNU 配對超額。建立的 `Pairing.created_by` 會記錄是哪位 Admin 建立的(一般邀請流程建立的維持 `None`),並寫入 `ADMIN_PAIRING_CREATED` 的 `AuditLog`。時數規則(每組每週 2 小時、每組 32 小時、Tutor 每學期 64 小時)目前**沒有**因為這個功能另外放寬,仍套用既有上限,作為尚未定案計畫別時數規則前的 fallback。

### 4.4 解除配對

- Tutor 或 Tutee 都能提出;同一 pairing 同時只能有一筆 pending request。
- `NO_SHOW`、`UNREACHABLE`、`SCHEDULE_CONFLICT`:Admin 可先處理;若從申請時間起連續 48 小時未處理,系統自動解除(2026-08 由「3 天」改為「48 小時」,見 `docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 10 項)。
- `CONDUCT`、`OTHER`:必填補充說明且永不自動解除,只能由 Admin 決定。
- 核准/自動解除時:Pairing 變 `ENDED`,未來尚未取消的課程會取消並釋放額度;已結束的課程與時數紀錄保留。
- Admin 拒絕時 pairing 保持 active。
- **2026-09-10 起,被解除的一方(未提出申請的另一方)會在 Dashboard「我的首頁」看到通知,涵蓋等待審核與已有結果兩種狀態**(使用者與系辦討論後提出的需求;先前只有申請人自己知情,對方要等配對從畫面上消失才會發現):
  - **等待審核中**:沿用既有的 `pairing_release_control.html`(配對卡片下方的狀態區塊,原本雙方都看得到、且不分理由一律顯示完整內容),新增依「是否為申請人本人」分流——申請人看到完整理由與補充說明;對方(counterpart)看到 `PairingReleaseRequest.counterpart_reason_display` 與遮蔽後的補充說明。
  - **已有結果(核准/系統自動解除/拒絕)**:新增獨立的通知區塊 `templates/dashboard/release_notices.html`,顯示在「我的首頁」`目前配對`卡片正上方,只給對方看(申請人排除在外,因為申請人已經知道自己送出過申請),核准/自動解除會標示已解除、拒絕會標示未通過。附一個「我知道了 / Got it」按鈕(`tutoring:acknowledge_pairing_release`,寫入 `PairingReleaseRequest.counterpart_acknowledged_at`),按過之後通知才會消失;在被按之前**每次登入都會持續顯示**,不是只顯示一次。
  - **理由遮蔽規則(使用者明確要求)**:`NO_SHOW`/`UNREACHABLE`/`SCHEDULE_CONFLICT` 三個理由如實顯示給對方;`CONDUCT`(態度或行為問題)與 `OTHER`(其他)一律顯示成通用的「其他原因 / Other」,**補充說明(`reason_note`)也一併隱藏**,避免把可能帶有指控性質的具體內容直接曝光給被指控的一方引發衝突,只讓對方知道「有申請/已解除」這個事實。這個遮蔽規則同時套用在等待審核中與已有結果兩種畫面。判斷邏輯集中在 `PairingReleaseRequest.is_sensitive_reason`/`counterpart_reason_display`(`tutoring/models.py`),不是在 template 裡重複判斷。
  - **只通知被解除的一方,申請人沒有對稱通知**(2026-09-10 使用者確認維持現狀,不加做):申請人只有在送出申請當下看到一次性的 flash message,之後管理員核准/拒絕都不會再收到任何提示;這是刻意的範圍限縮,不是遺漏。
  - 對應 migration:`tutoring/migrations/0034_pairingreleaserequest_counterpart_acknowledged_at.py`(新增 `counterpart_acknowledged_at`,無資料遷移)。
  - **2026-09-11 Admin dashboard「解除配對審核」處理紀錄的「結果 / Result」欄位改用 `.result-text`**(使用者要求):原本用 `.status-badge` 背景色塊呈現,比照口語能力審核紀錄(見上)已有的既有慣例,改成純文字並套用 `.status-approved`/`.status-rejected` 顏色但拿掉背景。

### 4.5 排課與額度

- 只有 active pairing 的 Tutor 可排課。
- 課程時數只能為 0.5、1、1.5、2 小時;正式時數依排課時數,不依實際簽到時間差。
- 開始時間可為全天任一時間,但分鐘只能是 00/05/10/.../55。
- 新課必須在未來且在 pairing 的 semester 範圍內。**2026-09-16 起,超出範圍的錯誤訊息附上確切的學期起訖日**(使用者要求),不再只說「須在本學期內」卻不講範圍是什麼(`tutoring/services.py::schedule_classes()`)。**2026-09-17 起,Tutor dashboard「我的課表」的「安排課程 / Schedule a class」面板標題旁也直接顯示同樣的學期起訖日**(`templates/dashboard/schedule_panel.html` 新增一個 `.privacy-chip`,文字為「上課日期須在本學期內 YYYY-MM-DD～YYYY-MM-DD」),日期直接讀 `current_semester.starts_on`/`ends_on`(`dashboard()` 既有算好的同一個學期物件,含 `MATCHING_EARLY_OPEN_DAYS` 提前開窗邏輯,不是另外寫死或重算),不需要等實際送出排課表單觸發錯誤才知道範圍。`current_semester` 為 `None` 時(理論上不會發生在已有 active pairing 的 Tutor 身上,但保守起見)不顯示這個標籤。
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
2. 雙方各自填寫自己的課堂紀錄(地點、本次教學目標、本日教學範圍與完整流程、使用之教材教具及設備、個別學習情形、心得回饋或改善方法,及 1–5 個佐證連結)。
3. 每人確認對方的簽到與課堂紀錄;可確認、要求修改或回報問題。
4. **2026-09-10 起,雙方互認完成後仍須經 Admin 逐筆核准才成為有效時數,不分是否為補登**(使用者要求,取代先前「一般課程互認後自動生效、只有補登才需要 Admin 核准」的規則;見下方細節)。

細節:

- **2026-09 起課堂紀錄欄位改版**:`ClassRecord.topic`/`.content` 沿用原欄位只改標籤(`topic`→「本次教學目標 / Teaching goal for this session」、`content`→「本日教學範圍與完整流程 / Today's teaching scope and complete process」,2026-10-01 使用者再次微調標籤文字,由 `tutoring/migrations/0040_alter_classrecord_content` 記錄這次純標籤變更);`.remarks` 同樣沿用原欄位只改標籤為「心得回饋或針對個別學習情況之改善方法 / Reflections and feedback, or improvement methods for individual learning」,維持選填。原本選填的多選標籤欄位 `skills_practiced`(聽力/口說/閱讀/寫作)已移除,改為兩個新的必填文字欄位:`materials_used`「使用之教材、教具及設備」(200 字內)與全新的 `individual_progress`「個別學習情形」(500 字內)。Django Admin 的 `SkillsPracticedFilter` 與 `accounts/forms.py::SKILL_CHOICES` 依賴的篩選/統計功能已一併移除;`SKILL_CHOICES`/`SKILL_LABELS` 本身保留,因為 Tutor 教學能力與 Tutee「希望加強項目」仍在使用同一份詞彙,只是不再套用在課堂紀錄上。`tutoring/0027` 為了滿足新增必填欄位時的 NOT NULL 遷移限制,曾先把既有舊紀錄的 `materials_used`/`individual_progress` 回填為一段placeholder 文字;`tutoring/0028` 已把這段文字清回空字串,改由 `class_detail.html`/`admin_record_card.html` 在值為空時顯示「未提供(此紀錄建立於欄位新增前)/ Not provided (this record predates this field)」——資料庫存的是乾淨的空字串,提示文字只在畫面層,不會和使用者真正填寫的內容混在一起。
- `ClassRecord.attachment` 是 2026-08-10 前課堂紀錄附件的歷史相容欄位;目前 Tutor/Tutee 表單都不再提供附件上傳,但舊資料仍可透過受保護下載 view 查看,不得直接移除 model 欄位或刪除既有檔案。
- **2026-08-10 起 Tutor 與 Tutee 課堂紀錄都改用外部佐證連結,不再使用附件上傳**。`ClassRecord.evidence_links` 是 JSONField(`list[str]`,`default=list`),`tutoring/forms.py::ClassRecordForm` 對雙方都提供同一個 `EvidenceLinksField`/`EvidenceLinksWidget`。
  - 驗證規則:最多 5 個,且每個都必須是合法的 `https://` 網址(`URLValidator(schemes=["https"])`),不限制網域(Google Drive、YouTube 只是範例,不是白名單)。超過 5 個與網址格式錯誤是自訂錯誤訊息。
  - **2026-08-25 起 Tutor 仍必填至少 1 個,Tutee 改為選填(可 0 個)**:`ClassRecordForm.__init__` 依 `author.role` 動態設定 `self.fields["evidence_links"].required`,Tutor 維持 `True`(沿用 Django `Field.required` 的標準空值檢查,空列表屬於 `empty_values`),Tutee 設為 `False` 且 label 額外標示「選填 / Optional」、說明文字改為「可選擇提供 0–5 個」。改動前雙方皆必填;是使用者實際使用後反映 Tutee 端要求提供佐證連結負擔過重才調整,Tutor 端不變。**2026-10-01 使用者再次調整雙方說明文字的措辭(先改 Tutee,使用者隨即指出「tutor也要改啊，不然很多tutor都沒有上傳授課照片」,兩邊一併調整)**:Tutee 版改為「可選擇提供 0–5 個可供對方及管理者查看的當次上課佐證連結，必須上傳實際授課照片、詳細教材等，作業或錄影可選填」;Tutor 版(原本必填 1–5 個不變)同步改為「請提供 1–5 個可供對方及管理者查看的當次上課佐證連結，必須上傳實際授課照片、詳細教材等，作業或錄影可選填」。**純文字措辭調整,實際驗證規則不變**(Tutor 仍是至少 1 個、Tutee 仍是 0–5 個皆可,系統都不檢查連結內容實際屬於哪一種類型),只是提醒文字更明確建議哪些證據類型比較重要,因應使用者反映許多 Tutor 送出的連結裡都沒有附上課照片。同步更新 `templates/accounts/handbook.html` 的 Tutee(8.4 節)與 Tutor(9.4 節,原本是條列式清單)兩處對應段落,Tutor 版清單項目標上「（必要）/ (required)」「（選填）/ (optional)」維持一致。
  - 顯示順序與輸入順序一致,可逐筆新增/刪除欄位:`EvidenceLinksWidget` 讓每個連結各自是一個 `name="evidence_links"` 的 `<input type="url">`,靠共用 name 讓 `value_from_datadict()` 用 `QueryDict.getlist()`(或一般 dict 時的 list 直接處理)收集回一個 list,與 Django 內建 `CheckboxSelectMultiple` 的原理相同。新增/刪除按鈕由 `static/js/class-record-links.js`(原生 DOM API + `data-*` hooks,無框架)在前端 clone/remove `.evidence-link-row`,最多到 5 筆,且固定保留最後一筆不給移除(即使 Tutee 選填也一樣,留空即代表不提供);伺服器端驗證才是真正把關,前端只是操作便利性。
  - 課程詳情頁(`class_detail.html`)與 Admin 課程詳情卡(`admin_record_card.html`)顯示對方紀錄時,依序判斷:有 `evidence_links` 就顯示連結;沒有但有 `attachment` 就顯示附件(2026-08 前的歷史資料);兩者都沒有時,若作者是 Tutee 顯示「未提供(選填)/ Not provided (optional)」,否則(理論上只會是很舊、附件與連結都缺的 Tutor 歷史資料)才顯示「未上傳 / Not uploaded」——避免把 Tutee 合法跳過選填連結的情況,誤顯示成「忘記上傳」的措辭。連結一律以 `target="_blank" rel="noopener noreferrer"` 開新分頁。
  - 系統不串接 Google Drive/YouTube API,不做連結有效性、權限或失效偵測;現有雙方互相確認流程本身就是查核機制(任何一方點開發現打不開,可要求對方修改或回報問題),Admin 仍可人工抽查。
- `ClassRecord.content` 與 `ClassRecord.remarks` 上限為 500 字元(model、表單 `maxlength` 與後端驗證一致);課程詳情頁載入 `static/js/character-count.js`,即時顯示 `0/500` 形式的字元計數。不能只依賴瀏覽器計數,伺服器端仍是最終把關。
- 舊 model 上還有一個 `reflection`(學習成果與回饋)欄位,但 `ClassRecordForm` 沒有把它列進 `Meta.fields`,提交流程完全不會用到,等同已棄用的欄位;修改課堂紀錄相關程式時不要誤以為它是現行必填欄位。
- 簽到於上課前 10 分鐘開放。
- 上課結束 30 分鐘後才簽到,視為補簽,必填原因。
- **2026-09-16 起,課堂紀錄改為課堂結束後才可提交**(使用者要求:「發現很多學生都還沒上完課就填寫課堂紀錄」)。同時把「是否算補登」的界線,從下課後 24 小時的浮動視窗,改成「上課當天 23:59:59 前」都算準時,超過當天才算補登(使用者原話:「一樣到當天的23:59算是在期限內」)——避免傍晚或深夜下課的課,因為 24 小時視窗橫跨到隔天很晚才算逾期;深夜上課的課過了午夜就立刻算補登,即使距離下課只過一兩小時,這是與舊制唯一的行為差異。`tutoring/services.py::submit_class_record()` 的開放判斷從 `now < session.starts_at` 改成 `now < session.ends_at`,`is_makeup` 判斷改用 `timezone.make_aware(datetime.combine(session.ends_at 的在地日期, time(23,59,59)), ...)` 當界線(沿用 `Semester.makeup_deadline_at` 既有的同一種「組出當天 23:59:59」寫法)。`tutoring/views.py::class_detail()` 的 `record_requires_makeup_reason`(控制按鈕文字與必填提示)同步改用相同公式。此規則變更只影響提交當下的判斷,不影響已送出的既有紀錄。**2026-09-16 當天再補強一步:課堂紀錄表單在課堂結束前直接不顯示**(使用者要求:「課堂紀錄先不要顯示，課程結束再顯示，不然會有人偷寫」)——原本雖然伺服器端已擋下提早送出,但表單本身仍然全程可見,使用者認為這樣還是可能有人提早在表單裡打好內容準備、課一結束就直接送出("偷寫")。`tutoring/views.py::class_detail()` 新增 `record_window_open`(`now >= session.ends_at`),`templates/tutoring/class_detail.html`「我的課堂紀錄」區塊改成 `{% if own_record or record_window_open %}` 才顯示表單,否則顯示「課堂結束後才能提交課堂紀錄」提示,比照課堂通報(`alert_window_open`)既有的同一種「表單 vs 提示」切換寫法。已送出過的紀錄(`own_record` 存在)不受影響,任何時候都能繼續編輯。伺服器端驗證(`submit_class_record()` 的 `now < session.ends_at`)維持不變,仍是最終把關,這次只是補上對應的畫面呈現。
- 每位使用者每學期最多 5 次補簽到、5 次補課堂紀錄;兩種額度分開計算。
- 補簽/補登最後期限:學期結束後第 1 天 23:59:59。
- 任何一方修改自己的紀錄時,系統會刪除對方針對該作者的舊確認,必須重新確認。
- **2026-09-10 起,`MakeupReview` model 已更名為 `ClassReview`(`tutoring/migrations/0030`,`RenameModel`+related_name 從 `makeup_review` 改為 `class_review`),語意從「只有補登才需要的審核」擴大為「每一堂課都需要的審核」**:雙方完成互認後,`tutoring/services.py::_sync_class_review()`(原 `_sync_makeup_review()`,已移除原本只在 `has_makeup` 時才建立/同步審核紀錄的判斷,現在無條件對每一堂課執行)一律建立/同步一筆 `ClassReview`,狀態進入 `PENDING`,再由 Admin 逐筆核准(`tutoring:review_class` URL,`review_class_session()` service,原名 `review_makeup()`);被拒絕不計有效時數。任一方在審核結果為 `APPROVED`/`REJECTED` 後修改自己的課堂紀錄,會把該筆審核重置回 `WAITING`,規則對是否為補登一視同仁(先前只有補登紀錄的修改才會觸發重置)。
- `class_is_valid()` 的唯一有效條件:課程未取消、剛好 2 筆 attendance、2 筆 class record、2 筆完整 CONFIRMED confirmation、且 `ClassReview.status == APPROVED`——**不再有「非補登可略過審核」的例外**。
- **此規則變更不溯及既往**(使用者確認只套用到之後完成互認的課程):`tutoring/migrations/0031` 是一次性資料遷移,把「規則生效當下、已符合舊版有效時數條件(互認完成但尚未有任何審核紀錄)」的課程直接建立一筆 `status=APPROVED` 的 `ClassReview`(`reviewed_by=None`,`review_note` 註明是規則變更時自動核准、非人工審核),確保已下載證明、已結案學期的有效時數不會因為這次規則變更而消失或需要重新審核。規則生效後才完成互認的課程,一律走正常的 `PENDING` 流程,沒有這層自動核准。
- Admin dashboard 原本的「補登審核 / Makeup review」頁籤已更名為「課程審核 / Class review」,`category_label` 新增「一般課程 / Regular class」分類(雙方皆非補登時顯示),原有的「補簽到」「補課堂紀錄」「補簽到＋補課堂紀錄」分類不變。
- **2026-09-16 課程審核新增「撤回 / Revert」功能(使用者要求)**:比照口語能力審核既有的撤回機制(`accounts/views.py::review_qualification` 的 `action=revert`),`tutoring/services.py::revert_class_review(session_id, admin)` 讓已 `APPROVED`/`REJECTED` 的 `ClassReview` 能撤回重新審核——狀態改回 `PENDING`(不是 `WAITING`,因為雙方互相確認的狀態沒有改變,只是審核結果作廢)、清空 `reviewed_by`/`review_note`/`reviewed_at`。`WAITING`(尚未完成互相確認)或本來就是 `PENDING` 的課程呼叫會擋下,因為沒有審核結果可撤回。UI 入口有兩處:Admin dashboard「課程審核」頁籤的已核准/未核准列表新增「撤回 / Revert」按鈕;`tutoring:class_detail`(Admin 版課程詳情頁,`admin_class_detail.html`)的審核結果區塊同樣新增此按鈕,兩處共用同一個 `tutoring:review_class` URL(`action=revert`)。沒有審核人員身分限制,任何 Admin 都可以撤回任一筆,與口語能力審核撤回、其餘審核類操作的既有慣例一致。**2026-09-16 補上 AuditLog**(使用者確認要補):`review_class_session()`(核准/不核准)與 `revert_class_review()`(撤回)原本完全沒有稽核紀錄,現在都會寫入(`CLASS_REVIEWED`/`CLASS_REVIEW_REVERTED`,`actor` 為操作的 Admin、`target_user` 為該堂課的 tutee,比照 `create_admin_pairing()` 既有慣例,`metadata` 另外帶 `session_id`/`tutor`/`tutee` 學號方便查詢)。
- **2026-10-01 課程審核新增「待補正 / Revise」第三種終局結果,並把審核按鈕文字簡化(使用者要求)**:`ClassReviewStatus` 新增 `REVISE = "待補正 / Revise"`(灰色標籤,沿用「過去課程」既有的 `--slate-700`/`--slate-100` 色票,不新增色票),代表課堂紀錄還有地方需要補正、不是終局的未通過,跟 `REJECTED`(真的不計入的未通過)語意區分開來。同時把 Admin 審核按鈕文字從「核准/不核准」簡化為「通過/未通過」(`APPROVED` 標籤同步從「已通過」簡化為「通過」,維持跟既有 `REJECTED` 的「未通過」對稱),三顆按鈕(通過/待補正/未通過)取代原本兩顆,兩處入口(Admin dashboard「課程審核」頁籤的 `templates/dashboard/index.html`、`tutoring:class_detail` 的 `admin_class_detail.html`)都已同步。`review_class_session()` 的參數簽章從 `approve: bool` 改為 `decision`(`CLASS_REVIEW_DECISIONS = {APPROVED, REJECTED, REVISE}` 三選一),`tutoring:review_class` view 依表單按鈕的 `action`(`approve`/`revise`/`reject`)對應到三種 decision。所有原本只檢查 `{APPROVED, REJECTED}` 判斷「已是決定、不可被自動同步/需要在編輯紀錄時重置」的地方都已擴充為包含 `REVISE`:`_sync_class_review()` 的 guard、`revert_class_review()` 的 guard(REVISE 一樣可撤回回到 PENDING)、`submit_class_record()` 編輯自己紀錄時的重置判斷(REVISE 後任一方再編輯紀錄,一樣會刪除對方的舊確認並重置回 WAITING,跟 APPROVED/REJECTED 的既有規則一致,不是只有這兩種狀態才重置)、`accounts/views.py::dashboard()` ADMIN 分支的 `anomaly_reasons` 判斷集合(兩處)。`ClassReview.review_note` 欄位 `verbose_name` 從「審核備註 / Review note」改為「審核意見 / Review comments」,**且首次對 Tutor/Tutee 開放顯示**:`tutoring/views.py::class_detail()` 非 Admin 分支新增 `class_review` context,`templates/tutoring/class_detail.html` 在互相確認區塊下方新增「管理員審核結果」區塊(狀態非 `WAITING` 才顯示,`WAITING` 時 Admin 根本還沒看過、沒有結果可顯示),呈現審核狀態徽章、審核意見(有填才顯示)與審核人員/時間——在此之前這份審核意見只有 Admin 自己的 `admin_class_detail.html` 看得到,Tutor/Tutee 完全不知道 Admin 寫了什麼。migration `tutoring/0041_alter_classreview_review_note_and_more.py`(純 `AlterField`,label/choices 變更,無資料遷移)。**一次性正式站資料訂正(非永久規則,只處理歷史資料分類)**:使用者要求把 2026-09-21(含)之後、已被標記 `REJECTED` 的課堂紀錄改歸類為 `REVISE`(因為這個更細緻的分類在那之前還不存在,當時只能二選一標成未通過),9/21 之前的維持 `REJECTED` 不變動;只改 `status` 欄位,`reviewed_by`/`review_note`/`reviewed_at` 原樣保留。見 `docs/VM_UPDATE_WORKFLOW.md` §11 對應部署編號的執行紀錄與實際訂正筆數。
- **2026-10-01 審核意見表單上方新增「上一則留言 / Previous comment」(使用者要求「比較好追蹤」)**:情境是 REVISE 後 Tutor/Tutee 補正、重新互相確認、審核回到 `PENDING` 等待管理員再次決定——在這之前 `submit_class_record()` 的重置邏輯與 `revert_class_review()` 都會把 `review_note` 清成空字串,導致管理員下次面對決定表單時完全看不到自己上一次寫了什麼(例如「請補充授課照片」)。兩處改為**刻意不再清空 `review_note`**(只清 `reviewed_by`/`reviewed_at`,因為這兩者代表「目前這個決定是誰做的」,舊決定作廢後沒有對應的人),讓上一次的意見原封不動保留,直到下一次 `review_class_session()` 送出新意見時整個覆蓋掉,不會累加。顯示端:`admin_class_detail.html` 的「課程審核 / Class review decision」表單,在 `<textarea name="note">` 上方新增 `{% if class_review.review_note %}` 區塊顯示「上一則留言 / Previous comment：...」;`templates/dashboard/index.html`「課程審核」頁籤裡,PENDING 狀態下原本就會顯示 `review.review_note` 的那一行(先前因為會被清空,PENDING 時實際上從未顯示過東西),標籤依狀態動態切換——`PENDING` 顯示「上一則留言 / Previous comment」,其餘已決定狀態(APPROVED/REJECTED/REVISE)維持原本的「審核意見 / Comments」標籤,避免跟「目前這個結果的意見」混淆。Tutor/Tutee 自己 `class_detail.html` 的「管理員審核結果」區塊刻意不比照調整標籤(影響範圍只限定在使用者明確點名的 Admin 審核決定表單),該區塊在 `PENDING` 時仍會顯示同一份留言,語意上可理解為「重新審核前、雙方可一併參考的既有意見」,不是錯誤顯示。新增回歸測試 `tutoring/tests.py::ClassWorkflowTests::test_review_note_carries_over_as_previous_comment_until_next_decision`,並更新 2 項既有測試(`test_revert_class_review_resets_approved_result_back_to_pending`、`test_revert_class_review_from_revise_back_to_pending`)的斷言,從「撤回後 `review_note` 變回空字串」改為「撤回後 `review_note` 維持撤回前的值」。純邏輯/template 調整,無 model/migration 變更。**2026-10-01 當天使用者追加「只要admin有給建議，都要顯示出來」,補齊上一輪遺漏的 `WAITING` 狀態**:上一輪只處理了「回到 `PENDING` 之後」的顯示,但 REVISE 後學生剛編輯完紀錄、對方還沒重新確認這段期間,審核狀態是 `WAITING`——而三處既有顯示邏輯當時都只在非 `WAITING` 狀態才顯示 `review_note`,導致這段 WAITING 空窗期管理員留的意見整個消失不見,直到雙方重新確認完成回到 `PENDING` 才會重新冒出來。修正:`admin_class_detail.html` 的 `WAITING` 分支(`{% elif class_review.status == 'WAITING' %}`)原本完全不輸出 `review_note`,補上同樣的「上一則留言 / Previous comment」顯示;`templates/dashboard/index.html` 課程審核列表的標籤判斷從「只有 `PENDING` 用上一則留言」擴大為「`PENDING` 或 `WAITING` 皆用上一則留言,其餘已決定狀態才用審核意見 / Comments」;Tutor/Tutee 自己的 `class_detail.html`「管理員審核結果」面板的顯示條件,從「狀態非 `WAITING` 才顯示」改為「狀態非 `WAITING`,或雖然是 `WAITING` 但有殘留的 `review_note`,才顯示」(`{% if class_review and class_review.status != 'WAITING' or class_review.review_note %}`,Django template 的 `and`/`or` 優先序與 Python 相同,`and` 比 `or` 先結合,所以這個寫法等同 `(class_review and 非WAITING) or 有留言`,`class_review` 為 `None` 時兩個子句都會是 falsy,不會誤判),面板內的標籤同步比照「`WAITING`/`PENDING` 用上一則留言、其餘用審核意見」的規則。**刻意不是「只要狀態是 WAITING 就一律顯示面板」**:全新、從未被審核過的課程第一次處於 `WAITING` 時 `review_note` 是空字串,面板仍正確保持隱藏(`test_tutor_and_tutee_class_detail_hides_admin_review_panel_while_waiting` 這項既有測試驗證此行為未被破壞)。新增回歸測試 `test_review_note_still_visible_while_waiting_for_mutual_reconfirmation`,458 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 template 調整無 model/migration/service 變更。**2026-10-01 當天使用者再問「在哪裡顯示？」並追加「如果是通過/待補正也要接列出所有審核紀錄」,發現上述「保留單一欄位不清空」這個做法本質上有缺陷,已改用獨立的歷史表重新實作**:`ClassReview` 只有一組 `status`/`review_note`/`reviewed_by`/`reviewed_at` 欄位,每次重新審核都會整個覆蓋,就算刻意不清空也只能保留「最近一次」的意見——如果同一堂課被要求補正兩次以上,較早那幾次的意見會被後面的決定直接蓋掉,永久遺失,無法滿足「列出所有審核紀錄」。新增 `ClassReviewDecision` model(`review` FK 到 `ClassReview`、`status`、`note`、`reviewed_by`、`created_at`,`Meta.ordering=["-created_at"]`,migration `tutoring/0042_classreviewdecision.py`,純新增資料表無資料遷移,Django Admin 註冊為 `ReadOnlyAdminMixin`):`review_class_session()` 每次成功決定時,除了照常更新 `ClassReview` 本身,另外呼叫 `ClassReviewDecision.objects.create(...)` 寫入一筆不會被覆蓋的快照。**因為有了這張永久保留的歷史表,原本「刻意不清空 review_note」的 hack 已經沒有存在必要,予以撤回**:`submit_class_record()` 的重置邏輯與 `revert_class_review()` 都改回清空 `review_note`(連同 `reviewed_by`/`reviewed_at`),讓這個即時欄位重新代表單純的語意「目前是否有決定中的意見」,不再身兼兩種互相衝突的角色。畫面上「上一則留言」的資料來源全面改讀 `class_review.decisions.first()`(最新一筆歷史紀錄)而非 `class_review.review_note`:`tutoring/views.py::class_detail()` 新增 `class_review_history` context(admin 與 Tutor/Tutee 分支皆有);`accounts/views.py::dashboard()` 的 `class_reviews` queryset 新增 `prefetch_related("decisions")`,逐筆附加 `review.latest_decision`;三處模板(`admin_class_detail.html`、`templates/dashboard/index.html`、`templates/tutoring/class_detail.html`)的「上一則留言」顯示來源統一換成 `class_review_history.0.note`/`review.latest_decision.note`。`admin_class_detail.html` 另外新增一個不受目前狀態影響、永遠顯示的「審核紀錄 / Review history」區塊(`class_review_history` 非空才顯示),用既有的 `.incident-report-reply-list`/`.incident-report-reply-item` 樣式(與異常回報回覆列表共用同一組 CSS,不新增樣式)逐筆列出每一次決定的時間、決定人、狀態徽章與意見內容——這才是真正回答使用者「如果是通過/待補正也要接列出所有審核紀錄」的部分:即使課程最後通過了,先前被要求補正的歷次意見仍會完整列在這裡。新增 2 項回歸測試(`test_review_class_session_accumulates_full_decision_history` 驗證同一堂課多次補正後歷史表正確累積不覆蓋、`test_admin_class_detail_lists_full_review_history_regardless_of_current_status` 驗證頁面即使目前狀態是通過,仍完整列出之前的待補正紀錄),並重寫前一輪新增的 2 項測試斷言(`review_note` 改回預期清空為 `""`,改為額外驗證 `ClassReviewDecision` 歷史表內容)。460 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨。**2026-10-01 當天使用者接著問「所以通過不會列出所有審核紀錄嗎？」,發現 `ClassReviewDecision` 只從部署當下起才開始記錄,部署前就已經通過/未通過/待補正的既有課程完全沒有對應的歷史紀錄,導致「審核紀錄」區塊對這些舊資料整個不顯示——看起來就像功能對已通過的課程沒有作用,其實是沒有回填歷史造成的落差,已修正**:新增一次性資料遷移 `tutoring/migrations/0043_backfill_classreviewdecision_history.py`,為每一筆「目前狀態已是終局決定(APPROVED/REJECTED/REVISE)、但還沒有任何 `ClassReviewDecision`」的 `ClassReview` 補一筆快照(內容就是該筆目前僅有的那組 `status`/`review_note`/`reviewed_by`,`created_at` 額外用 `.update()` 覆寫成 `reviewed_at` 的原始時間,因為 `auto_now_add=True` 的欄位在 `.create()` 當下一律會被強制蓋成「現在」,只有事後用 `QuerySet.update()`——不經過 `pre_save()`——才能改回真正發生的時間)。**刻意跳過 `reviewed_by` 為空的紀錄**(即 `tutoring/migrations/0031` 那批「2026-09-10 規則變更時系統自動核准、不是真人審核」的 grandfathered 紀錄):`ClassReviewDecision.reviewed_by` 不可為空,這類本來就沒有對應的審核人員可以歸屬,不是遺漏,是跟 0031 本身的「這不是一次真正的人工審核」定位一致。回填的是「我們能確定的唯一一次決定」,不是憑空捏造更早、實際上不存在的歷程(例如一個只被核准過一次的課程,回填後歷史清單就是 1 筆,不會多出不存在的紀錄)。新增回歸測試 `test_backfill_classreviewdecision_history_migration`(直接 `importlib.import_module` 匯入遷移檔案的函式呼叫,驗證一般決定正確回填、grandfathered 紀錄正確跳過、重複執行不會產生重複紀錄),461 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨。**2026-10-01 當天使用者接著指出「有了審核紀錄，目前單一審核結果有點多餘…能不能把這兩個合併，需要管理員審核的時候，才把課程審核 Class review decision卡片放在最下方」,重新調整 `admin_class_detail.html` 版面**:原本 WAITING/已決定狀態各自還有一個獨立的「目前狀態」完成框(重複顯示跟審核紀錄清單同樣的 status/note/reviewed_by),與下方新加的「審核紀錄」清單資訊重疊。改為:①已決定狀態(APPROVED/REJECTED/REVISE)不再顯示獨立完成框,「撤回 / Revert」按鈕改附加在「審核紀錄」區塊的 `panel-heading` 右側(只在這三種狀態才顯示,`.panel-heading` 本來就是 `flex`+`space-between`,放第二個子元素就會自動靠右,不需要新樣式);②`WAITING` 狀態若還沒有任何歷史紀錄(真正第一次等待雙方確認,從未被審核過)才顯示簡單的「等待雙方確認」提示框,有歷史紀錄時直接看歷史清單(其中最新一筆就等於原本想顯示的「上一則留言」,不再重複);③`PENDING` 的「課程審核 Class review decision」決定表單**移到頁面最下方**,排在「審核紀錄」區塊之後(原本在最上面,現在只有真的「需要管理員審核」時才出現,且退到最後)。**保留一個邊界情況的 fallback**:部署前就已經決定、但因為沒有 `reviewed_by` 而被 `0043` 刻意跳過回填的 grandfathered 紀錄(極少數,目前正式站是 0 筆),歷史清單會是空的,這種情況改用原本的單一完成框顯示(含撤回按鈕),避免這類舊資料完全沒有任何內容可看。新增 2 項回歸測試(`test_admin_class_detail_moves_decision_form_below_review_history` 驗證「審核紀錄」確實出現在決定表單之前、`test_admin_class_detail_approved_review_has_no_duplicate_single_result_summary` 驗證已通過的課程不再有重複的 `.completion-box`),並更新 1 項既有測試的斷言(WAITING 狀態下 Admin 頁面改檢查「審核紀錄」而非「上一則留言」,因為該標籤現在只保留給 PENDING 決定表單、dashboard 清單與 Tutor/Tutee 面板使用)。463 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 template 調整無 model/migration/service 變更。**部署後用正式站唯一一筆真實 `PENDING` 課程(session 134)驗證時發現一個真實 bug並當場修正**:grandfathered fallback 分支原本的條件只檢查 `{% elif class_review %}`(「`class_review` 存在」),沒有限定在已決定狀態——`PENDING` 且還沒有任何歷史紀錄(其實是最常見的情況,每一筆課程剛進入 `PENDING` 時都是如此)也會誤判成立,多顯示一個不該出現的「目前狀態」完成框與「撤回 / Revert」按鈕(PENDING 根本沒有任何決定可以撤回)。已改用明確條件 `{% elif class_review.status == 'APPROVED' or class_review.status == 'REJECTED' or class_review.status == 'REVISE' %}`,並新增回歸測試 `test_admin_class_detail_pending_with_no_history_shows_no_stray_completion_box`,464 項測試全數通過(同一次執行中另外 2 項與本次改動完全無關的既有測試,因剛好在午夜 00:00–00:40 之間執行而受「補登判定以當天 23:59:59 為界」這條既有規則觸發而短暫失敗,屬已知的測試時間敏感性問題,非本次改動造成,詳見本機測試紀錄),`ruff`、`makemigrations --check --dry-run` 皆乾淨。**2026-10-02 當天使用者再提出兩項調整**:①「撤回功能放在每個審核意見卡片，就是可以針對單一建議撤回」——撤回對「目前這一筆決定」才有意義(`ClassReview` 本身只有單一一組現在狀態,不是每一筆歷史紀錄都各自可撤回成不同的過去狀態),原本掛在「審核紀錄」區塊標題旁、跟任何卡片都沒有視覺關聯的共用撤回按鈕,已改成只出現在歷史清單**最新一筆(第一張)卡片裡面**(`class_review_history` 依 `-created_at` 排序,`{% for %}` 迴圈用 `forloop.first` 判斷),讓撤回的對象在畫面上就是「這一張卡片」,不是整份清單共用的模糊動作;同一堂課被要求補正多次時,畫面上仍然**只會有一顆**撤回按鈕(因為只有最新一筆是「目前狀態」,較早的幾筆純粹是歷史記錄,沒有可撤回的即時狀態)。②「tutor/tutee介面都不能顯示是哪個admin審核的，可以放時間」——`templates/tutoring/class_detail.html`「管理員審核結果」區塊原本顯示 `{{ class_review.reviewed_by.bilingual_name }} · {{ class_review.reviewed_at|date:"Y-m-d H:i" }}`(審核人員姓名+時間),已拿掉姓名只留時間;**範圍僅限 Tutor/Tutee 自己的頁面**,Admin 自己的 `admin_class_detail.html`(審核紀錄清單逐筆列出 `entry.reviewed_by.bilingual_name`)不受影響,Admin 本來就需要知道是哪位同事審核過以便內部追蹤。新增回歸測試 `test_admin_class_detail_revert_button_attaches_only_to_latest_history_card`(驗證多次補正後畫面上仍只有 1 顆撤回按鈕且位置落在最新一筆卡片內)、`test_tutor_and_tutee_class_detail_hides_reviewer_name_but_shows_time`(驗證 Tutor/Tutee 看不到審核人員姓名或學號、但看得到時間;同一堂課用 Admin 帳號開啟同一頁面時仍看得到姓名,確認範圍只限 Tutor/Tutee)。466 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 template 調整無 model/migration/service 變更。**2026-10-02 當天使用者接著要求卡片內部版面微調「標籤放在右上角、撤回鍵放在靠右中間」**:原本狀態徽章與時間疊在同一行文字流裡、撤回按鈕另外排在卡片最下方,改為徽章與撤回按鈕各自用 `position: absolute` 疊在卡片右側(`.class-review-history-item`/`.class-review-history-badge`/`.class-review-history-revert`,新增於 `static/css/app.css`,沿用既有 `.incident-report-reply-item` 的邊框/底色/圓角,只新增版面定位規則不重新設計卡片本身樣式):徽章固定在卡片右上角(`top: 10px; right: 12px`),撤回按鈕固定在卡片右側垂直置中(`top: 50%; transform: translateY(-50%)`),兩者都不佔用文件流,卡片的 `padding-right` 依是否有撤回按鈕(只有最新一筆卡片有)分兩種寬度(`34px`/`112px`)保留足夠空間不讓文字跑到底下;有撤回按鈕的卡片另外設 `min-height: 54px`,避免審核意見留空、卡片內容很短時按鈕上下溢出卡片邊界。純 CSS/template 調整,`templates/base.html` 的 `app.css` cache-busting 版本已更新為 `20261002-review-history-card-layout`。**2026-10-02 當天使用者回報「兩個重疊了…標籤放在按鈕左邊好了」**:短卡片(審核意見留空或很短)時,徽章(`top: 10px`)跟撤回按鈕(`top: 50%`)這兩個各自獨立定位的元素距離太近,視覺上疊在一起。改為把徽章跟撤回表單都塞進同一個 `.class-review-history-actions`(`display: flex; align-items: center; gap: 8px`)容器,整組一起用單一的 `top: 50%; transform: translateY(-50%)` 定位在卡片右側垂直置中——徽章在 DOM 順序上排在表單前面,flex 預設 `row` 方向讓徽章自然顯示在按鈕左邊,不會再有兩個獨立元素互相重疊的問題。卡片的 `padding-right` 同步調整(無撤回按鈕時 `34px` 只需容納徽章,有撤回按鈕時 `128px` 容納徽章+間距+按鈕)。更新 1 項既有測試的斷言(`test_admin_class_detail_revert_button_attaches_only_to_latest_history_card`,原本假設「撤回按鈕排在卡片內容文字之後」的文件順序,因為 actions 容器搬到卡片最前面而不再成立,改用「卡片開始/下一張卡片開始」的 `<li>` 邊界切片比對,不依賴內部元素的相對順序),466 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨。`app.css` cache-busting 版本再次更新為 `20261002-review-history-actions-row`。**2026-10-02 當天使用者回報兩個問題並一併修正**:①「審核紀錄 Review history 整個卡片都貼到老師提交資料 Teacher submission的卡片了」——`.panel` 本身沒有 margin、`.admin-record-grid` 也沒有 margin-bottom,`admin_class_detail.html` 在提交資料卡片之後的四個審核相關區塊,原本只有 PENDING 決定表單那一個(靠既有的 `.admin-review-decision { margin-top: 18px }`)有間距,WAITING 與已決定(含歷史清單)這兩種狀態完全沒套用任何提供間距的 class,因此緊貼在上方的卡片上——這其實是這個頁面從很早以前就存在的既有落差,只是這次新增的「審核紀錄」清單剛好是最常被看到的狀態,才被注意到。修正:新增共用的 `.class-review-block { margin-top: 18px }`(取代原本名稱較不通用的 `.admin-review-decision`,該 class 原本只有這一條 margin-top 規則,內容搬過去後移除),四個區塊(歷史清單、WAITING 提示框、grandfathered fallback 完成框、PENDING 決定表單)全部套用這個共用 class。②「審核紀錄的標籤再往上移一點，跟撤回按鈕對齊」——查明原因是 `.status-badge` 的全站預設 `margin: 18px 0 8px`(上下不對稱,是設計給獨立使用情境)被帶進 `.class-review-history-actions` 這個 flex row 裡,`align-items: center` 實際置中的是「含 margin 的盒子」,18px(上)比 8px(下)多出的 10px 讓徽章視覺上比按鈕偏低;新增 `.class-review-history-actions .status-badge { margin: 0; }` 覆寫掉這個預設 margin,讓置中真正只看徽章本身的內容框。**過程中也修正了一個自己造成的 bug**:原本想用 Django `{# ... #}` 單行註解語法寫一段跨行的說明文字,但 Django 官方明確規定 `{# #}` 不支援跨行,導致整段註解文字(含「審核紀錄」字樣)被當成純文字原封不動輸出到 HTML 裡,連帶讓既有的 `test_admin_class_detail_pending_with_no_history_shows_no_stray_completion_box`(斷言 PENDING 無歷史時畫面不應出現「審核紀錄」字樣)失敗——已改用支援跨行、且會被伺服器端完全剝離不會進入回應內容的 `{% comment %}...{% endcomment %}` 標籤。新增回歸測試 `test_admin_class_detail_review_sections_have_spacing_class_regardless_of_status`(驗證 WAITING 與已決定狀態都套用了 `.class-review-block`),並補上一項既有 PENDING 測試的斷言(確認 `class="panel class-review-block admin-review-decision"` 同時存在)。467 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 CSS/template 調整無 model/migration/service 變更。`app.css` cache-busting 版本更新為 `20261002-review-history-spacing-fix`。**2026-10-02 當天使用者改要求調整 dashboard「課程審核」頁籤本身(五個狀態區塊的清單,不是上面一直在改的單一課程詳情頁)的卡片設計與分頁**:①「審核意見拿掉，因為都要點進課堂紀錄查看才會審核」——`templates/dashboard/index.html` 每一列原本在 `<a class="review-detail-link">` 裡夾帶一行 `{% if review.latest_decision.note %}...上一則留言/審核意見...{% endif %}` 預覽文字,已整段移除——不管清單上顯不顯示這段文字,管理員要做出真正的決定前都一定要點進詳情頁看簽到與課堂紀錄,預覽文字不會少點一次,純粹是清單上的雜訊。②「標籤都可以移到右邊，第一行是…四大類標籤，第二行才是…標籤」——狀態徽章(`<i class="status-badge...">`,等待管理員核准/通過/未通過/待補正/等待雙方確認)與課程分類標籤(`<b>`,一般課程/補簽到/補課堂紀錄/補簽到＋補課堂紀錄)原本並排塞在 `.review-row-badges` 裡、置於卡片最前面(文字內容的最左/最上方);已整組搬到卡片既有的 2 欄 grid(`.makeup-review-row { grid-template-columns: minmax(240px,1fr) minmax(320px,0.8fr) }`)右側欄位(本來就是決定表單/撤回按鈕所在的那一欄,新增 `.review-row-actions` 包住「徽章堆疊 + 既有的表單/狀態方塊」,讓右欄維持單一 grid item 不破壞既有 2 欄結構),`.review-row-badges` 改成 `flex-direction: column; align-items: flex-end;`(原本是橫向 `flex-wrap: wrap`)讓狀態徽章排第一行、課程分類排第二行,並靠右對齊;狀態徽章在新的 flex 直排容器裡一樣踩到 `.status-badge` 全站預設不對稱 margin 的同個坑(見上面同一天稍早的修正紀錄),已比照新增 `.review-row-badges .status-badge { margin: 0; }`。③「由於比數會越來越多，每個區塊只7筆就換第二頁」——`accounts/views.py::dashboard()` ADMIN 分支的 `class_review_sections` 改用 `Paginator(rows, 7)`,每個狀態各自獨立分頁(查詢參數依狀態命名,如 `pending_page`/`waiting_page`,比照既有 `roster_page`/`pairing_page` 慣例,翻某一區塊的頁不影響其他區塊),分頁 nav 沿用既有的 `.simple-pagination` 樣式(`aria-label` 帶入該區塊的中文標籤方便區分);`section.open` 的判斷從單純的 `is_open`(只有 PENDING 預設展開)改成 `is_open or page_param in request.GET`,確保使用者正在某個區塊翻頁時,重新整理後該區塊的 `<details>` 不會意外收合、翻到一半找不到結果。`pending_class_reviews`(側邊欄未讀數字徽章用,見 `templates/dashboard/index.html` 第 27 行)維持讀取完整未分頁的 PENDING 清單,不受分頁影響。新增回歸測試 `test_admin_dashboard_class_review_card_omits_note_preview_and_orders_badges_status_first`(驗證清單不再預覽審核意見、且徽章在 DOM 順序上狀態先於分類)、`test_admin_dashboard_class_review_section_paginates_at_seven_per_page`(建立 9 筆 PENDING,驗證第一頁顯示 7 筆有「下一頁」無「上一頁」、第二頁顯示 2 筆有「上一頁」無「下一頁」),並更新 2 項既有測試(`test_review_note_carries_over_as_previous_comment_until_next_decision`、`test_review_note_still_visible_while_waiting_for_mutual_reconfirmation`)裡斷言 dashboard 會顯示留言預覽的部分,改為斷言「清單上看得到這堂課但看不到留言內容」。469 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,無 model/migration 變更。`app.css` cache-busting 版本更新為 `20261002-class-review-list-redesign`。**2026-10-02 部署後使用者截圖回報真實 bug,是同一個坑踩了第二次**:`templates/dashboard/index.html` 這次改版新增的兩段說明文字又用了 Django 不支援跨行的 `{# ... #}` 單行註解語法(跟稍早在 `admin_class_detail.html` 犯過、已在 CLAUDE.md 記錄過的同一個錯誤),導致整段中文註解文字原封不動輸出到畫面最上方,把卡片撐得極高,使用者截圖可直接看到裸露的「{# 2026-10-02(使用者要求…」文字。已全部改用 `{% comment %}...{% endcomment %}` 標籤修正。**使用者同時指出標籤堆疊版面「整個卡片就橫著，這樣省高度」**:上一輪把狀態徽章與課程分類改成直排兩行,疊高了卡片;已改回橫向同一行、靠右對齊(`justify-content: flex-end` 取代 `flex-direction: column`),保留 `.status-badge` 預設不對稱 margin 的歸零修正(無論橫排或直排都需要,避免徽章跟文字基線沒對齊)。新增回歸測試 `test_admin_dashboard_class_review_cards_have_no_leaked_template_comments`,直接鎖住「渲染出的 HTML 不應包含 `{#` 或任何本該只存在原始碼裡的中文說明文字」,作為這類錯誤的安全網,避免未來又在其他檔案犯第三次。470 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 CSS/template 調整無 model/migration 變更。`app.css` cache-busting 版本更新為 `20261002-class-review-list-fix`。**2026-10-02 使用者指出上一輪只做了一半**:「都說審核欄位和三個按鈕可以拿掉了，不會在卡片外做審核」——先前「審核意見拿掉」只移除了列表裡的留言「預覽」文字,PENDING 列的審核意見輸入框與通過/待補正/未通過三顆按鈕、WAITING 列多餘的「目前狀態」方塊、已決定列的撤回按鈕全部還留著。這次徹底移除:`templates/dashboard/index.html` 每一列的 `{% if PENDING %}...{% elif WAITING %}...{% else %}...{% endif %}` 動作區塊整段刪除,清單從此只剩導覽用途(日期時間/雙方姓名/審核人員資訊 + 狀態徽章),所有決定一律要點進 `admin_class_detail.html` 才能做。CSS 同步調整:`.makeup-review-row` 的 2 欄 grid 原本右欄用 `minmax(320px, 0.8fr)` 是為了容納審核意見輸入框與三顆按鈕,現在右欄只剩 badges,新增只限定這個清單用的修飾類別規則 `.review-history-row { grid-template-columns: minmax(240px, 1fr) auto; align-items: center; }`(刻意不改動共用的 `.makeup-review-row` 基礎規則,因為同一個 class 也被課堂通報的 `.class-alert-row` 沿用、那邊仍然需要表單欄位,不能一起被改窄)。更新 2 項既有測試(`test_admin_can_revert_class_review_from_dashboard_and_class_detail` 移除對 dashboard 撤回按鈕的斷言、改為直接 POST 測後端行為;`test_admin_review_forms_show_three_decision_buttons` 重新命名為 `test_admin_class_detail_shows_three_decision_buttons` 並只保留針對 `admin_class_detail.html` 的斷言),新增 1 項回歸測試 `test_admin_dashboard_class_review_list_has_no_inline_actions`(分別建立 PENDING/WAITING/已決定三種情境的課程,確認清單上都不再出現審核意見輸入框、三顆決定按鈕、撤回按鈕或「目前狀態」文字,同時確認這三堂課仍正確列在清單裡只是沒有動作元件)。471 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 CSS/template 調整無 model/migration/service 變更。`app.css` cache-busting 版本更新為 `20261002-class-review-list-no-actions`。**2026-10-02 使用者再要求「審核意見的撤回就不用放在紀錄裡」**:`admin_class_detail.html`「審核紀錄」區塊裡的撤回按鈕(2026-10-01 的「撤回功能放在每個審核意見卡片」要求時移進最新一筆卡片的 `.class-review-history-actions`)改回放到區塊標題(`panel-heading`)旁,不再塞進歷史清單的卡片裡——「審核紀錄」是單純的歷史回顧,撤回是會改變目前狀態的動作,使用者認為兩者應該分開,動作元件不應該混進紀錄列表本身(呼應 2026-10-02 稍早同一天對 dashboard 課程審核清單提出的同一個原則「不會在卡片外做審核」的反向版本——這裡是「不要把動作元件做進紀錄卡片裡」)。卡片本身簡化回只剩一顆狀態徽章(`.class-review-history-actions` 現在只包一個 `<span class="status-badge">`,拿掉 `<form>`),對應移除已經沒有用途的 `.class-review-history-item.has-revert`(`padding-right: 128px`)CSS 規則與 `has-revert` 修飾類別——所有卡片現在一律用 `34px` 的右側留白(只需要容納徽章)。更新 1 項既有測試(`test_admin_class_detail_revert_button_attaches_only_to_latest_history_card` 重新命名為 `test_admin_class_detail_revert_button_in_heading_not_inside_history_cards`,斷言從「撤回按鈕要落在最新一筆卡片『裡面』」改為「要落在第一張卡片『之前』」)。471 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 CSS/template 調整無 model/migration/service 變更。`app.css` cache-busting 版本更新為 `20261002-revert-button-out-of-history`。**2026-10-02 使用者立刻推翻上一輪,澄清真正要的是兩件事**:「不是，每個紀錄都要放撤回按鈕。我是說審核建議送出了，撤回這一筆，就不要留紀錄」——①撤回按鈕要**回到每一筆歷史卡片裡**(不是只有最新一筆、也不是共用一顆放在標題旁);②更關鍵的是「撤回」這個動作本身的語意整個改變:從「把 `ClassReview` 即時狀態退回 `PENDING`,同時在 `ClassReviewDecision` 永久保留一筆『被撤回的決定』當歷史」(`revert_class_review(session_id, admin)`,session 層級操作),改成「直接把這一筆 `ClassReviewDecision` 整筆刪除,它就不該再出現在審核紀錄裡」(`delete_class_review_decision(decision_id, admin)`,per-decision 層級操作)。`tutoring/services.py`:移除 `revert_class_review()`,新增 `delete_class_review_decision(*, decision_id, admin)`——刪除指定的 `ClassReviewDecision` 前先判斷它是否為該 `ClassReview` 目前最新一筆(`review.decisions.order_by("-created_at").first()`);**只有撤回的剛好是目前這筆決定時**才把 `ClassReview` 退回 `PENDING`(`status`/`reviewed_by`/`review_note`/`reviewed_at` 全部清空),撤回一筆已經被後面決定蓋過去的舊紀錄(例如先補正、後來通過,這時撤回那筆「補正」)純粹只是從歷史清單移除,不影響目前已經通過的狀態;寫入 `AuditLog`(`CLASS_REVIEW_DECISION_DELETED`,取代 `CLASS_REVIEW_REVERTED`,metadata 多帶 `decision_status` 記錄被刪除的是哪一種結果)。`tutoring/views.py`:`review_class()` 移除 `action == "revert"` 分支(現在只處理 approve/revise/reject 三種決定);新增 `delete_class_review_decision_view(request, decision_pk)`(`tutoring:delete_class_review_decision` URL,`classes/review-decisions/<int:decision_pk>/delete/`),固定導回 `tutoring:class_detail`。`admin_class_detail.html`:「審核紀錄」區塊的 `panel-heading` 移除共用撤回表單;每一筆 `<li class="incident-report-reply-item class-review-history-item">` 卡片內的 `.class-review-history-actions` 重新加回各自的 `<form action="{% url 'tutoring:delete_class_review_decision' entry.pk %}">`(與徽章同一個 flex 容器,維持 2026-10-02 稍早已修好的置中對齊);對應 `static/css/app.css` 的 `.class-review-history-item` 把 `padding-right` 從 `34px`(2026-10-02 稍早「撤回搬到標題旁」那一輪縮小的值)重新放寬回 `128px`,因為每張卡片又都要同時容納徽章與按鈕。**grandfathered fallback 分支(部署前就已決定、因缺少 `reviewed_by` 被 `0043` 跳過回填的極少數舊資料,目前正式站 0 筆)的撤回按鈕予以移除、不重新接上**:這個分支沒有對應的 `ClassReviewDecision` 可以刪除,舊版 `action=revert` 的 session 層級撤回已經不存在,若這類資料真的被誤判需要訂正,比照 `HourAdjustment` 等既有慣例走 Django Admin 手動處理,不為這個趨近於零發生率的邊界情況另外保留一條撤回路徑。`tutoring/tests.py`:移除 `revert_class_review` import,改匯入 `delete_class_review_decision`;原本 5 項呼叫 `revert_class_review()`/斷言 `CLASS_REVIEW_REVERTED`/斷言「撤回按鈕在標題旁、不在卡片裡」的測試改寫或重新命名(`test_delete_class_review_decision_resets_approved_result_to_pending`、`test_delete_class_review_decision_on_superseded_entry_keeps_current_status`、`test_delete_class_review_decision_raises_for_unknown_decision_id`、`test_non_admin_cannot_delete_class_review_decision`、`test_admin_can_delete_class_review_decision_from_class_detail`、`test_delete_class_review_decision_from_revise_back_to_pending`、`test_admin_class_detail_every_history_card_has_its_own_revert_button`、`test_class_review_actions_write_audit_log`),新增一項驗證「撤回較舊的、已被蓋過的決定不影響目前已通過狀態」與一項「刪除不存在的 decision_id 會丟出 `ObjectDoesNotExist`」的回歸測試。472 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,無 model/migration 變更(`ClassReviewDecision` model 本身不變,只是刪除語意變了)。`app.css` cache-busting 版本更新為 `20261002-revert-button-per-history-card`。**2026-10-02 使用者回報 Admin 課程詳情頁頭圖兩個問題,一併修正**:①「CLASS REVIEW DETAILS 改成白色，不然顏色有點重疊」——`.section-kicker` 全站預設文字色是 `var(--blue)`(`#8c1d40`),跟 `.class-detail-hero` 這類深色頭圖漸層共用的 `--ocean-800`(同樣是 `#8c1d40`)完全相同,kicker 文字疊在漸層經過那個顏色的那一段時幾乎看不見——這其實是 2026-09-08「彩色頭圖區塊配色 regression」(見上方對應紀錄)當時沒修完整的同一個問題,`.profile-hero`/`.guide-hero` 那輪已經蓋過 `.section-kicker` 的顏色,但 `.class-detail-hero`(課程詳情頁,Admin 與 Tutor/Tutee 共用)/`.tutor-schedule-hero`(老師個人課表、Admin 行政檔案頁)漏掉了。使用者要求「檢查類似的問題」後,一併補上這兩處同樣缺漏的淺色覆寫(`color: var(--ocean-100)`,跟既有兩處用同一個值)。②「如果是待補正重新送審后，在審核中多一個標籤：已補正＋日期時間」——`tutoring/views.py::class_detail()` Admin 分支新增 `revise_resubmitted_at` 計算:`class_review_history`(依 `-created_at` 排序)第一筆若是 `REVISE`,但目前即時狀態已經不是 `REVISE`(代表課堂紀錄已經被改過、正在往下一輪走),就取雙方課堂紀錄裡發生在那筆「待補正」決定之後的最新一次 `updated_at` 當作補正時間;若撤回的剛好是這筆「待補正」決定本身(`delete_class_review_decision()`),該筆會直接從歷史表消失,不會誤判。`admin_class_detail.html` 頭圖的「審核中 / Under review」徽章後面,`revise_resubmitted_at` 非空時多顯示一個「已補正 / Resubmitted · YYYY-MM-DD HH:MM」徽章(新增 `.class-status.resubmitted`,沿用 `.class-status.scheduled` 既有的淺色配色,跟「審核中」的黃色警示色區隔)。新增 2 項回歸測試(`test_admin_class_detail_shows_resubmitted_badge_after_revise_record_edited_and_reconfirmed` 驗證完整補正→雙方重新確認→徽章正確顯示補正時間、`test_admin_class_detail_no_resubmitted_badge_without_a_revise_cycle` 驗證一般 PENDING 與目前仍卡在 REVISE 的課程都不會誤顯示)。474 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 CSS/template/view 調整無 model/migration/service 變更。`app.css` cache-busting 版本更新為 `20261002-hero-kicker-contrast-resubmitted-badge`。**2026-10-02 Admin dashboard 四個最常看到 tutor/tutee 姓名的清單,學號/姓名都改成可點擊連到該人的行政檔案(使用者要求「admin所有介面，只要出現tutor/tutee比較常出現的地方（口語能力審核、配對管理、解除配對、課程審核），點擊學號或姓名都可以查看該tutor/tutee檔案」)**:在此之前,`accounts:admin_user_profile`(行政檔案整合頁,見第 2 節)唯一的入口是 Django Admin 的學生名冊(`RosterEntry`)清單裡的「查看檔案」連結,Admin 在日常最常操作的這幾個 dashboard 頁籤裡看到姓名/學號時完全無法直接點過去,必須先手動去名冊搜尋。`templates/dashboard/index.html` 四處全部補上連結(URL 皆為 `{% url 'accounts:admin_user_profile' <user>.pk %}`,沿用現有全站預設 `a` 樣式,未新增 CSS class):①「口語能力審核」待審核與審核紀錄兩張表格的 `document.tutor`;②「配對管理」配對列表的 `pairing.tutor`/`pairing.tutee`,以及待回覆邀請列表的 `invitation.tutor`/`invitation.tutee`/`invitation.initiated_by`;③「解除配對審核」待處理申請與處理紀錄的 `release.pairing.tutor`/`release.pairing.tutee`/`release.requested_by`;④「課程審核」清單的 `review.session.pairing.tutor`/`review.session.pairing.tutee`。前三處的姓名/學號原本都是單純文字(不在任何錨點裡),直接包上 `<a>` 即可;**唯獨「課程審核」清單需要額外重構**,因為姓名原本直接寫在 `.review-detail-link` 這顆連到 `tutoring:class_detail` 課程詳情頁的大錨點裡面,HTML 不允許 `<a>` 巢狀 `<a>`——已把姓名移出大錨點,獨立成 `.review-row-participants`(新增,但沒有專屬樣式,直接吃現有 `.makeup-review-row > div { display:grid; gap:5px }` 與 `.makeup-review-row span { color: var(--ink-muted); font-size: 0.67rem }` 這兩條既有通用規則),大錨點本身(日期/審核人員/查看詳情箭頭)點擊行為完全不受影響。不受影響、刻意不處理的對象:`document.reviewed_by`/`release.reviewed_by`/`review.reviewed_by` 都是 Admin 本人,`admin_user_profile()` 明確限定 `role__in=[TUTOR, TUTEE]`,連過去會 404,所以這些維持純文字;「配對排除 / Matching exclusions」頁籤雖然也常顯示 tutor/tutee 姓名,但不在使用者這次明確點名的 4 個頁籤範圍內,這次沒有一併處理,之後如果也要加可參照同樣的做法。新增回歸測試 `accounts/tests.py::AdminDashboardProfileLinkTests`(涵蓋口語能力審核待審核/已審核、配對列表、待回覆邀請、解除配對待處理/已處理共 3 項測試)與 `tutoring/tests.py::ClassWorkflowTests::test_admin_dashboard_class_review_names_link_to_participant_profiles`(額外驗證課程詳情的大錨點與姓名連結同時存在、互不衝突)。478 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 template/測試調整,無 model/migration/service/CSS 變更。**2026-10-03 使用者追加「課堂紀錄/view details裡面那一頁也要」**:從課程審核清單點「查看簽到與課堂紀錄 / View details」進去的 `admin_class_detail.html`,頁首「老師 / Teacher」「學生 / Student」卡片(`.admin-participant-summary`)原本也是純文字姓名,補上同樣連到 `accounts:admin_user_profile` 的連結;這兩張卡片本身是單純的 `<div>`,不像課程審核清單那樣包在導向別處的大錨點裡,直接包 `<a>` 即可,不需要額外重構。新增回歸測試 `test_admin_class_detail_participant_summary_links_to_profiles`,479 項測試全數通過(測試執行時剛好跨過午夜,觸發一項與本次改動完全無關的既有時間敏感性測試短暫失敗——`test_class_record_form_hidden_until_class_ends_then_appears` 用真實相對時間建立課程,00:00–00:40 之間執行會讓「已結束的課程」反而被判定為跨過當天 23:59:59 補登期限,這是已知的既有問題,非本次改動造成),`ruff`、`makemigrations --check --dry-run` 皆乾淨,純 template/測試調整。**2026-10-03 使用者立刻回報「學號換行，不用超連結，這樣比較好看」,修正剛部署的版面**:`.admin-participant-summary > div` 原本是 `display: grid`,`span`/`strong`/`small` 三個直屬子元素各自是獨立一個 grid row,姓名跟學號天然分成兩行——上一輪把 `<strong>` 姓名與 `<small>` 學號一起包進 `<a>` 之後,兩者變成同一個行內錨點底下的子元素,不再是 `.admin-participant-summary > div` 的直屬子元素,不會各自成行,姓名跟學號擠成同一行;學號也因此被誤納入可點擊範圍(使用者這裡明確只要姓名可點,學號維持純文字)。修正:只把 `<strong>` 姓名包進 `<a>`,`<small>` 學號移出錨點、恢復成跟 `<a>` 同層的直屬子元素(`<div><span>...</span><a><strong>姓名</strong></a><small>學號</small></div>`),重新變回 3 個 grid row,視覺跟改動前一致,差別只在姓名多了可點擊的底線/顏色。**此次調整範圍只限定在 `admin_class_detail.html` 的老師/學生卡片**:`templates/dashboard/index.html` 那四個清單(口語能力審核、配對管理、解除配對審核、課程審核)當初就是使用者明確要求「學號或姓名都可以點」,姓名+學號本來就設計成一起可點擊,且那幾處大多在 `<td>` 裡(靠全站既有的 `td strong, td small { display: block }` 規則各自成行,不像這裡的 `<div>` 版面需要自己的 grid)或本來就只顯示姓名沒有學號,不受這次調整影響,不要混為一談。既有回歸測試斷言的是連結网址字串是否存在於渲染內容,不檢查學號是否包在錨點內,調整後仍全數通過,未新增測試。純 template 調整,無 model/migration/service/CSS/測試變更。**2026-10-03 使用者接著回報「不想要學號有底線，學號就不要放連結」**:`templates/dashboard/index.html` 那四個清單裡,口語能力審核(待審核+審核紀錄表格)、配對管理(配對列表+待回覆邀請)這三處原本仍是姓名跟學號一起包進 `<a>`(一百一十八那次「學號或姓名都可以點」的原始做法),學號因此也套用全站預設 `a` 的底線樣式。比照 `admin_class_detail.html` 已經做過的同一種修正,把 `<small>` 學號移出錨點、變回跟 `<a>` 同層的 `<td>` 直屬子元素(靠既有的 `td strong, td small { display: block }` 規則維持各自成行),只有姓名維持可點擊。解除配對審核、課程審核這兩處本來就只顯示姓名沒有學號,不受影響。既有測試不檢查學號是否包在錨點內,調整後仍全數通過(482 項),未新增測試,純 template 調整。
- 「已排時數 / Reserved」與「有效時數 / Verified」是不同概念,不可混用。
- **2026-10-01 修正真實 bug:雙方已確認、審核已是 `PENDING` 之後,任一方又修改自己的課堂紀錄,`ClassReview` 沒有正確退回 `WAITING`**(使用者回報「9/23 唐子雯 x 朴敍亨，tutee放未確認，為什麼會放在等待管理員核准的區塊」)。`tutoring/services.py::submit_class_record()` 本來就會在編輯自己的紀錄時刪除「對方針對這份紀錄的舊確認」(`ClassConfirmation.objects.filter(session=session, subject=author).delete()`),但**只有當 `ClassReview.status` 已經是 `APPROVED`/`REJECTED` 時才會把狀態退回 `WAITING`**,漏掉了「審核還停留在 `PENDING`(雙方都確認過、但 Admin 還沒審)這個中間狀態」——刪除掉的那筆確認讓確認筆數從 2 掉回 1,但沒有人呼叫 `_sync_class_review()` 重新依現有確認筆數計算狀態,導致畫面卡在「等待管理員核准」,跟另一方實際上已經不算確認互相矛盾。修法:在 `submit_class_record()` 刪除舊確認之後,無條件呼叫 `_sync_class_review(session)`(與 `confirm_counterpart()` 既有呼叫方式一致),讓審核狀態永遠跟目前真正的確認筆數同步。新增回歸測試 `tutoring/tests.py::ClassWorkflowTests::test_editing_own_record_after_both_confirmed_resets_pending_review_to_waiting`(先確認移除修法後測試真的會失敗,排除誤判)。**此修法本身不溯及既往,只影響修復後才發生的「編輯已確認紀錄」事件**;已受影響的既有資料(查到的這筆 session 129)已用一次性唯讀腳本核對後,對所有目前狀態為 `PENDING` 的 `ClassReview` 重新呼叫 `_sync_class_review()` 做一次性修正(邏輯是現有函式本身,不是另外寫規則,真正已符合 2 筆確認的 `PENDING` 不受影響)。
- **2026-10-01 修正另一個真實 bug:Admin 課程詳情頁「確認結果」秀在錯的一邊卡片上**(使用者回報「晏祥徵 x 譚小珍，為什麼tutee沒有填寫課堂紀錄，tutor還可以確認無誤」)。`tutoring/views.py::class_detail()` 的 Admin 分支原本用 `reviewer_id` 篩選 `tutor_confirmation`/`tutee_confirmation`,等於把「這個人審核對方的那筆確認」秀在「這個人自己提交資料」的卡片上(`admin_record_card.html` 的 `heading="老師提交資料"`/`"學生提交資料"`),跟實際語意完全顛倒——應該顯示的是「這個人的提交內容有沒有被對方確認」,必須改用 `ClassConfirmation.subject_id`(被確認的對象,不是審核者)篩選才對得起來。此例中 Tutee 完成簽到但沒有送出課堂紀錄、Tutor 已送出課堂紀錄且被 Tutee 確認無誤——修法前「確認無誤」錯誤顯示在「學生提交資料」卡片(該卡片本該顯示「尚未確認」,因為根本沒有人確認過 Tutee 不存在的紀錄),「老師提交資料」卡片反而顯示「尚未確認」。**這純粹是 Admin 這個唯讀頁面的顯示 bug,不影響 `ClassReview`/`class_is_valid()` 的有效時數計算**(那兩處都直接讀整個 `confirmations` queryset,不經過這兩個被寫錯的 context 變數),所以這次不需要額外的一次性資料修正。新增回歸測試 `tutoring/tests.py::ClassWorkflowTests::test_admin_class_detail_confirmation_shows_under_the_confirmed_persons_own_card`(先確認移除修法後測試真的會失敗,重現的錯誤訊息與使用者回報的現象完全一致)。

### 4.7 課堂通報與異常回報

課堂通報(`ClassAlert`)與異常回報(`IncidentReport`)是兩套獨立機制,定位不同,不要混用或合併:

**課堂通報**(即時、上課中的緊急通報):

- 只在該課程實際開始至結束之間開放,不提前開放。
- 原因:聯絡不到對方、對方未出席、時間/地點問題、其他緊急狀況;OTHER 必填說明。
- 同一通報者對同一堂課只能有一筆 active alert。
- Admin 可標記為已紀錄(內部狀態值仍是 `RESOLVED`,`resolve_class_alert`)並留備註;已紀錄與通報者自行取消(`CANCELLED`)都是終點狀態,已紀錄後不能再取消,已取消後也不能再標記已紀錄。
- 用詞刻意選「已紀錄」而非「已處理」:很多通報(尤其人身安全等)系辦不一定能真的解決,Admin 這個動作只代表「已知悉並留存記錄,後續再討論」,不代表問題已解決。
- Admin dashboard「課堂通報」頁籤有 PENDING 待處理 + HISTORY 已紀錄兩區塊,紀錄含紀錄人、紀錄時間、備註。
- **2026-09-12 起通報者本人也看得到管理員標記已紀錄時留的備註(使用者要求,比照異常回報既有的做法)**:先前 `tutoring/views.py::class_detail()` 的 `own_alert` 只查 `status=ACTIVE`,一旦 Admin 標記已紀錄,這筆通報就從課程詳情頁完全消失,通報者看不到「已被處理」這件事,更看不到備註。已新增 `own_resolved_alerts`(查 `status=RESOLVED`,依 `resolved_at` 倒序),`templates/tutoring/class_detail.html` 在原本的通報表單/取消按鈕區塊下方,用 `.completion-box`(沿用簽到完成既有的綠色完成樣式)逐筆列出已紀錄的通報與管理員備註(`resolution_note`)。已取消(`CANCELLED`)的通報不顯示,因為是通報者自己取消,本人已經知情。

**異常回報**(事後、可分類的回報,`tutoring/services.py` 的 `submit_incident_report`/`resolve_incident_report`):

- 分類:學生缺席、老師缺席、場地問題、學習進度問題、人身安全、系統問題、其他(`IncidentReportCategory`;「系統問題」為 2026-09-11 新增,使用者要求)。
- 不限上課時段,Tutor/Tutee 任何時候都能送出回報,可送出多筆。
- **2026-09-11 起 `IncidentReport` 完全不綁定課程**(使用者要求:「課程整個拿掉,因為每堂課有自己的通報,跟當堂課有關就用課程通報,其餘的用異常通報就好」):`session` 欄位已從 model 完全移除(`tutoring/migrations/0036_remove_incidentreport_session_and_more`,同一個 migration 也加了「系統問題」分類),不是先改成選填後保留欄位——與當堂課有關的問題請改用該堂課自己的 `ClassAlert`(課堂通報),異常回報保留給其餘所有情境,兩者定位從此完全不重疊,不再有中間地帶。`submit_incident_report(reporter, category, content)` 不再接受任何 `session_id` 參數;`StandaloneIncidentReportForm` 只剩 `category`/`content` 兩個欄位,不再有課程下拉選單;`accounts/views.py::admin_user_profile()` 的「異常回報紀錄」區塊也因此改成只依「這位使用者自己送出過的回報」(`reporter=subject`)呈現,不再能靠課程/配對反查「此人所屬課程的回報」。
- 通報者送出後不能自行撤回,只有 Admin 能標記為已紀錄(內部狀態值仍是 `RESOLVED`)並留備註,同樣是「已知悉留存」而非「已解決」的語意。
- 無附件上傳。
- Admin dashboard「異常回報」頁籤有 PENDING 待處理 + HISTORY 已紀錄兩區塊,紀錄含紀錄人、紀錄時間、備註;因為不再綁定課程,清單改顯示送出時間(`created_at`)。**2026-09-25 兩區塊的「通報者 / Reporter」皆補上學號**(使用者要求「比較方便查找」),比照配對排除等既有列表的「姓名+`<small>`學號」呈現方式。**HISTORY 表格另新增可展開的「細節 / Details」**(`<details class="incident-report-detail">`,純 CSS,無 JS):表格本身只列分類/備註/紀錄人等欄位摘要,不逐字顯示通報內容以免欄位過寬,點開才顯示 `report.content` 全文;PENDING 區塊維持原樣,內容原本就已經直接顯示在卡片上,不需要這層收合。**2026-09-25 使用者接著要求版面微調**:「細節」原本塞在「通報者」欄位裡,改成獨立一整列(`<tr class="incident-report-detail-row"><td colspan="7">`,緊接在該筆資料列下方,`padding-top: 0` 讓視覺上依附於上一列),不再受限於單一欄位寬度;「通報者 / Reporter」欄位加寬(`.col-reporter`,`width: 22%`);「紀錄時間 / Logged at」欄位改成日期與時間分兩行(`<time>...</time><br><small>...</small>`),搭配既有的 `.col-nowrap`(`width: 1%`)讓該欄縮到最窄。
- **2026-09-10 起 Tutor/Tutee 端改為獨立頁籤送出,不再綁在單一課程頁面**(2026-09-11 起連課程下拉選單也一併拿掉,見上):新增 `tutoring/forms.py::StandaloneIncidentReportForm`,對應的 `tutoring/views.py::incident_report()` 無 `pk` 參數(URL 為 `matching/incident-reports/submit/`),送出後一律導回 Dashboard 的「異常回報」頁籤。舊的 `IncidentReportForm`(靠 URL 綁課程)已完全移除,沒有保留相容路徑。Tutor/Tutee dashboard 共用區塊 `templates/dashboard/participant_v2_panels.html` 含送出表單與「我送出的回報」歷史清單;`class_detail.html` 不再顯示異常回報區塊(課堂通報 `ClassAlert` 維持原樣不受影響,仍綁在課程詳情頁,因為它本來就是有時間窗限制、上課中才用得到的功能)。**2026-10-01「我送出的回報」卡片改版(使用者要求)**:狀態改成右上角的彩色徽章(沿用既有 `.status-badge`/`.status-approved`/`.status-rejected` 樣式,不是新樣式)——已紀錄為綠色「已紀錄 / Logged」,尚未紀錄為紅色「尚未紀錄 / Not yet logged」(措辭從「待處理 / Pending」改成「尚未紀錄」,呼應 Admin 端「已紀錄」的既有用詞,兩者對稱)。自己送出的內容與管理員的回覆明顯區分:管理員回覆(`resolution_note`)改放進獨立的綠色提示框(`.incident-report-admin-note`,沿用 `.completion-box` 同一組色票 `#b9dfca`/`#edf8f2` 但獨立成自己的 class,因為 `.completion-box` 的文字樣式是給簡短狀態文字用、字級太小不適合完整的回覆內容),不再跟自己的回報內容擠在同一段 `<p>` 前面加「紀錄備註 / Note：」。**2026-10-01 新增「回覆 / Reply」功能,讓一則回報可以持續延伸(使用者要求並確認範圍)**:新增 `tutoring.models.IncidentReportReply`(`report` FK + `content` + `created_at`)。**刻意設計成單向、只有通報者能用**,不是通報者與管理員都能回覆的雙向對話串(已與使用者確認)——因此這個 model 沒有 `author` 欄位,回覆者永遠是 `report.reporter`;管理員仍只透過既有的 `resolve_incident_report()`/`resolution_note` 回應,不另外做管理員回覆介面。`tutoring/services.py::add_incident_report_reply(report_id, reporter, content)` 檢查只有原通報者可以在自己的回報下追加(否則 `ValidationError`);**若這則回報先前已標記「已紀錄」,追加回覆會自動把狀態改回「尚未紀錄」提醒管理員有新內容(使用者確認採用)**,但 `resolution_note`/`resolved_by`/`resolved_at` 刻意保留不清空,讓管理員在重新看到這筆待處理回報時仍看得到先前的處理紀錄(畫面上以「先前紀錄 / Previous note」斜體呈現,與新的回覆內容區隔)。`tutoring:add_incident_report_reply` 視圖比照 `resolve_incident_report_view()` 的既有寫法(`request.POST.get("content", "")` 直接交給 service 驗證,不另外寫 Form class)。Admin 端的待處理卡片與已紀錄表格的「細節」收合區塊都會顯示完整的回覆列表(`report.replies.all`),`dashboard()` 的三個相關 queryset 皆加上 `.prefetch_related("replies")` 避免 N+1。對應 migration:`tutoring/migrations/0039_incidentreportreply.py`。**2026-10-01 Admin 與 Tutor/Tutee 的每一筆回報都改成可收合的卡片(使用者要求:「有些回覆只會越來越長」)**:比照既有 `.semester-hours-card` 的 `<details>`+圓形箭頭圖示慣例(`summary`/`summary::-webkit-details-marker`/`[open]` 旋轉箭頭),新增共用的 `.incident-report-card` 類別——Tutor/Tutee 端整張卡片(原本的 `.profile-note-box` 樣式改為這個新樣式)、Admin 待處理清單的每一筆都改成 `<details>`,只有清單中最新一筆(`forloop.first`,兩處查詢皆沿用 model 預設的 `-created_at` 排序)預設展開,其餘預設收合。Admin 端原本的 `.makeup-review-row` 版面(內容/表單左右兩欄)保留不變,只是整個移到 `<details>` 的展開區塊裡,並拿掉自己的邊框(`.incident-report-card .makeup-review-row { border: none; }`)避免跟外層卡片邊框重疊。HISTORY 表格的「細節」原本就已經是收合式,不受影響、不需要調整。**2026-10-03 側邊欄新增未讀數字提示(使用者提問「如果admin審核/紀錄的資料，tutor/tutee左側欄位對應的功能會有提示嗎？」後要求補上)**:在此之前,Tutor/Tutee 側邊欄只有「公告欄」「邀請管理」「私訊」三處會顯示未讀數字,Admin 核准/拒絕口語能力證明、課程審核結果、課堂通報/異常回報標記已紀錄之後,對應的側邊欄項目完全不會冒出任何提示,要自己點進去才會發現狀態變了。比照公告欄既有的「記錄上次查看時間、比對這段期間有沒有新變動」機制,新增 `accounts.models.DashboardSection`(TextChoices:`QUALIFICATION`/`HOURS`/`INCIDENT_REPORTS`,刻意只先涵蓋使用者這次明確點名的三類,解除配對結果已經有 `release_notices.html` 首頁橫幅提示,不在這次範圍內)與 `DashboardReadState`(`user` FK + `section` + `last_viewed_at`,`unique_together`;跟 `AnnouncementReadState` 的差異是一個使用者要分別追蹤三個分類,不是像公告欄那樣每人只有一筆)。`accounts/views.py::dashboard()` 計算三個數字:①`qualification_unread_count`(僅 Tutor;`QualificationDocument.reviewed_at` 晚於上次查看時間就是 1,否則 0,因為一位 Tutor 只有一筆文件);②`hours_unread_count`(Tutor/Tutee 皆有;`ClassReviewDecision`(不是即時的 `ClassReview.reviewed_at`,因為那個欄位會在 REVISE 補正週期中被清空/覆寫,重算一次「待補正」決定早就看過的舊紀錄會被誤判成新的)裡屬於此人配對、且 `created_at` 晚於上次查看時間的筆數,加上此人通報(`reporter=此人`)且已標記 `RESOLVED`、`resolved_at` 晚於上次查看時間的 `ClassAlert` 筆數——兩者合計掛在「輔導時數/輔導紀錄」(`#hours`)這個側邊欄項目,因為課堂通報沒有自己專屬的分頁,已紀錄狀態本來就顯示在課程詳情頁,跟課程審核結果同一個瀏覽入口;③`incident_reports_unread_count`(Tutor/Tutee 皆有;此人通報且已標記 `RESOLVED`、`resolved_at` 晚於上次查看時間的 `IncidentReport` 筆數)。新增 `accounts:mark_dashboard_section_read`(POST,`<str:section>` 路徑參數,未知 section 回 404)取代原本「每個分類各寫一份 mark_xxx_read view」的做法,一個 view 处理三個分類。`static/js/dashboard.js` 原本寫死只認「公告欄」的 `markAnnouncementsRead()` 已經改成通用的 `markSectionRead(target)`:任何側邊欄連結只要帶 `data-mark-read-url` 屬性,切到該分頁時都會觸發同樣的「POST 通知後端、立刻移除 `<em>` 徽章」流程——`mark_announcements_read` 本身(對應的 `AnnouncementReadState` model)完全沒有改動,新機制只是多認得這一個既有端點,新舊兩套並存,不是互相取代。新增回歸測試 `accounts/tests.py::DashboardSectionNotificationTests`(9 項,涵蓋三個分類各自的未讀/已讀切換、`ClassAlert`/`IncidentReport`/`ClassReviewDecision` 來源、未知 section 404、側邊欄徽章渲染),491 項測試全數通過,`ruff`、`makemigrations --check --dry-run` 皆乾淨,新增 migration `accounts/0024_dashboardreadstate.py`(純新增資料表,無資料遷移)。

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
- 下載區「選擇資料範圍」卡片新增「證明語言」單選(`HoursDownloadForm.language`,`zh`/`en`,預設中文),`build_hours_pdf()` 依此參數只呈現**單一語言**的標題、內文、表格表頭與日期格式(中文用民國紀年、英文用西元 `February 19, 2026` 格式),不會像 2026-08 前的舊版同時把中英文疊在同一張證明上;標題單行置中(y=623)。缺少所選語言文案(見下方 `PartnerProgram` 英文欄位)時擋下並顯示「請洽系辦設定」錯誤,不產生中英夾雜或壞掉的 PDF。姓名顯示是唯一不受證明語言影響的例外:兩個姓名都有一律顯示「中文姓名 / English Name」,只有一個就只顯示該一個且不留斜線(`display_name_markup()`),NTNU Tutor 特例分支也套用同一規則。檔名與 `AuditLog` metadata 都會記錄所選語言。
  - 實作這條規則時踩過一個 ReportLab 陷阱:Paragraph markup 的 `<b>` 標籤是透過該段落**預設字型**的 `registerFontFamily()` 對應表找粗體字型,不是「維持原字型只是加粗」。若英文證明段落中的中文姓名只包在 `<b>...</b>` 裡,會被解析成不含中文字符的西文字型,導致中文字符消失。因此姓名與任何「中西文混排且需要粗體」的文字一律要用明確的 `<font name="CertificateLiSong-Bold">`/`<font name="CertificateHelveticaNeue-Bold">` 分別包住中/英文片段,不能依賴 `<b>` 自動解析。
- Tutor 版證明底圖與英文文案:`PartnerProgram` 除既有中文的 `tutee_certificate_plan_name`/`tutee_certificate_activity_text`(及 Tutor 版對應欄位,皆隱含中文,未改名加 `_zh` 後綴以降低遷移風險)外,另有 `tutee_certificate_plan_name_en`/`tutee_certificate_activity_text_en`/`tutor_certificate_plan_name_en`/`tutor_certificate_activity_text_en` 四個英文對應欄位,新增合作計畫時中英文案都要填,只填中文會導致該計畫無法產生英文證明。
- PDF 底圖:`tutoring/resources/certificate_templates/`;字型:`assets/fonts/`;模板檔名、計畫名稱、活動描述文字皆從對應 `PartnerProgram` 欄位讀取,不再寫死於程式碼。
- 若某計畫缺少對應角色(Tutor/Tutee)的證明模板檔名,下載時會擋下並顯示錯誤,而非產生壞掉的 PDF(`build_hours_pdf()` 開頭檢查)。同一道檢查也涵蓋標題與內文文案本身:`build_hours_pdf()` 會依「是否為 `is_ntnu_tutor` 特例分支」精準比對驗證欄位與實際渲染欄位——`is_ntnu_tutor` 分支的內文完全寫死、從不讀取 `plan_name`/`activity_text`,因此只驗證所選語言的標題;其餘一般分支(Tutee 版與非 NTNU 的 Tutor 版)實際內文會套用 `plan_name`/`activity_text`,因此標題、`plan_name`、`activity_text` 三者在所選語言下都必須非空,任一缺漏都擋下並顯示「請洽系辦設定」,不會產生內文帶著空白子句(如中文版「「」」)的證明。**兩者不可對調**:曾經的實作錯誤是不論分支一律要求英文 `plan_name_en`/`activity_text_en` 非空、卻完全不驗證中文 `plan_name`/`activity_text`——這會讓「有標題但漏填內文」在中文證明上悄悄產生空白子句,同時讓 `is_ntnu_tutor` 分支被英文欄位擋下時其實那兩個欄位根本不會被用到。
- 電子章、主管簽名與系辦最終正式模板**尚未實作,也刻意不得自行產生或偽造**:目前所有證明都只有 ReportLab 疊字文字與部門提供的底圖浮水印,沒有任何簽名/印章圖層或機制。待系辦提供正式資產後才應評估是否新增;在那之前不應假造或用純文字模擬簽名/印章的視覺效果。
- PDF 產製位於 `tutoring/reporting.py`,使用 ReportLab 疊字後以 pypdf 合併底圖。
- **2026-08 起所有本模組產生的 PDF(時數證明與 Admin 匯出 PDF)都套用「盡力防護」的複製/選取限制**(`docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 3 項,`reporting._restrict_copy_and_selection()`,`build_hours_pdf()`/`build_export_pdf()` 回傳前都會呼叫):用 `pypdf.PdfWriter.encrypt()` 只授予 `PRINT`/`PRINT_TO_REPRESENTATION` 權限(禁止 `EXTRACT`/`MODIFY` 等其餘權限),`user_password=""` 代表**不需要密碼即可開啟**,`owner_password` 是每次產生時隨機產生、用完即丟(系統不需要也不會再解除限制)。**這是純粹依賴 PDF 閱讀器配合的權限旗標,不是真正的 DRM**:無法阻止螢幕截圖、OCR、重新輸入或使用忽略權限旗標的工具開啟,對外文案與說明不得宣稱為絕對防拷貝。刻意不指定 `algorithm=`(維持 pypdf 預設的 RC4-128),因為這裡的目的是「相容性優先的權限限制」而非「機密性」,比起 AES-256 在少數舊版閱讀器上有更廣泛的支援度。
- 下載區同時提供「預覽」與「下載」兩個按鈕,共用同一份表單與驗證邏輯,靠 submit button 的 `name="intent"`(`preview`/`download`)區分:預覽回應 `Content-Disposition: inline` 並用 `formtarget="_blank"` 開新分頁,由瀏覽器內建 PDF 檢視器顯示;下載回應 `attachment`,強制下載。
- Admin 匯出(`tutoring:export_excel`)是五步流程:①必選 `PartnerProgram`;②選該計畫的全部 Tutor、全部 Tutee 或單一符合計畫資格的使用者;③選該計畫專屬/舊版共用學期,或自訂日期;④選欄位;⑤選格式。後端會再次驗證使用者與學期都屬於所選計畫,`_export_rows(program=...)` 也依 `pairing__tutee__roster_entry__program` 過濾課程,避免跨計畫 Tutor 的其他課程混入。三種格式為:`.xlsx`(`build_excel_xlsx()`,用 `openpyxl`,UI 預設勾選)、`.csv`(`build_export_csv()`,標準庫 `csv`,寫入 UTF-8 BOM)、`.pdf`(`build_export_pdf()`,ReportLab 橫向 A4 自動分頁)。三種格式共用欄位與 `_export_rows()`,選用計畫、對象、期間、欄位及格式都寫進 `ADMIN_EXCEL_EXPORTED` AuditLog metadata。
- 所有下載與匯出都寫入 `AuditLog`;預覽寫入 `HOURS_PDF_PREVIEWED`,下載寫入 `HOURS_PDF_DOWNLOADED`,事件分開方便區分「看過」與「實際下載」。
- `tutoring.models.HourAdjustment`(行政更正紀錄,2026-08 前文案稱「時數調整紀錄」)用於補登系統紀錄以外的時數或更正資料,比照舊版概念但**刻意不沿用舊版建立無 Tutee 假課程的作法**——沒有假 `ClassSession`/`Pairing`,是獨立 model:使用者、學期、合作計畫、時數、原因、建立者(Admin)、時間戳記。設計上的關鍵限制(已與使用者確認):
  - **只能為正數**,只能加不能扣;若某筆時數算錯需要往下修正,必須用其他方式處理(例如取消對應課程),不透過這個功能扣時數。
  - **只影響證明 PDF 的「總時數」,不會在明細版逐筆列出**(`hour_report_data()` 把 `session_total` 與 `adjustment_total`分開算,加總後才是 `total`;`build_hours_pdf()` 只讀 `total`,明細列表 `sections`/`rows` 完全不受影響)。逐筆調整紀錄只在 Admin 內部彙整頁(`accounts:admin_user_profile`)可見,標明「僅內部稽核可見」。
  - 計入哪一次下載的判斷是「該筆調整的學期整個落在下載的日期範圍內」(`reporting.hour_adjustment_total()`,`semester.starts_on/ends_on` 需完全落在 `starts_on/ends_on` 區間),不是用調整紀錄本身的日期(它沒有日期,只有學期)。
  - Tutor 選特定合作計畫下載時,只會算該計畫的調整紀錄(`program` 外鍵);`tutor_available_programs()` 也一併更新,讓「只有調整紀錄、資料庫裡完全沒有真實課程」的計畫仍會出現在 Tutor 的下拉選單,避免補登的舊資料反而無法被看到或下載。
  - 建立/管理都**留在 Django Admin 裡**(`tutoring/admin.py::HourAdjustmentAdmin`),只能單筆新增/修改,沒有另外開一個獨立於 Django Admin 之外的自訂前台頁面,符合這個功能低頻率使用的定位;新增/修改時會寫入 `AuditLog`(`HOUR_ADJUSTMENT_CREATED`/`HOUR_ADJUSTMENT_UPDATED`)。model `clean()` 擋下時數 ≤ 0 與非 Tutor/Tutee 對象兩種情況,Django Admin 送出表單時會自動觸發。
  - **2026-08 已移除批次 Excel 匯入入口**(原「匯入 Excel / Import from Excel」連結、`import_hour_adjustments()`、`HourImportForm` 及對應測試已刪除,見 `docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 19 項):系辦決議不將系統上線前的舊紙本時數批次匯入新系統,此功能保留給未來 Admin 更正系統上線後的錯誤資料,不再用於補登舊紙本時數。model、migration 與既有資料未受影響。

### 4.10 上課文件

`tutoring.models.ClassDocument`(2026-08 新增,見 `docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 5 項):Admin 依合作計畫(必填)、適用學期(選填,留空代表適用該計畫所有學期)上傳課程文件,至少保存中文標題、英文標題、檔案、是否啟用、上傳時間、上傳者。

- **顯示對象完全由資料驅動,不寫死計畫代碼**:`PartnerProgram.class_documents_enabled`(布林,預設 `False`)決定該計畫是否開放此功能;migration `accounts/0014` 目前只把 `MARYLAND` 設為 `True`,符合會議紀錄「第一階段顯示對象:馬里蘭 Tutee、馬里蘭課程名單中的大學部 Tutor」的範圍。之後若系辦決定讓 NTNU 或新計畫也使用這個功能,只需要在 Django Admin 把該計畫的這個欄位打開,不需要改程式。
- **可見範圍與「可配對範圍」共用同一套判斷,不重新發明一套規則**:`tutoring/services.py::visible_class_document_programs(user)` 對 Tutee 直接看 `user_program(user)`(其唯一所屬計畫);對 Tutor 則對每個已開放此功能的計畫呼叫既有的 `tutor_can_serve_program(tutor, program)`(第 4 項的同一個函式,含馬里蘭限定大學部的規則),確保「看得到上課文件」與「配得到該計畫學生」的資格判斷永遠一致、不會分岔。`visible_class_documents(user)` 在此之上再過濾 `is_active=True`。
- 使用者選單(`templates/components/app_header.html`)新增「上課文件 / Class documents」項目,只在 `class_documents_visible` 為真時顯示;此變數由新增的 `accounts/context_processors.py::class_documents_menu()` context processor(已加進 `config/settings.py` 的 `TEMPLATES.context_processors`)提供。選用 context processor 而非讓每個 view 各自傳入,是因為共用的 `components/app_header.html` 目前橫跨 9 個不同 view 的頁面(`accounts`、`tutoring` 兩個 app 都有),逐一修改容易漏掉且日後新增頁面也會忘記加。
- 新頁面 `accounts:class_documents`(`templates/accounts/class_documents.html`)列出使用者有資格且已啟用的文件;下載走獨立的 `accounts:download_class_document` view(不是直接連到 `file.url`),原因是驗收條件明確要求「下載行為需保留稽核紀錄」——現有的口語能力證明、課堂紀錄附件下載都只是直接連到 media URL,沒有經過任何 view,不會產生 `AuditLog`,這個功能是本專案第一個「下載需要稽核」的檔案類型,因此需要自己的 gate 檢查(`document.program not in visible_class_document_programs(request.user)` 才放行)與 `AuditLog.record(event_type="CLASS_DOCUMENT_DOWNLOADED")`。
- 檔案格式與大小:比照既有 `validate_qualification_file`/`validate_class_record_attachment` 共用的 `_validate_upload()` 擴充出 `validate_class_document_file()`,允許 PDF/Word/PowerPoint/Excel/JPG/PNG(課程教材常見格式,比證明文件/課堂附件的允許清單更寬),上限 10 MB(比 1 MB/500 KB 更寬,課程教材通常較大)。
- 電子章、主管簽名、正式模板的邊界說明(見上方 4.9 節)同樣適用於此處:文件本身就是系辦上傳的原始檔案,系統不做任何浮水印或簽章疊加。
- **2026-09-08 起新增自訂 Admin dashboard 上傳/管理 UI**,取代原本「只能在 Django Admin 操作」的設計(使用者事後要求,原始定位是低頻率使用):Admin dashboard 新增「上課文件 / Class documents」頁籤(`templates/dashboard/admin_v2_panels.html`),沿用學期設定既有的「新增表單 + 逐筆卡片,卡片內含編輯用 `<details>` 收合表單」版面(`.semester-setting-list`/`.semester-card`/`.semester-edit-disclosure` 共用同一組 CSS,沒有新增樣式)。
  - 新增 `tutoring/forms.py::ClassDocumentUploadForm`(`ModelForm`):`program` 限定 `class_documents_enabled=True` 的計畫;`semester` 選填,留空代表適用該計畫所有學期;`clean()` 額外檢查所選學期若已綁定計畫,必須與所選 `program` 一致,避免文件錯配到其他合作計畫的學期。`file` 在 model 上仍是必填,但沿用 Django `FileField` 「編輯既有 instance 且未提供新檔案時,`clean()` 會自動退回 `initial`(即維持原檔案)」的標準行為(與 `QualificationUploadForm` 的重新送審流程相同機制),所以編輯時不需要每次重新上傳檔案。**2026-09-22 修正:`semester` 下拉選單改用 `tutoring/forms.py::SemesterChoiceField`,標籤附上所屬合作計畫名稱**(使用者回報:「因為目前ntnu和maryland都是115-1，下拉選單都呈現一樣的學期，這樣看不出來哪個哪個計劃」)——原本用 Django 預設的 `ModelChoiceField` 標籤,直接顯示 `Semester.__str__()`(只有 `name_zh`/`name_en`,不含計畫),不同計畫剛好取一樣名稱的學期(例如都叫「115學年度第1學期」)在下拉選單裡會完全看不出差異。新標籤格式為「{學期名稱} · {計畫中文名稱}」(舊版共用期間 `program=None` 時顯示「（舊版共用期間 / Legacy shared period）」)。**同樣的問題也存在於 `AdminPairingForm.semester`(Admin 手動配對工具)**,這次沒有一併修,因為使用者只回報「上課文件」這一處;已記錄在此供之後決定是否也要修。
  - 新增 `tutoring/views.py::save_class_document(request, pk=None)`(建立/編輯共用同一個 view,比照 `save_semester()` 的寫法)與 `delete_class_document(request, pk)`,皆為 `@login_required`+`@require_POST`,手動檢查 `request.user.role != Role.ADMIN` 才允許(未使用 `role_required` 裝飾器,與同檔案其餘學期管理 view 的既有寫法一致)。新增時設定 `uploaded_by=request.user`(編輯時不覆寫,保留原上傳者);新增/修改/刪除皆寫入對應的 `AuditLog`(`CLASS_DOCUMENT_UPLOADED`/`CLASS_DOCUMENT_UPDATED`/`CLASS_DOCUMENT_DELETED`)——這是因為這兩個 view 走自訂前台流程,不會被 `mirror_admin_log_entry_to_audit_log()`(只鏡射 Django Admin 後台操作)自動涵蓋,若不手動寫入會完全沒有稽核紀錄。刪除只移除資料庫紀錄,不會連帶清除 storage 上的實體檔案(與 `QualificationDocument` 重新上傳、其餘私人檔案的既有行為一致,屬於本專案目前對檔案清理刻意保守、統一不做的既有慣例,不是這次新增功能的疏漏)。
  - `accounts:download_class_document` 新增 Admin 例外:Admin 可下載/預覽任何文件,不受 `is_active`/`visible_class_document_programs()` 資格檢查限制(比照 `download_qualification()` 既有的 `request.user.role != Role.ADMIN and ...` 寫法),方便上傳後立即核對檔案內容是否正確。
  - Django Admin 後台(`tutoring/admin.py::ClassDocumentAdmin`)**予以保留、未移除**,兩條路徑並存;透過 Django Admin 操作仍會被既有的 `mirror_admin_log_entry_to_audit_log()` 訊號自動鏡射進 `AuditLog`,自訂前台則靠上述手動 `AuditLog.record()`,兩者不衝突也不去重(比照 4.9 節 `HourAdjustment` 的既有慣例)。
  - 測試見 `tutoring/tests.py::ClassDocumentAdminUploadTests`(上傳、非 Admin 被拒、跨計畫學期擋下、免重新上傳檔案即可編輯、刪除、dashboard 正確帶出新表單與既有清單)與 `ClassDocumentTests::test_admin_can_download_any_document_regardless_of_active_state`。

### 4.11 公告欄

`accounts.models.Announcement`(2026-09-24 新增,使用者要求「tutor/tutee 左側功能欄多加一個公告欄」):Tutor 與 Tutee 首頁上方新增一個獨立頁籤,顯示系辦公告事項(目前是系辦提供的 5 則配對/課程紀錄規範說明)。比照 4.10 節 `ClassDocument` 的 Admin 自行編輯慣例,而非把公告文字寫死在 template 裡:

- 單一模型,不分角色(Tutor/Tutee 目前看到同一份公告),欄位為中文公告內容(`content`,純文字,最多 1000 字)、英文公告內容(`content_en`,同上限,**2026-09-25 起必填**,見下)、顯示順序(數字越小越前面)、顯示中(布林,關閉即暫時隱藏但不刪除內容),以及建立者、建立/更新時間。
- **2026-09-25 新增英文公告內容(使用者要求「內容加上英文」)**:公告是給全體 Tutor/Tutee 看的正式系辦公告,和第 4.6/4.9 節列出的「使用者自由填寫備註」(如 `PairingReleaseRequest.reason_note`)刻意維持單一語言不同——`AnnouncementForm` 讓 `content_en` 也是必填欄位,兩者都填才能送出。`content_en` 在 model 層仍是 `blank=True`(migration 新增欄位時的既有相容慣例,避免補資料時卡在 NOT NULL),真正的「必填」把關在表單層(`self.fields["content_en"].required = True`)。顯示時比照全站既有的「長雙語句用換行」慣例(`static/css/app.css::.bilingual-note`,已用於多處表單說明文字),中英文放在同一個 `<p>` 裡用 `<br>` 分隔,不是各自獨立的段落,也不是斜線硬擠成一行。既有的 5 則公告已於部署後透過 Admin UI(或對應的一次性腳本)補上英文翻譯。
- Admin dashboard 新增「公告欄管理」頁籤(`templates/dashboard/admin_v2_panels.html`),沿用學期設定/上課文件既有的「新增表單 + 逐筆卡片,卡片內含編輯用 `<details>` 收合表單」版面(`.semester-setting-list`/`.semester-card`/`.semester-edit-disclosure` 共用同一組 CSS)。因公告沒有「合作計畫」/「適用學期」欄位,列表列只需 3 欄而非既有的 5 欄,新增 `.announcement-setting-row` 修飾類別覆寫 `.semester-setting-row` 的 `grid-template-columns`,其餘邊框/底色/陰影等樣式沿用不變。
- `accounts/views.py::save_announcement(request, pk=None)`(建立/編輯共用同一個 view)與 `delete_announcement(request, pk)`,皆用 `@role_required(Role.ADMIN)` 保護(非 Admin 會被導回 dashboard 並顯示錯誤訊息,不是 404),寫入 `ANNOUNCEMENT_CREATED`/`ANNOUNCEMENT_UPDATED`/`ANNOUNCEMENT_DELETED` `AuditLog`。Django Admin(`accounts/admin.py::AnnouncementAdmin`)同時保留,兩條路徑並存,不做去重(比照 4.9/4.10 節既有慣例)。
- Tutor/Tutee 端是唯讀顯示:`dashboard()` 對三種角色的 context 一律附上 `active_announcements`(`Announcement.objects.filter(is_active=True)`,依 model 預設的 `display_order` 排序),`templates/dashboard/participant_v2_panels.html`(Tutor/Tutee 共用同一份 partial)新增「公告欄」頁籤。
- **2026-09-25 改為逐則卡片呈現,並新增「未讀/NEW」提示機制(使用者要求)**:使用者反映原本一整塊編號清單的呈現方式,之後陸續新增公告時使用者不會特別注意到有新內容,要求「每一條用成一個卡片,然後顯示日期,如果是新增的就會有一個 new 的標示,左側欄位的『公告欄』也有提示,使用者要點進來看過這個提示才會不見」。
  - 每則公告改成獨立卡片(`.announcement-card`),顯示建立日期(`Announcement.created_at`)與內容;是否為「新」由新增的 `accounts.models.AnnouncementReadState`(對 `User` 的 `OneToOneField`,`last_viewed_at` 可為空,比照 `TutorProfile`/`TuteeProfile` 的既有「每人一筆狀態」慣例)判斷——`dashboard()` 逐一比對每則公告的 `created_at` 是否晚於這位使用者的 `last_viewed_at`(從未查看過則一律視為新的),算出的 `is_new` 直接掛在每個 `Announcement` 物件上供 template 使用,同時加總成 `unread_announcement_count`。**已讀與否是「使用者」的屬性,不是「公告」的屬性**,因此獨立成一張表,不掛在 `Announcement` 本身——同一則公告對不同使用者可能一個已讀一個未讀。
  - Tutor/Tutee 側邊欄「公告欄」連結比照既有的「待回覆邀請」等連結,依 `unread_announcement_count` 顯示數字徽章(`<em>{{ unread_announcement_count }}</em>`),Admin 的「公告欄管理」連結不受影響(不需要這個概念)。
  - **「點進來看過才會消失」**:因為側邊欄分頁切換是純前端(`static/js/dashboard.js` 的 `activate()`,`event.preventDefault()` 後不會整頁重新載入),徽章要即時消失勢必要一個背景通知後端的動作。新增 `accounts:mark_announcements_read`(`POST`,`@login_required`,只更新這位使用者的 `AnnouncementReadState.last_viewed_at = now()`,**不寫 AuditLog**——比照私訊「開啟對話即標記已讀」的既有慣例,這是單純的使用者端已讀狀態,不是需要稽核的行政操作)。`dashboard.js::activate()` 切到 `"announcements"` 分頁時會呼叫新增的 `markAnnouncementsRead()`:用既有的 `csrftoken` cookie 讀取慣例組出 `fetch(...)` 呼叫這個端點,成功後直接把側邊欄該連結裡的 `<em>` 徽章從 DOM 移除,不用等下次整頁重新載入才消失。端點網址透過側邊欄連結上的 `data-mark-read-url="{% url 'accounts:mark_announcements_read' %}"` 屬性帶給 JS(沿用「JS 用 `data-*` hooks、不寫死路由」的既有慣例),不是寫死在 `dashboard.js` 裡。
  - 卡片樣式沿用既有 `.semester-card` 同一種白底卡片語彙(邊框/圓角/陰影相同數值),`is-new` 修飾類別疊加既有 `.alert-active-box` 的柔和黃色配色(`#e2c86f`/`#fff7d9`)標示這則是新公告;NEW 徽章沿用 `.unread-badge` 既有的紅底白字圓角膠囊樣式(`var(--danger)`)。
  - **此變更不溯及既往**:所有目前登入過的真實使用者在部署當下都還沒有 `AnnouncementReadState` 紀錄,因此第一次載入 dashboard 時會看到全部現有公告都標記為「新」,直到各自點開「公告欄」分頁一次為止——這是刻意的簡單化處理(視為「尚未用這套新機制確認讀過」),不是 bug。
- 側邊欄連結刻意放在 Tutor/Tutee 的「我的首頁」正上方(使用者明確要求),但**登入後預設仍停留在「我的首頁」**:`static/js/dashboard.js` 的頁面載入邏輯是讀網址 hash(`location.hash.slice(1) || "overview"`)決定要顯示哪個分頁,與側邊欄連結在 HTML 裡的先後順序完全無關(哪個連結帶 `is-active` 也只是初始 markup 的樣式,載入後一律由這段 JS 依 hash 重新校正)。因此可以同時滿足「公告欄排在最上面」與「預設看到的還是我的首頁」這兩個表面上看似衝突的需求,不需要任何額外的特判邏輯。Admin 側邊欄新增對應的「公告欄管理」連結,位置在「系統總覽」之後。
- 目前的 5 則公告內容是透過這個新介面由 Admin 手動輸入,不是寫死在程式碼或 migration 資料遷移裡;之後系辦要新增/修改/下架公告都直接在「公告欄管理」頁籤操作即可。
- 測試見 `accounts/tests.py::AnnouncementTests`(Admin 建立/編輯/刪除、非 Admin 被拒、Tutor/Tutee dashboard 皆能看到依 `display_order` 排序的啟用中公告、已隱藏的公告不顯示、新增公告欄連結後預設進入分頁仍是 overview、從未查看過的使用者看到全部公告皆為新、已查看過的時間點之前的公告不算新、側邊欄未讀徽章正確顯示與隱藏、`mark_announcements_read` 端點更新已讀時間且需要登入與 POST、卡片正確顯示日期與 NEW 徽章、缺英文內容會被表單擋下、卡片同時顯示中英文內容)。

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
accounts/context_processors.py 全站共用的 template context(目前只有上課文件選單顯示與否)
accounts/management/    本機 demo 帳號 seed
tutoring/               配對、排課、簽到、紀錄、互認、補登、報表
tutoring/services.py    核心業務規則;新規則優先放這裡而非 view/template
tutoring/reporting.py   PDF 證明與 Excel XML 匯出
tutoring/management/    狀態排程與 V1/V2 demo seed
templates/              Django templates;dashboard 依角色拆 partial
static/css/app.css      全站樣式
static/js/              dashboard、使用者選單、國家/語言下拉資料
media/                  使用者上傳,勿提交真實個資或口語能力證明
assets/fonts/           PDF 內嵌字型
tutoring/resources/     各合作計畫的證明 PDF 底圖,檔名由 PartnerProgram 設定引用
output/                 本機人工檢查用預覽與會議輸出(PDF/DOCX 等),整個目錄不進版控,不是正式資料來源
```

### 主要 URL

- `/` 登入
- `/register/` 名冊核對與密碼草稿
- `/register/confirm/` 確認學號(第一/第二階段之間的中間步驟,見第 4.1 節)
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
- 所有重要行為(登入、註冊、口語能力審核、解除、下載、匯出)應寫 `AuditLog`,metadata 不放密碼/安全問題答案。
- 寫入 `AuditLog` 一律呼叫 `AuditLog.record(**kwargs)`,不要直接用 `AuditLog.objects.create(**kwargs)`。`record()` 把寫入包在自己的 nested `transaction.atomic()`(在外層 `@transaction.atomic` 內等於一個 savepoint)裡,失敗時只回滾這筆 insert 並記錄到 `logging.getLogger("csl.audit")`,不會讓稽核紀錄寫入失敗連帶弄壞呼叫端原本的資料庫交易(資通系統防護基準檢核表第 19 項)。
- Django Admin 後台直接做的新增/修改/刪除(不經過自訂 view/service)會由 `accounts/signals.py::mirror_admin_log_entry_to_audit_log()` 自動鏡射進 `AuditLog`(監聽內建 `admin.LogEntry` 的 `post_save`,在 `AccountsConfig.ready()` 連接),涵蓋所有註冊在 Admin 的 model,新增 `ModelAdmin` 不用額外處理。已經在自訂 view/service 裡手動寫 `AuditLog.record()` 的動作(如 `HourAdjustment`)會因此多出一筆通用的鏡射紀錄,這是刻意接受的重複,不做去重。
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
python manage.py seed_admin_demo --password '<local-only-password>'
python manage.py process_matching_state
```

`seed_admin_demo` 是給 Admin dashboard 全頁籤各放幾筆資料用的:多建幾個 DEMO-TUTOR2/3、DEMO-TUTEE2/3/4、DEMO-MARYLAND 帳號並跑滿口語能力審核(PENDING)、配對管理(待回覆邀請)、解除審核(PENDING)、課堂通報(ACTIVE)、異常回報(PENDING+已紀錄各一)、補登審核(PENDING)、時數調整、私訊等每一種待處理狀態,可安全重複執行(每次都以「今天」為基準重新計算日期並重建,不會疊加)。其中 DEMO-TUTEE4 刻意不配對、不邀請,保留給「Tutor 匿名瀏覽並邀請→Tutee 接受」這段即時展示用(DEMO-TUTOR 本學期名額已滿,示範時改用有空位的 DEMO-TUTOR2 發邀請)。另外會額外建立一個已結束的「114學年度第2學期」(is_active=False)並補幾堂已完成有效課程,因為時數證明要學期結束滿 3 天才開放下載(見第 4.9 節),當前這個「今天±45 天」的啟用學期永遠無法示範下載,需要一個真正已結束的學期才能展示「時數與 PDF 證明」下載流程。

- Lint(`ruff`,設定在 `pyproject.toml`):只開 `F`(pyflakes,抓未使用的 import/變數、未定義名稱等真的會出錯的問題)與 `E9`(語法錯誤),刻意不開 `E`(pycodestyle 風格規則,含行長)或 import 排序規則,因為既有程式碼從未套用過任何格式化工具,貿然開啟會逼出一次跟本次修改無關的全庫重排版大 diff。`.github/workflows/ci.yml` 的 CI 會跑 `ruff check .`;開發者本機可執行 `pip install -r requirements-dev.txt` 後跑同一指令。若之後真的要導入 `ruff format`(或其他 formatter)做全庫重排版,應該是一次獨立、刻意的決定與 PR,不要在功能改動裡順便夾帶。
- CI(GitHub Actions,`.github/workflows/ci.yml`):對 `main` 的 push 與所有 PR 觸發,跑一個用 Postgres service container 的 job,依序執行 `ruff check .`、`pip-audit`、`makemigrations --check --dry-run`、`python manage.py test`、`DJANGO_DEBUG=0 python manage.py check --deploy`。`pip-audit` 發現已知漏洞時會擋下 build;目前沒有自動部署、排程掃描或額外通知。

## 8. 文件維護與同步機制

這份文件(以及 `docs/PROGRESS.md`、`docs/DEPLOY.md`、`docs/SECURITY_CHECKLIST.md`)只有在被持續更新的情況下才有價值。以下是具體的同步規則,不是選項:

1. **何時必須更新本文件**
   - 新增/修改角色權限、配對規則、額度計算、簽到與互認流程、時數/證明規則 → 更新對應的第 2–4 節。
   - 新增/修改 model、目錄結構、URL 路由 → 更新第 5 節。
   - 任何 migration 或新增測試 → 更新 `docs/PROGRESS.md` 的數字快照。
   - 部署流程、環境變數、正式 server 設定變更 → 更新 `docs/DEPLOY.md`。
   - 資安控制狀態、第三方元件版本或安全等級變更 → 更新 `docs/SECURITY_CHECKLIST.md` 的逐項狀態、統計與 SBOM。

2. **每次開發 session 開始前(尤其是換 agent 或隔了一段時間再開發時)**
   - 先實際跑 `python manage.py test --verbosity 1` 與確認 migration 檔案數,和 `docs/PROGRESS.md` 記錄的快照核對;不一致就先更新快照,不要假設文件是對的。
   - 若使用者的新指示和本文件衝突,以使用者最新明確指示為準,並**在同一個 session 內**同步修改本文件與測試,不要留到之後才補。

3. **commit / PR 層級的提醒**
   - 建議在 PR 說明或 commit message 固定加一行檢查:「是否涉及業務規則變更?是否已同步更新 CLAUDE.md / docs/PROGRESS.md?」
   - 現有 CI 尚未檢查文件同步;之後可考慮加入非阻斷提醒:當 `tutoring/services.py`、`accounts/models.py` 等核心檔案有 diff,而 `CLAUDE.md`/`docs/PROGRESS.md` 沒有對應 diff 時顯示提醒。

4. **版本節點稽核**
   - 每次要開新的大版本(例如未來 V5)之前,重新完整盤點 `CLAUDE.md`、`docs/PROGRESS.md`、`docs/DEPLOY.md`、`docs/SECURITY_CHECKLIST.md` 的準確性,而不是只增量修改,避免小修小補堆疊出不一致。

## 9. Agent 接手原則

1. 先讀相關 model/service/form/view/test,再改 template;不要只按畫面猜資料狀態。
2. 使用者提出的新規則若和本文件衝突,以使用者最新明確指示為準,並同步更新本文件與測試(見第 8 節)。
3. 不要把 demo 帳密、真實學生名冊、口語能力證明、`.env` 或 DB dump 寫入版本控制。
4. 保留現有使用者修改與資料;不要用 `git reset --hard`、刪 DB、重建 migrations 或清空 media。
5. 交付前說明實作、測試、migration、已知限制;若只完成 UI mock,必須明確標示沒有後端行為。
