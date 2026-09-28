(function () {
  "use strict";

  var PX_PER_MIN = 6; // grid horizontal scale
  var DAY_WIDTH = 1440 * PX_PER_MIN;

  var dataEl = document.getElementById("epg-data");
  var epgData = null;
  try {
    epgData = dataEl ? JSON.parse(dataEl.textContent) : null;
  } catch (err) {
    epgData = null;
  }

  // ---------- shared helpers ----------

  function esc(s) {
    return (s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function normalize(s) {
    return (s || "").toLowerCase();
  }

  function mskNowParts() {
    var fmt = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Moscow",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    var parts = fmt.formatToParts(new Date());
    var h = +parts.find(function (p) { return p.type === "hour"; }).value;
    var m = +parts.find(function (p) { return p.type === "minute"; }).value;
    return h * 60 + m;
  }

  function mskToday() {
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(new Date());
  }

  function channelMatches(ch, query, day) {
    if (!query) return true;
    var q = normalize(query);
    if (normalize(ch.name).indexOf(q) !== -1) return true;
    return ch.programmes.some(function (p) {
      return (day === "all" || p.day === day) && normalize(p.title).indexOf(q) !== -1;
    });
  }

  // ---------- grid view ----------

  var grid = null;
  if (epgData && epgData.channels && epgData.channels.length) {
    grid = {
      head: document.getElementById("head-scroll"),
      main: document.getElementById("main-scroll"),
      side: document.getElementById("side-scroll"),
      ruler: document.getElementById("ruler"),
      sideBody: document.getElementById("side"),
      mainBody: document.getElementById("main"),
      day: epgData.days.indexOf(mskToday()) !== -1 ? mskToday() : epgData.days[0] || null,
    };
  }

  function buildRuler() {
    if (!grid) return;
    var html = "";
    for (var m = 0; m < 1440; m += 30) {
      var isHour = m % 60 === 0;
      var hh = String(Math.floor(m / 60)).padStart(2, "0");
      html +=
        '<div class="tick' + (isHour ? " hour" : "") + '" style="left:' + m * PX_PER_MIN + 'px">' +
        (isHour ? hh + ":00" : "") +
        "</div>";
    }
    grid.ruler.style.width = DAY_WIDTH + "px";
    grid.ruler.innerHTML = html;
  }

  function renderGrid(query) {
    if (!grid || !grid.day) return;
    var day = grid.day;
    var q = normalize(query);
    var channels = epgData.channels.filter(function (ch) {
      return ch.programmes.some(function (p) { return p.day === day; }) && channelMatches(ch, q, day);
    });

    var sideHtml = channels
      .map(function (ch) {
        var icon = ch.icon ? '<img src="' + esc(ch.icon) + '" alt="" loading="lazy">' : "";
        return '<div class="epg-side-row">' + icon + "<span>" + esc(ch.name) + "</span></div>";
      })
      .join("");

    var mainHtml = channels
      .map(function (ch) {
        var blocks = ch.programmes
          .filter(function (p) { return p.day === day; })
          .map(function (p) {
            var isMatch = q && normalize(p.title).indexOf(q) !== -1;
            var left = p.start_min * PX_PER_MIN;
            var width = Math.max(p.duration_min * PX_PER_MIN, 26);
            var tooltip = p.time + "–" + p.time_stop + " " + p.title + (p.desc ? " — " + p.desc : "");
            return (
              '<div class="epg-block' + (isMatch ? " match" : "") + '" style="left:' + left + "px;width:" + width + 'px" ' +
              'data-start="' + esc(p.start) + '" data-stop="' + esc(p.stop) + '" title="' + esc(tooltip) + '">' +
              '<span class="t">' + esc(p.time) + "</span> <span class=\"ttl\">" + esc(p.title) + "</span></div>"
            );
          })
          .join("");
        return '<div class="epg-row">' + blocks + "</div>";
      })
      .join("");

    grid.sideBody.innerHTML = sideHtml;
    grid.mainBody.innerHTML = mainHtml;
    grid.mainBody.style.width = DAY_WIDTH + "px";

    if (day === mskToday()) {
      var nowMin = mskNowParts();
      var line = document.createElement("div");
      line.className = "now-line";
      line.style.left = nowMin * PX_PER_MIN + "px";
      grid.mainBody.appendChild(line);
    }

    markLiveGrid();
  }

  function markLiveGrid() {
    if (!grid) return;
    var now = new Date();
    grid.mainBody.querySelectorAll(".epg-block[data-start]").forEach(function (el) {
      var start = new Date(el.dataset.start);
      var stop = new Date(el.dataset.stop);
      el.classList.toggle("live", now >= start && now < stop);
    });
  }

  function buildDayButtons() {
    var wrap = document.getElementById("day-buttons");
    if (!wrap || !epgData) return;
    var days = epgData.days;
    if (!days.length) return;
    var frag = document.createDocumentFragment();

    function makeBtn(day) {
      var d = new Date(day + "T00:00:00");
      var label = isNaN(d.getTime())
        ? day
        : d.toLocaleDateString("cs-CZ", { weekday: "short", day: "2-digit", month: "2-digit" });
      var b = document.createElement("button");
      b.textContent = label;
      b.dataset.day = day;
      if (grid && day === grid.day) b.classList.add("active");
      b.addEventListener("click", function () {
        Array.prototype.forEach.call(wrap.children, function (c) {
          c.classList.toggle("active", c === b);
        });
        if (grid) grid.day = day;
        applyAll();
        applyListDayFilter(day);
      });
      return b;
    }

    days.forEach(function (day) {
      frag.appendChild(makeBtn(day));
    });
    wrap.appendChild(frag);
  }

  // ---------- text list view (server-rendered fallback / crawler content) ----------

  var listChannels = Array.prototype.slice.call(document.querySelectorAll("#seznam .channel"));

  function applyListFilters(query) {
    var q = normalize(query);
    listChannels.forEach(function (sec) {
      var name = normalize(sec.dataset.name);
      var ch = epgData ? epgData.channels.find(function (c) { return c.name === sec.dataset.name; }) : null;
      var matches = !q || name.indexOf(q) !== -1 || (ch && ch.programmes.some(function (p) { return normalize(p.title).indexOf(q) !== -1; }));
      sec.style.display = matches ? "" : "none";
    });
  }

  function applyListDayFilter(day) {
    listChannels.forEach(function (sec) {
      var visible = 0;
      Array.prototype.forEach.call(sec.querySelectorAll(".day-group"), function (g) {
        var show = day === "all" || g.dataset.day === day;
        g.style.display = show ? "" : "none";
        if (show) visible++;
      });
      if (visible === 0 && sec.style.display !== "none") sec.dataset.emptyDay = "1";
    });
  }

  function markLiveList() {
    var now = new Date();
    document.querySelectorAll("#seznam .programmes li[data-start]").forEach(function (li) {
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

  // ---------- wiring ----------

  var search = document.getElementById("search");

  function applyAll() {
    var q = search ? search.value : "";
    renderGrid(q);
    applyListFilters(q);
  }

  if (search) search.addEventListener("input", applyAll);

  var jumpNow = document.getElementById("jump-now");
  if (jumpNow) {
    jumpNow.addEventListener("click", function () {
      if (grid && epgData.days.indexOf(mskToday()) !== -1) {
        grid.day = mskToday();
        var wrap = document.getElementById("day-buttons");
        if (wrap) {
          Array.prototype.forEach.call(wrap.children, function (c) {
            c.classList.toggle("active", c.dataset.day === grid.day);
          });
        }
        applyAll();
        applyListDayFilter(grid.day);
      }
      if (grid) {
        var nowMin = mskNowParts();
        grid.main.scrollLeft = Math.max(0, nowMin * PX_PER_MIN - grid.main.clientWidth / 2);
      }
    });
  }

  if (grid) {
    buildRuler();
    grid.main.addEventListener("scroll", function () {
      grid.head.scrollLeft = grid.main.scrollLeft;
      grid.side.scrollTop = grid.main.scrollTop;
    });
    grid.side.addEventListener("scroll", function () {
      grid.main.scrollTop = grid.side.scrollTop;
    });
  }

  buildDayButtons();
  applyAll();
  if (grid && grid.day) applyListDayFilter(grid.day);
  markLiveList();
  setInterval(function () {
    markLiveList();
    markLiveGrid();
  }, 60000);
})();
