/* Каталог: карта мест занятий и «Найти ближайшие ко мне».
 *
 * Карта открывается только по кнопке: до нажатия ни библиотека карты, ни
 * картинки OpenStreetMap не загружаются. На карте те же места, что в списке
 * под ней, то есть с учётом фильтров. Места без точки на карте остаются
 * только в списке.
 *
 * «Ближайшие» спрашивают у браузера, где человек находится, и пересортируют
 * список по расстоянию. Расстояние считается здесь же, в браузере: место
 * человека на сайт не отправляется и нигде не хранится.
 */
(function () {
  "use strict";

  var tools = document.querySelector("[data-map-tools]");
  var box = document.getElementById("catalog-map");
  var list = document.querySelector(".cards");
  if (!tools || !box || !list) { return; }

  var text = tools.dataset;
  var toggle = tools.querySelector("[data-map-toggle]");
  var nearButton = tools.querySelector("[data-near-me]");
  var status = tools.querySelector("[data-map-status]");
  tools.hidden = false;

  // Цвета берём из токенов сайта, а не пишем здесь свои.
  var css = window.getComputedStyle(document.documentElement);
  var ACCENT = css.getPropertyValue("--accent").trim() || "#22333f";
  var SURFACE = css.getPropertyValue("--surface").trim() || "#ffffff";

  var map = null;
  var markers = {};
  var youMarker = null;
  var you = null;

  function say(message) { status.textContent = message || ""; }

  function cards() {
    return Array.prototype.slice.call(list.querySelectorAll(".provider-card"));
  }

  function point(card) {
    var lat = parseFloat(card.dataset.lat);
    var lng = parseFloat(card.dataset.lng);
    return isNaN(lat) || isNaN(lng) ? null : [lat, lng];
  }

  // Расстояние по поверхности Земли, в километрах.
  function distanceKm(a, b) {
    var rad = Math.PI / 180;
    var dLat = (b[0] - a[0]) * rad;
    var dLng = (b[1] - a[1]) * rad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(a[0] * rad) * Math.cos(b[0] * rad) *
      Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  }

  function formatKm(km) {
    var value = km < 10 ? km.toFixed(1) : String(Math.round(km));
    return text.textKm.replace("%s", value.replace(".", ","));
  }

  function loadLeaflet() {
    if (window.L) { return Promise.resolve(); }
    return new Promise(function (resolve, reject) {
      var css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = text.leafletCss;
      document.head.appendChild(css);
      var script = document.createElement("script");
      script.src = text.leafletJs;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function popupContent(card) {
    var link = card.querySelector(".pc-name a");
    var wrap = document.createElement("div");
    var name = document.createElement("strong");
    name.textContent = link ? link.textContent : "";
    wrap.appendChild(name);
    var city = card.querySelector(".pc-city");
    if (city) {
      var line = document.createElement("div");
      line.textContent = city.textContent.replace(/\s+/g, " ").trim();
      wrap.appendChild(line);
    }
    if (link) {
      var more = document.createElement("a");
      more.href = link.getAttribute("href");
      more.textContent = text.textMore;
      wrap.appendChild(more);
    }
    return wrap;
  }

  function buildMap() {
    map = window.L.map(box, { scrollWheelZoom: false });
    window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    cards().forEach(function (card) {
      var p = point(card);
      if (!p) { return; }
      markers[card.dataset.providerId] = window.L.circleMarker(p, {
        radius: 9, weight: 2, color: SURFACE, fillColor: ACCENT, fillOpacity: 1
      }).bindPopup(popupContent(card)).addTo(map);
    });
    fitView();
  }

  function fitView() {
    if (!map) { return; }
    var points = cards().map(point).filter(Boolean);
    if (you) {
      // С местом человека: он и три ближайших к нему, а не вся страна.
      points.sort(function (a, b) { return distanceKm(you, a) - distanceKm(you, b); });
      points = [you].concat(points.slice(0, 3));
      if (!youMarker) {
        youMarker = window.L.circleMarker(you, {
          radius: 7, weight: 3, color: ACCENT, fillColor: SURFACE, fillOpacity: 1
        }).bindTooltip(text.textYou).addTo(map);
      } else {
        youMarker.setLatLng(you);
      }
    }
    if (!points.length) {
      map.setView([48.0, 67.0], 4);
      say(text.textNone);
    } else if (points.length === 1) {
      map.setView(points[0], 14);
    } else {
      map.fitBounds(points, { padding: [30, 30], maxZoom: 15 });
    }
  }

  function setOpen(open) {
    box.hidden = !open;
    toggle.textContent = open ? text.textHide : text.textShow;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  toggle.addEventListener("click", function () {
    if (!box.hidden) { setOpen(false); return; }
    setOpen(true);
    toggle.disabled = true;
    loadLeaflet().then(function () {
      toggle.disabled = false;
      if (!map) { buildMap(); } else { map.invalidateSize(); fitView(); }
    }).catch(function () {
      toggle.disabled = false;
      setOpen(false);
    });
  });

  function sortByDistance() {
    var all = cards();
    all.forEach(function (card) {
      var p = point(card);
      card._km = p ? distanceKm(you, p) : Infinity;
      var label = card.querySelector("[data-distance]");
      if (label) {
        label.hidden = !p;
        label.textContent = p ? formatKm(card._km) : "";
      }
    });
    all.sort(function (a, b) { return a._km - b._km; });
    all.forEach(function (card) { list.appendChild(card); });
  }

  nearButton.addEventListener("click", function () {
    if (!navigator.geolocation) { say(text.textDenied); return; }
    nearButton.disabled = true;
    say(text.textLocating);
    navigator.geolocation.getCurrentPosition(function (pos) {
      nearButton.disabled = false;
      you = [pos.coords.latitude, pos.coords.longitude];
      sortByDistance();
      say(text.textSorted);
      fitView();
    }, function () {
      nearButton.disabled = false;
      say(text.textDenied);
    }, { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 });
  });
})();
