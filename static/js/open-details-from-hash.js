(() => {
  const hash = window.location.hash.slice(1);
  if (!hash) return;
  const target = document.getElementById(hash);
  if (!target || target.tagName !== "DETAILS") return;
  target.open = true;
  target.scrollIntoView({ block: "center" });
})();
