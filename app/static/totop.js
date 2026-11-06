/* Кнопка «наверх».
 *
 * Зачем: каталог, список методов и таблицы в админке длинные, и листать
 * обратно к началу руками долго. Кнопка висит в правом нижнем углу и
 * возвращает к началу страницы одним нажатием.
 *
 * Появляется не сразу: пока не пролистали больше экрана с половиной, её
 * нет. На короткой странице возвращаться некуда, а угол она занимает.
 *
 * Разметка приходит с атрибутом hidden, и снимает его этот скрипт. Если
 * скрипт не выполнится, кнопки просто не будет: страница листается как
 * обычно, и ничего не ломается.
 */
(function () {
  "use strict";

  var button = document.getElementById("to-top");
  if (!button) {
    return;
  }

  var shown = false;
  var waiting = false;

  function update() {
    waiting = false;
    var offset = window.pageYOffset || document.documentElement.scrollTop || 0;
    var need = offset > window.innerHeight * 1.5;
    if (need === shown) {
      return;
    }
    shown = need;
    button.classList.toggle("is-visible", need);
  }

  // Прокрутка сыплет событиями пачками; считаем не чаще, чем рисует браузер.
  function onScroll() {
    if (waiting) {
      return;
    }
    waiting = true;
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(update);
    } else {
      update();
    }
  }

  function calmMotion() {
    return window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  button.addEventListener("click", function () {
    if ("scrollBehavior" in document.documentElement.style) {
      window.scrollTo({ top: 0, behavior: calmMotion() ? "auto" : "smooth" });
    } else {
      window.scrollTo(0, 0);
    }

    // Клавиатуру тоже возвращаем в начало: иначе следующий Tab продолжил бы
    // ходить по ссылкам подвала, которых на экране уже нет. Прокрутку при
    // этом не трогаем, её делает scrollTo выше.
    var logo = document.querySelector(".site-header .logo");
    if (logo && typeof logo.focus === "function") {
      try {
        logo.focus({ preventScroll: true });
      } catch (error) {
        logo.focus();
      }
    }
  });

  button.hidden = false;
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
  update();
})();
