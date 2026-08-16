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
    const programSelect = exportForm.querySelector("[data-export-program]");
    const userPicker = exportForm.querySelector("[data-export-user-picker]");
    const userRows = Array.from(exportForm.querySelectorAll("[data-export-user-row]"));
    const userChecks = userRows.map((row) => row.querySelector('input[type="checkbox"]'));
    const selectedCount = exportForm.querySelector("[data-selected-user-count]");
    const audienceRadios = Array.from(exportForm.querySelectorAll('input[name="audience"]'));
    const userSearch = exportForm.querySelector("[data-export-user-search]");
    const periodRadios = Array.from(exportForm.querySelectorAll('input[name="period_mode"]'));
    const periodPanels = Array.from(exportForm.querySelectorAll("[data-export-period-panel]"));
    const semesterSelect = exportForm.querySelector("[data-export-semester]");
    const semesterOptions = semesterSelect ? Array.from(semesterSelect.options) : [];
    const semesterEmpty = exportForm.querySelector("[data-export-semester-empty]");
    const fieldChecks = Array.from(exportForm.querySelectorAll('input[name="export_fields"]'));
    const selectedFieldCount = exportForm.querySelector("[data-selected-field-count]");

    const currentAudience = () => audienceRadios.find((item) => item.checked)?.value || "tutors";
    const isInSelectedProgram = (row) => {
      const programId = programSelect?.value || "";
      return (row.dataset.programIds || "").split(/\s+/).includes(programId);
    };
    const matchesAudience = (row, audience = currentAudience()) => {
      if (audience === "tutors") return row.dataset.role === "TUTOR";
      if (audience === "tutees") return row.dataset.role === "TUTEE";
      return true;
    };
    const updateSelectedCount = () => {
      const count = userChecks.filter((input) => input.checked && !input.disabled).length;
      if (selectedCount) selectedCount.textContent = `${count} 位已選取 / selected`;
    };
    const updateUserRows = ({ syncAudienceSelection = false } = {}) => {
      const audience = currentAudience();
      const query = userSearch?.value.trim().toLocaleLowerCase() || "";
      userRows.forEach((row) => {
        const input = row.querySelector('input[type="checkbox"]');
        const inProgram = isInSelectedProgram(row);
        const inAudience = matchesAudience(row, audience);
        const matchesSearch = !query || row.dataset.searchText.toLocaleLowerCase().includes(query);
        row.hidden = !inProgram || !inAudience || !matchesSearch;
        input.disabled = !inProgram;
        if (!inProgram) input.checked = false;
        if (syncAudienceSelection && audience !== "specific") {
          input.checked = inProgram && inAudience;
        }
      });
      if (userPicker) userPicker.open = true;
      updateSelectedCount();
    };
    const updateAudience = () => updateUserRows({ syncAudienceSelection: true });
    const updateProgramDependents = () => {
      const programId = programSelect?.value || "";
      updateUserRows({ syncAudienceSelection: currentAudience() !== "specific" });

      const matchingOptions = semesterOptions.filter((option) => {
        const optionProgram = option.dataset.programId;
        return optionProgram === programId || optionProgram === "shared";
      });
      semesterOptions.forEach((option) => {
        const enabled = matchingOptions.includes(option);
        option.hidden = !enabled;
        option.disabled = !enabled;
      });
      if (semesterSelect) {
        const currentIsAvailable = matchingOptions.some((option) => option.value === semesterSelect.value);
        semesterSelect.value = currentIsAvailable ? semesterSelect.value : (matchingOptions[0]?.value || "");
        semesterSelect.disabled = matchingOptions.length === 0;
      }
      if (semesterEmpty) semesterEmpty.hidden = matchingOptions.length > 0;
    };
    audienceRadios.forEach((radio) => radio.addEventListener("change", updateAudience));
    userChecks.forEach((input) => input.addEventListener("change", () => {
      const specific = audienceRadios.find((item) => item.value === "specific");
      if (specific) specific.checked = true;
      updateUserRows();
    }));
    userSearch?.addEventListener("input", () => updateUserRows());
    programSelect?.addEventListener("change", updateProgramDependents);
    exportForm.querySelector("[data-select-visible-users]")?.addEventListener("click", () => {
      const visibleChecks = userRows
        .filter((row) => !row.hidden)
        .map((row) => row.querySelector('input[type="checkbox"]'));
      const specific = audienceRadios.find((item) => item.value === "specific");
      if (specific) specific.checked = true;
      visibleChecks.forEach((input) => { input.checked = true; });
      updateUserRows();
    });
    exportForm.querySelector("[data-clear-export-users]")?.addEventListener("click", () => {
      const specific = audienceRadios.find((item) => item.value === "specific");
      if (specific) specific.checked = true;
      userChecks.forEach((input) => { input.checked = false; });
      updateUserRows();
    });
    const updatePeriod = () => {
      const selected = periodRadios.find((item) => item.checked)?.value || "semester";
      periodPanels.forEach((panel) => { panel.hidden = panel.dataset.exportPeriodPanel !== selected; });
    };
    periodRadios.forEach((radio) => radio.addEventListener("change", updatePeriod));
    const updateSelectedFieldCount = () => {
      const count = fieldChecks.filter((input) => input.checked).length;
      if (selectedFieldCount) selectedFieldCount.textContent = `${count} / ${fieldChecks.length} 欄已選取`;
    };
    fieldChecks.forEach((input) => input.addEventListener("change", updateSelectedFieldCount));
    exportForm.querySelector("[data-select-all-export-fields]")?.addEventListener("click", () => {
      fieldChecks.forEach((input) => { input.checked = true; });
      updateSelectedFieldCount();
    });
    exportForm.querySelector("[data-clear-export-fields]")?.addEventListener("click", () => {
      fieldChecks.forEach((input) => { input.checked = false; });
      updateSelectedFieldCount();
    });
    updateProgramDependents();
    updatePeriod();
    updateSelectedFieldCount();
  }

  document.querySelectorAll(".certificate-download-form").forEach((form) => {
    const versionRadios = Array.from(form.querySelectorAll('input[name="version"]'));
    const detailFields = form.querySelector("[data-certificate-detail-fields]");
    const summaryNote = form.querySelector("[data-certificate-summary-note]");
    const updateCertificateVersion = () => {
      const version = versionRadios.find((item) => item.checked)?.value || "summary";
      if (detailFields) detailFields.hidden = version !== "detailed";
      if (summaryNote) summaryNote.hidden = version === "detailed";
    };
    versionRadios.forEach((radio) => radio.addEventListener("change", updateCertificateVersion));
    updateCertificateVersion();
  });

  // Django rotates the CSRF cookie after login. If another dashboard tab was already
  // open, its hidden token becomes stale even though the signed-in session is valid.
  // Refresh POST forms from the current same-origin cookie immediately before submit;
  // server-side CSRF validation remains fully enabled and authoritative.
  const currentCsrfToken = () => {
    const prefix = "csrftoken=";
    const cookie = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(prefix));
    return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
  };
  document.querySelectorAll('form[method="post"]').forEach((form) => {
    form.addEventListener("submit", () => {
      const csrfField = form.querySelector('input[name="csrfmiddlewaretoken"]');
      const csrfToken = currentCsrfToken();
      if (csrfField && csrfToken) csrfField.value = csrfToken;
    });
  });

  activate(location.hash.slice(1) || "overview", { updateHistory: false });
})();
