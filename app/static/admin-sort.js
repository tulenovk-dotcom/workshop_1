/* Админка: сортировка любой таблицы по нажатию на заголовок колонки.
 *
 * Первое нажатие - по возрастанию (▲), повторное - по убыванию (▼).
 * Числа сравниваются как числа (пробелы, «%» и «₸» не мешают), даты вида
 * 17.11.2026 или 17.11.2026 13:40 - как даты, остальное - как текст по
 * алфавиту. Пустые ячейки и прочерк «—» всегда уходят в конец.
 *
 * Не сортируются: колонка «Действия», пустые заголовки, столбики-доли
 * (class="stat-col-bar") и заголовки с data-no-sort. Таблица с
 * data-sort-server сортируется на сервере сама (например, «Переходы»),
 * её скрипт не трогает. Итоговая строка в <tfoot> остаётся на месте.
 */
(function () {
  "use strict";

  var DATE = /^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/;
  var NUMBER = /^[-+]?\d[\d\s ]*(?:[.,]\d+)?\s*(?:%|₸)?$/;

  function cellValue(cell) {
    if (!cell) { return { kind: 2, value: "" }; }
    if (cell.dataset.sortValue !== undefined) {
      var raw = cell.dataset.sortValue;
      var asNumber = parseFloat(raw);
      return isNaN(asNumber) ? { kind: 1, value: raw.toLowerCase() } : { kind: 0, value: asNumber };
    }
    var text = (cell.textContent || "").replace(/\s+/g, " ").trim();
    if (!text || text === "—" || text === "-") { return { kind: 2, value: "" }; }
    var date = text.match(DATE);
    if (date) {
      return {
        kind: 0,
        value: Date.UTC(+date[3], +date[2] - 1, +date[1], +(date[4] || 0), +(date[5] || 0))
      };
    }
    if (NUMBER.test(text)) {
      return {
        kind: 0,
        value: parseFloat(text.replace(/[\s %₸]/g, "").replace(",", "."))
      };
    }
    return { kind: 1, value: text.toLowerCase().replace(/ё/g, "е") };
  }

  function compare(a, b) {
    if (a.kind !== b.kind) { return a.kind - b.kind; }
    if (a.kind === 1) { return a.value.localeCompare(b.value, "ru"); }
    return a.value - b.value;
  }

  function sortable(th) {
    var label = (th.textContent || "").trim();
    return label && label !== "Действия" && !th.hasAttribute("data-no-sort")
      && !th.classList.contains("stat-col-bar");
  }

  function setup(table) {
    if (table.hasAttribute("data-sort-server")) { return; }
    var body = table.tBodies[0];
    var head = table.tHead;
    if (!body || !head || !head.rows.length) { return; }
    var headers = Array.prototype.slice.call(head.rows[head.rows.length - 1].cells);

    headers.forEach(function (th, column) {
      if (!sortable(th)) { return; }
      th.classList.add("sortable");
      th.setAttribute("role", "button");
      th.tabIndex = 0;
      th.title = "Сортировать";

      function run() {
        var order = th.dataset.order === "asc" ? "desc" : "asc";
        headers.forEach(function (other) {
          delete other.dataset.order;
          other.removeAttribute("aria-sort");
        });
        th.dataset.order = order;
        th.setAttribute("aria-sort", order === "asc" ? "ascending" : "descending");

        var rows = Array.prototype.slice.call(body.rows).map(function (row, index) {
          return { row: row, index: index, value: cellValue(row.cells[column]) };
        });
        rows.sort(function (a, b) {
          // Пустые - всегда в конце, в какую сторону ни сортируй.
          if ((a.value.kind === 2) !== (b.value.kind === 2)) {
            return a.value.kind === 2 ? 1 : -1;
          }
          var result = compare(a.value, b.value);
          if (order === "desc") { result = -result; }
          return result || a.index - b.index;
        });
        rows.forEach(function (item) { body.appendChild(item.row); });
      }

      th.addEventListener("click", function (event) {
        if (event.target.closest("a, button, input, select")) { return; }
        run();
      });
      th.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          run();
        }
      });
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("table.admin-table"), setup);
})();
