// The floating chat button: polls chat:pulse, shows the unread total and
// rings a bell when a new message arrives. Loaded before Alpine starts, after bell.js.
(function () {
  const POLL_MS = 5000;
  let memorySeen = null; // used when localStorage is blocked

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
        window.senkenBell?.play();
        this.ringing = false;
        requestAnimationFrame(() => (this.ringing = true));
        setTimeout(() => (this.ringing = false), 900);
      },
    };
  };
})();
