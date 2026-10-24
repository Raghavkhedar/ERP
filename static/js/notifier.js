// Notifications on every page: polls notifications:pulse, keeps the bell's
// count, and for each new notification shows a popup, rings the bell and, when
// the tab is in the background, a desktop notification. Loaded before Alpine
// starts, after bell.js.
document.addEventListener("alpine:init", () => {
  const POLL_MS = 5000;
  const TOAST_MS = 8000;
  const el = document.getElementById("notifier");
  if (!el) return;
  const pulseUrl = el.dataset.pulse;
  const seenKey = `notify-seen-${el.dataset.user}`;
  const baseTitle = document.title;
  let memorySeen = null; // used when localStorage is blocked
  let toastId = 0;

  // The newest notification id already shown, shared by all open tabs so each
  // one is announced once, not once per tab.
  function readSeen() {
    try {
      const value = localStorage.getItem(seenKey);
      return value === null ? memorySeen : Number(value);
    } catch {
      return memorySeen;
    }
  }

  function writeSeen(id) {
    memorySeen = id;
    try {
      localStorage.setItem(seenKey, String(id));
    } catch {}
  }

  const supported = "Notification" in window;

  Alpine.store("notify", {
    unread: 0,
    toasts: [],
    permission: supported ? Notification.permission : "denied",

    get canAsk() {
      return this.permission === "default";
    },

    async askPermission() {
      if (!supported) return;
      this.permission = await Notification.requestPermission();
    },

    // Alpine calls init() once when the store is registered.
    init() {
      this.check();
      setInterval(() => this.check(), POLL_MS);
    },

    async check() {
      let data;
      const seen = readSeen();
      try {
        const response = await fetch(`${pulseUrl}?after=${seen ?? 0}`, {
          headers: { Accept: "application/json" },
        });
        // A logged-out session redirects to the login page, which isn't JSON.
        if (!response.ok || !response.headers.get("content-type")?.includes("json")) return;
        data = await response.json();
      } catch {
        return;
      }
      this.unread = data.unread;
      document.title = data.unread ? `(${data.unread}) ${baseTitle}` : baseTitle;

      // The first visit only sets the baseline, so old notifications don't replay.
      if (seen === null) {
        writeSeen(data.latest);
        return;
      }
      if (!data.items.length) return;
      writeSeen(Math.max(...data.items.map((item) => item.id)));
      data.items.forEach((item) => this.announce(item));
      window.senkenBell?.play();
    },

    announce(item) {
      const toast = { ...item, key: ++toastId };
      this.toasts.push(toast);
      setTimeout(() => this.dismiss(toast), TOAST_MS);
      if (document.hidden && this.permission === "granted") {
        const note = new Notification("Senken ERP", { body: item.text, tag: `notify-${item.id}` });
        note.onclick = () => {
          window.focus();
          window.location.href = item.url;
        };
      }
    },

    dismiss(toast) {
      this.toasts = this.toasts.filter((t) => t !== toast);
    },
  });
});
