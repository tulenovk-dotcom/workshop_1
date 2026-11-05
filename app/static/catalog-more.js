/* Каталог: показываем по 20 карточек, остальные открываются кнопкой «Показать ещё».
 *
 * Все карточки остаются в странице, скрываются только лишние. Так карта и
 * «Найти ближайшие ко мне» работают со всем списком. После сортировки по
 * расстоянию catalog-map.js присылает событие catalog:sorted, и здесь заново
 * решаем, какие карточки показывать.
 *
 * Без скрипта кнопка спрятана, и весь список виден сразу.
 */
(function () {
  "use strict";

  var list = document.querySelector(".cards");
  var more = document.querySelector("[data-more]");
  if (!list || !more) { return; }

  var button = more.querySelector("[data-show-more]");
  var label = button.dataset.label || button.textContent;
  var pageSize = parseInt(list.dataset.pageSize, 10) || 20;
  var shown = pageSize;

  function cards() {
    return Array.prototype.slice.call(list.querySelectorAll(".provider-card"));
  }

  function render() {
    var all = cards();
    all.forEach(function (card, index) {
      card.hidden = index >= shown;
    });
    more.hidden = all.length <= shown;
  }

  button.addEventListener("click", function () {
    var before = shown;
    shown += pageSize;
    render();
    // Фокус на первую новую карточку: видно, что список продолжился,
    // и клавиатурный пользователь не теряет место.
    var first = cards()[before];
    var link = first && first.querySelector(".pc-name a");
    if (link) { link.focus(); }
  });

  document.addEventListener("catalog:sorted", render);

  render();
})();
