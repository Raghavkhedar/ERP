// "Your day" on the home page: click (or double-tap) the timeline to add a
// 15 minute block, drag a block to move it, click it to rename or delete it.
// The server decides what's allowed and joins touching blocks; after every
// change the panel is fetched again and swapped in.
document.addEventListener("alpine:init", () => {
  const csrf = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? "";
  const clamp = (n, lo, hi) => Math.min(Math.max(n, lo), hi);

  Alpine.data("dayPanel", () => ({
    error: "",
    lastTap: 0,
    lastY: 0,
    hour: 56,
    first: 10,

    init() {
      const d = this.$root.dataset;
      this.hour = Number(d.hourHeight);
      this.first = Number(d.firstHour);
    },

    get step() {
      return this.hour / 4; // pixels in 15 minutes
    },

    async send(data) {
      const body = new URLSearchParams();
      for (const [key, value] of Object.entries(data)) {
        [].concat(value).forEach((v) => body.append(key, v));
      }
      this.error = "";
      try {
        const response = await fetch(this.$root.dataset.url, {
          method: "POST",
          headers: { Accept: "application/json", "X-CSRFToken": csrf() },
          body,
        });
        if (!response.ok) {
          this.error = (await response.json().catch(() => ({}))).error || "That didn't save.";
        }
      } catch {
        this.error = "Couldn't reach the server.";
      }
      await this.refresh();
    },

    async refresh() {
      try {
        const response = await fetch(this.$root.dataset.panel);
        if (response.ok) {
          // The lift only travels in on first load, not after every edit.
          this.$refs.body.classList.add("settled");
          this.$refs.body.innerHTML = await response.text();
        }
      } catch {}
    },

    // A one-line text box that calls save(text) once, on Enter or on leaving it.
    field(value, save, cancel, extra) {
      const input = document.createElement("input");
      input.value = value;
      input.maxLength = 200;
      input.setAttribute("aria-label", "Block name");
      input.className =
        "w-full rounded-lg bg-white ring-1 ring-blue-200 px-1 text-xs focus-visible:outline-none";
      let settled = false;
      const settle = (fn) => {
        if (settled) return;
        settled = true;
        fn();
      };
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") settle(() => save(input.value));
        if (e.key === "Escape") settle(cancel);
      });
      input.addEventListener("blur", () => settle(() => save(input.value)));
      input.addEventListener("pointerdown", (e) => e.stopPropagation());
      return input;
    },

    // Empty area: a click (mouse) or a double-tap (touch) starts a new block.
    tap(e) {
      if (e.target !== e.currentTarget || e.currentTarget.querySelector("[data-draft]")) return;
      const grid = e.currentTarget;
      const y = e.clientY - grid.getBoundingClientRect().top;
      if (e.pointerType !== "mouse") {
        const again = Date.now() - this.lastTap < 350 && Math.abs(y - this.lastY) < 24;
        this.lastTap = Date.now();
        this.lastY = y;
        if (!again) return;
      }
      const top = clamp(Math.floor(y / this.step) * this.step, 0, grid.offsetHeight - this.step);
      const card = document.createElement("div");
      card.dataset.draft = "";
      card.style.cssText = `top:${top}px;height:30px;left:0;right:4px`;
      card.className = "absolute z-20 mt-px overflow-hidden rounded-xl bg-pop/50 px-1";
      const minutes = this.first * 60 + Math.round((top * 60) / this.hour);
      const start = `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
      const input = this.field(
        "",
        (text) => (text.trim() ? this.send({ action: "add", start, title: text }) : card.remove()),
        () => card.remove(),
      );
      input.placeholder = "Name it";
      card.append(input);
      grid.append(card);
      input.focus();
    },

    // Press on a block, then either drag it (snaps to 15 minutes) or let go in
    // place to rename it.
    down(e) {
      if (e.button > 0 || e.target.closest("input,button")) return;
      const el = e.currentTarget;
      const ids = el.dataset.ids.split(",");
      const top0 = parseFloat(el.style.top);
      const limit = el.parentElement.offsetHeight - el.offsetHeight;
      const startY = e.clientY;
      let moved = false;
      let top = top0;
      el.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const dy = ev.clientY - startY;
        if (!moved && Math.abs(dy) < 4) return;
        moved = true;
        top = clamp(top0 + Math.round(dy / this.step) * this.step, 0, limit);
        el.style.top = `${top}px`;
        el.style.zIndex = 30;
        el.classList.add("cursor-grabbing");
      };
      const up = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        if (!moved) return this.edit(el);
        const delta = Math.round((top - top0) / this.step) * 15;
        delta ? this.send({ action: "move", ids, delta }) : this.refresh();
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
    },

    edit(el) {
      if (el.querySelector("input")) return;
      const ids = el.dataset.ids.split(",");
      const input = this.field(
        el.dataset.title,
        (text) => {
          if (!text.trim()) return this.send({ action: "delete", ids });
          text.trim() === el.dataset.title
            ? this.refresh()
            : this.send({ action: "rename", ids, title: text });
        },
        () => this.refresh(),
      );
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete";
      remove.className = "mt-0.5 text-xs underline";
      remove.addEventListener("mousedown", (e) => e.preventDefault());
      remove.addEventListener("click", () => this.send({ action: "delete", ids }));
      el.replaceChildren(input, remove);
      input.focus();
      input.select();
    },
  }));
});
