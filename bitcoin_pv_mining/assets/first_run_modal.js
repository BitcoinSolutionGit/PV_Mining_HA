(function () {
  function syncFirstRunBodyClass() {
    try {
      var overlay = document.getElementById("first-run-overlay");
      var visible = false;
      if (overlay) {
        var style = window.getComputedStyle(overlay);
        visible = style && style.display !== "none" && style.visibility !== "hidden";
      }
      document.body.classList.toggle("first-run-active", !!visible);
    } catch (_) {}
  }

  function boot() {
    syncFirstRunBodyClass();
    try {
      var observer = new MutationObserver(syncFirstRunBodyClass);
      observer.observe(document.body, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["style", "class"],
      });
    } catch (_) {}
    window.setInterval(syncFirstRunBodyClass, 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
