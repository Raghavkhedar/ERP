// A filter dropdown that always stays on screen: fixed under its button, pulled
// back inside the window, and given a height that fits what room is left.
document.addEventListener("alpine:init", () => {
  Alpine.data("filterPanel", () => ({
    o: false,
    toggle() {
      this.o = !this.o;
      if (this.o) this.$nextTick(() => this.place());
    },
    place() {
      const gap = 8;
      const b = this.$refs.btn.getBoundingClientRect();
      const p = this.$refs.panel;
      p.style.maxHeight = "";
      const left = Math.max(gap, Math.min(b.left, innerWidth - p.offsetWidth - gap));
      const below = innerHeight - b.bottom - gap * 2;
      const above = b.top - gap * 2;
      // Open upward only when there is clearly more room above than below.
      const up = below < Math.min(p.scrollHeight, 240) && above > below;
      const room = Math.max(up ? above : below, 120);
      p.style.maxHeight = room + "px";
      p.style.left = left + "px";
      p.style.top = up
        ? Math.max(gap, b.top - Math.min(p.scrollHeight, room) - gap / 2) + "px"
        : b.bottom + gap / 2 + "px";
    },
  }));
});
