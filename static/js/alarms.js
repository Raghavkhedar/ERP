// Task alarms on every page: polls tasks:alarms and keeps the popup open,
// ringing every few seconds, until each alarm is snoozed or dismissed.
// Loaded before Alpine starts, after bell.js.
document.addEventListener("alpine:init", () => {
  const POLL_MS = 15000;
  const RING_MS = 8000;
  const el = document.getElementById("alarms");
  if (!el) return;
  const csrf = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? "";
  let lastRing = 0;

  Alpine.store("alarms", {
    ringing: [],

    init() {
      this.check();
      setInterval(() => this.check(), POLL_MS);
    },

    async check() {
      let data;
      try {
        const response = await fetch(el.dataset.url, { headers: { Accept: "application/json" } });
        if (!response.ok || !response.headers.get("content-type")?.includes("json")) return;
        data = await response.json();
      } catch {
        return;
      }
      this.ringing = data.alarms;
      if (data.alarms.length && Date.now() - lastRing > RING_MS) {
        lastRing = Date.now();
        window.senkenBell?.play();
      }
    },

    async act(alarm, body) {
      this.ringing = this.ringing.filter((a) => a !== alarm);
      try {
        await fetch(alarm.action, {
          method: "POST",
          headers: { Accept: "application/json", "X-CSRFToken": csrf() },
          body: new URLSearchParams(body),
        });
      } catch {}
      this.check();
    },
  });
});
