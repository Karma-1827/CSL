# PROGRESS.md

本文件記錄專案的開發進度、已知缺口與尚未定案的產品/維運決策。這是「會頻繁變動」的內容,從 `CLAUDE.md` 拆出以減少每次 agent 啟動時的 context 負擔。

> 最後盤點日期:2026-07-21
> 下列數字(migrations、tests 數量)是盤點當下的快照,**每次開發前建議重新跑一次確認**,見 `CLAUDE.md` 的「文件維護與同步機制」一節。

## 已完成

- V0:名冊式兩階段註冊、三角色、登入/登出、三安全問題恢復、Profile、資格文件、Admin 基礎管理、雙語響應式 UI、安全設定。
- V1/V1.1:匿名候選資料、資格門檻、雙向邀請、五日逾期、名額限制、接受/拒絕/取消、配對後完整 Profile、解除配對與三日自動解除、個人資料/手冊、私訊入口。
- V2:學期管理、24 小時/五分鐘排課、每週重複、額度限制、取消/改期、雙方簽到、雙方紀錄、互認、補登與 Admin 審核、課堂通報、Admin 課程總覽、老師個人課表、時數歷史、PDF 證明、Admin `.xls` 匯出、pairing 私訊。
- migrations:`accounts` 4 個、`tutoring` 9 個。
- tests:`accounts` 18 個、`tutoring` 39 個,共 57 個。

## 已知缺口 / TODO

- 沒有 Git repository/commit history;開始多人協作前應初始化 Git、建立私有 remote,且先清除 demo/個資並檢查 `.gitignore`。
- 正式 VM 部署、服務管理、HTTPS proxy、備份、監控、RPO/RTO 尚未落地(細節見 `docs/DEPLOY.md`)。
- 沒有名冊 Excel/CSV 批次匯入 UI;目前靠 Django Admin 或程式 seed/key-in。
- `/profile/` 目前唯讀,沒有一般使用者修改 Profile 的流程與審核政策。
- 資格文件只是一個通用 upload＋Admin 結果;大學/碩士/博士各自可接受的證明種類尚未建成資料欄位或規則。
- `OTHER` 合作計畫的邀請權限尚未定案:目前能下載合作證明,但不能像 Maryland 主動邀請。
- 使用手冊標示 V1.1,內容尚未完整加入 V2 排課、簽到、紀錄、補登、時數證明與私訊說明。
- 私訊非即時且無通知;是否需要未讀 badge/Email/推播尚未決定(外部通知目前屬系統邊界外)。
- Admin 只能查看 active 課堂通報,沒有「Admin 已處理/處理備註」工作流。
- Excel 只有 `.xls` XML;CSV/真正 `.xlsx`/其他格式未做。
- Maryland PDF 底圖的英文標題原檔含重複字樣 `Certificate of Certificate of Language Exchange Hours`;這是底圖內容,程式目前未修正。
- 兩份底圖的 PDF 結構會令 pypdf 輸出 `Ignoring wrong pointing object ...` 警告;目前產物與測試正常,但換正式模板時應重新檢查/最佳化 PDF。
- `README.md` 只完整列到 V1,且啟動 port 是 8000;與目前 V2 實作、日常 8001 驗收不同,後續應同步更新。
- 尚無 CI、Python formatter/linter/type checker 設定。

## 尚未定案的產品/維運決策

- 真實資料量、保存期限與刪除政策。
- 正式 RPO、RTO、備份頻率與維運窗口交接。
- 各學制 Tutor 的正式資格證明清單及是否必須在註冊時上傳。
- 新合作學校/計畫的邀請權限、時數上限與證明模板。
- 最終正式 PDF 文字、簽章、日期與模板是否需校方再核准。
