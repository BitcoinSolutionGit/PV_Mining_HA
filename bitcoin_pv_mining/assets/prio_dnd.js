(function () {
  function wire(list) {
    if (!list || list.dataset.dndWired === "1") return;
    list.dataset.dndWired = "1";
    console.log("[prio_dnd] wired");

    let dragEl = null;

    list.addEventListener("dragstart", function (e) {
      const item = e.target.closest(".prio-item");
      if (!item) return;
      dragEl = item;
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", item.dataset.pid || ""); } catch (_) {}
      }
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

    list.addEventListener("drop", function (e) {
      e.preventDefault();
      const ids = Array.from(list.querySelectorAll(".prio-item")).map(el => el.dataset.pid);
      const wireInput = document.getElementById("prio-dnd-wire");
      if (wireInput) {
        const json = JSON.stringify(ids);
        if (wireInput.value !== json) {
          wireInput.value = json;
          wireInput.dispatchEvent(new Event("input",  { bubbles: true }));
          wireInput.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    });
  }

  function scan() {
    document.querySelectorAll("#prio-list").forEach(wire);
  }

  document.addEventListener("DOMContentLoaded", scan);
  new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });
})();
