# MPTS 正式部署前檢查紀錄（2026-08-17）

本文件記錄準備上傳學校 VM 前，針對目前工作目錄執行的程式、資安與瀏覽器驗收結果。這是一次性驗收快照；正式 DNS、TLS、Nginx、PostgreSQL、備份及監控仍須在 VM 上完成。

## 自動化檢查結果

| 檢查 | 結果 |
| --- | --- |
| Django 完整測試 | 291/291 通過 |
| `python manage.py check` | 通過 |
| `python manage.py check --deploy`（使用非正式檢查值） | 通過，0 issue |
| `makemigrations --check --dry-run` | 無遺漏 migration |
| 本機資料庫 migration | `accounts`、`tutoring`、Django 內建 migration 全部已套用 |
| Ruff | 通過 |
| `pip check` | 無相依性衝突 |
| `pip-audit --local` | 0 個已知漏洞 |
| `collectstatic --dry-run` | 成功辨識並可收集 137 個靜態檔案 |
| CSP inline 內容掃描 | 無 inline event handler、inline script 或 inline style block |
| 私有附件連結掃描 | Template 未直接輸出 media URL；仍由受保護下載 view 驗證權限 |

完整測試中出現的兩類訊息皆為既有、預期輸出，不是測試失敗：

- `Failed to write AuditLog ... boom`：測試刻意模擬稽核日誌寫入失敗，確認主要交易不會被連帶破壞。
- `Ignoring wrong pointing object ...`：既有證明 PDF 底圖的結構警告；產物與測試正常，之後換正式底圖時仍應重新最佳化。

## 瀏覽器 Golden Path 抽查

使用本機實際瀏覽器登入並巡查，頁面均可開啟，瀏覽器 console 無 error/warning：

- Tutor：首頁、課表、時數、私訊、尋找學生、邀請、口語能力證明。
- 一般 Tutee：首頁、課表、輔導紀錄、私訊、邀請。
- Maryland Tutee：尋找老師、個人資料選單、上課文件權限。
- Admin：總覽、口語能力審核、配對、解除審核、課堂通報、異常回報、補登審核、學期、全系課程、資料匯出、名冊匯入、系統紀錄。
- Django Admin 名冊：新的固定篩選列可見，身份、學生類別、所屬計畫及註冊狀態等篩選欄位均存在；複合篩選另有自動化測試。

本輪只做唯讀巡查，未在正式用途資料上新增配對、課程、簽到或審核結果；這些狀態轉換由完整測試套件覆蓋。

## 打包邊界

`deploy/build_release.sh` 只打包程式、migration、template、static、部署範本與文件，並明確排除：

- 本機 PostgreSQL 資料與任何資料庫 dump。
- `media/` 內的本機上傳及 Demo 文件（目前約 47 MB）。
- `.env`、真實密碼、Secret Key、Git/IDE/虛擬環境、cache、preview 與會議文件。
- 未納入正式程式的 DOC/DOCX。

私有授權字型與內部系戳預設不打包。只有確認為校內授權、且壓縮包只傳到受管控的學校 VM 時，才使用：

```bash
INCLUDE_PRIVATE_ASSETS=1 deploy/build_release.sh
```

不得把含私有素材的壓縮包上傳公開 GitHub、公開雲端空間或交給未授權人員。

## 上傳後仍未完成的事項

壓縮包可供上傳與安裝，但在以下事項完成前，不可視為已可公開上線：

1. 以真實值填妥 `/opt/mpts/.env`；不得直接使用範本的 `TODO`。
2. 以真實 DNS、TLS 憑證路徑、部署路徑、校內/VPN 網段填妥 Nginx 與 systemd 範本。
3. 建立全新的正式 PostgreSQL 資料庫，執行 migration；不可複製目前本機資料庫（目前含 23 個 Demo 使用者、24 筆 Demo 名冊及 12 堂 Demo 課）。
4. 建立正式 Admin；不得沿用本機 Admin/Demo 密碼。
5. 執行 `collectstatic`、啟用 Gunicorn 與 `process_matching_state` timer。
6. 設定 HTTPS、防火牆與 `/system-admin/` 校內/VPN 白名單。
7. 建立 PostgreSQL＋media 備份，完成至少一次獨立還原演練。
8. 設定 CPU、RAM、磁碟、HTTP 5xx、服務與備份失敗告警。
9. 以正式 HTTPS 網址完成登入後角色弱點掃描與手機/桌機人工驗收。
10. 系辦仍須確認「學號＋學生類別」是否足以作為註冊本人驗證；目前只能證明輸入資料與名冊一致，無法證明操作者本人持有該學號。

## 已知非阻斷項目

- 私有檔案目前可由 Django `FileResponse` 安全傳送；Nginx `X-Accel-Redirect` 尚未接線，屬正式環境效能優化，不是權限繞過漏洞。`/media/` 不可直接公開。
- PDF 底圖仍會產生 pypdf 結構警告，但測試與人工預覽正常。
- 資料保存期限、RPO、RTO、維運窗口與事件通報 SOP 仍需系辦／資訊中心書面定案。
