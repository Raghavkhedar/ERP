// The command bar: Ctrl/Cmd+K, "/", or the header button opens a field that
// finds pages, candidates and tasks. Arrow keys choose, Enter opens, Esc closes.
document.addEventListener("alpine:init", () => {
  const typing = () => {
    const el = document.activeElement;
    return el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  };

  Alpine.data("commandBar", (url) => ({
    open: false,
    q: "",
    results: [],
    active: 0,
    controller: null,
    timer: null,

    init() {
      window.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          this.open ? this.hide() : this.show();
        } else if (e.key === "/" && !this.open && !typing()) {
          e.preventDefault();
          this.show();
        }
      });
    },

    show() {
      this.open = true;
      this.q = "";
      this.fetchResults();
      this.$nextTick(() => this.$refs.input.focus());
    },

    hide() {
      this.open = false;
    },

    search() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.fetchResults(), 120);
    },

    async fetchResults() {
      this.controller?.abort();
      this.controller = new AbortController();
      try {
        const response = await fetch(`${url}?q=${encodeURIComponent(this.q)}`, {
          signal: this.controller.signal,
          headers: { Accept: "application/json" },
        });
        if (!response.ok) return;
        this.results = (await response.json()).results;
        this.active = 0;
      } catch {}
    },

    move(step) {
      if (!this.results.length) return;
      this.active = (this.active + step + this.results.length) % this.results.length;
      this.$nextTick(() =>
        document.getElementById(`command-${this.active}`)?.scrollIntoView({ block: "nearest" }),
      );
    },

    go(result) {
      if (result) window.location.href = result.url;
    },

    startsGroup(i) {
      return i === 0 || this.results[i - 1].group !== this.results[i].group;
    },
  }));
});
