/* Анкета: выбор между бесплатным размещением и продвижением.
 *
 * Блок спрятан, пока не выбран город, где продвижение работает. Список
 * таких городов сервер кладёт в data-promo-cities: он считается из самого
 * каталога, поэтому город появляется в нём сам, как только карточек станет
 * достаточно.
 *
 * Без скрипта блок так и остаётся спрятанным, и человек размещается
 * бесплатно. Это намеренно: лучше не предложить платное, чем предложить
 * тому, кому оно не положено. Сервер в любом случае проверяет город заново.
 */
(function () {
  "use strict";

  var picker = document.querySelector("[data-plan-picker]");
  var choice = document.getElementById("city_choice");
  var other = document.getElementById("city_other");
  if (!picker || !choice) { return; }

  var cities = (picker.dataset.promoCities || "").split("|").filter(Boolean);

  function cityValue() {
    // «Другой город» вписывается в отдельное поле - оно и главнее.
    if (other && other.value.trim()) { return other.value.trim(); }
    return choice.value.trim();
  }

  function update() {
    var allowed = cities.indexOf(cityValue()) !== -1;
    picker.hidden = !allowed;
    if (!allowed) {
      // Спрятали - значит выбор снят: иначе человек сменил город, а
      // отметка о продвижении осталась бы висеть незаметно для него.
      var free = picker.querySelector('input[value="free"]');
      if (free) { free.checked = true; }
    }
  }

  choice.addEventListener("change", update);
  if (other) { other.addEventListener("input", update); }
  update();
})();
