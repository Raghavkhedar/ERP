// The desk bell sound, shared by the chat button and the notification popups.
// Loaded before Alpine starts.
(function () {
  if (window.senkenBell) return; // already loaded by another partial
  let audio = null;

  // Browsers only let a page play sound after the person has clicked or typed
  // on it, so the audio context is created (or resumed) on the first gesture.
  function unlock() {
    try {
      audio = audio || new AudioContext();
      if (audio.state === "suspended") audio.resume();
    } catch {
      audio = null;
    }
  }
  ["pointerdown", "keydown"].forEach((type) =>
    document.addEventListener(type, unlock, { once: true, capture: true }),
  );

  // A small desk bell: a few inharmonic partials that decay at different rates.
  function play() {
    unlock();
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

  window.senkenBell = { play };
})();
