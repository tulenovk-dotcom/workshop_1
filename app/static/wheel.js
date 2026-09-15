"use strict";

// Колесо выбора значения: прокрутка с примагничиванием и наклоном строк,
// как в будильнике iOS.
function setupWheel(wheel) {
  const list = wheel.querySelector(".wheel-list");
  const items = [...wheel.querySelectorAll(".wheel-item")];
  const input = document.getElementById(wheel.dataset.wheelFor);
  if (!list || !items.length || !input) return;

  const step = () => items[0].offsetHeight || 36;
  let frame = null;

  const paint = () => {
    const center = list.scrollTop + list.clientHeight / 2;
    const height = step();
    items.forEach((item) => {
      const distance = (item.offsetTop + height / 2 - center) / height;
      const limited = Math.max(-3, Math.min(3, distance));
      item.style.transform =
        `rotateX(${limited * 20}deg) scale(${1 - Math.abs(limited) * 0.06})`;
      item.style.opacity = String(Math.max(0.28, 1 - Math.abs(limited) * 0.3));
      const selected = Math.abs(distance) < 0.5;
      item.classList.toggle("is-selected", selected);
      item.setAttribute("aria-selected", selected ? "true" : "false");
    });
  };

  const commit = () => {
    const index = Math.max(0, Math.min(items.length - 1,
      Math.round(list.scrollTop / step())));
    const value = items[index].dataset.value;
    if (input.value !== value) {
      input.value = value;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };

  const scrollToIndex = (index, smooth) => {
    list.scrollTo({ top: index * step(), behavior: smooth ? "smooth" : "auto" });
  };

  list.addEventListener("scroll", () => {
    if (frame) cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => { paint(); commit(); });
  });

  items.forEach((item, index) =>
    item.addEventListener("click", () => scrollToIndex(index, true)));

  list.addEventListener("keydown", (event) => {
    const current = Math.round(list.scrollTop / step());
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = current + (event.key === "ArrowDown" ? 1 : -1);
      scrollToIndex(Math.max(0, Math.min(items.length - 1, next)), true);
    }
  });

  const start = items.findIndex((item) => item.dataset.value === input.value);
  scrollToIndex(start < 0 ? 0 : start, false);
  paint();
}

document.querySelectorAll(".wheel").forEach(setupWheel);

// На телефоне фильтры занимают весь первый экран, поэтому свёрнуты.
const filtersBox = document.getElementById("filters-box");
if (filtersBox && window.matchMedia("(max-width: 900px)").matches) {
  filtersBox.open = false;
}
