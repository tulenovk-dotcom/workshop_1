/* Поиск по длинному списку выбора (пока он один - «Место занятий» на
 * странице оплат).
 *
 * Поле поиска стоит над самим списком и оставляет в нём только
 * подходящие строки: сравнение без учёта регистра, «ё» как «е», все
 * слова запроса должны найтись, в любом порядке. «шаг алматы» оставит
 * алматинский «Шаг за шагом».
 *
 * Лишние строки прячутся и заодно отключаются: атрибут hidden старый
 * Safari у строк списка не понимает, и там они останутся видны, но
 * выбрать их всё равно не выйдет.
 *
 * Если выбранная строка больше не подходит под запрос, выбор снимается:
 * иначе можно было бы записать оплату тому, кого на экране уже нет.
 *
 * Без скрипта поле спрятано, а список работает как обычно.
 */
(function () {
  "use strict";

  var inputs = document.querySelectorAll("[data-pick-search]");
  if (!inputs.length) { return; }

  function norm(text) {
    return (text || "").toLowerCase().replace(/ё/g, "е");
  }

  Array.prototype.forEach.call(inputs, function (input) {
    var list = document.getElementById(input.dataset.pickSearch);
    if (!list) { return; }
    var field = input.closest(".field") || document;
    var count = field.querySelector("[data-pick-search-count]");

    // Первая строка - приглашение «Выберите из каталога», у неё пустое
    // значение. Её не прячем никогда, иначе список окажется без начала.
    var items = Array.prototype.filter.call(list.options, function (option) {
      return option.value !== "";
    }).map(function (option) {
      return { option: option, text: norm(option.textContent) };
    });

    function update() {
      var query = norm(input.value).trim();
      var words = query ? query.split(/\s+/) : [];
      var shown = 0;
      items.forEach(function (item) {
        var ok = !words.length || words.every(function (word) {
          return item.text.indexOf(word) !== -1;
        });
        item.option.hidden = !ok;
        item.option.disabled = !ok;
        if (ok) { shown += 1; }
      });

      var chosen = list.options[list.selectedIndex];
      if (chosen && chosen.value !== "" && chosen.hidden) { list.value = ""; }

      if (count) {
        if (!words.length) { count.textContent = ""; }
        else if (shown) { count.textContent = "Подходит: " + shown + " из " + items.length; }
        else { count.textContent = "Ничего не найдено. Проверьте написание или поищите по городу."; }
      }
    }

    input.hidden = false;
    input.addEventListener("input", update);
    update();
  });
})();
