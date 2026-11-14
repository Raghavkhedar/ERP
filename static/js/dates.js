// Every date field shows and takes DD/MM/YYYY; the form still submits YYYY-MM-DD.
// Native date inputs follow the browser's locale, so they are swapped for flatpickr.
// shortcut: inputs marked data-native (the Alpine-driven work-history rows) are left alone.
(() => {
  const kinds = {
    date: { dateFormat: "Y-m-d", altFormat: "d/m/Y" },
    "datetime-local": { dateFormat: "Y-m-d\\TH:i", altFormat: "d/m/Y H:i", enableTime: true, time_24hr: true },
  };
  const enhance = (root) => {
    if (!window.flatpickr) return;
    const pick = 'input[type="date"]:not([data-native]), input[type="datetime-local"]:not([data-native])';
    [...(root.matches?.(pick) ? [root] : []), ...root.querySelectorAll(pick)].forEach((el) => {
      window.flatpickr(el, {
        ...kinds[el.type],
        altInput: true,
        altInputClass: el.className + " dp",
        allowInput: false,
        disableMobile: true,
      });
    });
  };
  const start = () => {
    enhance(document);
    new MutationObserver((list) => list.forEach((m) => m.addedNodes.forEach((n) => n.nodeType === 1 && enhance(n)))).observe(document.body, { childList: true, subtree: true });
  };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", start) : start();
})();
