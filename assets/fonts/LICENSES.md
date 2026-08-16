# 字型來源與授權

證明 PDF(`tutoring/reporting.py::build_hours_pdf()`)使用的字型,來源與授權如下。兩者皆為開放授權、可合法重新散布,取代先前直接從開發者 Mac 複製的 Windows/Office 授權字型(`Kaiu.ttf`、`TimesNewRoman.ttf`/`-Bold.ttf`,已移除)。詳見 `docs/SECURITY_CHECKLIST.md`「第三方元件清冊(SBOM)」一節。

## TW-Kai.ttf(標楷體/CertificateKai)

- 來源:國家發展委員會/數位發展部「全字庫」開放資料([data.gov.tw/dataset/5961](https://data.gov.tw/dataset/5961),下載自 <https://www.cns11643.gov.tw/opendata/Fonts_Kai.zip> 內的 `TW-Kai-98_1.ttf`,原始壓縮檔另含 `TW-Kai-Ext-B`/`TW-Kai-Plus` 兩個生僻字擴充檔,未使用)。
- 授權:字型檔內嵌授權聲明,使用者可擇一適用「政府資料開放授權條款第一版」或「SIL Open Font License 1.1版(OFL 1.1)」,兩者皆允許重製、散布與商業使用。
- 下載日期:2026-07-26。

## LiberationSerif-Regular.ttf / LiberationSerif-Bold.ttf(英文/數字/CertificateTimesNewRoman)

- 來源:Red Hat「Liberation Fonts」專案([github.com/liberationfonts/liberation-fonts](https://github.com/liberationfonts/liberation-fonts),2.1.5 版 release 附的 `liberation-fonts-ttf-2.1.5.tar.gz`)。
- 授權:SIL Open Font License 1.1(OFL 1.1),完整授權條文見同一份 release 內的 `LICENSE` 檔案。
- 與 Times New Roman **度量相容**(metric-compatible):字元寬高與 Times New Roman 一致,取代後不會讓既有 PDF 排版跑掉。
- 下載日期:2026-07-26。

## 本機私有證明素材（不進版控）

- `DFLiSongStd-W3/W5/W7.otf` 為華康儷宋體；其內嵌授權聲明限制安裝與轉交，不屬於本專案可公開散布的開源素材。
- `DFLiSongStd-W3/W5/W7.ttf` 是為 ReportLab 相容性在本機由上述 OTF 轉換的副本，沿用相同授權限制。
- `Helvetica Neue Condensed Bold.ttf` 為本機提供的 Helvetica Neue 字型，同樣不隨原始碼散布。
- 上述檔案與 `assets/certificates/` 內的系戳均由 `.gitignore` 排除。正式 VM 必須由有權使用這些素材的管理者另行放置；未放置時程式會使用開源字型，且不顯示系戳。
