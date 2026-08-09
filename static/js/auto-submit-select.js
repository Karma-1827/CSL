document.querySelectorAll("[data-auto-submit-select]").forEach((select) => {
  select.addEventListener("change", () => {
    select.form.submit();
  });
});
