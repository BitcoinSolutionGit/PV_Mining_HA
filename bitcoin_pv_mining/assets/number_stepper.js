(function () {
  function decimalPlaces(step) {
    const s = String(step || 1);
    if (s.includes("e-")) {
      const n = parseInt(s.split("e-")[1], 10);
      return Number.isFinite(n) ? n : 0;
    }
    const idx = s.indexOf(".");
    return idx >= 0 ? (s.length - idx - 1) : 0;
  }

  function clamp(value, min, max) {
    let out = value;
    if (Number.isFinite(min)) out = Math.max(out, min);
    if (Number.isFinite(max)) out = Math.min(out, max);
    return out;
  }

  function parseNumeric(raw) {
    if (raw == null) return NaN;
    return parseFloat(String(raw).replace(",", "."));
  }

  function stepInput(input, direction) {
    const step = parseFloat(input.getAttribute("step") || "1");
    const min = parseFloat(input.getAttribute("min"));
    const max = parseFloat(input.getAttribute("max"));
    const current = parseNumeric(input.value);
    const start = Number.isFinite(current)
      ? current
      : (Number.isFinite(min) ? min : 0);
    const next = clamp(start + ((Number.isFinite(step) ? step : 1) * direction), min, max);
    const places = decimalPlaces(step);
    input.value = String(Number(next.toFixed(places)));
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  document.addEventListener("click", function (event) {
    const btn = event.target.closest(".app-num-stepper-btn");
    if (!btn) return;

    const wrapper = btn.closest(".app-num-stepper");
    if (!wrapper) return;

    const input = wrapper.querySelector(".app-num-stepper-input");
    if (!input || input.disabled || input.readOnly) return;

    stepInput(input, btn.classList.contains("minus") ? -1 : 1);
  });
})();
