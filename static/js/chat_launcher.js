// The floating chat button: polls chat:pulse, shows the unread total and
// rings a bell when a new message arrives. Loaded before Alpine starts.
(function () {
  const POLL_MS = 5000;
  let audio = null;
  let memorySeen = null; // used when localStorage is blocked

  // Browsers only let a page play sound after the person has clicked or typed
  // on it, so the audio context is created (or resumed) on the first gesture.
  function unlockAudio() {
    try {
      audio = audio || new AudioContext();
      if (audio.state === "suspended") audio.resume();
    } catch {
      audio = null;
    }
  }
  ["pointerdown", "keydown"].forEach((type) =>
    document.addEventListener(type, unlockAudio, { once: true, capture: true }),
  );

  // A small desk bell: a few inharmonic partials that decay at different rates.
  function playBell() {
    unlockAudio();
    if (!audio || audio.state !== "running") return;
    const now = audio.currentTime;
    const out = audio.createGain();
    out.gain.value = 0.2;
    out.connect(audio.destination);
    [
      [1, 1],
      [2.76, 0.35],
      [5.4, 0.12],
    ].forEach(([ratio, level]) => {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.frequency.value = 988 * ratio;
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(level, now + 0.008);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.4 / Math.sqrt(ratio));
      osc.connect(gain).connect(out);
      osc.start(now);
      osc.stop(now + 1.5);
    });
  }

  // The newest message id already rung for, shared by all open tabs so a
  // message rings once, not once per tab.
  function readSeen(key) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? memorySeen : Number(value);
    } catch {
      return memorySeen;
    }
  }

  function writeSeen(key, id) {
    memorySeen = id;
    try {
      localStorage.setItem(key, String(id));
    } catch {}
  }

  window.chatLauncher = function (pulseUrl, seenKey) {
    const baseTitle = document.title;
    return {
      unread: 0,
      ringing: false,

      init() {
        this.check();
        setInterval(() => this.check(), POLL_MS);
      },

      async check() {
        let data;
        try {
          const response = await fetch(pulseUrl, { headers: { Accept: "application/json" } });
          // A logged-out session redirects to the login page, which isn't JSON.
          if (!response.ok || !response.headers.get("content-type")?.includes("json")) return;
          data = await response.json();
        } catch {
          return;
        }
        this.unread = data.unread;
        document.title = data.unread ? `(${data.unread}) ${baseTitle}` : baseTitle;

        if (data.newest === null) return;
        const seen = readSeen(seenKey);
        if (seen !== null && data.newest <= seen) return;
        writeSeen(seenKey, data.newest);
        if (seen !== null) this.ring(); // the first visit only sets the baseline
      },

      ring() {
        playBell();
        this.ringing = false;
        requestAnimationFrame(() => (this.ringing = true));
        setTimeout(() => (this.ringing = false), 900);
      },
    };
  };
})();
