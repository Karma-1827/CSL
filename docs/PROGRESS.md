# PROGRESS.md

本文件記錄專案的開發進度、已知缺口與尚未定案的產品/維運決策。這是「會頻繁變動」的內容,從 `CLAUDE.md` 拆出以減少每次 agent 啟動時的 context 負擔。

> 最後盤點日期:2026-08-17 —— V3/V3.1 核心項目完成,V4 進行中。2026-08-17 已完成一次上傳 VM 前驗收：291 項完整測試、Ruff、migration、`check --deploy`、`pip check`、`pip-audit`、`collectstatic` 與主要角色瀏覽器巡查均通過；詳細紀錄見 `docs/PRE_DEPLOYMENT_CHECK_2026-08-17.md`。系辦會議後 20 項需求(`docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md`)已全數完成(第一批 10 項 + 第二批 10 項),詳見下方「已完成」。20 項需求之外,另有使用者事後追加的名冊匯入卡片 UI 調整(以合作計畫為單位重新分組)。師大資訊中心弱掃前整改(`docs/VULNERABILITY_SCAN_IMPROVEMENTS.md`)批次 0-6、8 已完成並 push 至 `origin/main`;批次 7(註冊本人驗證)因涉及業務規則決策暫停待系辦回覆,批次 9(送掃前收尾)待批次 7 定案與實際 VM 到位後執行,詳見下方「已完成」該小節。
> 下列數字(migrations、tests 數量)是盤點當下的快照,**每次開發前建議重新跑一次確認**,見 `CLAUDE.md` 的「文件維護與同步機制」一節。本次盤點已實際執行 `python manage.py check`、`python manage.py makemigrations --check --dry-run` 與完整測試套件(均無異常);測試總數請直接執行 `python manage.py test` 取得目前準確數字。

## 已完成

### 2026-08-10 最新需求調整（取代下方歷史開發紀錄中的舊規則）

- 安全問題三題必須互不相同:註冊表單會在每個重複題目欄位顯示雙語錯誤,資料庫另以 `three_distinct_security_questions` check constraint 防止繞過表單寫入重複題目。
- 身份別新增「港澳生 / Hong Kong and Macao student」(`IdentityCategory.HONG_KONG_MACAO`),Tutor/Tutee 註冊下拉選單與 model choices 已同步。
- 暱稱功能全面移除:刪除 `User.nickname`、註冊與 Profile 編輯欄位、個人資料/Admin/配對後畫面顯示及相關測試；Email 仍為必填聯絡資料。對應 migration 為 `accounts/0017_remove_user_nickname_and_more.py`。
- Tutor 與 Tutee 的課堂紀錄統一使用 1–5 個必填 `https://` 佐證連結;雙方目前表單都不再顯示附件上傳。既有 `ClassRecord.attachment` 僅保留歷史資料相容與受保護下載,未刪除舊檔案。
- `ClassRecord.content`/`.remarks` 上限由 2000 改為 500 字元,model、表單 `maxlength` 與伺服器端驗證一致；課程詳情頁新增即時 `0/500` 字元計數(`static/js/character-count.js`)。對應 migration 為 `tutoring/0023_alter_classrecord_content_and_more.py`。
- Admin 資料匯出改為五步:選擇合作計畫、選擇老師/學生/特定使用者、選擇隨計畫更新的學期或日期、選擇欄位、選擇輸出格式。選老師或學生時,下方名單只顯示對應身分且整類納入匯出;特定使用者可在所選計畫內跨身分勾選一位或多位。名單與學期選項會在前端隨計畫篩選,後端仍會驗證計畫資格並在報表查詢再次限制課程計畫,避免跨計畫資料混入。
- 證明 PDF 套用新版共用模板與本機私有素材:中文內文使用華康儷宋 W3、粗體/標題使用 W7,英文使用 Helvetica Neue Condensed Bold；日期依台灣時區計算並在底部置中、加寬字距,右下角系戳放大為 110pt 並向左、向上調整。摘要版加大左右留白,詳細版每頁最多 6 筆,避免表格碰到底部日期與放大後的系戳。私有字型與系戳不進版控,缺少時使用原有開源字型且略過系戳。已重新產生中文摘要、中文詳細跨頁及英文摘要預覽,以 Poppler 逐頁檢查無遮擋。

下方提到「新增暱稱」、「只有 Tutor 使用佐證連結／Tutee 使用附件」或「課堂紀錄 2000 字」的段落,是當時版本的實作歷史,已被本節取代,不可當作現行需求。

- V0:名冊式兩階段註冊、三角色、登入/登出、三安全問題恢復、Profile、資格文件、Admin 基礎管理、雙語響應式 UI、安全設定。
- V1/V1.1:匿名候選資料、資格門檻、雙向邀請、五日逾期、名額限制、接受/拒絕/取消、配對後完整 Profile、解除配對與三日自動解除、個人資料/手冊、私訊入口。
- V2:學期管理、24 小時/五分鐘排課、每週重複、額度限制、取消/改期、雙方簽到、雙方紀錄、互認、補登與 Admin 審核、課堂通報、Admin 課程總覽、老師個人課表、時數歷史、PDF 證明、Admin `.xls` 匯出、pairing 私訊。
- **V3(核心功能完成):**
  - 名冊批次匯入(CSV/.xlsx,Admin dashboard「名冊匯入」頁籤,only-new,附範本下載,寫入 `ROSTER_IMPORTED` AuditLog)。原本是任一列驗證失敗即整批不寫入的 all-or-nothing,後續已改為只有「完整欄位」進階匯入的逐列驗證失敗才整批擋下,學號重複則一律靜默略過(見下方「名冊匯入卡片化」項目)。
  - Profile 可編輯(`/profile/` 新增編輯表單,Tutor/Tutee 可自行更新電話/性別/母語/國籍/系所/聽說讀寫程度/簡介或需求備註/可上課時段等非名冊欄位,自動生效不需審核,寫入 `PROFILE_UPDATED` AuditLog;姓名、學號、安全問題答案不開放自行修改)。
  - 待回覆邀請上限(每位使用者同學期 PENDING 邀請上限 3 筆,雙向合計;Tutor 配對滿額後其餘 pending 邀請自動取消)。
  - 配對結束後的私訊紀錄入口:學期結束或解除配對仍保留 `PairingMessage`,Dashboard「私訊」拆成進行中與可展開的過往對話紀錄;ended pairing 可重開閱讀但不能傳送,且不再顯示只允許 active pairing 使用的完整 Profile 連結。
  - 異常回報分類系統(`IncidentReport`,獨立於課堂通報之外的新模型):不限上課時段、6 大分類、Admin 可標記已紀錄並留備註(用詞為「已紀錄」而非「已處理」,因為不是所有回報系辦都能真的解決),PENDING/HISTORY 兩區塊。
  - 課堂通報 Admin 處理狀態:`ClassAlert` 新增 `RESOLVED` 狀態與 `resolved_by`/`resolved_at`/`resolution_note` 欄位,Admin 可標記已紀錄並留備註;已紀錄與已取消都是終點狀態,互斥不可逆。Admin dashboard 課堂通報頁籤同步拆為 PENDING/HISTORY。
  - 合作計畫重構為獨立表格(`accounts.models.PartnerProgram`,取代寫死的 `ProgramSource` enum):新增計畫不需改程式,可在 Django Admin 設定邀請權限、下載權限、Tutor/Tutee 各自的證明標題與文案。同時完成四項連動的產品決策:①一般 NTNU 外籍生 Tutee 現在**開放下載時數證明**;②`OTHER` 合作計畫預設**不可**主動邀請 Tutor(與 Maryland 不同,維持原行為但改為可調整);③Tutor 下載時數證明新增「合作計畫」下拉選單,只列出該 Tutor 實際帶過、且已設定 Tutor 版證明模板的計畫;④證明底圖改為**全部計畫、Tutor/Tutee 共用同一份 `csl_template.pdf`**(只印師大頭銜與浮水印,無標題無內文),標題與內文段落改為 `build_hours_pdf()` 用 ReportLab 動態疊字(標楷體+Times New Roman 粗體),新增計畫從此**不需要新的 PDF 美編底圖**,填標題/文案文字即可。已用 PyMuPDF 產生 NTNU Tutor/Tutee、Maryland Tutor 三種證明的實際 PDF 轉圖片人工檢查排版,確認標題位置正常、不與內文重疊。資料遷移已將既有名冊資料正確轉換,無資料遺失。
  - 時數證明預覽功能:下載區新增「預覽」按鈕,與「下載」共用表單與驗證邏輯,靠 `intent` 欄位切換 `Content-Disposition`(inline 開新分頁 vs attachment 強制下載),無新增頁面或 JS。分開寫入 `HOURS_PDF_PREVIEWED`/`HOURS_PDF_DOWNLOADED` AuditLog。
  - 修正 Tutor 選方案下載證明時的時數計算 bug:原本不管選哪個計畫,時數都是這位 Tutor 全部計畫加總;現在 `hour_report_data()`/`valid_sessions_for_user()` 新增 `program` 參數,依 `pairing__tutee__roster_entry__program` 篩選,選 NTNU 就只算 NTNU 學生的時數。已補回歸測試鎖住(`test_download_hours_only_counts_selected_programs_sessions`)。
  - NTNU Tutor 版證明內文改為系辦指定格式(特例寫死,非通用 `plan_name`/`activity` 句型):「本系{學制}學生 XXX,學號 XXX,於民國 X 年 X 月-X 月,於本校擔任國際生華語輔導老師,總計授課 X 小時。特此證明」,學制文字依 `RosterEntry.education_level` 動態代入。摘要版字體放大並置中;詳細版沿用原排版只換文字。已用 PyMuPDF 產生真實 demo 資料(DEMO-TUTOR,NTNU 4.5 小時、Maryland 4 小時分開列示)的 PDF 轉圖片人工檢查,確認換行、置中、時數隔離都正確。
  - 本機開發用學期改名為「114學年度第3學期」(2026/07/01–2026/08/31),取代原本滾動式的「V1.1 本機測試學期」;`seed_matching_demo` 指令的預設學期也同步改成這組固定名稱與日期。
  - 補了 DEMO-TUTOR 與 DEMO-MARYLAND 的配對及 6 堂雙方互認完成的課程(NTNU 3 堂、Maryland 3 堂),方便手動測試證明下載與方案下拉選單。
  - Admin 學期時間設定新增「編輯」與「刪除」:後端 `save_semester`/`update_semester` 其實早就支援編輯,只是前端從沒接上,這次補上——UI 改成卡片右上角一顆編輯筆 icon(`<details>`/`<summary>`,無 JS),點擊展開編輯表單;另新增 `delete_semester`(真刪除,僅限尚無 `Pairing` 的學期,靠 DB `PROTECT` 約束防呆)區別於原本只給已結束學期用的「封存」(`archive_semester`)。編輯日期是回溯性的,UI 已加警告文字但無強制檢查,細節見 `CLAUDE.md` 4.2 節。過程中順手修掉一個既有 bug:`SemesterSettingsForm`/`SemesterCreateForm` 的日期 widget 沒設定 `format="%Y-%m-%d"`,編輯既有學期時日期欄位會顯示空白。**這項功能已用 Playwright 實際開瀏覽器登入點擊測試過**(建立臨時 Admin 帳號測試、測完刪除),是本專案目前少數真人瀏覽器驗證過的功能。
  - 名冊匯入卡片化 + 註冊改由使用者填寫姓名/學制/身份別:起因是系辦實務上一次只會拿到「純學號」清單,且是**分開的**、每種身分一份檔案(華語系學生、師大外籍生、馬里蘭大學…)。改動四項,彼此連動:
    ① `RosterEntry.student_id` 全面正規化為大寫,註冊第一階段學號查找也改為大小寫不敏感,與登入行為一致(`RosterEntry.clean()`)。
    ② 註冊第二階段新增使用者自填欄位:中文姓名(必填)、英文姓名(選填)、身份別(本地生/僑生/港澳生/外籍生,必填),Tutor 另外新增學制下拉選單(大學部/碩士班/博士班);`RosterEntry.name_zh`/`identity_category`/`education_level` 因此改為 `blank=True`(migration `accounts/0007`),送出註冊表單時寫回 `RosterEntry` 並建立 `User`。
    ③ Admin dashboard「名冊匯入」頁籤新增**分類卡片式快速匯入**(`accounts:roster_import_quick`,新 service `import_roster_ids()`/`_read_single_column_values()`):固定「華語系學生」卡片(Tutor)+ 每個啟用中 `PartnerProgram` 各一張卡片(對應 Tutee 該計畫)+ 一張連到 Django Admin 新增計畫的卡片;只吃單欄學號清單,容忍標題列/中文表頭列等雜訊,角色與計畫完全由「上傳到哪張卡片」決定,不看檔案內容或任何 role 欄位。舊版完整欄位 CSV/Excel 匯入保留為同頁籤內的「進階匯入」摺疊區塊。
    ④ 兩種匯入路徑的重複學號處理都改為:學號已存在就靜默略過、保留系統內既有資料,只匯入真正新的學號(不再是「有重複就整批擋下」)。
    新增 `accounts/tests.py::QuickRosterImportTests`(8 個測試,含模擬使用者實際檔案結構的雜訊 xlsx 測試)並更新 5 個既有測試以符合新的必填欄位與略過邏輯。
  - UI 微調:名冊匯入卡片的中英標題一律換行(`.quick-import-card h2 small { display: block; }`,與既有 `.guide-card` 的雙語標題換行慣例一致);`OTHER` 其他合作計畫因尚未有實際對接對象,先用 migration `accounts/0008` 把 `is_active` 設為 `False`,從快速匯入卡片清單隱藏(資料保留,之後要用可在 Django Admin 改回啟用)。
- **V3.1(驗收與必要補強,核心項目已完成):**
  - Tutor 端候選學生複合篩選:比照舊版(`CSL-system`)概念補回性別、華語程度、母語、加強項目、星期、時段篩選,重新用 Django service layer 實作(`anonymous_tutee_candidates()` 新增 `filters` 參數,不觸碰資料庫欄位,不改變配對前匿名欄位範圍)。UI 是 `find-tutee` 分頁一個 GET 表單(送回 `accounts:dashboard#find-tutee`,沿用既有 `class-overview-filter` 的「GET+hash」模式維持分頁狀態),星期/加強項目/時段用既有 checkbox chip 視覺語言(比照 `target-skills-card` 的核選樣式,並統一 `.chip-check` 固定寬度與文字置中,避免不同標籤長度導致排版參差)。母語欄位後來從自由關鍵字改成下拉選單,共用註冊表單同一份 `static/js/profile-options.js` 語言清單,篩選邏輯也從模糊比對改成精準比對。篩選卡片預設收合,原本常駐的面板標題徽章「配對前不顯示姓名與學號」改成一個「搜尋條件 / Search filters」`<details>/<summary>` 收合開關(`.candidate-filter-disclosure`,無 JS),點擊才展開;隱私提示本身仍保留在側邊欄 `sidebar-note`,沒有因此消失。Maryland Tutee 瀏覽 Tutor 的另一側篩選也已於同一版本補齊(見下方項目)。新增 `OVERALL_LEVEL_CHOICES` 共用常數(`accounts/forms.py`)消除原本兩處重複的 TOCFL 等級 choices 字面量。
  - 私訊未讀摘要:比照舊版(`CSL-system`)概念補回「未讀數、最後一則訊息、最後訊息時間、依最近活動排序」,後端基礎(`PairingMessage.read_at`)本來就有,新增的是 `tutoring/services.py::annotate_conversation_summaries()`——對每個 pairing 撈最後一則訊息與未讀數(未讀判定沿用既有的 `read_at__isnull=True` 且非本人發送),再依「最後訊息時間、若無訊息則用 `Pairing.started_at`」排序。因為每人最多就 2 個進行中配對加上少數過往配對,直接用 Python 迴圈算,沒有寫複雜的 annotate/subquery。UI 更新 `participant_v2_panels.html` 的對話清單卡片(新增未讀 badge、訊息摘要、時間)與側邊欄「私訊」連結的總未讀數 badge(比照既有「課堂通報」badge 樣式)。
  - 課堂紀錄分類(輔導類型):比照舊版(`CSL-system`)概念補回,`ClassRecord` 新增 `skills_practiced` JSONField(選填,`migration tutoring/0013`),沿用 `accounts/forms.py::SKILL_CHOICES`(聽力/口說/閱讀/寫作)同一套分類,不另外定義新 enum。`ClassRecordForm` 加對應 CheckboxSelectMultiple 欄位,`class_detail.html`/`admin_record_card.html` 以標籤呈現(顯示用的中英標籤透過 view 附加 `record.skill_labels`,沿用 `tutoring/services.py::SKILL_LABELS`,避免 model 反向 import services 造成循環引用)。Admin 統計走最小版本:`tutoring/admin.py` 幫 `ClassRecordAdmin` 加 `SkillsPracticedFilter`(`SimpleListFilter`,用 JSONField `contains` 查詢),讓 Admin 在內建清單頁依單一類型篩選/看筆數,沒有另外做自訂統計面板,之後真的常用再考慮。過程中確認 `ClassRecord.reflection` 欄位其實已經是死欄位——`ClassRecordForm.Meta.fields` 從未包含它,提交流程不會用到,順手在 `CLAUDE.md` 標註避免之後被誤認是現行欄位。
  - **完整更新角色使用手冊**(補齊 V3.1 第 4 項欠款):`templates/accounts/handbook.html` 三種角色的卡片內容全面重寫,涵蓋 V2 排課/簽到/課堂紀錄/雙方確認/補登/時數證明,以及 V3/V3.1 的候選篩選、私訊未讀摘要、課堂紀錄分類與附件、課堂通報/異常回報;版本標示改為 V3.1。Admin 角色原本只有 1 張籠統的「系統管理」卡片,拆成名冊匯入、資格審核、學期設定、配對與解除審核、課程總覽與行政檔案、課堂通報與異常回報、補簽到/補紀錄審核、時數修正與匯出共 8 張,對應各自的既有功能頁面。
  - 候選篩選補齊 Tutee(Maryland)瀏覽 Tutor 側:`anonymous_tutor_candidates()` 比照 `anonymous_tutee_candidates()` 加上 `filters` 參數(性別、母語、星期、時段;Tutor 沒有「華語程度」/「加強項目」對應欄位,不提供這兩項),`accounts/views.py` 的 dashboard 與 `templates/dashboard/index.html` 的 `find-tutor` 分頁補上同一套收合式篩選 UI(`<details>/<summary>`,與 `find-tutee` 樣式一致)。
  - README/launch.json 校正:`README.md` 原本只列到 V0/V1、啟動指令寫 port 8000,已重寫為只放技術棧、本機啟動、建立 Admin、測試、環境變數、配對狀態排程等會持續有效的操作型內容,port 改為與日常驗收一致的 8001,並移除逐版功能清單(改為指向 `CLAUDE.md`/`docs/PROGRESS.md`,避免以後又跟實際進度脫節)。`.vscode/launch.json` 的除錯設定同步把 port 改成 8001。`docs/DEPLOY.md` 原本記錄兩者不一致的提醒也一併更新,順手補了一句「先 `ps aux | grep runserver` 確認沒有殘留舊 process 再啟動新的」——這是本次開發過程中實際踩到的坑(改完程式碼但看不到效果,後來發現是舊 runserver process 沒關掉)。
  - 真正的 Excel `.xlsx`/CSV 匯出:`tutoring/reporting.py` 把原本 `build_excel_xml()` 的逐列組資料邏輯抽成共用的 `_export_rows()`,新增 `build_excel_xlsx()`(用專案既有依賴 `openpyxl`)與 `build_export_csv()`(標準庫 `csv`,寫入 UTF-8 BOM 讓 Windows Excel 開啟中文表頭不亂碼),三種格式欄位/資料完全一致,只是輸出容器不同。`tutoring/views.py::export_excel()` 讀取表單的 `file_format`(`xlsx`/`csv`/`xls`,預設 `xls` 以維持既有呼叫端相容),依格式切換 builder、`Content-Type`、副檔名,並把選用格式一併寫進 `ADMIN_EXCEL_EXPORTED` 的 `AuditLog.metadata`。前端匯出表單(`templates/dashboard/admin_v2_panels.html`)新增「選擇格式」卡片,預設勾選 `.xlsx`(標示 Recommended),另有 `.csv`(供匯入其他系統)與 `.xls`(相容舊流程),取代原本「未來可加入其他格式」的預留文案。
  - 證明 PDF 字型換成開放授權字型:`assets/fonts/Kaiu.ttf`、`TimesNewRoman.ttf`/`-Bold.ttf`(確認為 Windows/Monotype 授權字型,字型內嵌 metadata 直接寫 `(c) 2006 The Monotype Corporation`)與完全未使用的 `NotoSansTC.ttf` 全部移除,換成 `TW-Kai.ttf`(國發會/數位發展部「全字庫」開放資料)與 `LiberationSerif-Regular.ttf`/`-Bold.ttf`(Red Hat Liberation Fonts,SIL OFL 1.1,與 Times New Roman 度量相容),來源與授權記錄在新增的 `assets/fonts/LICENSES.md`。`tutoring/reporting.py::build_hours_pdf()` 只改 4 行字型檔案路徑,內部 ReportLab 字型家族代號維持不變,沒有動到其他排版程式碼。換字型後寫了一份一次性腳本(未留在 repo)重新產生 NTNU 摘要版/詳細版(含跨頁到第 2 頁)、Maryland 摘要版共 4 種 PDF,用 Poppler 轉圖人工比對標題、內文、表格、浮水印,排版與原本一致、無缺字;126 項測試全數通過。詳見 `docs/SECURITY_CHECKLIST.md`「第三方元件清冊(SBOM)」一節。
- **V4 提前完成的項目(尚未走完整個 V4,但這幾項已經做完):**
  - 課堂紀錄附件:系辦確認需要後補上,`ClassRecord` 新增選填 `attachment` FileField(`migration tutoring/0014`),限 PDF/JPG/PNG、最大 500 KB。把原本 `validate_qualification_file()` 的副檔名檢查抽成共用的 `_validate_upload()`,新增的 `validate_class_record_attachment()` 只是換一個 500 KB 的上限,避免重複驗證邏輯。`ClassRecordForm` 用一般 `FileInput`(不是 `ClearableFileInput`),刻意不提供「清除附件」的 UI——重新提交表單但不選新檔案時會自動保留原本附件(這是 Django `FileField.clean()` 對 `initial` 的預設行為,不用額外寫程式處理),要移除只能用新檔案覆蓋,或請 Admin 從 Django Admin 後台處理,避免多做一個「清除」邏輯的複雜度。課程詳情頁與 Admin 課程詳情卡都加了附件下載連結(新增 `ClassRecord.attachment_filename` property 取乾淨檔名)。**異常回報(`IncidentReport`)附件確認不做**(2026-07-26 使用者確認目前不需要)。
  - Admin 個人總覽(行政檔案):比照舊版「從名單查看個資、資格、配對與部分紀錄」概念,新增 `accounts:admin_user_profile` 唯讀彙整頁,單一 Tutor/Tutee 的基本資料、Profile、資格狀態(Tutor)、全部學期配對紀錄、依學期分組課程與時數、課堂通報/異常回報(各取最近 20 筆)一次看完,不用再切 Django Admin/課程總覽/不同頁籤。刻意不做任何操作按鈕,審核/核准/標記仍在原本頁面做,這頁只負責「看」,範圍已跟使用者確認過。入口是 Django Admin 學生名冊清單新增的「查看檔案」欄位連結。順手把 `profile()`/`matched_profile()`/新頁面共用的教學/學習 Profile 組裝邏輯抽成 `_role_profile_context()`,消除原本三處幾乎一樣的程式碼。
  - Admin 時數修正(HourAdjustment):比照舊版「管理員手動新增歷史時數」概念,但依使用者確認的兩個關鍵決定重新設計,**不沿用舊版建立無 Tutee 假課程的作法**——新增獨立 `tutoring.models.HourAdjustment` model(`migration tutoring/0015`):使用者、學期、合作計畫、時數、原因、建立者。①只能為正數(只能加不能扣,要扣時數用其他方式處理,例如取消對應課程);②只影響證明 PDF 的「總時數」,明細版逐筆列表完全不受影響、不會出現「補登 X 小時」這種列在正式文件上的字樣(`hour_report_data()` 把 `session_total`/`adjustment_total` 分開算再加總成 `total`,`build_hours_pdf()` 只讀 `total`)。判斷某筆調整算不算進某次下載,是看「調整所屬學期是否整個落在下載的日期範圍內」(`reporting.hour_adjustment_total()`),因為調整紀錄本身沒有日期只有學期。順手修正 `tutor_available_programs()`,讓「只有調整紀錄、資料庫沒有真實課程」的計畫也會出現在 Tutor 的下載下拉選單,不然補登的舊資料會變成看不到也下載不到。內部彙整頁(`accounts:admin_user_profile`)也加了一個「手動時數調整紀錄」區塊可以看到逐筆調整(明確標註僅內部稽核可見,不影響對外證明的呈現方式)。
  - 時數匯入(Excel/CSV 批次匯入 `HourAdjustment`):做完單筆版的「時數調整紀錄」後,使用者提出如果剛好有現成的 Excel 表,想直接匯入而不是一筆一筆手動輸入。做法比照既有名冊匯入的架構重新實作一份小的:`tutoring/services.py::import_hour_adjustments()` 讀兩欄 CSV/Excel(學號、時數,容忍標題列,邏輯跟 `accounts/services.py` 的名冊讀檔函式相似但沒有共用程式碼,避免跨 app 依賴內部私有函式),學期/合作計畫/原因在匯入表單上選一次套用到整批;採 all-or-nothing 驗證(任一列有問題整批不寫入),跟「時數調整紀錄」這種會影響證明時數的資料應有的嚴謹度一致,而不是像名冊快速匯入那樣靜默略過壞列。入口沒有另外開一個獨立頁面,而是用 `ModelAdmin.get_urls()` 掛進 Django Admin 的 `HourAdjustment` 清單頁(右上角「匯入 Excel」連結+一個範本下載連結),符合這個功能低頻率使用、目前只給 Admin 用的定位。成功匯入寫一筆彙總的 `HOUR_ADJUSTMENT_IMPORTED` AuditLog(不是每列各寫一筆)。
  - CI 與 lint:新增 `pyproject.toml`(`ruff` 設定,只開 `F`/`E9` 抓真的會出錯的問題,刻意不開風格/排序規則以免逼出一次跟功能改動無關的全庫重排版)、`requirements-dev.txt`(`-r requirements.txt` + `ruff`)、`.github/workflows/ci.yml`(Postgres service container,依序跑 `ruff check .`、`makemigrations --check --dry-run`、`python manage.py test`、`DJANGO_DEBUG=0 python manage.py check --deploy`,對 `main` 的 push 與所有 PR 觸發)。設定過程中用 `ruff check --select F,E9` 抓到 9 個既有的未使用 import(`accounts/views.py`、`tutoring/admin.py`、`tutoring/models.py`、`tutoring/reporting.py`、`tutoring/views.py`、`tutoring/tests.py`)與 2 個未使用區域變數,已用 `--fix` 自動修正並手動確認測試仍全數通過,避免 CI 一啟用就是紅的。
  - 證明 PDF 換成開放授權字型(見上方「已完成」字型換裝說明)。
  - 資安檢核表補強三項(`docs/SECURITY_CHECKLIST.md` 第 19、45、56、57 項):①新增 `AuditLog.record()` classmethod 取代所有 `AuditLog.objects.create()`,用 nested `transaction.atomic()`(savepoint)包住寫入,失敗只回滾這筆 insert、記錄到 `logging.getLogger("csl.audit")`,不會讓稽核紀錄寫入失敗連帶弄壞呼叫端原本的資料庫交易(`accounts/tests.py::AuditLogResilienceTests` 用 mock 模擬寫入失敗驗證外層交易不受影響)。②新增測試在 `DEBUG=False` 下故意讓一個 view 拋例外,驗證回應是 Django 內建通用 500 頁面、不含 traceback/專案路徑/例外訊息(`accounts/tests.py::ProductionErrorPageTests`),把原本「理論上符合但沒測過」的項目變成有證據的 ✅。③`requirements-dev.txt` 加 `pip-audit`,`.github/workflows/ci.yml` 新增依賴漏洞掃描 step——**掛上去當天就掃出真的問題**:`Pillow 11.3.0`、`pypdf 6.10.0` 都有已修復的已知 CVE,已於同日升級(見下方「已完成」)。
  - 升級 `Pillow`(11.3.0→12.3.0)與 `pypdf`(6.10.0→6.14.2)修復已知 CVE:`pip-audit` 掃出的漏洞升完版重跑掃描確認 0 已知漏洞,`.github/workflows/ci.yml` 的 `pip-audit` step 從非阻斷改回會擋 build。升級前確認過 Pillow 12.0 的破壞性變更(`ImageCms`/`fromarray()`/`ImageMorph`)專案完全沒用到,而且專案其實沒有任何程式碼直接 `import PIL`——`Pillow` 只是宣告的依賴,沒被直接呼叫,風險本來就低;pypdf 只用到穩定多年的 `PdfReader`/`PdfWriter`/`merge_page`/`add_page` 基本 API。升級後仍照 PDF 改動慣例重新產生 NTNU 摘要版/詳細版(含跨頁)PDF,用 Poppler 轉圖人工比對確認排版與升級前完全一致。
  - 閒置帳號標記(`docs/SECURITY_CHECKLIST.md` 第 3 項):Django Admin 的 `User` 清單新增「閒置帳號 / Idle account」篩選器(`accounts/admin.py::IdleAccountFilter`),可篩出 180 天以上未登入、或從未登入過的帳號。這項使用者明確選擇「只標記,不自動停用」(2026-07-26 AskUserQuestion 確認),原因是華語班有寒暑假,學生/老師超過門檻天數沒登入很正常,自動停用有誤鎖到還在配對期使用者的風險;要不要停用由 Admin 自行判斷,系統只負責讓 Admin 容易找到候選名單。
  - Django Admin 後台操作整合進 `AuditLog`(`docs/SECURITY_CHECKLIST.md` 第 15 項):新增 `accounts/signals.py::mirror_admin_log_entry_to_audit_log()`,監聽 Django 內建 `admin.LogEntry` 的 `post_save` 訊號,把後台每一筆新增/修改/刪除都鏡射寫進 `AuditLog`。選用訊號而非逐一改每個 `ModelAdmin`,是因為這樣自動涵蓋所有目前與未來註冊的 model,不用擔心漏改。修改對象若本身是 `User`,`target_user` 會指向該使用者。已知的小取捨:`HourAdjustment` 這種原本就有專屬 `AuditLog` 事件的動作,現在會多一筆通用的鏡射紀錄(兩種 `event_type` 不同,不會互相干擾既有的 `.get()` 查詢),刻意不做去重,因為對唯讀稽核表而言,多一筆冗餘遠比漏記划算。
- **2026-08 系辦會議後 20 項需求 — 第一批(低風險/獨立項目,見 `docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md`)：**
  - 第 1 項:系統更名為「華語實習暨輔導系統 / Mandarin Practicum and Tutoring System」(MPTS),更新所有使用者可見畫面(登入品牌區、Dashboard 頁首/頁尾、HTML title、Django Admin 標題、證明/匯出檔名、README);系所本身的 `CSL`(Chinese as a Second Language)縮寫與內部 Python 識別字(`CSLLoginView`、`CSLUserAdmin`)不變。
  - 第 2 項:安全問題題庫拆成 `QUESTION_CHOICES`(全部,回復密碼用)與 `ACTIVE_QUESTION_CHOICES`(排除 3 題已停用題目,新註冊用),停用/改字/新增各如上述,已用回歸測試鎖住「新註冊不能選停用題目」與「舊帳號仍可用停用題目復原密碼」兩種情境。
  - 第 6 項:「資格證明/資格審核」全面改稱「口語能力證明/口語能力審核」,僅改使用者可見文案與 Admin 欄位名稱,`QualificationDocument`/`QualificationStatus` 等 Python 識別字不變。
  - 第 8 項:註冊與 `/profile/` 新增暱稱(選填)、Email(必填,僅格式驗證,不寄信)欄位;中英文姓名欄位下方加註「將顯示於時數證明,請填寫正式姓名」提示。
  - 第 9 項:Tutor/Tutee 註冊與編輯個人資料頁的時段選項下方,加註「其他時間請配對後與對方討論」的雙語提示。
  - 第 10 項:解除配對自動處理期限由「3 天未處理」改為「連續 48 小時未處理」(`PAIRING_AUTO_RELEASE_HOURS`),所有畫面/訊息/手冊/測試同步移除「三天」字樣,新增 47:59/48:00 邊界測試。
  - 第 17 項:Admin 資料匯出新增 `.pdf` 格式(`build_export_pdf()`,ReportLab `platypus.SimpleDocTemplate` 自動分頁的橫向報表,已人工檢視多頁輸出),移除舊版 Excel 2003 XML `.xls` 格式與 `build_excel_xml()`。
  - 第 18 項:`ClassRecord.content`/`.remarks` 新增 2000 字元上限(model `max_length` + 表單 `maxlength`,前後端一致),`topic` 既有上限與已棄用的 `reflection` 欄位不受影響。
  - 第 19 項:移除 `HourAdjustment` 的批次 Excel 匯入入口(URL、view、表單、範本下載、清單頁按鈕與對應測試皆刪除);model、既有資料與單筆新增/編輯功能不受影響,AuditLog 描述文字改為「行政更正」用語,不再暗示用來匯入舊紙本時數。
  - 第 20 項:`docs/PROGRESS.md`「尚未定案的產品/維運決策」與 `docs/DEPLOY.md`「上線前仍待確認」都已明確列出個資/口語能力證明/課堂紀錄/私訊/證明 PDF/AuditLog 的保存政策與 RPO/RTO 待系辦/資訊中心確認,程式未新增任何依假設年限刪除資料的邏輯。
  - 尚未排入這一批的項目(3、4、5、7、11–16)留待後續批次;第 15 項(資料模型地基)已於第二批完成,見下。
- **2026-08 系辦會議後 20 項需求 — 第二批(進行中,見 `docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md`)：**
  - 第 15 項(計畫別、可重疊執行期間)**已完成**,是第 4、12、13、16 項的資料模型地基:
    - `Semester` 新增可為空的 `program` FK(`None` = 舊版共用期間,保留給既有資料與尚未指定計畫的期間相容用;新建立的期間表單一律要求選計畫,編輯既有期間仍可不選)與 `applicable_users` M2M(留空 = 該計畫所有符合資格帳號都適用,不需要為舊資料回填名單)。
    - 重疊檢查改成「同一 `program` 值內才擋」,移除原本「目前與未來最多三個學期」的全域筆數上限(model、`SemesterCreateForm`/`SemesterSettingsForm`、`accounts:dashboard` 的 `configured_non_past_semester_count` 判斷、admin_v2_panels.html 的 3/3 提示與手冊文字都已同步移除)。
    - 新增 `tutoring/services.py::active_semester(program=None)`(取代原本無參數版本,優先找計畫專屬且啟用中的期間,找不到才退回舊版共用期間)、`semester_applies_to_user()`、`user_program()` 三個小工具,`dashboard()` 的 `matching_open` 與 `send_invitation()` 都已改用,依當事人(Tutee)所屬計畫決定要看哪個期間。
    - `Semester.validate_applicable_users()` 擋下非 Tutor/Tutee、已停用帳號,以及計畫不符的 Tutee(Tutor 目前不受計畫限制,因為還沒有第 4 項的修課名單機制)。
    - 新增 `tutoring.tests.ProgramScopedSemesterTests`(9 個測試)涵蓋:可建立超過三筆期間、同計畫重疊擋下/不同計畫重疊放行、舊版共用期間彼此仍擋重疊、`active_semester()` 的計畫優先/退回邏輯、同一使用者可同時適用多計畫多期間、空白適用對象等於開放給所有人、適用對象驗證擋下計畫不符的 Tutee、`send_invitation()` 會選到計畫專屬期間而非不相關的舊版期間。另外用真實 HTTP 流程(登入、建立 NTNU 與 Maryland 重疊期間、嘗試建立同計畫重疊期間)驗證過一次,行為與測試一致。
    - 尚未涵蓋(留給第 12、13、16 項一併處理):排課/時數統計/證明下載目前仍直接讀 `Pairing.semester`,不會重新判斷「此刻該用哪個期間」。候選瀏覽依計畫名單過濾已由第 4 項補齊,見下。
  - 第 4 項(馬里蘭學生與大學部 Tutor 專屬配對)**已完成**:
    - 名冊匯入頁籤每個啟用中合作計畫新增一張「{計畫}修課 Tutor」卡片(`accounts:roster_import_quick` 的 `category_code` 用 `TUTOR:<程式碼>`),把 Tutor 學號匯入時一併設定 `RosterEntry.program`——沿用 Tutee 早就在用的同一個欄位與匯入流程,`RosterEntry.clean()` 原本就沒有禁止 Tutor 設定 `program`,只是先前的匯入介面沒有入口,所以完全不需要新 model 或新 migration。
    - 新增 `tutoring/services.py::tutor_can_serve_program(tutor, program)` 作為唯一判斷依據:沒有修課名單的一般 Tutor 只服務 NTNU;有修課名單的 Tutor 只服務名單所屬計畫,馬里蘭計畫額外要求 `education_level=BACHELOR`(不只看學制,因為不是所有大學部生都修這門課,見需求文件原文)。同一條規則同時套用在 `anonymous_tutee_candidates()`、`anonymous_tutor_candidates()`、`send_invitation()`(不論誰發起邀請,不能繞過畫面直接呼叫成功),確保「看不到」跟「配不到」永遠一致。
    - `user_program()`(第 15 項引入)同步更新為也認得有修課名單的 Tutor,讓他們的「目前適用期間」判斷正確對應到該計畫,不會被誤判成一般 Tutor。
    - 新增 `tutoring.tests.MatchingFixtureTestCase`(抽出共用 fixture,避免測試類別互相繼承導致重複執行)、`MarylandTutorRosterTests`(6 個測試,涵蓋一般 Tutor 看不到/配不到馬里蘭學生、馬里蘭 Tutor 看不到/配不到 NTNU 學生、名單內但學制不符會被擋下、一般配對不受影響)與 `accounts.tests` 新增 1 個測試驗證修課名單匯入正確寫入 `RosterEntry.program`。修正既有 `MatchingTests` 5 個測試(原本的假設是任何合格 Tutor 都能配對馬里蘭學生,已改用具備修課資格的 Tutor fixture)。另外用真實 HTTP 匯入一筆馬里蘭修課 Tutor 學號驗證過一次。
  - 第 12 項(Admin 為合作計畫額外手動配對)**已完成**(第一階段規格):
    - Dashboard「配對管理」頁籤新增「Admin 手動配對」表單(`AdminPairingForm`,選 Tutor/Tutee/期間),送出後呼叫 `tutoring/services.py::create_admin_pairing()` 直接建立 `Pairing`,不經過邀請/接受;`Pairing` 新增 `created_by` 欄位(`migration tutoring/0019`)只在這個路徑被設定,標示是哪位 Admin 建立的,一般邀請流程建立的維持 `None`。
    - 除了「不需要邀請」,其餘檢查(角色、帳號啟用、`tutor_can_serve_program()` 計畫名單、期間 `applicable_users`、Tutee 是否已有 active Tutor、是否重複配對)與一般邀請流程共用同一套規則——**明確和使用者確認過**:Admin 不能藉此繞過第 4 項的計畫限制。
    - 名額規則採使用者確認的「同學期總量上限 3 位」版本(而非「每計畫各自 +1」):`tutor_has_admin_pairing_capacity()` 對 NTNU 維持原本 2 位上限,非 NTNU 合作計畫可以讓 Admin 多建立第 3 位;一般邀請流程的 `tutor_has_capacity()` 完全沒有變動,只有走這個新功能才可能到 3 位。時數上限(每組每週 2 小時/每組 32 小時/Tutor 每學期 64 小時)刻意不變,先當 fallback,不猜測計畫別新數字。
    - 新增 `tutoring.tests.AdminPairingTests`(6 個測試):一般使用者呼叫會被擋下(service 層與 view 層各一個)、Admin 可直接建立配對且正確標記 `created_by`、非 NTNU 計畫可以拿到第 3 位、NTNU 無法拿到第 3 位、計畫名單與重複配對檢查依然生效。另外用真實登入+表單送出驗證過「NTNU 滿額被擋下」與「非 NTNU 正常建立」兩種情境。
  - 第 13 項(時數證明語言選擇)**已完成**:
    - 下載區「選擇資料範圍」卡片新增證明語言單選(`HoursDownloadForm.language`,`zh`/`en`,預設中文),UI 沿用既有 `.candidate-filter-chips`/`.chip-check` 樣式,沒有新增 CSS class。`build_hours_pdf()` 新增必填的 `language` 參數,依語言只呈現該語言的標題/內文/表格表頭/日期格式(中文用民國紀年、英文用西元),不再像舊版同時把中英標題疊在同一張證明上;標題改成單行置中(y=623),取代原本中文 y=635/英文 y=612 的雙行堆疊排版。
    - `PartnerProgram` 新增 `tutee_certificate_plan_name_en`/`tutee_certificate_activity_text_en`/`tutor_certificate_plan_name_en`/`tutor_certificate_activity_text_en` 四個欄位(`migration accounts/0011`,既有 `plan_name`/`activity_text` 欄位維持不變、視為隱含中文,不做 `_zh` 改名以降低遷移風險),`migration accounts/0012` 資料遷移為既有 NTNU/MARYLAND/OTHER 三筆計畫回填英文文案草稿。缺少所選語言文案時擋下並顯示「請洽系辦設定」錯誤,不會產生中英夾雜的證明。
    - 姓名顯示規則維持雙語例外(不受證明語言影響):兩個姓名都有就顯示「中文姓名 / English Name」,只有一個就只顯示該一個、不留斜線,新增 `display_name_markup()` 統一實作此規則,NTNU Tutor 特例分支也一併套用(先前只顯示中文姓名,已修正)。
    - 除錯過程中用 curl 對真實 dev server 產生 PDF 並人工檢視,抓到一個規則的實作 bug:`mixed_font_markup()`/`display_name_markup()` 原本用 `<b>` 標籤加粗中文姓名,但 ReportLab 的 `<b>` 是透過 Paragraph 預設字型的 `registerFontFamily()` 對應表解析粗體字型;英文證明段落預設字型是 `CertificateSerif`(Liberation Serif,無中文字符),其粗體對應也是純西文字型,導致英文證明上的中文姓名被靜默吃掉(只剩「/ Jamie Chen」,中文名整個消失)。修正方式是兩個函式都改成用明確的 `<font name="...">` 指定中/英文字型,不再依賴 `<b>` 解析,不受所在段落預設字型影響。
    - 檔名與 `AuditLog`(`HOURS_PDF_PREVIEWED`/`HOURS_PDF_DOWNLOADED`)的 `metadata` 都新增記錄所選語言。
    - 新增 `tutoring.tests.PartnerProgramCertificateTests` 內 7 個新測試涵蓋:語言影響檔名與 AuditLog metadata、英文證明只出現英文文字與西元日期(不含民國/中文標題)、雙姓名在中英文證明都正確顯示(這條直接鎖住上述修正的 bug,防止回歸)、單姓名在中英文證明都不留斜線、NTNU Tutor 與一般計畫兩種分支缺少英文文案時都正確擋下並顯示「請洽系辦設定」、英文詳細版使用英文表頭與 `Page X of Y` 分頁文字。舊有 6 個測試因 `language` 改為必填欄位補上 `"language": "zh"`。已用 curl 對 dev server 下載 NTNU Tutor(特例分支)與 Maryland Tutor(通用分支)各 4 種語言/版本組合的真實 PDF,轉圖人工檢查排版、姓名顯示、表頭語言、頁碼文字皆正確(含前述 bug 修正前後的對照)。
  - 第 16 項(計畫別、角色別證明標題與文案)**已完成**:盤點後發現「Admin 可依合作計畫 × 角色 × 語言設定標題與內文」這個資料模型與大部分渲染邏輯其實已經在 V3 的 `PartnerProgram` 重構與第 13 項一起做完了(標題、`plan_name`、`activity_text` 皆為 Admin 可編輯欄位,新增計畫不需改程式);真正缺的是**驗證邏輯沒有精準對應各分支實際會讀取哪些欄位**:
    - 原本 `build_hours_pdf()` 的缺文案檢查只驗證中文路徑的 `title`,完全沒檢查中文的 `plan_name`/`activity_text`;若 Admin 只填了標題卻漏填內文,中文證明會悄悄產生帶空白子句的證明(如「「」」),而不是清楚的「請洽系辦設定」錯誤。
    - 同時,英文路徑不分分支一律要求 `plan_name_en`/`activity_text_en` 非空,但 `is_ntnu_tutor` 特例分支的內文完全寫死、從不讀取這兩個欄位,導致這個分支被完全用不到的欄位誤擋下(目前 NTNU 因 migration `accounts/0012` 已回填英文文案而未觸發,是隱性風險而非目前的實際故障)。
    - 修正:驗證邏輯改成依 `is_ntnu_tutor` 精準比對——該分支只驗證所選語言的 `title`;其餘分支(Tutee 版、非 NTNU 的 Tutor 版)驗證所選語言的 `title`+`plan_name`+`activity_text` 三者皆非空,與實際渲染時讀取的欄位完全對齊。
    - 電子章、主管簽名、系辦最終正式模板確認**尚未實作也不應自行偽造**,已補充記錄於 `CLAUDE.md` 4.9 節,作為待系辦提供正式資產前的明確邊界。
    - 新增 3 個測試:中文路徑缺 `plan_name`/`activity_text` 各自正確擋下並顯示「請洽系辦設定」(鎖住上述修正)、`is_ntnu_tutor` 分支即使四個 `plan_name`/`activity_text`(中英)全部留空,中英文皆仍可正常下載(回歸防呆,避免驗證邏輯之後又被改回「一律要求」)。
  - 第 5 項(合作計畫「上課文件」)**已完成**(第一階段規格):
    - 新增 `tutoring.models.ClassDocument`(`migration tutoring/0020`):合作計畫(必填,`PROTECT`)、適用學期(選填,`SET_NULL`,留空代表適用該計畫所有學期)、中英文標題、檔案、是否啟用、上傳者、上傳時間。檔案格式與大小另外寫一個 `validate_class_document_file()`(擴充既有 `_validate_upload()` 加上可自訂允許副檔名/錯誤文案的參數,不影響既有兩個呼叫端的預設行為),允許 PDF/Word/PowerPoint/Excel/JPG/PNG、上限 10 MB,比口語能力證明(1 MB)、課堂紀錄附件(500 KB)更寬,符合課程教材通常較大的實際狀況。
    - `PartnerProgram` 新增 `class_documents_enabled` 布林欄位(`migration accounts/0013`,預設 `False`),決定該計畫是否開放此功能,新增計畫或之後要讓 NTNU 開放都只需要在 Django Admin 打開這個欄位,不需要改程式;`migration accounts/0014` 依會議紀錄「第一階段顯示對象:馬里蘭 Tutee、馬里蘭課程名單中的大學部 Tutor」只把 `MARYLAND` 設為 `True`。
    - 新增 `tutoring/services.py::visible_class_document_programs(user)`:Tutee 直接看 `user_program(user)`;Tutor 對每個已開放此功能的計畫呼叫既有的 `tutor_can_serve_program()`(第 4 項同一個函式,含馬里蘭限定大學部規則),確保「看得到上課文件」與「配得到該計畫學生」的資格判斷共用同一套邏輯,不會分岔出第二套規則。`visible_class_documents(user)` 在此之上再過濾 `is_active=True`。
    - 新增 `accounts/context_processors.py::class_documents_menu()`(已註冊進 `config/settings.py` 的 `TEMPLATES.context_processors`),讓使用者選單(`templates/components/app_header.html`)能在橫跨 `accounts`/`tutoring` 兩個 app、共 9 個不同 view 的頁面上一致顯示或隱藏「上課文件」項目,不需要逐一修改每個 view 的 context(這是本專案第一個自訂 context processor)。
    - 新增 `accounts:class_documents`(列表頁)與 `accounts:download_class_document`(下載,`role_required(TUTOR, TUTEE)` + 資格檢查 + `AuditLog.record(event_type="CLASS_DOCUMENT_DOWNLOADED")`)兩個 view。下載刻意走獨立 view 而非直接連到 `file.url`,因為驗收條件明確要求「下載行為需保留稽核紀錄」——這是本專案第一個「下載需要稽核」的檔案類型,既有的口語能力證明、課堂紀錄附件下載都只是直接連到 media URL,沒有經過任何 view,不會產生 `AuditLog`。
    - 上傳/管理留在 Django Admin(`tutoring/admin.py::ClassDocumentAdmin`),沒有另開自訂前台上傳頁面,符合低頻率使用的定位;Admin 後台操作已由既有的 `mirror_admin_log_entry_to_audit_log()` 訊號自動鏡射進 `AuditLog`。
    - 新增 `tutoring.tests.ClassDocumentTests`(9 個測試,繼承 `MatchingFixtureTestCase` 共用 fixture):馬里蘭 Tutee/大學部 Tutor 可見馬里蘭計畫、NTNU Tutee 與一般 Tutor(隱含服務 NTNU)皆看不到任何計畫(因為 NTNU 這一階段未開放)、馬里蘭名單但非大學部的 Tutor 看不到(鎖住與第 4 項相同的限制規則)、`visible_class_documents()` 正確排除停用文件與不合資格計畫、文件列表頁只列出合資格且啟用中的文件、選單顯示與資格判斷一致、合資格使用者下載成功並正確寫入 `AuditLog`、不合資格使用者下載回 404、停用文件即使對合資格使用者也回 404。另外用 curl 對 dev server 做過一次真實端到端驗證:馬里蘭 Tutee 登入後選單出現「上課文件」、可看到並下載測試文件(檔名、`Content-Disposition: attachment`、PDF 內容皆正確);切換到一般 NTNU Tutee 登入後選單不顯示該項目,且直接猜網址下載會被擋下回 404。
  - 第 7 項(進入個人檔案前再次確認學號)**已完成**:
    - 第一階段(`accounts:register`)成功建立 `RegistrationDraft` 後,不再直接依角色導向 `/register/tutor/`/`/register/tutee/`,而是先導向新增的 `/register/confirm/`(`accounts:register_confirm`),清楚列出學號,要求按「確認學號正確」才會被導向對應的第二階段表單;按「返回修改」則回到第一階段。
    - 確認狀態是 session 裡的一個布林旗標(`registration_confirmed`),`_role_registration()`(第二階段共用 view)一開始就檢查這個旗標,沒確認一律導回確認頁,不管是直接用網址列開啟第二階段網址、或重新整理確認頁多次都不會意外建立帳號。確認本身完全不動 `RegistrationDraft.expires_at`,原本 30 分鐘的時效不受影響。
    - 抽出 `_pending_registration(request)`(不檢查角色)供確認頁與既有 `_registration_roster(request, expected_role)`(檢查角色,供第二階段 view 使用)共用核心的草稿有效性檢查,避免兩處各寫一份邏輯。既有的「GET `/register/` 時清掉舊草稿」邏輯同步也清掉確認旗標,確保用瀏覽器返回鍵回到第一階段永遠是乾淨重來。
    - 修正既有 5 個測試(`RegistrationTests`/`AccountRecoveryTests`)在第一、二階段之間補上確認步驟的 POST,否則會卡在確認頁收不到預期的重新導向;新增 6 個測試涵蓋驗收條件本身:未確認不得直接開啟第二階段網址、確認頁正確顯示學號且不建立帳號、重新整理確認頁多次不建立帳號、返回第一階段會清掉草稿導致第二階段網址不可用、確認不會延長草稿時效、確認頁在沒有有效草稿時導回第一階段。另外用 curl 對 dev server 做過一次真實端到端驗證(第一階段→確認頁→直接猜第二階段網址被擋下→確認後才能正常進入第二階段表單)。
  - 第 3 項(PDF 限制選取與複製)**已完成**:
    - 新增 `tutoring/reporting.py::_restrict_copy_and_selection()`,用 `pypdf.PdfWriter.encrypt()` 只授予 `PRINT`/`PRINT_TO_REPRESENTATION` 權限、其餘(含 `EXTRACT`/`MODIFY`)一律禁止;`user_password=""` 代表不需密碼即可開啟,`owner_password` 是每次呼叫時隨機產生、用完即丟(系統本身不需要也不會再解除限制)。`build_hours_pdf()`(時數證明)與 `build_export_pdf()`(Admin 匯出 PDF)回傳前都會套用這道處理,兩種本模組會產生的 PDF 都受影響。
    - 刻意不指定 `encrypt()` 的 `algorithm=` 參數(維持 pypdf 預設的 RC4-128),因為這裡要的是「相容性優先的權限限制」而非「機密性」,RC4-128 對舊版 PDF 閱讀器的相容性比 AES-256 更廣;已在 `CLAUDE.md` 明確記錄「這只是依賴閱讀器配合的權限旗標,不是真正的 DRM,無法防止螢幕截圖、OCR 或忽略權限旗標的工具」的技術界線,避免對外誤宣稱為絕對防拷貝。
    - 新增 2 個測試:`PartnerProgramCertificateTests.test_certificate_pdf_restricts_copy_but_allows_printing`(直接呼叫 `build_hours_pdf()`,確認 `reader.is_encrypted`、`extract_text()` 不需密碼即可成功、`PRINT`/`PRINT_TO_REPRESENTATION` 權限存在、`EXTRACT`/`MODIFY` 權限不存在);擴充既有 `V2FeatureTests.test_admin_export_can_produce_pdf` 補上同樣的權限斷言。另外用 curl 對 dev server 下載真實的時數證明(單頁)與 Admin 匯出 PDF(兩頁),以 `pdfinfo`/`pdftoppm` 確認:兩者皆回報 `Encrypted: yes (print:yes copy:no change:no)`、不需密碼即可用 Poppler 轉圖、視覺排版與加密前完全一致(含多頁匯出報表的表頭重複與分頁)。
  - 第 11 項(配對後顯示暱稱與 Email)**已完成**:
    - `accounts:matched_profile`(配對後完整個人資料頁,`templates/accounts/matched_profile.html`)基本資料區塊新增暱稱、Email 兩欄,直接讀取 `counterpart.nickname`/`counterpart.email`,沒有另外的權限判斷——因為這個 view 本身早就只在雙方有 `ACTIVE` 配對時才會回應 200,查無配對直接 `Http404`(既有行為,未修改),等於天然只有配對雙方能看到這兩個新欄位。
    - 私訊頁(`templates/tutoring/messages.html`)對方名稱區的 `<h1>` 名稱下方新增一行 Email(`{{ counterpart.email }}`)。私訊頁本身允許 `ENDED` 配對唯讀查看歷史(既有行為,見第 4.8 節),因此 Email 也比照對方真實姓名(`bilingual_name`)既有的顯示邏輯,配對結束後仍會留在歷史對話頁面,不特別為這個新欄位做「配對結束後在私訊頁隱藏」的特例——這是刻意的一致性選擇,不是遺漏,已記錄在 `CLAUDE.md` 4.3 節。
    - 配對前的匿名候選卡片、邀請詳情、篩選結果皆不受影響(這些模板本來就沒有讀取 `nickname`/`email`/`name_zh`/`name_en`/`username` 等身分欄位,不需要額外的隱藏邏輯);`CLAUDE.md` 4.3 節「配對前不得顯示」清單新增「暱稱」一項,明確涵蓋這個欄位。
    - 新增/擴充 4 個測試:擴充 `MatchingTests.test_tutee_can_expand_anonymous_teacher_information_from_received_invitation` 設定 Tutor 的暱稱/Email 後,確認配對前的匿名邀請詳情不會外流這兩個欄位;擴充 `test_active_pair_can_open_each_others_full_profile` 確認配對後雙方個人資料頁正確顯示彼此的暱稱/Email(暱稱刻意選用不是任何 fixture 真實姓名子字串的值,避免斷言誤判成功);新增 `V2FeatureTests.test_messages_page_shows_counterparts_email_next_to_their_name` 確認私訊頁對方名稱區顯示 Email。另外用 curl 對 dev server 做過端到端驗證:配對雙方的個人資料頁與私訊頁皆正確顯示暱稱/Email,同時確認未配對的候選卡片清單沒有外流測試帳號刻意設定的暱稱/Email 字串。
  - 第 14 項(Tutor 課堂紀錄改用外部佐證連結)**已完成**(第二批最後一項,完成後系辦會議 20 項需求全數實作完畢):
    - 新增 `ClassRecord.evidence_links` JSONField(`migration tutoring/0021`,`list[str]`,`default=list`),保留既有 `attachment` 欄位不變(Tutee 仍用)。`tutoring/forms.py::ClassRecordForm` 新增 `author` 參數,依角色動態拿掉/保留 `attachment`/`evidence_links` 兩個欄位其中一個:Tutor 只有 `evidence_links`(必填),Tutee(或未傳 `author` 的呼叫端,視為 Tutee 形狀以維持既有測試相容)只有 `attachment`(選填,不變)。
    - 新增自訂 `EvidenceLinksField`/`EvidenceLinksWidget`:最少 1、最多 5 個連結,且每個都須為合法 `https://` 網址(`URLValidator(schemes=["https"])`,不限網域,Google Drive/YouTube 只是範例非白名單)。「至少 1 個」沿用 Django `required` 的標準空值檢查(空列表在 `Field.empty_values` 內),不另外寫自訂訊息;超過 5 個與網址格式錯誤才是自訂訊息。widget 讓每個連結都是共用 `name="evidence_links"` 的獨立 `<input type="url">`,靠 `value_from_datadict()` 用 `QueryDict.getlist()`(或一般 dict 傳 list 時的相容處理)收集回一個 list——這個 fallback 分支在直接用 `ClassRecordForm(data={...})` 建構、傳入純 Python list 的單元測試中曾經踩到一個 bug(把整個 list 當成單一元素塞進外層 list,對它呼叫 `.strip()` 就炸掉),已修正為先判斷 `isinstance(value, (list, tuple))`。
    - 新增 `static/js/class-record-links.js`(原生 DOM API + `data-*` hooks,無框架)讓 Tutor 可逐筆新增(clone 一列,最多 5 列)/刪除(至少留 1 列)欄位,純粹是前端便利性,真正的把關在伺服器端驗證。
    - `class_detail.html`/`admin_record_card.html` 顯示對方紀錄時改用「**資料是否存在**」(`{% if counterpart_record.evidence_links %}`)而非「作者角色」決定顯示連結還是附件——這是刻意設計,讓 2026-08 前的既有 Tutor 附件紀錄(合法歷史資料,`evidence_links` 會是空列表)仍可被看到,不會被新規則強制隱藏。連結一律 `target="_blank" rel="noopener noreferrer"` 開新分頁,符合驗收條件。
    - 系統不串接 Google Drive/YouTube API,不做連結有效性、權限或失效偵測;沿用既有雙方互相確認流程作為查核機制。
    - 新增 6 個測試(`ClassWorkflowTests`):Tutor/Tutee 表單欄位組成互斥、缺連結擋下、超過 5 個擋下、非 https 網址擋下、任意網域的合法 https 網址皆接受(不限 Drive/YouTube)、透過真實 view 送出後 `evidence_links` 依輸入順序存入且 Tutee 端能看到帶正確 `rel`/`target` 屬性的連結。其中最後一個 view 層級測試踩到一個時區陷阱:一開始直接用 `real_now.hour`/`real_now.minute`(UTC 時間)組出上課時間,但 `schedule_classes()` 是用 `Asia/Taipei` 本地時間解讀,導致算出的上課時間其實是「未來」判斷失敗;修正為先 `timezone.localtime(real_now)` 轉成本地時間再取 hour/minute。另外用 curl 對 dev server 做過端到端驗證:Tutor 畫面正確拿掉附件、換上連結欄位與新增按鈕;Tutee 畫面附件欄位不受影響;Tutor 送出 2 個連結後,Tutee 端正確看到兩個都帶 `target="_blank" rel="noopener noreferrer"` 的可點連結;Tutor 送出 0 個連結被正確擋下並顯示必填錯誤。
- **2026-08-08 名冊匯入卡片改為「以合作計畫為單位」**(20 項需求之外,使用者事後追加的 UI 調整):`templates/dashboard/admin_v2_panels.html` 的快速匯入卡片從「固定 Tutor 卡片 + 每計畫兩張卡片(Tutee、Tutor 修課名單各一張)」改成「每個啟用中 `PartnerProgram` 一張卡片,卡片內同時有 Tutor 名單與學生名單兩個上傳區塊」,對應系辦實際的心智模型(NTNU = 華語系碩班 Tutor + 師大外籍生 Tutee;MARYLAND = 限定大學部 Tutor + 馬里蘭 Tutee)。純模板/CSS 改動,`accounts:roster_import_quick` view 與 `import_roster_ids()` 完全未變:NTNU 卡片的 Tutor 區塊沿用既有的 `category_code="TUTOR"`(即 `RosterEntry.program=None`,對應 `tutor_can_serve_program()` 把無計畫 Tutor 隱含視為服務 NTNU 的既有規則),其餘計畫沿用既有的 `category_code="TUTOR:<程式碼>"`;新增計畫的流程不變,仍是先在 Django Admin 新增 `PartnerProgram`。已用真實 HTTP 流程(登入 Admin、對 NTNU/MARYLAND 兩個計畫各自的 Tutor/Tutee 兩個上傳區塊各匯入一筆測試學號)驗證四種組合都正確寫入對應的 `role`/`program`。
- **2026-08-11 快速名冊匯入支援「學號＋身分別」**:依系辦實際 `ST101總名單1150805-給華語系.xlsx` 格式,`accounts/services.py::import_roster_ids()` 改讀前兩欄,接受「入學身份」中的僑生、港澳生、陸生、外國學生等值並轉為系統身分代碼;新增 `IdentityCategory.MAINLAND`(陸生 / Mainland Chinese student,migration `accounts/0018`)。舊單欄檔仍相容。重新匯入只會補既有空白身分別,不覆蓋非空白值;未知值略過並提示。實際比對 2,371 個唯一學號後,已補齊 2,370 筆空白身分,1 筆原本即相同,無衝突、無新增學號。新增測試涵蓋兩欄解析、五種身分映射、空白回填、不覆蓋及未知身分略過。
- migrations:`accounts` 14 個、`tutoring` 21 個(第 3、7、11 項皆純屬邏輯/模板變更,無 model 異動;第 14 項新增 1 個 model 欄位;名冊匯入卡片改版無 model 異動)。
- tests:**每次開發前建議重新執行 `python manage.py test` 確認實際數字**,不同 session 間可能因外部改動而變化,不在此維護容易過期的固定數字。
- ~~已知不穩定測試~~:**2026-08-08 已修正**(弱掃整改批次 0,見下方新段落)。`test_schedule_reserves_weekly_quota_and_dashboard_shows_class` 原本用「今天+1 天、今天+2 天」推算兩堂課日期,週六執行時兩者會跨到不同的週一至週日區間,導致每週 2 小時上限的 `ValidationError` 沒被觸發而失敗。已改為錨定在未來某週固定的週二/週三,不論執行當天是星期幾都同週且必為未來日期,已用 7 種星期模擬驗證。
- 順手修正一個與先前改動無關的既有測試斷言:`test_summary_and_detailed_certificate_use_pdf_template` 檢查的證明書標題文字是舊版(「輔導實習時數證明書」),證明 PDF 模板早已更新為「實習證明」,測試斷言沒同步更新,已改為比對目前正確標題。
- **多數項目仍只用 Django test client 驗證過,尚未完成整套真實瀏覽器 golden path 人工驗收。**目前已用瀏覽器驗證學期編輯/刪除,並抽查登入頁與 Tutor 註冊頁的手機版響應式排版;另用 `curl` 模擬真實登入/表單提交流程(取 CSRF token、帶 session cookie)對「使用手冊」頁面、`.xlsx`/`.csv` 匯出做過端到端驗證(下載檔案分別用 `openpyxl`/`file`/`xxd` 確認格式與內容正確)。候選篩選、邀請/配對、排課至互認等其餘完整情境仍應安排一次瀏覽器 golden path,不能只靠 test client/curl 累積信心。

### 2026-08-08 起:師大資訊中心網站弱點掃描前整改(見 `docs/VULNERABILITY_SCAN_IMPROVEMENTS.md`)

進行中,依該文件第 8 節的批次順序執行,批次 7(註冊本人驗證)因涉及業務規則決策,等系辦回覆前不動,不阻擋其他批次:

- **批次 0(建立乾淨基準)已完成**:補上缺少的 `accounts/migrations/0015_alter_rosterentry_identity_category.py`(`IdentityCategory.LOCAL` 標籤文字調整,無資料影響);修正上方提到的週六排課測試。
- **批次 1(套件升級與 Demo seed 雙重防呆)已完成**:
  - `pypdf` 6.14.2→6.15.0,修復 `pip-audit` 新掃出的 CVE-2026-71852、CVE-2026-71870,`pip-audit` 重跑確認 0 已知漏洞。重新產生 NTNU Tutor 摘要版/詳細版(含跨頁)、Maryland Tutee、Admin 匯出 PDF,用 Poppler 轉圖比對排版、字型、加密權限旗標(`Encrypted: yes (print:yes copy:no)`)皆與升級前一致。
  - 新增 `accounts/management/commands/_demo_guard.py::ensure_demo_seed_allowed()`(檔名底線開頭,Django 的 `find_commands()` 會自動排除,不會被誤判成一條指令),所有 6 個 `seed_*` 指令(`seed_demo`、`seed_test_roster`、`seed_matching_demo`、`seed_admin_demo`、`seed_v2_demo`、`seed_v2_time_demo`)改用同一個共用檢查,要求同時滿足 `DEBUG=True` **且**環境變數 `ALLOW_DEMO_SEED=1` 才可執行,不再只檢查 `DEBUG`——原本 `seed_demo.py`/`seed_test_roster.py` 完全沒有防呆,其餘 4 個只檢查 `DEBUG`,任何一項正式主機誤設 `DJANGO_DEBUG=1` 都會讓這些指令可執行。`seed_demo.py` 的風險是意外建立一個持續存在的高權限 `DEMO-ADMIN`(注意:密碼由執行者以 `--password` 提供,不是寫死明碼,風險是「帳號長期存在」而非「密碼外流」);`seed_test_roster.py` 的風險是污染正式名冊、留下可被公開自行註冊的 `TEST-*` 身分。這屬於維運防呆,防的是操作者手滑,不是外部攻擊者(攻擊者若已能執行伺服器管理指令,直接下 `createsuperuser` 更快)。新增 `accounts/tests.py::DemoSeedGuardTests`(4 個測試,涵蓋全部 6 個指令):`DEBUG=True` 但缺 `ALLOW_DEMO_SEED`會擋、`ALLOW_DEMO_SEED=1` 但 `DEBUG=False` 會擋、兩者皆缺會擋、兩者皆滿足才會真的執行。
  - `.github/workflows/ci.yml` 新增 `schedule: cron: "0 3 * * 1"`(每週一),即使當週沒有 push/PR 也會重跑含 `pip-audit` 的完整 CI,避免「新 CVE 出現但沒人 push 觸發 CI」的空窗——這次的 `pypdf` 新 CVE 正是手動執行 `pip-audit` 才發現,凸顯排程掃描的實際必要性。
  - `docs/SECURITY_CHECKLIST.md` 第 56、57 項與 SBOM 表格已同步更新 pypdf 版本與掃描狀態,第 57 項由 🟡 升級為 ✅。
- **批次 2(正式環境設定 fail closed)已完成**:`config/settings.py` 在 `DEBUG=False` 時新增 fail-closed 檢查——缺少 `DJANGO_SECRET_KEY`、金鑰仍等於開發用 `DEV_SECRET_KEY_FALLBACK`、`POSTGRES_PASSWORD` 空白、`DJANGO_ALLOWED_HOSTS` 為空/`*`/僅 localhost 皆會拋出 `ImproperlyConfigured` 拒絕啟動;新增 `DJANGO_CSRF_TRUSTED_ORIGINS` 環境變數解析。`docs/DEPLOY.md` 補上這些檢查的說明,並明確記錄 `SECURE_PROXY_SSL_HEADER` 只有在 Nginx 確實清除並重設用戶端來源 header 時才可信,偽造的 `X-Forwarded-Proto` 不應被信任。新增 `config/tests.py`(以 `importlib.reload` 重新載入設定模組的方式測試)涵蓋上述每種缺漏情境。
- **批次 3(私人附件改為受保護下載)已完成**:口語能力證明新增 `accounts:download_qualification` view(僅文件本人與 Admin,共用新的 `_private_file_response()` helper),課堂紀錄附件新增 `tutoring:download_class_record_attachment`(僅該堂 Tutor/Tutee 與 Admin);`templates/accounts/admin_user_profile.html`、`templates/dashboard/index.html`、`templates/tutoring/class_detail.html`、`templates/tutoring/admin_record_card.html` 移除直接輸出 `file.url`,改連到受保護 view。新上傳檔案改用 `_uuid_upload_path()` 產生的 UUID 伺服器端檔名(`qualification_upload_to`/`class_record_attachment_upload_to`/`class_document_upload_to`),原始檔名另存 `original_filename`/`original_attachment_filename` 欄位僅供介面顯示,不影響既有歷史檔案路徑。下載回應加上 `Content-Disposition: attachment`、`Cache-Control: private, no-store`、`X-Content-Type-Options: nosniff`。新增未登入、非本人、非配對成員、無關 Tutor/Tutee 的越權測試。
- **批次 4(Django Admin 安全邊界)已完成**:`Pairing`、`MatchingInvitation`、`ClassSession`、`Attendance`、`ClassRecord`、`ClassConfirmation`、`MakeupReview`、`PairingReleaseRequest` 等 8 個核心業務 model 的 `ModelAdmin` 加上 `ReadOnlyAdminMixin`(覆寫 `has_add_permission`/`has_change_permission`/`has_delete_permission` 一律回傳 `False`,刻意不覆寫 `has_view_permission`,因為 Django 預設實作不會委派給 `has_change_permission`,超級使用者的檢視權限不受影響),防止透過 Django Admin 繞過 service 層規則直接寫入配對/排課/簽到資料。Admin 登入表單換成 `ThrottledAdminAuthenticationForm`,套用與主站登入相同的共享節流。`docs/DEPLOY.md` 補上 Nginx 對 `/system-admin/` 的 IP/VPN 限制設定範本(尚待實際網段驗證)。新增測試涵蓋:一般 Tutor/Tutee 無法進入 Django Admin、上述 8 個 model 透過 Admin 表單提交新增/修改會被拒絕但仍可檢視/篩選、超級使用者的唯讀檢視不受影響。
- **批次 5(登入、名冊查詢與帳號恢復共享節流)已完成**:
  - 新增 `django.core.cache.backends.db.DatabaseCache`(PostgreSQL 資料表 `django_cache_table`,經 `accounts/migrations/0016_create_cache_table.py` 以 `call_command("createcachetable")` 建立),取代預設 `LocMemCache`,讓節流計數跨 Gunicorn worker 共享且重啟不消失。
  - 新增 `accounts/throttle.py` 共用節流 helper(`is_throttled`/`any_throttled`/`register_failure`/`register_failures`/`clear_throttles`),登入、Admin 登入、帳號恢復、名冊查詢(`RegistrationLookupForm.clean_student_id()`,新增,原本完全沒有節流)統一改用雙層節流:IP+學號/識別碼(5 次/15 分鐘)+ 識別碼跨 IP(20 次/15 分鐘),避免同一 NAT 下不同學號互相鎖住,同時攔截跨 IP 的分散式嘗試。
  - 新增 `TRUSTED_PROXY_COUNT` 設定(環境變數 `DJANGO_TRUSTED_PROXY_COUNT`,預設 `0`),`client_ip()` 改為只有設定可信 proxy 層數時才解析 `X-Forwarded-For`,否則一律採信 `REMOTE_ADDR`,不再直接信任用戶端可偽造的第一個 `X-Forwarded-For` 值。`deploy/nginx/proxy_params_mpts.conf` 對應改用 `proxy_set_header X-Forwarded-For $remote_addr;`(明確覆寫,非附加),因為 Nginx 是本部署拓樸中唯一、直接相連的可信一跳(Gunicorn 只監聽 Unix socket)。
  - 新增測試涵蓋:不同可信 proxy 層數設定下 `client_ip()` 的解析結果、IP+學號與跨 IP 兩層節流各自的觸發與獨立性、共享 cache backend 跨模組請求皆讀到相同計數、名冊查詢節流。
- **批次 6(輸入、輸出與瀏覽器安全)已完成**:
  - `tutoring/models.py::_validate_upload()` 擴充真實內容驗證:JPG/PNG 用 Pillow `Image.open()`/`verify()` 並限制最大解析尺寸(`MAX_IMAGE_DIMENSION_PX = 6000`,避免解壓縮炸彈);PDF 檢查檔頭與結構並限制頁數(`MAX_PDF_PAGES = 500`);Office 檔案檢查 ZIP 結構與實際格式;皆不再只信任副檔名或瀏覽器回報的 `Content-Type`。
  - 新增 `tutoring/reporting.py::_spreadsheet_safe_value()`/`_spreadsheet_safe_rows()`,對以 `=`/`+`/`-`/`@` 開頭的使用者可控制匯出文字(學號、中英文姓名等)加前置單引號轉義,`build_excel_xlsx()`/`build_export_csv()` 皆套用同一套規則,防止 CSV/XLSX 公式注入。
  - 新增 `accounts/middleware.py::PrivateNoStoreMiddleware`,為 Dashboard、Profile、matched profile、課堂、私訊、Admin、私人附件、PDF/Excel/CSV 匯出等敏感回應統一加上 `Cache-Control: private, no-store`,避免登出後瀏覽器上一頁重新顯示可操作的敏感頁面快取。
  - 新增 `accounts/middleware.py::ContentSecurityPolicyMiddleware`,移除 `templates/accounts/register_confirm.html` 的 inline style、`templates/accounts/admin_tutor_schedule.html` 的 inline `onchange`、`templates/dashboard/admin_v2_panels.html` 的 inline `onsubmit`,改為外部 CSS class 與 `addEventListener` 綁定。2026-08-10 複核模板與靜態資源後,已由 Report-Only 切換為正式強制 CSP(無 `unsafe-inline`),並加上 `Permissions-Policy`。
  - 新增測試涵蓋:公式注入字串在 CSV/XLSX 皆被正確轉義且一般中英文姓名/學號不受影響、假造內容(HTML 改名 `.pdf`、超大尺寸圖片、損壞圖片、內容與副檔名不符)皆被拒絕而合法檔案仍可上傳、敏感頁面回應皆帶有 `Cache-Control: private, no-store`、CSP header 存在且政策內容正確。
- **批次 8(VM 前置部署準備文件,不需實際 VM 的部分)已完成**:新增 `deploy/` 目錄,含 `gunicorn.conf.py`、`nginx/mpts.conf.example`、`nginx/proxy_params_mpts.conf`、`systemd/mpts-gunicorn.service`、`systemd/mpts-process-matching-state.service`+`.timer`、`.env.production.example`;`requirements.txt` 新增 `gunicorn==26.0.0`;`docs/DEPLOY.md` 補齊完整的部署、升級、回滾、備份與故障排除說明(runbook)。取得實際 VM/DNS/正式網段後才能完成的項目(DNS、TLS 憑證、`CSRF_TRUSTED_ORIGINS` 實值、防火牆、SSH 來源限制、PostgreSQL localhost 限制、NFS 備份、監控、還原演練、壓力測試)仍是待辦,見下方「已知缺口」。
- **批次 7(註冊本人驗證)仍暫停**,等待使用者向系辦確認一次性註冊碼、Admin 核准或其他驗證方案,不阻擋其他批次。
- **2026-08-17 已完成正式 VM 首次部署**(資訊中心分配,`https://mpts.tcsl.ntnu.edu.tw/`,`140.122.64.169`):套件安裝、服務帳號、PostgreSQL(TCP 127.0.0.1,見下方 peer auth 註記)、Gunicorn+systemd、Nginx、Let's Encrypt TLS(含續約 hook)、`/system-admin/` VPN 網段白名單皆已在真實 VM 上驗證可用,細節與過程中修正的環境落差記在 `docs/DEPLOY.md`「首次部署實際踩過的坑」。另有 `docs/VM_UPDATE_WORKFLOW.md`(後續更新 SOP,含 detached HEAD 部署原則)與 `docs/PRE_DEPLOYMENT_CHECK_2026-08-17.md`(部署前的自動化+瀏覽器 golden path 驗收快照)。已建立正式 Admin 帳號並實測登入成功。已建立每日本機備份(`deploy/backup_mpts.sh`+`mpts-backup.timer`,03:15 執行 `pg_dump`+`media/` 打包,保留 14 天,已實測還原到一次性測試資料庫並核對筆數一致,細節見 `docs/DEPLOY.md`「備份與還原」);**這只是本機磁碟備份,不是異地備援**,異地/NFS 備份仍待資訊中心確認可用位置。尚未設定監控告警、尚未送弱掃、名冊尚未匯入;批次 9(送弱掃前的正式環境收尾:移除 demo 帳密、建立掃描用測試帳號、監控告警、正式弱掃)仍需等批次 7 定案後才能視為完整關閉。
- **2026-08-10 弱掃前再複核補強**:`PrivateNoStoreMiddleware` 擴充到未登入的登入/註冊/帳號恢復/設定新密碼流程;CSP 正式強制並加入 `Permissions-Policy`;Nginx 範本加入 `server_tokens off`、TLS 1.2/1.3、TLS 1.2 cipher allowlist、請求/連線限制與 client/proxy timeout。完整 273 項測試全數通過。實際 VM 的 DNS、憑證、網段、防火牆、NFS、監控、X-Accel-Redirect、備份還原與正式 AppScan 仍列在批次 9。
- migrations(本輪弱掃整改新增):`accounts` 新增 `0015`(身分類別 choices 文字調整,無資料影響)、`0016`(建立共享 cache 資料表,`RunPython` 呼叫 `createcachetable`);`tutoring` 無新增(批次 0-8 皆為邏輯/設定/模板變更)。累計 `accounts` 16 個、`tutoring` 22 個 migration。
- **2026-08-10 已將本輪弱掃整改(批次 0-6、8,共 9 個 commit)push 至 `origin/main`**;push 前發現遠端多了一個本機沒有的 merge commit(`c79c898`,GitHub PR UI 上合併已在本機以 fast-forward 整合過的分支),經 `git merge-base`/`git diff --stat` 確認內容完全相同後以一般 `git merge`(非 rebase/force-push)整合,零內容差異,合併後重跑完整測試套件(272 項全數通過)、`ruff check .`、`makemigrations --check --dry-run` 皆乾淨才 push。

## 版本規劃

### V4:正式上線與行政營運(目前進行中)

V3/V3.1 核心業務功能已完成,V4 的重心轉為「讓系統真的能在校方 VM 上對外服務」,以及收尾少數還沒做完的功能缺口:

1. **學校資安檢核與 VM production artifacts(V4 核心,本機可完成項目已完成)**:取得師大資訊中心的「資通系統防護基準檢核表」等文件後,已逐條對照 CSL 現況整理成獨立的 **`docs/SECURITY_CHECKLIST.md`**。登入/名冊/帳號恢復/Django Admin 節流已改用 PostgreSQL 共享儲存,並完成可信 proxy 判定與 Nginx 覆寫 X-Forwarded-For 範本;另已完成 session 閒置登出、私人附件權限、上傳真實內容驗證、CSV/XLSX 公式防護、敏感頁禁止快取、強制 CSP/Permissions-Policy、依賴稽核及正式環境 fail-closed。實際部署 checklist(WSGI server、Nginx、HTTPS/TLS、systemd、備份、監控)仍在 `docs/DEPLOY.md`;VM 規格、DNS、憑證、正式網段與弱點掃描尚待學校 VM 到位後完成。註冊本人驗證方式另待系辦決策。
2. **密碼效期與密碼歷程(檢核表第 33、34 項)**:實作方式已想清楚(見下方說明),但**開發前務必先跟系辦確認全校是否已有密碼政策**,避免系統自己訂一套跟校方规定衝突或重複的規則。若確認要做:
   - 效期:`User` 新增 `password_changed_at` 欄位,註冊/改密碼時更新;比照 `django.contrib.auth.middleware` 的模式寫一個輕量 middleware,登入後若 `now - password_changed_at` 超過政策天數(例如 90 天),強制導向改密碼頁面才能繼續使用系統。
   - 歷程:新增 `PasswordHistory` model(user、password_hash、created_at),改密碼時把新密碼分別跟最近 3 筆歷史雜湊比對(用 `django.contrib.auth.hashers.check_password`,不能明文比對),相同就擋下;成功變更後把最舊的一筆歷史紀錄清掉,只保留最近 3 筆。
   - 兩者都要注意:`createsuperuser`、Django Admin 直接改密碼、`set_recovered_password`(忘記密碼流程)都要一併納入更新 `password_changed_at`/寫入 `PasswordHistory`,不能只處理登入頁的改密碼表單。
3. **視系辦後續需求評估**:站內通知中心、per-program 時數上限例外、`HourAdjustment` 是否需要支援負數(更正場景)等,都先觀察是否真的有需求再決定要不要做,不預先開發。

### 舊版功能取捨

- **新版已取代且不重做:**Dashboard 側欄、Profile、匿名邀請、解除配對、排課、簽到、課堂紀錄、補登、通報、學期、時數、PDF、資料匯出及配對私訊。
- **已沿用概念並以 Django 重寫、且已完成:**候選篩選(Tutor 瀏覽 Tutee 與 Maryland Tutee 瀏覽 Tutor 兩側)、私訊摘要、輔導類型標籤、課堂紀錄附件、Admin 使用者總覽、安全的時數調整帳(含 Excel 批次匯入)。
- **不沿用:**Email 驗證、100 小時門檻、證明申請/再次核發、09:00–19:00 限制、舊版硬編碼檔案管理、未完成的 WebSocket 線上狀態、建立假課程補時數。

## 已知缺口 / TODO

- 已完成 Git 初始化並 push 至私有 remote(`https://github.com/Karma-1827/CSL.git`),且已有多次 commit 可追溯;精確數量請以 Git 指令為準,不在文件內維護容易過期的固定數字。尚未建立正式的分支/PR 流程慣例。
- 正式 VM 部署、服務管理、HTTPS proxy、備份、監控、RPO/RTO 尚未落地(V4 核心項目,細節見 `docs/DEPLOY.md`)。
- **資安檢核表(`docs/SECURITY_CHECKLIST.md`)裡還有 23 項「未實施」**,其中密碼效期與歷程限制需要先跟系辦確認全校政策才能決定要不要做。詳見該文件「總結與行動優先序」一節。
- **V3/V3.1/V4 尚未完成完整真人瀏覽器 golden path 驗收。**目前只有學期編輯/刪除與登入/註冊響應式排版抽查已經過瀏覽器驗證;仍應依序驗收名冊匯入卡片、兩階段註冊、候選篩選、邀請/配對、排課、簽到、課堂紀錄與附件、互認、補登、通報、私訊、時數下載、Admin 個人總覽、時數調整與匯入。
- Profile 編輯沒有配對當下的快照機制;配對成立後若一方修改聽說讀寫程度或可上課時段,對方看到的資料會即時變動,是否需要快照或提示尚未定案。
- 資格文件只是一個通用 upload＋Admin 結果;大學/碩士/博士各自可接受的證明種類尚未建成資料欄位或規則。
- Maryland PDF 底圖的英文標題原檔含重複字樣 `Certificate of Certificate of Language Exchange Hours`;這是底圖內容,程式目前未修正。
- 兩份底圖的 PDF 結構會令 pypdf 輸出 `Ignoring wrong pointing object ...` 警告;目前產物與測試正常,但換正式模板時應重新檢查/最佳化 PDF。

## 尚未定案的產品/維運決策

- **名冊更新後的帳號狀態:**目前名冊匯入只會新增學號或略過重複學號，不會比對「上次名冊有、這次消失」的學號，也不會自動停用已註冊帳號；因此被移出新名冊的既有使用者仍可登入。待系辦確認應採「自動停用」、「保留」或「人工判斷」後，再回寫決策並實作對應流程。
- **資料保存政策(待系辦/資訊中心確認,`docs/MEETING_CHANGE_REQUIREMENTS_2026-08-04.md` 第 20 項)：**尚未取得以下正式答案,系統目前不會、也不應在答案確定前自行寫死刪除年限或新增自動刪除排程:
  - 個資、口語能力證明文件、課堂紀錄(含未來的 Tutor 外部佐證連結)、私訊、正式證明 PDF 與 AuditLog 各自應保存多久。
  - 佐證連結的「階段結束後至少保留 10 天」只是使用者提示層級的最低要求(見第 4.6 節相關功能上線後的說明),不等於整體資料庫保存政策。
  - 未來若真的要做資料清理,必須同時滿足稽核需要、法律/校務規定與備份資料的一致性,不能只看單一資料表。
- 正式 RPO、RTO、備份頻率與維運窗口交接(同上,待系辦/資訊中心確認;見 `docs/DEPLOY.md`、`docs/SECURITY_CHECKLIST.md` 第 24/27/28 項)。
- 各學制 Tutor 的正式資格證明清單及是否必須在註冊時上傳。
- 新合作學校/計畫的治理機制(`PartnerProgram`)已就緒,但實際要接哪個新計畫、時數上限是否要有 per-program 例外、Tutor 版證明模板由誰提供,仍待系辦逐案決定。
- 最終正式 PDF 文字、簽章、日期與模板是否需校方再核准。
- `HourAdjustment` 目前刻意設計為「只能加不能扣」;若之後真的出現需要往下更正時數的實際案例,要不要開放負數、或維持「扣時數一律改走取消課程」的原則,留待真的遇到再決定。
- 系統正式安全等級尚待系辦/資訊中心核定(初估「中」,見 `docs/SECURITY_CHECKLIST.md`);以及忘記密碼流程用「學號＋安全問題＋10 分鐘時效」取代 email/簡訊一次性 token 的替代設計,是否能被認可為符合「密碼重設機制」控制項(該文件第 37 項)。
