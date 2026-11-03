// Small progressive enhancements; every page works without this file.
(function () {
  // Toasts: dismiss on click, fade out success messages after a while.
  document.querySelectorAll(".toast").forEach(function (t) {
    t.querySelector("button")?.addEventListener("click", function () { t.remove(); });
    if (!t.classList.contains("error")) setTimeout(function () { t.remove(); }, 6000);
  });

  // Confirmation for destructive actions: <form data-confirm="...">
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Copy-to-clipboard buttons: <button data-copy="#input-id">
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    var input = document.querySelector(btn.getAttribute("data-copy"));
    if (!input) return;
    input.select();
    (navigator.clipboard ? navigator.clipboard.writeText(input.value) : Promise.resolve(document.execCommand("copy")))
      .then(function () {
        var old = btn.innerHTML;
        btn.textContent = "Copied";
        setTimeout(function () { btn.innerHTML = old; }, 1500);
      });
  });

  // Dashboard filter: <div class="filters" data-target=".student-row"><button data-filter="all|attention|ok">
  document.querySelectorAll(".filters").forEach(function (group) {
    group.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-filter]");
      if (!btn) return;
      group.querySelectorAll("button").forEach(function (b) { b.classList.toggle("on", b === btn); });
      var f = btn.getAttribute("data-filter");
      document.querySelectorAll(group.getAttribute("data-target")).forEach(function (row) {
        var status = row.getAttribute("data-status");
        var show = f === "all" || (f === "attention" ? status === "red" || status === "amber" : status === "green" || status === "grey");
        row.classList.toggle("hidden", !show);
      });
    });
  });

  // Weekly log: keep an unsent draft in this browser so nothing gets lost.
  var box = document.querySelector("textarea[data-autosave]");
  if (box) {
    var key = "phd-tracker:" + box.getAttribute("data-autosave");
    var note = document.querySelector("[data-autosave-note]");
    try {
      var saved = localStorage.getItem(key);
      if (saved && !box.value.trim()) {
        box.value = saved;
        if (note) note.textContent = "Restored your unsent draft from this browser.";
      }
    } catch (err) { /* storage unavailable */ }
    var timer;
    box.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        try { localStorage.setItem(key, box.value); if (note) note.textContent = "Draft saved in this browser"; } catch (err) {}
      }, 600);
    });
    box.form.addEventListener("submit", function () { try { localStorage.removeItem(key); } catch (err) {} });
  }
})();
