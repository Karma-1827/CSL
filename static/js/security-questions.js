(() => {
  const groups = Array.from(document.querySelectorAll("[data-security-question-group]"));
  if (!groups.length) return;

  groups.forEach((group) => {
    const selects = Array.from(group.querySelectorAll('select[name^="question_"]'));
    if (selects.length < 2) return;

    function refresh() {
      const selectedValues = selects.map((select) => select.value).filter((value) => value);
      selects.forEach((select) => {
        Array.from(select.options).forEach((option) => {
          if (!option.value) return;
          const pickedByAnother = selectedValues.includes(option.value) && select.value !== option.value;
          option.disabled = pickedByAnother;
        });
      });
    }

    selects.forEach((select) => select.addEventListener("change", refresh));
    refresh();
  });
})();
