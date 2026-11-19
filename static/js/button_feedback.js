// Button feedback: a submit or HTMX button shows "Processing…", then "Saved ✓"
// (or "Not saved ✕" when it failed), then goes back to what it was.
// Opt out with data-feedback="off"; reword with data-done / data-fail.
(function () {
  const SHOW_MS = 1600;
  const STUCK_MS = 10000; // a download keeps the page alive; give the button back
  const STORE = "button-feedback";
  const SPIN = '<svg class="fb-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9"/></svg>';
  const TICK = '<svg class="fb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  const CROSS = '<svg class="fb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  const HX = "[hx-get],[hx-post],[hx-put],[hx-patch],[hx-delete]";
  const timers = new WeakMap();

  const key = (btn) => {
    const form = btn.form;
    const action = form ? form.getAttribute("action") || location.pathname : "";
    return [action, btn.name, btn.value, btn.dataset.fbLabel || btn.textContent.trim()].join("|");
  };
  const skip = (btn) => !btn || btn.tagName !== "BUTTON" || btn.closest('[data-feedback="off"]');

  function set(btn, state, text, icon) {
    if (!btn.dataset.fbHtml) {
      btn.dataset.fbHtml = btn.innerHTML;
      btn.dataset.fbLabel = btn.textContent.trim();
      btn.style.minWidth = btn.offsetWidth + "px";
    }
    btn.classList.remove("is-busy", "is-done", "is-failed");
    btn.classList.add(state);
    btn.setAttribute("aria-busy", state === "is-busy");
    btn.innerHTML = icon + `<span>${text}</span>`;
  }

  function restore(btn) {
    clearTimeout(timers.get(btn));
    if (btn.dataset.fbHtml === undefined) return;
    btn.innerHTML = btn.dataset.fbHtml;
    btn.classList.remove("is-busy", "is-done", "is-failed");
    btn.removeAttribute("aria-busy");
    btn.style.minWidth = "";
    delete btn.dataset.fbHtml;
    delete btn.dataset.fbLabel;
  }

  function busy(btn, giveUpAfter) {
    set(btn, "is-busy", "Processing…", SPIN);
    timers.set(btn, setTimeout(() => restore(btn), giveUpAfter));
  }

  function finish(btn, ok) {
    clearTimeout(timers.get(btn));
    if (ok) set(btn, "is-done", btn.dataset.done || "Saved", TICK);
    else set(btn, "is-failed", btn.dataset.fail || "Not saved", CROSS);
    timers.set(btn, setTimeout(() => restore(btn), SHOW_MS));
  }

  // Plain forms: the page reloads, so remember the button and finish after the load.
  document.addEventListener("submit", (e) => {
    const btn = e.submitter;
    const form = e.target;
    if (skip(btn) || form.matches(HX) || btn.matches(HX)) return;
    if (btn.classList.contains("is-busy")) return e.preventDefault(); // no double submit
    if (e.defaultPrevented) return; // Alpine or the browser stopped it
    try { sessionStorage.setItem(STORE, key(btn)); } catch {}
    busy(btn, STUCK_MS);
  });

  function afterLoad() {
    let wanted;
    try { wanted = sessionStorage.getItem(STORE); sessionStorage.removeItem(STORE); } catch {}
    if (!wanted) return;
    const btn = [...document.querySelectorAll("form button")].find((b) => !skip(b) && key(b) === wanted);
    if (btn) finish(btn, !document.querySelector("main .text-red-600"));
  }
  document.addEventListener("DOMContentLoaded", afterLoad);
  window.addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    document.querySelectorAll("button.is-busy").forEach(restore);
  });

  // HTMX: the swap often replaces the form, so finish the button that took its place.
  let pending = new Map(); // key → ok
  document.addEventListener("htmx:beforeRequest", (e) => {
    const btn = e.detail.requestConfig.triggeringEvent?.submitter || e.detail.elt.querySelector?.('button[type="submit"], button:not([type])') || e.detail.elt;
    if (skip(btn) || btn.closest('[data-feedback="off"]')) return;
    e.detail.elt.__fb = btn;
    busy(btn, STUCK_MS);
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    const btn = e.detail.elt.__fb;
    if (!btn) return;
    delete e.detail.elt.__fb;
    const ok = e.detail.successful;
    if (btn.isConnected) return finish(btn, ok);
    pending.set(btn.dataset.fbLabel + "|" + btn.name + "|" + btn.value, ok); // swapped out
    setTimeout(() => pending.clear(), 500);
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    if (!pending.size) return;
    e.target.querySelectorAll?.("button").forEach((b) => {
      const k = b.textContent.trim() + "|" + b.name + "|" + b.value;
      if (!skip(b) && pending.has(k)) { finish(b, pending.get(k)); pending.delete(k); }
    });
  });
})();
