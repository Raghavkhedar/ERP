// Task alarms on every page: polls tasks:alarms and keeps the popup open,
// beeping until each alarm is snoozed or dismissed. Loaded before Alpine starts.
document.addEventListener("alpine:init", () => {
  const POLL_MS = 5000;
  const BEEP_EVERY_MS = 2500;
  const el = document.getElementById("alarms");
  if (!el) return;
  const csrf = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? "";
  const RENOTIFY_MS = 30000;
  const supported = "Notification" in window;
  const baseTitle = document.title;
  let lastNotified = 0;
  let asked = false;
  let audio = null;
  let flash = null;

  // Browsers only let a page play sound after a click or key press on it, and
  // a reload forgets that, so keep trying to unlock on every gesture until the
  // audio context runs, and ring the moment it does.
  function unlock() {
    try {
      audio = audio || new AudioContext();
      if (audio.state === "suspended") {
        audio.resume().then(() => {
          store().locked = audio.state !== "running";
          beepIfRinging();
        });
      }
    } catch {
      audio = null;
    }
    store().locked = !audio || audio.state !== "running";
  }
  ["pointerdown", "keydown", "touchend"].forEach((type) =>
    document.addEventListener(type, unlock, { capture: true }),
  );

  const store = () => Alpine.store("alarms");

  // The system notification is what makes a sound when the browser is in the
  // background, as WhatsApp Web's does: it needs the person's permission once.
  async function askPermission() {
    if (supported && Notification.permission === "default") {
      await Notification.requestPermission();
    }
    store().permission = supported ? Notification.permission : "denied";
  }

  function notify(alarms) {
    if (!supported || Notification.permission !== "granted") return;
    if (!document.hidden && document.hasFocus()) return; // the popup is in front
    if (Date.now() - lastNotified < RENOTIFY_MS) return;
    lastNotified = Date.now();
    const more = alarms.length > 1 ? ` (+${alarms.length - 1} more)` : "";
    const note = new Notification("Task alarm", {
      body: alarms[0].title + more,
      tag: "task-alarm",
      renotify: true,
      requireInteraction: true,
    });
    note.onclick = () => {
      window.focus();
      window.location.href = alarms[0].url;
    };
  }

  // Setting an alarm is the moment to ask, so the permission prompt has a click behind it.
  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!supported || Notification.permission !== "default" || asked) return;
      if (!form.querySelector?.('[name="remind_at"]')?.value) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      asked = true; // once per page, so a dismissed prompt can't loop
      askPermission().finally(() => form.requestSubmit(event.submitter));
    },
    { capture: true },
  );
  const beepIfRinging = () => {
    if (store().ringing.length) beep();
  };

  // Three loud, sharp beeps.
  function beep() {
    if (!audio || audio.state !== "running") return;
    const out = audio.createGain();
    out.gain.value = 0.5;
    out.connect(audio.destination);
    [0, 0.22, 0.44].forEach((offset) => {
      const start = audio.currentTime + offset;
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = "square";
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(1, start + 0.01);
      gain.gain.setValueAtTime(1, start + 0.12);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.16);
      osc.connect(gain).connect(out);
      osc.start(start);
      osc.stop(start + 0.2);
    });
  }

  Alpine.store("alarms", {
    ringing: [],
    locked: false,
    permission: supported ? Notification.permission : "denied",

    get canAsk() {
      return this.permission === "default";
    },

    askPermission,

    init() {
      unlock();
      this.check();
      setInterval(() => this.check(), POLL_MS);
      setInterval(beepIfRinging, BEEP_EVERY_MS);
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
      const wasQuiet = !this.ringing.length;
      this.ringing = data.alarms;
      this.titleFlash();
      if (data.alarms.length) notify(data.alarms);
      if (wasQuiet && data.alarms.length) {
        unlock();
        beep();
      }
    },

    // Flash the tab title so an alarm is seen even when it can't be heard.
    titleFlash() {
      if (!this.ringing.length) {
        clearInterval(flash);
        flash = null;
        document.title = baseTitle;
      } else if (!flash) {
        let on = false;
        flash = setInterval(() => {
          on = !on;
          document.title = on ? "⏰ Task alarm" : baseTitle;
        }, 1000);
      }
    },

    async act(alarm, body) {
      this.ringing = this.ringing.filter((a) => a !== alarm);
      this.titleFlash();
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
