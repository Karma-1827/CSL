(() => {
  const inputs = document.querySelectorAll("input[type=file][data-max-file-bytes]");

  inputs.forEach((input) => {
    const maxBytes = Number.parseInt(input.dataset.maxFileBytes, 10);
    if (!Number.isFinite(maxBytes)) return;
    const sizeLabel = input.dataset.maxFileSizeLabel || "";

    const error = document.createElement("p");
    error.className = "field-error";
    error.hidden = true;
    input.insertAdjacentElement("afterend", error);

    const validate = () => {
      const file = input.files && input.files[0];
      if (file && file.size > maxBytes) {
        error.textContent = `檔案不可超過 ${sizeLabel}。 / File size must not exceed ${sizeLabel}.`;
        error.hidden = false;
        return false;
      }
      error.hidden = true;
      error.textContent = "";
      return true;
    };

    input.addEventListener("change", validate);

    const form = input.closest("form");
    if (form) {
      form.addEventListener("submit", (event) => {
        if (!validate()) event.preventDefault();
      });
    }
  });
})();
