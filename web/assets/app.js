(function () {
  "use strict";

  var search = document.getElementById("search");
  var dayButtonsWrap = document.getElementById("day-buttons");
  var channels = Array.prototype.slice.call(document.querySelectorAll(".channel"));
  var dayGroups = Array.prototype.slice.call(document.querySelectorAll(".day-group"));
  var allDays = Array.prototype.slice.call(new Set(dayGroups.map(function (el) { return el.dataset.day; }))).sort();

  var activeDay = "all";

  function buildDayButtons() {
    if (!dayButtonsWrap) return;
    var frag = document.createDocumentFragment();

    function makeBtn(value, label) {
      var b = document.createElement("button");
      b.textContent = label;
      b.dataset.day = value;
      if (value === activeDay) b.classList.add("active");
      b.addEventListener("click", function () {
        activeDay = value;
        Array.prototype.forEach.call(dayButtonsWrap.children, function (c) {
          c.classList.toggle("active", c.dataset.day === value);
        });
        applyFilters();
      });
      return b;
    }

    frag.appendChild(makeBtn("all", "Vše"));
    allDays.forEach(function (day) {
      var d = new Date(day + "T00:00:00");
      var label = isNaN(d.getTime()) ? day : d.toLocaleDateString("cs-CZ", { day: "2-digit", month: "2-digit" });
      frag.appendChild(makeBtn(day, label));
    });
    dayButtonsWrap.appendChild(frag);
  }

  function normalize(s) {
    return (s || "").toLowerCase();
  }

  function applyFilters() {
    var query = normalize(search ? search.value : "");
    channels.forEach(function (ch) {
      var name = normalize(ch.dataset.name);
      var matchesSearch = !query || name.indexOf(query) !== -1;
      var visibleGroups = 0;
      Array.prototype.forEach.call(ch.querySelectorAll(".day-group"), function (g) {
        var show = activeDay === "all" || g.dataset.day === activeDay;
        g.style.display = show ? "" : "none";
        if (show) visibleGroups++;
      });
      ch.style.display = matchesSearch && visibleGroups > 0 ? "" : "none";
    });
  }

  function markLive() {
    var now = new Date();
    document.querySelectorAll(".programmes li[data-start]").forEach(function (li) {
      var start = new Date(li.dataset.start);
      var stop = new Date(li.dataset.stop);
      var isLive = now >= start && now < stop;
      li.classList.toggle("live", isLive);
      var badge = li.querySelector(".live-badge");
      if (isLive && !badge) {
        badge = document.createElement("span");
        badge.className = "live-badge";
        badge.textContent = "ŽIVĚ";
        li.insertBefore(badge, li.firstChild);
      } else if (!isLive && badge) {
        badge.remove();
      }
    });
  }

  if (search) search.addEventListener("input", applyFilters);
  buildDayButtons();
  markLive();
  setInterval(markLive, 60000);
})();
