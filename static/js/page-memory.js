/*
 * 「回到原本位置」(2026-11-18,使用者回報「回到上一頁都不會留在原本的位置」)。
 * 與後端 accounts/navigation.py 搭配,詳細設計見該檔案開頭說明。這支 JS 做四件事:
 *   1. 點擊站內連結時,自動附上 ?back=<目前完整網址>(含分頁參數與頁籤 hash),
 *      詳情頁的「← 返回」就能回到原本的頁碼。
 *   2. 目前網址已帶 back 時,頁面上的 POST 表單也帶上 back,操作後導向才回得到原位置。
 *   3. 離開頁面時記下捲動位置與 <details> 的展開狀態(sessionStorage,只存數字與布林值)。
 *   4. 用瀏覽器「上一頁」或「← 返回」回來時,等頁籤顯示完畢後還原上述狀態。
 * 站台 CSP 啟用 Trusted Types:這裡不寫入任何 HTML(沒有 innerHTML 等),只讀寫網址與捲動位置。
 */
(() => {
  "use strict";

  const BACK_PARAM = "back";
  const MAX_URL_LENGTH = 1800;
  const DASHBOARD_PATH = "/dashboard/";
  const SKIP_PATH_PREFIXES = ["/static/", "/media/", "/system-admin/", "/logout/", "/protected-media/"];
  const STATE_PREFIX = "csl:page-memory:";
  const INDEX_KEY = "csl:page-memory-index";
  const RESTORE_NEXT_KEY = "csl:page-memory-restore-next";
  const MAX_ENTRIES = 40;

  const storage = (() => {
    try {
      const probe = "csl:page-memory-probe";
      window.sessionStorage.setItem(probe, "1");
      window.sessionStorage.removeItem(probe);
      return window.sessionStorage;
    } catch (error) {
      return null;
    }
  })();

  const normalize = (href) => {
    try {
      const url = new URL(href, window.location.href);
      if (url.origin !== window.location.origin) return "";
      return url.pathname + url.search + url.hash;
    } catch (error) {
      return "";
    }
  };
  const currentKey = () => normalize(window.location.href);

  const isSkippedPath = (pathname) => SKIP_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix));

  // ---- 1. 連結:自動附上 back ------------------------------------------------------------
  const tagLink = (anchor) => {
    if (!anchor || !anchor.getAttribute("href")) return;
    if (Object.prototype.hasOwnProperty.call(anchor.dataset, "noBack")) return;
    if (anchor.target === "_blank" || anchor.hasAttribute("download")) return;
    let url;
    try {
      url = new URL(anchor.href, window.location.href);
    } catch (error) {
      return;
    }
    if (url.origin !== window.location.origin) return;
    if (url.pathname === window.location.pathname) return; // 同一頁:分頁、頁籤、錨點
    if (url.pathname === DASHBOARD_PATH || isSkippedPath(url.pathname)) return;
    if (url.searchParams.has(BACK_PARAM)) return;
    url.searchParams.set(BACK_PARAM, currentKey());
    if (url.pathname.length + url.search.length + url.hash.length > MAX_URL_LENGTH) return;
    anchor.href = url.href;
  };
  // click:左鍵/Enter/Cmd+click;auxclick:中鍵;contextmenu:右鍵「在新分頁開啟」
  ["click", "auxclick", "contextmenu"].forEach((type) => {
    document.addEventListener(type, (event) => {
      const target = event.target instanceof Element ? event.target : null;
      tagLink(target ? target.closest("a[href]") : null);
    }, true);
  });

  // ---- 2. 表單:目前網址帶 back 時一併帶進 action ---------------------------------------------
  const pageBack = new URL(window.location.href).searchParams.get(BACK_PARAM) || "";
  if (pageBack) {
    document.querySelectorAll("form").forEach((form) => {
      if ((form.getAttribute("method") || "get").toLowerCase() !== "post") return;
      const rawAction = form.getAttribute("action");
      if (!rawAction) return; // 沒有 action 代表送回目前網址,back 已經在網址上
      let url;
      try {
        url = new URL(rawAction, window.location.href);
      } catch (error) {
        return;
      }
      if (url.origin !== window.location.origin || isSkippedPath(url.pathname)) return;
      if (url.searchParams.has(BACK_PARAM)) return;
      url.searchParams.set(BACK_PARAM, pageBack);
      form.setAttribute("action", url.pathname + url.search + url.hash);
    });
  }

  // ---- 3. 記錄捲動位置與展開狀態 -------------------------------------------------------------
  const readIndex = () => {
    try {
      const parsed = JSON.parse(storage.getItem(INDEX_KEY) || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  };
  const saveState = () => {
    if (!storage) return;
    const key = currentKey();
    if (!key) return;
    try {
      const details = Array.from(document.querySelectorAll("details"), (node) => node.open);
      storage.setItem(STATE_PREFIX + key, JSON.stringify({ y: Math.round(window.scrollY), d: details }));
      const index = readIndex().filter((item) => item !== key);
      index.push(key);
      while (index.length > MAX_ENTRIES) storage.removeItem(STATE_PREFIX + index.shift());
      storage.setItem(INDEX_KEY, JSON.stringify(index));
    } catch (error) {
      // sessionStorage 已滿或被停用時靜默略過,不影響頁面本身。
    }
  };
  const readState = (key) => {
    if (!storage) return null;
    try {
      const parsed = JSON.parse(storage.getItem(STATE_PREFIX + key) || "null");
      return parsed && typeof parsed.y === "number" ? parsed : null;
    } catch (error) {
      return null;
    }
  };
  window.addEventListener("pagehide", saveState);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveState();
  });

  // 「← 返回」與帶 back 的表單送出,都是用「新的導覽」回到列表,瀏覽器不會自動還原捲動,
  // 所以先記下「下一頁要還原哪個網址」。
  const setRestoreNext = (href) => {
    const key = normalize(href);
    if (storage && key) storage.setItem(RESTORE_NEXT_KEY, key);
  };
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const link = target ? target.closest("a.back-link") : null;
    if (link) setRestoreNext(link.href);
  }, true);
  document.addEventListener("submit", (event) => {
    if (pageBack && event.target instanceof HTMLFormElement) setRestoreNext(pageBack);
  }, true);

  // ---- 4. 還原 ----------------------------------------------------------------------------
  if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";

  let userScrolled = false;
  ["wheel", "touchstart", "keydown", "mousedown"].forEach((type) => {
    window.addEventListener(type, () => { userScrolled = true; }, { passive: true, once: true });
  });

  const restore = () => {
    const key = currentKey();
    const pending = storage ? storage.getItem(RESTORE_NEXT_KEY) : "";
    if (storage) storage.removeItem(RESTORE_NEXT_KEY);
    const navigation = (window.performance.getEntriesByType("navigation")[0] || {}).type;
    const shouldRestore = navigation === "back_forward" || navigation === "reload" || (pending && pending === key);
    if (!shouldRestore) return;
    const state = readState(key);
    if (!state) return;

    const nodes = Array.from(document.querySelectorAll("details"));
    if (Array.isArray(state.d) && state.d.length === nodes.length) {
      nodes.forEach((node, index) => { node.open = Boolean(state.d[index]); });
    }
    const scrollNow = () => {
      if (!userScrolled) window.scrollTo(0, state.y);
    };
    window.requestAnimationFrame(() => {
      scrollNow();
      window.requestAnimationFrame(scrollNow);
    });
    window.addEventListener("load", scrollNow, { once: true });
    window.setTimeout(scrollNow, 300);
  };

  // dashboard.js 等頁面腳本會在 DOMContentLoaded 前依網址 hash 顯示對應頁籤;
  // 等它們都跑完再還原,捲動高度才正確。
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", restore, { once: true });
  else restore();
})();
