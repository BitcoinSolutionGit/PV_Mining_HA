(function () {
  function attach() {
    const list = document.getElementById("prio-list");
    if (!list) return false;

    // Doppelt anhängen verhindern
    if (list.dataset.dndAttached === "1") return true;
    list.dataset.dndAttached = "1";

    console.log("[prio_dnd] attached on #prio-list");

    let dragEl = null;

    list.addEventListener("dragstart", function (e) {
      const item = e.target.closest(".prio-item");
      if (!item) return;
      dragEl = item;
      e.dataTransfer && (e.dataTransfer.effectAllowed = "move");
      item.classList.add("dragging");
    });

    list.addEventListener("dragend", function (e) {
      const item = e.target.closest(".prio-item");
      if (item) item.classList.remove("dragging");
      dragEl = null;
    });

    list.addEventListener("dragover", function (e) {
      e.preventDefault();
      const target = e.target.closest(".prio-item");
      if (!dragEl || !target || target === dragEl) return;
      const rect = target.getBoundingClientRect();
      const after = e.clientY > (rect.top + rect.height / 2);
      list.insertBefore(dragEl, after ? target.nextSibling : target);
    });

    // Drop auf dem Container ODER irgendwo innerhalb
    document.addEventListener("drop", function (e) {
      const container = e.target.closest("#prio-list");
      if (!container) return;
      e.preventDefault();

      const ids = Array.from(container.querySelectorAll(".prio-item"))
        .map(el => el.dataset.pid);

      console.log("[prio_dnd] drop ->", ids);

      const wire = document.getElementById("prio-dnd-wire");
      if (wire) {
        const json = JSON.stringify(ids);
        if (wire.value !== json) {
          wire.value = json;
          wire.dispatchEvent(new Event("input",  { bubbles: true }));
          wire.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    });

    return true;
  }

  // 1) Sofort versuchen
  if (!attach()) {
    // 2) Später nochmal, wenn DOM vollständig ist
    document.addEventListener("DOMContentLoaded", attach);
    // 3) Und per MutationObserver, falls Tab dynamisch gerendert wird
    const obs = new MutationObserver(() => attach());
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }
})();
