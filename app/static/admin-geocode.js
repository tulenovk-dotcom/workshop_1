/* Админка: «Найти по адресу» у поля «Точка на карте».
 *
 * Берёт город и адрес из формы и спрашивает координаты у OpenStreetMap
 * (служба Nominatim) прямо из браузера администратора. Сайт сам ничего
 * никуда не отправляет. Найденная точка - подсказка: OpenStreetMap знает
 * казахстанские адреса не все, поэтому рядом выводится ссылка, по которой
 * точку можно проверить глазами.
 */
(function () {
  "use strict";

  var button = document.querySelector("[data-geocode]");
  var input = document.getElementById("coords");
  var status = document.querySelector("[data-geocode-status]");
  if (!button || !input || !window.fetch) { return; }
  button.hidden = false;

  function cityValue() {
    var choice = document.getElementById("city_choice");
    var other = document.getElementById("city_other");
    // «Другой город» вписывается в отдельное поле - оно и главнее.
    if (other && other.value.trim()) { return other.value.trim(); }
    var city = choice ? choice.value : "";
    var listed = choice && choice.selectedIndex > 0 &&
      choice.selectedIndex < choice.options.length - 1;
    return listed ? city.trim() : "";
  }

  function say(text) {
    if (status) { status.textContent = text; }
  }

  button.addEventListener("click", function () {
    var address = (document.getElementById("address") || {}).value || "";
    var query = [address.trim(), cityValue(), "Казахстан"].filter(Boolean).join(", ");
    if (!address.trim()) {
      say("Сначала заполните адрес.");
      return;
    }
    button.disabled = true;
    say("Ищу: " + query + "...");
    var url = "https://nominatim.openstreetmap.org/search?format=json&limit=1" +
      "&countrycodes=kz&accept-language=ru&q=" + encodeURIComponent(query);
    fetch(url, { headers: { "Accept": "application/json" } })
      .then(function (response) { return response.json(); })
      .then(function (found) {
        button.disabled = false;
        if (!found || !found.length) {
          say("По этому адресу точка не нашлась. Скопируйте координаты из 2ГИС " +
              "или Google Карт: правая кнопка мыши на здании.");
          return;
        }
        var lat = Number(found[0].lat).toFixed(6);
        var lng = Number(found[0].lon).toFixed(6);
        input.value = lat + ", " + lng;
        status.textContent = "Найдено: " + found[0].display_name + ". ";
        var check = document.createElement("a");
        // m= ставит центр карты ровно в точку; /geo/ привязался бы к
        // ближайшему объекту вроде района и показал бы не то место.
        check.href = "https://2gis.kz/?m=" + lng + "%2C" + lat + "%2F18";
        check.target = "_blank";
        check.rel = "noopener";
        check.textContent = "Проверить точку в 2ГИС";
        status.appendChild(check);
      })
      .catch(function () {
        button.disabled = false;
        say("Служба поиска не ответила. Попробуйте ещё раз или вставьте координаты вручную.");
      });
  });
})();
