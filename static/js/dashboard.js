(() => {
  const links = Array.from(document.querySelectorAll("[data-dashboard-target]"));
  const panels = Array.from(document.querySelectorAll("[data-dashboard-panel]"));
  const pageHeading = document.querySelector("[data-dashboard-page-heading]");
  const pageKicker = document.querySelector("[data-dashboard-page-kicker]");
  const pageTitle = document.querySelector("[data-dashboard-page-title]");
  if (!links.length || !panels.length) return;

  const available = new Set(panels.map((panel) => panel.dataset.dashboardPanel));

  function activate(target, options = {}) {
    const selected = available.has(target) ? target : "overview";
    panels.forEach((panel) => {
      const isSelected = panel.dataset.dashboardPanel === selected;
      panel.hidden = !isSelected;
      panel.classList.toggle("is-active", isSelected);
      panel.classList.toggle(
        "has-promoted-heading",
        isSelected && selected !== "overview"
      );
    });
    if (pageKicker && pageTitle) {
      if (selected === "overview") {
        pageKicker.textContent = pageHeading?.dataset.homeKicker || "HELLO";
        pageTitle.textContent = pageHeading.dataset.homeTitle || "你好！";
        pageHeading.classList.remove("is-section-heading");
      } else {
        const selectedPanel = panels.find((panel) => panel.dataset.dashboardPanel === selected);
        const sourceHeading = selectedPanel?.querySelector(":scope > .view-heading");
        const sourceKicker = sourceHeading?.querySelector(":scope > span");
        const sourceTitle = sourceHeading?.querySelector(":scope > h2");
        pageKicker.textContent = sourceKicker?.textContent?.trim() || "DASHBOARD";
        pageTitle.innerHTML = sourceTitle?.innerHTML || "";
        pageHeading.classList.add("is-section-heading");
      }
    }
    links.forEach((link) => {
      const isSelected = link.dataset.dashboardTarget === selected;
      link.classList.toggle("is-active", isSelected);
      if (isSelected) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    if (options.updateHistory !== false) history.replaceState(null, "", `#${selected}`);
    if (options.focus) {
      pageHeading?.scrollIntoView({ behavior: "auto", block: "start" });
    }
  }

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      if (!link.dataset.dashboardTarget) return;
      event.preventDefault();
      activate(link.dataset.dashboardTarget, { focus: true });
    });
  });

  window.addEventListener("hashchange", () => activate(location.hash.slice(1), { updateHistory: false }));

  document.querySelectorAll("[data-info-toggle]").forEach((button) => {
    const popover = button.parentElement?.querySelector("[data-info-popover]");
    if (!popover) return;
    button.addEventListener("click", () => {
      const willOpen = popover.hidden;
      document.querySelectorAll("[data-info-popover]").forEach((item) => { item.hidden = true; });
      document.querySelectorAll("[data-info-toggle]").forEach((item) => item.setAttribute("aria-expanded", "false"));
      popover.hidden = !willOpen;
      button.setAttribute("aria-expanded", String(willOpen));
    });
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest?.(".info-popover-wrap")) return;
    document.querySelectorAll("[data-info-popover]").forEach((item) => { item.hidden = true; });
    document.querySelectorAll("[data-info-toggle]").forEach((item) => item.setAttribute("aria-expanded", "false"));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("[data-info-popover]").forEach((item) => { item.hidden = true; });
    document.querySelectorAll("[data-info-toggle]").forEach((item) => item.setAttribute("aria-expanded", "false"));
  });

  const exportForm = document.querySelector(".data-export-form");
  if (exportForm) {
    const userPicker = exportForm.querySelector("[data-export-user-picker]");
    const userRows = Array.from(exportForm.querySelectorAll("[data-export-user-row]"));
    const userChecks = userRows.map((row) => row.querySelector('input[type="checkbox"]'));
    const selectedCount = exportForm.querySelector("[data-selected-user-count]");
    const scopeRadios = Array.from(exportForm.querySelectorAll('input[name="scope"]'));
    const periodRadios = Array.from(exportForm.querySelectorAll('input[name="period_mode"]'));
    const periodPanels = Array.from(exportForm.querySelectorAll("[data-export-period-panel]"));

    const updateSelectedCount = () => {
      const count = userChecks.filter((input) => input.checked).length;
      if (selectedCount) selectedCount.textContent = `${count} 位已選取 / selected`;
    };
    const selectScope = (value) => {
      const radio = scopeRadios.find((item) => item.value === value);
      if (radio) radio.checked = true;
      if (value === "all") {
        userChecks.forEach((input) => { input.checked = true; });
      } else if (userPicker) {
        userPicker.open = true;
      }
      updateSelectedCount();
    };
    scopeRadios.forEach((radio) => radio.addEventListener("change", () => selectScope(radio.value)));
    userChecks.forEach((input) => input.addEventListener("change", () => selectScope("selected")));
    exportForm.querySelector("[data-export-user-search]")?.addEventListener("input", (event) => {
      const query = event.target.value.trim().toLocaleLowerCase();
      userRows.forEach((row) => { row.hidden = Boolean(query) && !row.dataset.searchText.toLocaleLowerCase().includes(query); });
    });
    exportForm.querySelector("[data-select-visible-users]")?.addEventListener("click", () => {
      userRows.filter((row) => !row.hidden).forEach((row) => { row.querySelector('input[type="checkbox"]').checked = true; });
      selectScope("selected");
      updateSelectedCount();
    });
    exportForm.querySelector("[data-clear-export-users]")?.addEventListener("click", () => {
      userChecks.forEach((input) => { input.checked = false; });
      selectScope("selected");
      updateSelectedCount();
    });
    const updatePeriod = () => {
      const selected = periodRadios.find((item) => item.checked)?.value || "semester";
      periodPanels.forEach((panel) => { panel.hidden = panel.dataset.exportPeriodPanel !== selected; });
    };
    periodRadios.forEach((radio) => radio.addEventListener("change", updatePeriod));
    selectScope(scopeRadios.find((item) => item.checked)?.value || "all");
    updatePeriod();
  }

  document.querySelectorAll(".certificate-download-form").forEach((form) => {
    const versionRadios = Array.from(form.querySelectorAll('input[name="version"]'));
    const detailFields = form.querySelector("[data-certificate-detail-fields]");
    const updateCertificateVersion = () => {
      const version = versionRadios.find((item) => item.checked)?.value || "summary";
      if (detailFields) detailFields.hidden = version !== "detailed";
    };
    versionRadios.forEach((radio) => radio.addEventListener("change", updateCertificateVersion));
    updateCertificateVersion();
  });

  activate(location.hash.slice(1) || "overview", { updateHistory: false });
})();
