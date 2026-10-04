/* Окно «сайт в тестовом режиме» при первом визите.
 *
 * Это единственный скрипт на сайте, и появился он по необходимости:
 * запомнить, что посетитель закрыл окно, без JavaScript нельзя - хранилище
 * браузера читается только так. Всё остальное на сайте по-прежнему работает
 * без скриптов, и эта страница тоже: разметка окна скрыта атрибутом hidden,
 * и если скрипт не выполнится, посетитель просто не увидит окна.
 *
 * Хранилище может быть недоступно - приватный режим, запрет сторонних
 * данных, переполнение. Поэтому каждое обращение к нему обёрнуто в try:
 * не вышло запомнить - окно появится снова, и это единственное следствие.
 */
(function () {
  "use strict";

  var KEY = "erekshe.test-notice.until";
  var WEEK = 7 * 24 * 60 * 60 * 1000;

  var overlay = document.getElementById("test-notice");
  if (!overlay) {
    return;
  }

  function hiddenUntil() {
    try {
      return parseInt(window.localStorage.getItem(KEY), 10) || 0;
    } catch (error) {
      return 0;
    }
  }

  function remember() {
    try {
      window.localStorage.setItem(KEY, String(Date.now() + WEEK));
    } catch (error) {
      // Молча: не запомнили - покажем снова через неделю... или раньше.
    }
  }

  if (Date.now() < hiddenUntil()) {
    return;
  }

  var buttons = overlay.querySelectorAll("button");
  var opener = document.activeElement;

  function close() {
    remember();
    overlay.hidden = true;
    document.removeEventListener("keydown", onKey);
    if (opener && typeof opener.focus === "function") {
      opener.focus();
    }
  }

  // Esc закрывает, Tab ходит по кругу внутри окна: пока окно открыто,
  // уводить клавиатуру на страницу под ним незачем.
  function onKey(event) {
    if (event.key === "Escape") {
      close();
      return;
    }
    if (event.key !== "Tab" || buttons.length < 2) {
      return;
    }
    var first = buttons[0];
    var last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      last.focus();
      event.preventDefault();
    } else if (!event.shiftKey && document.activeElement === last) {
      first.focus();
      event.preventDefault();
    }
  }

  overlay.addEventListener("click", function (event) {
    // Щелчок по затемнению вокруг окна - тоже «закрыть».
    if (event.target === overlay || event.target.hasAttribute("data-notice-close")) {
      close();
    }
  });

  document.addEventListener("keydown", onKey);
  overlay.hidden = false;
  if (buttons.length) {
    buttons[buttons.length - 1].focus();
  }
})();
