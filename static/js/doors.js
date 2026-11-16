// Lift doors for login. Submitting stops the doors half way while the server
// checks the password. A wrong one opens them again and shows the error in
// place (after clanging a bit further shut); a right one closes them fully, and the next page opens them.
// sessionStorage carries "doors" across the redirect. Skipped under reduced motion.
(function () {
  const root = document.documentElement;
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const remember = (on) => {
    try { on ? sessionStorage.setItem("doors", "1") : sessionStorage.removeItem("doors"); } catch {}
  };

  // Arriving shut (set by the inline script in <head>): open smoothly.
  if (root.classList.contains("doors-shut")) {
    remember(false);
    setTimeout(() => root.classList.remove("doors-shut"), 150);
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (calm || !form.matches("form[data-doors]") || form.dataset.plain) return;
    event.preventDefault();
    if (root.classList.contains("doors-wait")) return; // a login is already being checked
    root.classList.add("doors-wait");
    try {
      const [res] = await Promise.all([
        fetch(form.action || location.href, { method: "POST", body: new FormData(form), credentials: "same-origin" }),
        pause(650),
      ]);
      if (res.redirected) {
        remember(true);
        root.classList.add("doors-shut");
        await pause(700);
        location.href = res.url;
        return;
      }
      // Wrong password: put the fresh form (with its error) in place of this one.
      const next = new DOMParser().parseFromString(await res.text(), "text/html").querySelector("form[data-doors]");
      if (!next) throw new Error("no form");
      form.replaceWith(next);
      next.querySelector("[autofocus]")?.focus();
      // The gates clang a bit further shut before they open again.
      root.classList.add("doors-deny");
      await pause(450);
      root.classList.remove("doors-deny", "doors-wait");
    } catch {
      // Network trouble: fall back to a plain submit.
      root.classList.remove("doors-wait");
      form.dataset.plain = "1";
      form.submit();
    }
  });
})();
