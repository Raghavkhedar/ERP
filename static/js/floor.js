// x-floor="count": shows the count on a lift-style floor display and rolls
// the new number in when it changes. Loaded before Alpine starts.
document.addEventListener("alpine:init", () => {
  Alpine.directive("floor", (el, { expression }, { evaluateLater, effect }) => {
    const read = evaluateLater(expression);
    let shown = null;
    effect(() =>
      read((value) => {
        if (value === shown) return;
        const digit = document.createElement("span");
        digit.className = "floor-digit" + (shown === null ? " still" : "");
        digit.textContent = value > 99 ? "99+" : value;
        el.replaceChildren(digit);
        shown = value;
      })
    );
  });
});
