(() => {
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    const wrap = document.createElement("span");
    wrap.className = "password-toggle-wrap";
    input.insertAdjacentElement("beforebegin", wrap);
    wrap.appendChild(input);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "password-toggle-button";
    toggle.textContent = "顯示 / Show";
    toggle.setAttribute("aria-label", "顯示密碼 / Show password");
    toggle.setAttribute("aria-pressed", "false");
    wrap.appendChild(toggle);

    toggle.addEventListener("click", () => {
      const isHidden = input.type === "password";
      input.type = isHidden ? "text" : "password";
      toggle.textContent = isHidden ? "隱藏 / Hide" : "顯示 / Show";
      toggle.setAttribute("aria-pressed", String(isHidden));
      toggle.setAttribute("aria-label", isHidden ? "隱藏密碼 / Hide password" : "顯示密碼 / Show password");
    });
  });
})();
