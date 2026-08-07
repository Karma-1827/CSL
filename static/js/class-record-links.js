(() => {
  const lists = Array.from(document.querySelectorAll("[data-evidence-link-list]"));
  if (!lists.length) return;

  lists.forEach((list) => {
    const addButton = list.nextElementSibling;
    if (!addButton || !addButton.hasAttribute("data-evidence-link-add")) return;
    const maxLinks = parseInt(list.dataset.maxLinks, 10) || 5;

    function refresh() {
      const rows = Array.from(list.querySelectorAll("[data-evidence-link-row]"));
      rows.forEach((row) => {
        const removeButton = row.querySelector("[data-evidence-link-remove]");
        if (removeButton) removeButton.hidden = rows.length <= 1;
      });
      addButton.hidden = rows.length >= maxLinks;
    }

    list.addEventListener("click", (event) => {
      const removeButton = event.target.closest("[data-evidence-link-remove]");
      if (!removeButton) return;
      const row = removeButton.closest("[data-evidence-link-row]");
      if (row && list.querySelectorAll("[data-evidence-link-row]").length > 1) {
        row.remove();
        refresh();
      }
    });

    addButton.addEventListener("click", () => {
      const rows = list.querySelectorAll("[data-evidence-link-row]");
      if (rows.length >= maxLinks) return;
      const newRow = rows[0].cloneNode(true);
      const input = newRow.querySelector("[data-evidence-link-input]");
      if (input) input.value = "";
      list.appendChild(newRow);
      refresh();
    });

    refresh();
  });
})();
