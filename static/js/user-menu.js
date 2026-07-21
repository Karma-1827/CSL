(() => {
  document.querySelectorAll("[data-account-menu]").forEach((menu) => {
    const trigger = menu.querySelector("[data-account-menu-trigger]");
    const popover = menu.querySelector("[data-account-menu-popover]");
    if (!trigger || !popover) return;

    const close = () => {
      popover.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    };
    const open = () => {
      popover.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
    };

    trigger.addEventListener("click", () => (popover.hidden ? open() : close()));
    document.addEventListener("click", (event) => {
      if (!menu.contains(event.target)) close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !popover.hidden) {
        close();
        trigger.focus();
      }
    });
  });
})();
