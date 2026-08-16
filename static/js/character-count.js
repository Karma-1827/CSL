(() => {
  const fields = document.querySelectorAll("[data-character-count]");

  fields.forEach((field) => {
    const maximum = Number.parseInt(field.dataset.characterCount, 10);
    if (!Number.isFinite(maximum)) return;

    const counter = document.createElement("span");
    counter.className = "character-count";
    counter.setAttribute("aria-live", "polite");

    const update = () => {
      counter.textContent = `${field.value.length}/${maximum}`;
    };

    field.insertAdjacentElement("afterend", counter);
    field.addEventListener("input", update);
    update();
  });
})();
