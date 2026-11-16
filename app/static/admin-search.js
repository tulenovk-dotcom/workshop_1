/* Админка, «Все записи каталога»: поиск по таблице прямо на странице.
 *
 * Каждая строка несёт в data-search текст (название, специальность, город,
 * район, адрес), а в data-phones номера. Текст сравнивается без учёта
 * регистра и с «ё» как «е»; номер - только по цифрам, чтобы скобки,
 * пробелы и дефисы не мешали. Все слова запроса должны найтись в строке,
 * в любом порядке: «логопед алматы» найдёт логопеда из Алматы.
 *
 * Запрос пишется в адрес страницы (?q=...), поэтому после «Изменить» и
 * возврата назад поиск остаётся на месте.
 */
(function () {
  "use strict";

  var box = document.querySelector("[data-admin-search]");
  if (!box) { return; }
  var input = box.querySelector("input");
  var count = box.querySelector("[data-admin-search-count]");
  var empty = document.querySelector("[data-admin-search-empty]");
  var rows = Array.prototype.slice.call(document.querySelectorAll("tr[data-search]"));

  function norm(text) {
    return (text || "").toLowerCase().replace(/ё/g, "е");
  }
  function digits(text) {
    return (text || "").replace(/\D/g, "");
  }

  var index = rows.map(function (row) {
    return {
      row: row,
      text: norm(row.dataset.search),
      phones: digits(row.dataset.phones)
    };
  });

  // Запрос из одних цифр, пробелов, скобок и плюса - это номер телефона:
  // его сравниваем целиком по цифрам, иначе «+7 707 406» распался бы на
  // три слова. Нужно хотя бы три цифры, чтобы «1» не нашлась везде.
  function phoneQuery(query) {
    return /^[\d\s()+-]+$/.test(query) && digits(query).length >= 3
      ? digits(query) : "";
  }

  function matches(item, query, words) {
    var phone = phoneQuery(query);
    if (phone) {
      // Номер могли ввести и с восьмёркой, и с семёркой в начале.
      var tail = phone.replace(/^[78](?=\d{10}$)/, "");
      return item.phones.indexOf(tail) !== -1 || item.text.indexOf(query) !== -1;
    }
    return words.every(function (word) { return item.text.indexOf(word) !== -1; });
  }

  function update() {
    var query = norm(input.value).trim();
    var words = query ? query.split(/\s+/) : [];
    var shown = 0;
    index.forEach(function (item) {
      var ok = !words.length || matches(item, query, words);
      item.row.hidden = !ok;
      if (ok) { shown += 1; }
    });
    count.textContent = words.length
      ? "Найдено: " + shown + " из " + index.length
      : "";
    if (empty) { empty.hidden = !(words.length && shown === 0); }

    var url = new URL(window.location.href);
    if (input.value.trim()) { url.searchParams.set("q", input.value.trim()); }
    else { url.searchParams.delete("q"); }
    window.history.replaceState(null, "", url);
  }

  box.hidden = false;
  input.value = new URLSearchParams(window.location.search).get("q") || "";
  input.addEventListener("input", update);
  update();
})();
