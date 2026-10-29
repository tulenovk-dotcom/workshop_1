/* Кнопка телефона: номер приходит с сервера только по нажатию.
 *
 * Что делает: перехватывает отправку формы «Позвонить» / «Показать номер»,
 * спрашивает номер коротким запросом и ставит его на место кнопки.
 * На телефоне после этого сразу открывается звонок, на компьютере человек
 * видит номер и может его переписать.
 *
 * Если скрипт не сработал или запрос не прошёл, форма отправляется обычным
 * способом, и сайт показывает карточку уже с номером. Кнопка не ломается
 * ни при каком исходе.
 */
(function () {
  "use strict";

  function hasMouse() {
    return window.matchMedia &&
      window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  }

  function showNumber(form, data) {
    var button = form.querySelector("button");
    var link = document.createElement("a");
    link.className = button.className + " phone-shown";
    link.href = "tel:" + data.tel;
    link.textContent = data.phone;
    form.replaceWith(link);
    return link;
  }

  function showError(form, text) {
    var old = form.parentNode.querySelector(".phone-error");
    if (old) { old.remove(); }
    var note = document.createElement("p");
    note.className = "notice notice-warn phone-error";
    note.textContent = text;
    form.insertAdjacentElement("afterend", note);
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute || !form.hasAttribute("data-phone-form")) { return; }
    if (!window.fetch) { return; }
    event.preventDefault();
    var button = form.querySelector("button");
    if (button.disabled) { return; }
    button.disabled = true;

    fetch(form.action, {
      method: "POST",
      headers: { "Accept": "application/json" },
      credentials: "same-origin"
    }).then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    }).then(function (result) {
      if (!result.ok) {
        button.disabled = false;
        showError(form, result.data.error || "");
        return;
      }
      var link = showNumber(form, result.data);
      if (!hasMouse()) {
        // Телефон: сразу открываем звонок, номер при этом уже на экране.
        window.location.href = link.href;
      }
    }).catch(function () {
      // Что-то пошло не так - отправляем форму по-старому.
      button.disabled = false;
      form.submit();
    });
  });
})();
