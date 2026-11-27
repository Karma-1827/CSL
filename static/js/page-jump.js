/*
 * 分頁「直接輸入頁數」(2026-11-27,使用者要求全站所有分頁都能輸入頁數)。
 * 各分頁列(nav.simple-pagination)在伺服器端只輸出「目前頁 / 總頁數」文字,並帶 data-page-param
 * (頁碼的查詢參數名稱)、data-page-current、data-page-total。這支腳本把文字換成數字輸入框,
 * 按 Enter 後以該列既有的「上一頁/下一頁」連結為底(保留所有搜尋/篩選參數與頁籤 hash)改掉頁碼參數再前往,
 * 超出範圍自動取最前/最後一頁。沒有 JS 時維持原本的純文字,上一頁/下一頁照常可用。
 * 站台 CSP 啟用 Trusted Types:只用 DOM API 建立元素,不寫入 HTML。
 */
(() => {
  "use strict";

  const setup = (nav) => {
    const param = nav.dataset.pageParam;
    const total = parseInt(nav.dataset.pageTotal, 10);
    const current = parseInt(nav.dataset.pageCurrent, 10);
    const label = nav.querySelector("span");
    const anchor = nav.querySelector("a[href]");
    if (!param || !label || !anchor || !(total > 1)) return;

    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.max = String(total);
    input.value = String(current);
    input.className = "page-jump-input";
    input.setAttribute("aria-label", "頁數，按 Enter 前往 / Page number, press Enter to go");
    input.title = "輸入頁數後按 Enter / Type a page number and press Enter";

    const suffix = document.createElement("span");
    suffix.textContent = "/ " + total;

    const wrap = document.createElement("span");
    wrap.className = "page-jump";
    wrap.appendChild(input);
    wrap.appendChild(suffix);
    label.replaceWith(wrap);

    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      let page = parseInt(input.value, 10);
      if (Number.isNaN(page)) page = current;
      page = Math.min(Math.max(page, 1), total);
      if (page === current) return;
      const url = new URL(anchor.href, window.location.href);
      url.searchParams.set(param, String(page));
      window.location.assign(url.toString());
    });
  };

  const init = () => document.querySelectorAll("nav.simple-pagination[data-page-param]").forEach(setup);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
