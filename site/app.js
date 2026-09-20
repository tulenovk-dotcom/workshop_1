"use strict";

const SEED = JSON.parse(document.getElementById("seed-data").textContent);
const STORE_KEY = "ras-catalog-demo-v4";
const ADMIN_KEY = "ras-catalog-admin";
const ADMIN_LOGIN = "admin";
const ADMIN_PASSWORD = "admin";

const PROVIDER_TYPES = {
  center: "Реабилитационный центр",
  clinic: "Медицинская клиника",
  specialist: "Частный специалист",
  kindergarten: "Коррекционный детский сад",
  school: "Школа / инклюзивный класс",
  state: "Государственная организация (ПМПК, КППК)",
};

const SPECIALTIES = ["Логопед", "Дефектолог", "АВА-терапевт", "Нейропсихолог",
  "Психолог", "Эрготерапевт", "Детский невролог", "Детский психиатр"];

// В фильтре показываются только эти методы; справочник шире и питает
// метки доказательности и страницу «Методы помощи».
const FILTER_METHOD_CODES = ["aba", "si", "speech_massage", "floortime",
  "pecs", "neuro", "montessori"];

// «До 3 лет» - строго меньше трёх, «Старше 12 лет» - строго больше
// двенадцати. Соседние группы пересекаются на границе, как в подписях.
const AGE_RANGES = [
  ["0-3", "До 3 лет", 0, 2],
  ["3-5", "3–5 лет", 3, 5],
  ["5-7", "5–7 лет", 5, 7],
  ["7-12", "7–12 лет", 7, 12],
  ["12+", "Старше 12 лет", 13, 18],
];

const AGE_RANGE_BOUNDS = Object.fromEntries(
  AGE_RANGES.map(([code, , low, high]) => [code, [low, high]]));

const PRICING = { free: "Бесплатно", paid: "Платно" };

const APPLICANT_KINDS = {
  organization: "Организация",
  specialist: "Частный специалист",
};

// Места занятий, которые может указать организация: «частный специалист»
// сюда не входит - для него отдельная ветка формы со специальностью.
const ORGANIZATION_TYPES = Object.fromEntries(
  Object.entries(PROVIDER_TYPES).filter(([code]) => code !== "specialist"));

const APPLICATION_STATUSES = {
  new: "Новая",
  in_progress: "В работе",
  approved: "Одобрена",
  rejected: "Отклонена",
};

const MAX_APPLICATIONS_PER_HOUR = 3;

const EVIDENCE = {
  proven: { label: "Доказано", css: "ev-proven", note: "" },
  limited: {
    label: "Ограниченные данные", css: "ev-limited",
    note: "Данных об эффективности этого метода при РАС пока недостаточно.",
  },
  none: {
    label: "Без доказательств при РАС", css: "ev-none",
    note: "Метод не имеет подтверждённой эффективности при РАС.",
  },
};

let state = loadState();
// Черновик формы заявки: после ошибки страница перерисовывается целиком,
// поэтому введённое держим здесь, как и фильтры каталога.
let applicationDraft = {};
let isAdmin = readAdmin();
let filters = {
  q: "", city: "", provider_type: "", specialty: "", method: "",
  age: "", proven_only: false,
};

function loadState() {
  let loaded = null;
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) loaded = JSON.parse(raw);
  } catch (e) { /* приватный режим - работаем без сохранения */ }
  const base = loaded || JSON.parse(JSON.stringify(SEED));
  base.applications = base.applications || [];
  base.application_times = base.application_times || [];
  return base;
}

function saveState() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) {}
}

function readAdmin() {
  try { return sessionStorage.getItem(ADMIN_KEY) === "1"; } catch (e) { return false; }
}

function writeAdmin(value) {
  isAdmin = value;
  try {
    if (value) sessionStorage.setItem(ADMIN_KEY, "1");
    else sessionStorage.removeItem(ADMIN_KEY);
  } catch (e) {}
}

function resetDemo() {
  state = JSON.parse(JSON.stringify(SEED));
  saveState();
}

// --- данные -----------------------------------------------------------------

const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
  (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

const nextId = (rows) => rows.reduce((max, row) => Math.max(max, row.id), 0) + 1;

const methodById = (id) => state.methods.find((m) => m.id === id);
const providerById = (id) => state.providers.find((p) => p.id === id);

function sortedMethods() {
  return [...state.methods].sort((a, b) =>
    a.sort_order - b.sort_order || a.name.localeCompare(b.name, "ru"));
}

function providerMethods(providerId) {
  return state.provider_methods
    .filter((link) => link.provider_id === providerId)
    .map((link) => methodById(link.method_id))
    .filter(Boolean)
    .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, "ru"));
}

function publishedReviews(providerId) {
  return state.reviews
    .filter((r) => r.provider_id === providerId && r.status === "published")
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

function reviewsByStatus(status) {
  return state.reviews
    .filter((r) => r.status === status)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

function ratingOf(providerId) {
  const rows = publishedReviews(providerId);
  if (!rows.length) return { value: null, count: 0 };
  const sum = rows.reduce((acc, r) => acc + r.rating, 0);
  return { value: Math.round((sum / rows.length) * 10) / 10, count: rows.length };
}

function cities() {
  return [...new Set(state.providers.map((p) => p.city).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "ru"));
}

function filterMethods() {
  return FILTER_METHOD_CODES
    .map((code) => state.methods.find((m) => m.code === code))
    .filter(Boolean);
}

const applicationById = (id) => state.applications.find((a) => a.id === id);

function applicationMethods(application) {
  const codes = application.method_codes || [];
  return codes
    .map((code) => state.methods.find((m) => m.code === code))
    .filter(Boolean);
}

function newApplicationsCount() {
  return state.applications.filter((a) => a.status === "new").length;
}

function moderationCounts() {
  const reviews = reviewsByStatus("pending").length;
  const applications = newApplicationsCount();
  return { reviews, applications, total: reviews + applications };
}

/** Казахстанский номер к виду «+7 707 123 45 67», иначе null. */
function normalizePhone(value) {
  let digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 10 && "67".includes(digits[0])) digits = "7" + digits;
  else if (digits.length === 11 && digits[0] === "8") digits = "7" + digits.slice(1);
  if (digits.length !== 11 || digits[0] !== "7" || !"67".includes(digits[1])) return null;
  return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)} ${digits.slice(7, 9)} ${digits.slice(9)}`;
}

const looksLikeEmail = (value) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);

function specialtiesInUse() {
  return [...new Set(state.providers.map((p) => p.specialty).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "ru"));
}

function searchProviders() {
  const ageRange = AGE_RANGE_BOUNDS[filters.age] || null;
  const query = filters.q.trim().toLowerCase();

  const found = state.providers.filter((p) => {
    if (query && !p.name.toLowerCase().includes(query)) return false;
    if (filters.city && p.city !== filters.city) return false;
    if (filters.provider_type && p.provider_type !== filters.provider_type) return false;
    if (filters.specialty && p.specialty !== filters.specialty) return false;

    const methods = providerMethods(p.id);
    if (filters.method && !methods.some((m) => m.code === filters.method)) return false;
    if (ageRange) {
      const [low, high] = ageRange;
      if (p.age_from !== null && p.age_from > high) return false;
      if (p.age_to !== null && p.age_to < low) return false;
    }
    if (filters.proven_only) {
      const hasProven = methods.some((m) => m.evidence_level === "proven");
      const hasNone = methods.some((m) => m.evidence_level === "none");
      if (!hasProven || hasNone) return false;
    }
    return true;
  });

  return found.sort((a, b) => {
    const ra = ratingOf(a.id).value;
    const rb = ratingOf(b.id).value;
    if (ra === null && rb !== null) return 1;
    if (rb === null && ra !== null) return -1;
    if (ra !== rb) return rb - ra;
    return a.name.localeCompare(b.name, "ru");
  });
}

// --- разметка ---------------------------------------------------------------

const price = (value) => value === null || value === undefined
  ? "" : String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");

function initials(name) {
  const parts = String(name || "").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0].toUpperCase()).join("") || "?";
}

function nameHue(name) {
  let hash = 0;
  for (const ch of String(name || "")) hash = (hash * 31 + ch.codePointAt(0)) % 360;
  return hash;
}

function logoHtml(provider, size) {
  if (provider.logo_path) {
    return `<img class="logo-img logo-${size}" src="${esc(provider.logo_path)}"
      alt="Фото или логотип: ${esc(provider.name)}" loading="lazy">`;
  }
  const hue = nameHue(provider.name);
  return `<span class="logo-img logo-${size} logo-fallback" aria-hidden="true"
    style="background: hsl(${hue} 45% 93%); color: hsl(${hue} 40% 32%)">${esc(initials(provider.name))}</span>`;
}

function ratingHtml(providerId) {
  const { value, count } = ratingOf(providerId);
  if (!count) return '<span class="rating rating-empty">Нет отзывов</span>';
  return `<span class="rating"><span class="star">★</span>${value.toFixed(1)}
    <span class="rating-count">(${count})</span></span>`;
}

function priceLine(p) {
  if (p.pricing === "free") return "Бесплатно";
  if (p.price_from && p.price_to && p.price_from !== p.price_to) {
    return `${price(p.price_from)}–${price(p.price_to)} ₸ за занятие`;
  }
  if (p.price_from || p.price_to) {
    return `${price(p.price_from || p.price_to)} ₸ за занятие`;
  }
  return "Цена не указана";
}

function ageLine(p) {
  if (p.age_from !== null && p.age_to !== null) return `${p.age_from}–${p.age_to} лет`;
  if (p.age_from !== null) return `от ${p.age_from} лет`;
  if (p.age_to !== null) return `до ${p.age_to} лет`;
  return "Возраст не указан";
}

const waLink = (value) => {
  const digits = String(value || "").replace(/\D/g, "");
  return digits ? `https://wa.me/${digits}` : "";
};

const siteLink = (value) => {
  const raw = String(value || "").trim();
  if (!raw) return "";
  return /^https?:\/\//.test(raw) ? raw : `https://${raw}`;
};

const instagramLink = (value) => {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^https?:\/\//.test(raw)) return raw;
  return `https://instagram.com/${raw.replace(/^@/, "")}`;
};

function optionList(items, selected, placeholder) {
  const head = placeholder ? `<option value="">${esc(placeholder)}</option>` : "";
  return head + items.map(([value, label]) =>
    `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(label)}</option>`
  ).join("");
}

// --- страницы ---------------------------------------------------------------

function catalogView() {
  return `
<section class="intro">
  <h1>Где получить помощь ребёнку с РАС в Казахстане</h1>
  <p>Реабилитационные центры, медицинские клиники, частные специалисты,
     коррекционные детские сады, школы и государственные организации.
     У каждого метода указан уровень доказательности, чтобы родителям было
     проще выбирать программу помощи.</p>
</section>

<section class="evidence-key">
  <h2>Что значат метки у методов</h2>
  <dl>
    <div>
      <dt><span class="badge ev-proven">Доказано</span></dt>
      <dd>Эффективность при РАС подтверждена исследованиями.</dd>
    </div>
    <div>
      <dt><span class="badge ev-limited">Ограниченные данные</span></dt>
      <dd>Метод изучен мало, надёжных выводов пока нет.</dd>
    </div>
    <div>
      <dt><span class="badge ev-none">Без доказательств при РАС</span></dt>
      <dd>Исследования влияния на проявления РАС не подтверждают.</dd>
    </div>
  </dl>
  <p class="hint">
    Метка говорит о состоянии исследований, а не о качестве работы
    конкретного специалиста. <a href="#/methods">Подробнее о методах</a>
  </p>
</section>

<h2 class="filters-title">Подобрать помощь</h2>

<form class="filters" id="filters" autocomplete="off">
  <div class="field field-wide">
    <label for="f-q">Поиск по названию или ФИО</label>
    <input type="search" id="f-q" name="q" value="${esc(filters.q)}"
           placeholder="Например: центр, логопед, фамилия">
  </div>
  <div class="field">
    <label for="f-city">Город</label>
    <select id="f-city" name="city">
      ${optionList(cities().map((c) => [c, c]), filters.city, "Все города")}
    </select>
  </div>
  <div class="field">
    <label for="f-type">Где заниматься</label>
    <select id="f-type" name="provider_type">
      ${optionList(Object.entries(PROVIDER_TYPES), filters.provider_type, "Все варианты")}
    </select>
  </div>
  <div class="field">
    <label for="f-specialty">Специальность</label>
    <select id="f-specialty" name="specialty">
      ${optionList(SPECIALTIES.map((s) => [s, s]), filters.specialty, "Все специальности")}
    </select>
  </div>
  <div class="field">
    <label for="f-method">Метод</label>
    <select id="f-method" name="method">
      ${optionList(filterMethods().map((m) => [m.code, m.name]), filters.method, "Все методы")}
    </select>
  </div>
  <div class="field">
    <label for="f-age">Возраст ребёнка</label>
    <select id="f-age" name="age">
      ${optionList(AGE_RANGES.map(([code, label]) => [code, label]), filters.age, "Любой возраст")}
    </select>
  </div>
  <div class="field field-check">
    <label class="switch-row">
      <span class="switch">
        <input type="checkbox" id="f-proven" name="proven_only"${filters.proven_only ? " checked" : ""}>
        <span class="switch-track"></span>
      </span>
      <span class="switch-label">Только доказательные методы</span>
    </label>
    <p class="hint">Без методов без доказательств.</p>
  </div>
  <div class="filter-actions">
    <button type="submit" class="btn btn-primary">Найти</button>
    <button type="button" class="btn btn-ghost" data-action="reset-filters">Сбросить</button>
  </div>
</form>

<div id="results">${resultsView()}</div>
`;
}

function resultsView() {
  const found = searchProviders();
  const cards = found.map((p) => {
    const methods = providerMethods(p.id);
    const contact = p.whatsapp
      ? `<a class="btn btn-cta" href="${esc(waLink(p.whatsapp))}" target="_blank"
           rel="noopener">Написать в WhatsApp</a>`
      : p.phone
        ? `<a class="btn btn-cta" href="tel:${esc(p.phone.replace(/\s/g, ""))}">Позвонить</a>`
        : `<a class="btn btn-cta" href="#/provider/${p.id}">Открыть карточку</a>`;

    return `
<article class="card provider-card">
  <div class="pc-media">
    ${logoHtml(p, "xl")}
    ${ratingHtml(p.id)}
  </div>

  <div class="pc-main">
    <h2 class="pc-name"><a href="#/provider/${p.id}">${esc(p.name)}</a></h2>
    <div class="badges">
      ${methods.map((m) => `<span class="badge ${EVIDENCE[m.evidence_level].css}"
          title="${esc(EVIDENCE[m.evidence_level].label)}">${esc(m.name)}</span>`).join("")}
    </div>
    <p class="pc-line"><span class="pc-key">Где заниматься:</span>
      ${esc(PROVIDER_TYPES[p.provider_type] || p.provider_type)}${p.specialty ? ", " + esc(p.specialty) : ""}
      ${p.is_test ? '<span class="chip chip-test">тестовая запись</span>' : ""}</p>
    <p class="pc-line"><span class="pc-key">Возраст детей:</span> ${ageLine(p)}</p>
    ${p.has_state_funding ? '<p class="pc-line pc-line-accent">Есть гос. финансирование</p>' : ""}
    ${p.description ? `<p class="pc-description">${esc(p.description.length > 230
      ? p.description.slice(0, 230).trimEnd() + "…" : p.description)}</p>` : ""}
  </div>

  <div class="pc-side">
    <p class="pc-city">${esc(p.city)}${p.district ? `<span>${esc(p.district)}</span>` : ""}</p>
    <p class="pc-price">${priceLine(p)}</p>
    ${contact}
    ${p.pricing === "free" ? '<p class="pc-hint">занятия бесплатные</p>' : ""}
    <a class="pc-more" href="#/provider/${p.id}">Подробнее</a>
  </div>
</article>`;
  }).join("");

  return `<p class="results-count">Найдено: ${found.length}</p>
    ${found.length ? "" : '<p class="empty">По заданным условиям ничего не найдено. Попробуйте изменить фильтры.</p>'}
    <div class="cards">${cards}</div>`;
}

function providerView(id, notice) {
  const p = providerById(id);
  if (!p) return '<p class="empty">Запись не найдена.</p>';
  const methods = providerMethods(p.id);
  const reviews = publishedReviews(p.id);

  const notices = {
    ok: '<p class="notice notice-ok">Спасибо! Отзыв отправлен на модерацию и появится после проверки.</p>',
    limit: '<p class="notice notice-warn">С одного устройства можно оставить один отзыв о месте занятий в сутки.</p>',
    invalid: '<p class="notice notice-warn">Заполните имя, оценку и текст отзыва.</p>',
  };

  return `
<p class="breadcrumbs"><a href="#/">← Вернуться к каталогу</a></p>
<article class="provider">
  <div class="card-head">
    <span class="chip">${esc(PROVIDER_TYPES[p.provider_type] || p.provider_type)}</span>
    ${p.is_test ? '<span class="chip chip-test">Тестовая запись</span>' : ""}
    ${ratingHtml(p.id)}
  </div>
  <div class="provider-head">
    ${logoHtml(p, "lg")}
    <div>
      <h1>${esc(p.name)}</h1>
      ${p.specialty ? `<p class="provider-specialty">${esc(p.specialty)}</p>` : ""}
    </div>
  </div>
  ${p.description ? `<p class="provider-description">${esc(p.description)}</p>` : ""}

  <div class="actions">
    ${p.phone ? `<a class="btn btn-primary" href="tel:${esc(p.phone.replace(/\s/g, ""))}">Позвонить</a>` : ""}
    ${p.whatsapp ? `<a class="btn btn-whatsapp" href="${esc(waLink(p.whatsapp))}"
        target="_blank" rel="noopener">Написать в WhatsApp</a>` : ""}
  </div>

  <h2>Информация</h2>
  <dl class="info-grid">
    <div><dt>Город</dt><dd>${esc(p.city)}</dd></div>
    ${p.district ? `<div><dt>Район</dt><dd>${esc(p.district)}</dd></div>` : ""}
    ${p.address ? `<div><dt>Адрес</dt><dd>${esc(p.address)}</dd></div>` : ""}
    ${p.phone ? `<div><dt>Телефон</dt><dd>${esc(p.phone)}</dd></div>` : ""}
    ${p.whatsapp ? `<div><dt>WhatsApp</dt><dd>${esc(p.whatsapp)}</dd></div>` : ""}
    ${p.website ? `<div><dt>Сайт</dt><dd><a href="${esc(siteLink(p.website))}"
        target="_blank" rel="noopener">${esc(p.website)}</a></dd></div>` : ""}
    ${p.instagram ? `<div><dt>Instagram</dt><dd><a href="${esc(instagramLink(p.instagram))}"
        target="_blank" rel="noopener">${esc(p.instagram)}</a></dd></div>` : ""}
    <div><dt>Возраст детей</dt><dd>${ageLine(p)}</dd></div>
    <div><dt>Оплата</dt><dd>${priceLine(p)}</dd></div>
    <div><dt>Гос. финансирование</dt><dd>${p.has_state_funding ? "Есть" : "Нет данных"}</dd></div>
  </dl>

  <h2>Методы</h2>
  ${methods.length ? `<ul class="method-list">${methods.map((m) => {
    const info = EVIDENCE[m.evidence_level];
    return `<li>
      <div class="method-head"><strong>${esc(m.name)}</strong>
        <span class="badge ${info.css}">${esc(info.label)}</span></div>
      ${info.note ? `<p class="method-note">${esc(info.note)}</p>` : ""}
    </li>`;
  }).join("")}</ul>` : '<p class="empty">Методы не указаны.</p>'}

  <h2 id="reviews">Отзывы</h2>
  ${notice ? notices[notice] || "" : ""}
  ${reviews.length ? `<ul class="reviews">${reviews.map((r) => `
    <li class="review">
      <div class="review-head"><strong>${esc(r.author_name)}</strong>
        <span class="review-rating">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</span>
        <span class="review-date">${esc(r.created_at.slice(0, 10))}</span></div>
      <p>${esc(r.text)}</p>
    </li>`).join("")}</ul>` : '<p class="empty">Опубликованных отзывов пока нет.</p>'}

  <h3>Оставить отзыв</h3>
  <form class="review-form" id="review-form" data-provider="${p.id}">
    <div class="field">
      <label for="r-name">Ваше имя</label>
      <input type="text" id="r-name" name="author_name" maxlength="80" required>
    </div>
    <div class="field">
      <label for="r-rating">Оценка</label>
      <select id="r-rating" name="rating">
        <option value="5">5 - отлично</option>
        <option value="4">4 - хорошо</option>
        <option value="3">3 - нормально</option>
        <option value="2">2 - плохо</option>
        <option value="1">1 - очень плохо</option>
      </select>
    </div>
    <div class="field field-wide">
      <label for="r-text">Текст отзыва</label>
      <textarea id="r-text" name="text" rows="5" maxlength="2000" required
        placeholder="Расскажите о занятиях, специалистах и результатах"></textarea>
    </div>
    <div class="filter-actions">
      <button type="submit" class="btn btn-primary">Отправить на модерацию</button>
    </div>
    <p class="hint">Отзывы публикуются после проверки модератором. Не оставляйте
       медицинские диагнозы и персональные данные других людей.</p>
  </form>
</article>`;
}

function methodsView() {
  const blocks = Object.entries(EVIDENCE).map(([level, info]) => {
    const items = sortedMethods().filter((m) => m.evidence_level === level);
    if (!items.length) return "";
    return `
<section class="level-block">
  <h2><span class="badge ${info.css}">${esc(info.label)}</span></h2>
  ${info.note ? `<p class="level-note">${esc(info.note)}</p>` : ""}
  <div class="method-cards">
    ${items.map((m) => `<article class="method-card">
      <h3>${esc(m.name)}</h3>
      <p>${esc(m.description)}</p>
      <p class="method-links"><a href="#/" data-action="filter-method"
         data-method="${esc(m.code)}">Найти, где занимаются этим методом</a></p>
    </article>`).join("")}
  </div>
</section>`;
  }).join("");

  return `
<section class="intro">
  <h1>Методы помощи простым языком</h1>
  <p>Здесь коротко о том, что делают специалисты на занятиях и насколько метод
     изучен при РАС. Уровень доказательности помогает понять, на что опираться
     в программе помощи ребёнку, а что рассматривать только как дополнение.</p>
</section>
${blocks}
<p class="footer-note">Уровень доказательности отражает состояние исследований,
   а не качество работы конкретного специалиста. Решения о программе помощи
   ребёнку обсуждайте с врачом и специалистами, которые его наблюдают.</p>`;
}

function freeHelpView() {
  const sections = ["Заключение ПМПК", "Государственный социальный заказ",
    "Портал социальных услуг и очередь", "Какие документы подготовить",
    "Куда обращаться в своём городе"];
  return `
<section class="intro">
  <h1>Как получить помощь бесплатно</h1>
  <p class="placeholder-note">Страница в подготовке - текст будет добавлен позже.</p>
</section>
<div class="placeholder">
  ${sections.map((title) => `<h2>${esc(title)}</h2><p>Текст будет добавлен.</p>`).join("")}
</div>
<p class="footer-note">Пока страница не заполнена, актуальный порядок получения
   бесплатных занятий уточняйте в местном управлении образования или социальной защиты.</p>`;
}

function applicationFormView(errors) {
  const f = applicationDraft;
  const v = (key) => esc(f[key] ?? "");
  const checkedMethods = new Set(f.methods || []);
  const errorBlock = errors && errors.length ? `
<div class="notice notice-warn form-errors">
  <p><strong>Заявка не отправлена. Проверьте, пожалуйста:</strong></p>
  <ul>${errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>
</div>` : "";

  return `
<section class="intro">
  <h1>Разместите информацию о себе в каталоге</h1>
  <p>Для реабилитационных центров, клиник, частных специалистов, детских садов
     и школ, которые работают с детьми с РАС.</p>
</section>

<section class="steps">
  <h2>Как проходит размещение</h2>
  <ol class="steps-list">
    <li><span class="step-num">1</span> Вы отправляете заявку.</li>
    <li><span class="step-num">2</span> Мы проверяем информацию и можем
      запросить лицензию или диплом.</li>
    <li><span class="step-num">3</span> Публикуем карточку в каталоге.</li>
  </ol>
  <p class="hint">Размещение бесплатное.</p>
</section>

${errorBlock}

<form class="admin-form application-form" id="application-form" autocomplete="off">
  <fieldset class="field field-wide kind-picker">
    <legend>Вы заполняете анкету от имени *</legend>
    <label class="radio">
      <input type="radio" name="applicant_kind" value="organization"${f.applicant_kind === "organization" ? " checked" : ""}>
      Организации (центр, клиника, детский сад, школа)
    </label>
    <label class="radio">
      <input type="radio" name="applicant_kind" value="specialist"${f.applicant_kind === "specialist" ? " checked" : ""}>
      Себя как частного специалиста (работаю сам)
    </label>
  </fieldset>

  <div class="field only-organization">
    <label for="a-org">Название организации *</label>
    <input type="text" id="a-org" name="org_name" maxlength="160" value="${v("org_name")}">
  </div>
  <div class="field only-organization">
    <label for="a-type">Где заниматься</label>
    <select id="a-type" name="provider_type">
      ${optionList(Object.entries(ORGANIZATION_TYPES), f.provider_type || "", "Не указано")}
    </select>
  </div>
  <div class="field only-specialist">
    <label for="a-person">Фамилия, имя, отчество *</label>
    <input type="text" id="a-person" name="person_name" maxlength="160" value="${v("person_name")}">
  </div>
  <div class="field only-specialist">
    <label for="a-specialty">Специальность</label>
    <select id="a-specialty" name="specialty">
      ${optionList(SPECIALTIES.map((x) => [x, x]), f.specialty || "", "Не указана")}
    </select>
  </div>

  <div class="field">
    <label for="a-city">Город *</label>
    <input type="text" id="a-city" name="city" maxlength="80" required value="${v("city")}">
  </div>
  <div class="field">
    <label for="a-address">Адрес</label>
    <input type="text" id="a-address" name="address" maxlength="200" value="${v("address")}">
  </div>

  <fieldset class="field field-wide methods-picker">
    <legend>Методы, с которыми вы работаете</legend>
    ${sortedMethods().map((m) => `<label class="checkbox">
      <input type="checkbox" name="methods" value="${esc(m.code)}"${checkedMethods.has(m.code) ? " checked" : ""}>
      ${esc(m.name)}
      <span class="badge ${EVIDENCE[m.evidence_level].css}">${esc(EVIDENCE[m.evidence_level].label)}</span>
    </label>`).join("")}
  </fieldset>

  <div class="field">
    <label for="a-age-from">Возраст детей от</label>
    <input type="number" id="a-age-from" name="age_from" min="0" max="18" value="${v("age_from")}">
  </div>
  <div class="field">
    <label for="a-age-to">Возраст детей до</label>
    <input type="number" id="a-age-to" name="age_to" min="0" max="18" value="${v("age_to")}">
  </div>
  <div class="field">
    <label for="a-price-from">Стоимость занятия от, ₸</label>
    <input type="number" id="a-price-from" name="price_from" min="0" step="500" value="${v("price_from")}">
  </div>
  <div class="field">
    <label for="a-price-to">Стоимость занятия до, ₸</label>
    <input type="number" id="a-price-to" name="price_to" min="0" step="500" value="${v("price_to")}">
  </div>
  <div class="field field-check">
    <label class="switch-row">
      <span class="switch">
        <input type="checkbox" id="a-free" name="pricing_free" value="1"${f.pricing_free ? " checked" : ""}>
        <span class="switch-track"></span>
      </span>
      <span class="switch-label">Занятия бесплатные</span>
    </label>
    <p class="hint">Тогда стоимость заполнять не нужно.</p>
  </div>

  <div class="field">
    <label for="a-link">Сайт или Instagram</label>
    <input type="text" id="a-link" name="link" maxlength="200"
           placeholder="example.kz или @account" value="${v("link")}">
  </div>
  <div class="field">
    <label for="a-contact">Контактное лицо *</label>
    <input type="text" id="a-contact" name="contact_person" maxlength="120" required value="${v("contact_person")}">
  </div>
  <div class="field">
    <label for="a-phone">Телефон *</label>
    <input type="tel" id="a-phone" name="phone" required
           placeholder="+7 701 234 56 78" value="${v("phone")}">
  </div>
  <div class="field">
    <label for="a-whatsapp">WhatsApp</label>
    <input type="tel" id="a-whatsapp" name="whatsapp"
           placeholder="+7 701 234 56 78" value="${v("whatsapp")}">
  </div>
  <div class="field">
    <label for="a-email">Электронная почта</label>
    <input type="email" id="a-email" name="email" maxlength="120" value="${v("email")}">
  </div>

  <div class="field field-wide">
    <label for="a-comment">Комментарий</label>
    <textarea id="a-comment" name="comment" rows="5" maxlength="2000"
              placeholder="Коротко о занятиях, программе и специалистах">${v("comment")}</textarea>
    <p class="hint">До 2000 символов.</p>
  </div>

  <div class="trap" aria-hidden="true">
    <label for="a-trap">Не заполняйте это поле</label>
    <input type="text" id="a-trap" name="company_site" tabindex="-1" autocomplete="off" value="">
  </div>

  <div class="field field-wide consent-field">
    <label class="checkbox">
      <input type="checkbox" name="consent" value="1" required${f.consent ? " checked" : ""}>
      Я согласен на обработку персональных данных и принимаю
      <a href="#/privacy">политику конфиденциальности</a> *
    </label>
  </div>

  <div class="filter-actions">
    <button type="submit" class="btn btn-primary">Отправить заявку</button>
  </div>
  <p class="hint field-wide">
    Поля со звёздочкой обязательные. Мы проверим информацию и свяжемся
    с вами в течение двух рабочих дней.
  </p>
</form>`;
}

function applicationSentView() {
  return `
<section class="intro">
  <h1>Спасибо!</h1>
  <p class="notice notice-ok">Мы проверим информацию и свяжемся с вами
     в течение 2 рабочих дней.</p>
</section>
<div class="placeholder">
  <h2>Что дальше</h2>
  <p>Мы посмотрим заявку и при необходимости попросим прислать лицензию или
     диплом. После проверки карточка появится в каталоге - размещение
     бесплатное.</p>
  <p>В демоверсии заявка сохранилась только в этом браузере: посмотреть её
     можно в админке, в разделе «Заявки».</p>
</div>
<p class="footer-note"><a href="#/">← Вернуться к каталогу</a></p>`;
}

function privacyView() {
  return `
<section class="intro">
  <h1>Политика конфиденциальности</h1>
  <p class="notice notice-warn">Черновик, текст требует проверки юристом.
     Не используйте его как готовый юридический документ.</p>
</section>
<div class="placeholder">
  <h2>Какие данные мы собираем</h2>
  <p>Сайт собирает данные в двух случаях.</p>
  <p><strong>Заявка на размещение.</strong> Название организации или ФИО
     специалиста, город, адрес, методы работы, возраст детей, стоимость
     занятий, сайт или Instagram, имя контактного лица, телефон, WhatsApp,
     электронная почта и комментарий. Вместе с заявкой сохраняются дата
     отправки и отметка о согласии на обработку данных, а в рабочей версии
     сайта - ещё и IP-адрес отправителя.</p>
  <p><strong>Отзыв о месте занятий.</strong> Имя, которое указал автор,
     оценка, текст отзыва и дата.</p>

  <h2>Зачем они нужны</h2>
  <p>Данные заявки нужны, чтобы проверить информацию, связаться с вами и
     опубликовать карточку в каталоге. Данные отзыва - чтобы показать его
     другим родителям после проверки модератором. IP-адрес в рабочей версии
     сохраняется только для защиты от спама.</p>

  <h2>Где они хранятся</h2>
  <p>В рабочей версии - в базе сайта. Публично видна только та часть, которую
     мы опубликовали в карточке, и опубликованные отзывы. Телефон контактного
     лица, почта, IP-адрес и комментарии к заявке в каталоге не показываются.</p>
  <p>Мы не передаём данные третьим лицам и не используем их для рассылок,
     не связанных с вашей заявкой.</p>

  <h2>Как запросить удаление</h2>
  <p>Напишите нам с того же контакта, который указали в заявке, и попросите
     удалить данные. Мы удалим заявку и карточку из каталога. Отзывы
     удаляются по обращению автора.</p>
  <p class="placeholder-note">Контакт для обращений на странице пока не указан -
     его нужно добавить до публикации сайта.</p>
</div>`;
}

function loginView(error) {
  return `
<section class="login-box">
  <h1>Вход в админку</h1>
  ${error ? '<p class="notice notice-warn">Неверный логин или пароль.</p>' : ""}
  <form id="login-form">
    <div class="field field-wide">
      <label for="l-login">Логин</label>
      <input type="text" id="l-login" name="login" autocomplete="username" required autofocus>
    </div>
    <div class="field field-wide">
      <label for="l-password">Пароль</label>
      <input type="password" id="l-password" name="password"
             autocomplete="current-password" required>
    </div>
    <button type="submit" class="btn btn-primary">Войти</button>
  </form>
  <p class="hint">Демо-доступ: логин <strong>admin</strong>, пароль <strong>admin</strong>.</p>
</section>`;
}

function adminNav() {
  const mod = moderationCounts();
  return `
<nav class="admin-nav">
  <a href="#/admin">Где заниматься</a>
  <a class="admin-nav-flag${mod.total ? "" : " admin-nav-flag-clear"}"
     href="#/admin">На модерации (${mod.total})</a>
  <a href="#/admin/applications">Заявки${mod.applications ? ` (${mod.applications})` : ""}</a>
  <a href="#/admin/reviews">Отзывы${mod.reviews ? ` (${mod.reviews})` : ""}</a>
  <a href="#/admin/methods">Справочник методов</a>
  <a href="#/" data-action="logout">Выйти</a>
</nav>`;
}

function moderationBlock() {
  const mod = moderationCounts();
  if (!mod.total) {
    return `
<section class="moderation" id="moderation">
  <h2>Требует проверки</h2>
  <p class="notice notice-ok">Всё проверено.</p>
</section>`;
  }
  const apps = state.applications
    .filter((a) => a.status === "new")
    .sort((a, b) => b.id - a.id)
    .slice(0, 5);
  const reviews = reviewsByStatus("pending").slice(0, 5);

  const appsHtml = apps.length ? `
<ul class="moderation-list">
  ${apps.map((a) => `<li>
    <div class="moderation-head"><strong>${esc(a.name)}</strong>
      <span class="muted">${esc(a.city)} · ${esc(APPLICANT_KINDS[a.applicant_kind] || a.applicant_kind)}</span></div>
    <p class="muted">${esc(a.created_at.slice(0, 10))} · ${esc(a.contact_person)}</p>
    <div class="row-actions">
      <a class="btn btn-small" href="#/admin/application/${a.id}">Открыть</a>
    </div></li>`).join("")}
</ul>
<p class="hint"><a href="#/admin/applications?status=new">Все новые заявки →</a></p>`
    : '<p class="hint">Новых заявок нет.</p>';

  const reviewsHtml = reviews.length ? `
<ul class="moderation-list">
  ${reviews.map((r) => {
    const provider = providerById(r.provider_id);
    return `<li>
    <div class="moderation-head"><strong>${esc(r.author_name)}</strong>
      <span class="review-rating">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</span></div>
    <p class="muted">${esc(r.created_at.slice(0, 10))} ·
      <a href="#/provider/${r.provider_id}">${esc(provider ? provider.name : "-")}</a></p>
    <p class="moderation-text">${esc(r.text.length > 160 ? r.text.slice(0, 160) + "…" : r.text)}</p>
    <div class="row-actions">
      <button type="button" class="btn btn-small btn-primary"
              data-action="review" data-id="${r.id}" data-status="published">Одобрить</button>
      <button type="button" class="btn btn-small btn-danger"
              data-action="review" data-id="${r.id}" data-status="rejected">Отклонить</button>
      <a class="btn btn-small" href="#/admin/reviews">Открыть</a>
    </div></li>`;
  }).join("")}
</ul>
<p class="hint"><a href="#/admin/reviews">Все отзывы на модерации →</a></p>`
    : '<p class="hint">Отзывов на модерации нет.</p>';

  return `
<section class="moderation" id="moderation">
  <h2>Требует проверки (${mod.total})</h2>
  <div class="moderation-cols">
    <div class="moderation-col">
      <h3>Новые заявки (${mod.applications})</h3>
      ${appsHtml}
    </div>
    <div class="moderation-col">
      <h3>Отзывы на модерации (${mod.reviews})</h3>
      ${reviewsHtml}
    </div>
  </div>
</section>`;
}

function adminApplicationsView(status) {
  const rows = [...state.applications]
    .filter((a) => !status || a.status === status)
    .sort((a, b) => b.id - a.id);

  const chips = [["", "Все"], ...Object.entries(APPLICATION_STATUSES)]
    .map(([code, label]) => `<a class="chip${status === code ? " chip-active" : ""}"
       href="#/admin/applications${code ? `?status=${code}` : ""}">${esc(label)}</a>`).join("");

  const table = rows.length ? `
<div class="table-wrap">
  <table class="admin-table">
    <thead><tr><th>Дата</th><th>Кто</th><th>Город</th><th>Контакт</th>
      <th>Статус</th><th>Действия</th></tr></thead>
    <tbody>
      ${rows.map((a) => `<tr>
        <td>${esc(a.created_at.slice(0, 10))}</td>
        <td><a href="#/admin/application/${a.id}">${esc(a.name)}</a>
          <div class="muted">${esc(APPLICANT_KINDS[a.applicant_kind] || a.applicant_kind)}</div></td>
        <td>${esc(a.city)}</td>
        <td>${esc(a.contact_person)}<div class="muted">${esc(a.phone)}</div></td>
        <td><span class="chip status-${esc(a.status)}">${esc(APPLICATION_STATUSES[a.status] || a.status)}</span>
          ${a.provider_id ? `<div class="muted"><a href="#/provider/${a.provider_id}">карточка создана</a></div>` : ""}</td>
        <td class="row-actions"><a class="btn btn-small" href="#/admin/application/${a.id}">Открыть</a></td>
      </tr>`).join("")}
    </tbody>
  </table>
</div>`
    : '<p class="empty">Заявок с таким статусом пока нет.</p>';

  return `
<h1>Заявки на размещение</h1>
${adminNav()}
<p class="admin-summary">Всего в списке: ${rows.length}</p>
<p class="status-filter">${chips}</p>
${table}`;
}

function adminApplicationView(id) {
  const a = applicationById(Number(id));
  if (!a) return '<p class="empty">Заявка не найдена.</p>';
  const methods = applicationMethods(a);
  const provider = a.provider_id ? providerById(a.provider_id) : null;
  const row = (label, value) => value
    ? `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>` : "";

  return `
<h1>Заявка № ${a.id}</h1>
${adminNav()}
<p class="breadcrumbs"><a href="#/admin/applications">← Ко всем заявкам</a></p>

<article class="provider">
  <div class="card-head">
    <span class="chip">${esc(APPLICANT_KINDS[a.applicant_kind] || a.applicant_kind)}</span>
    <span class="chip status-${esc(a.status)}">${esc(APPLICATION_STATUSES[a.status] || a.status)}</span>
    <span class="muted">Отправлена ${esc(a.created_at.slice(0, 10))}</span>
  </div>

  <h2>${esc(a.name)}</h2>

  <dl class="info-grid">
    ${row("Где заниматься", a.provider_type ? esc(PROVIDER_TYPES[a.provider_type] || a.provider_type) : "")}
    ${row("Специальность", esc(a.specialty))}
    ${row("Город", esc(a.city))}
    ${row("Адрес", esc(a.address))}
    ${row("Контактное лицо", esc(a.contact_person))}
    ${row("Телефон", esc(a.phone))}
    ${row("WhatsApp", esc(a.whatsapp))}
    ${row("Почта", esc(a.email))}
    ${row("Сайт или Instagram", esc(a.link))}
    ${row("Возраст детей", ageLine(a))}
    ${row("Стоимость", priceLine(a))}
    ${row("Согласие на обработку", "дано " + esc(a.consent_at.slice(0, 10)))}
    ${row("Обновлена", esc(a.updated_at.slice(0, 10)))}
  </dl>

  <h2>Методы</h2>
  ${methods.length ? `<div class="badges">${methods.map((m) =>
    `<span class="badge ${EVIDENCE[m.evidence_level].css}">${esc(m.name)}</span>`).join("")}</div>`
    : '<p class="empty">Методы не указаны.</p>'}

  ${a.comment ? `<h2>Комментарий заявителя</h2>
  <p class="provider-description">${esc(a.comment)}</p>` : ""}

  <h2>Обработка</h2>
  ${provider ? `<p class="notice notice-ok">По заявке создана карточка:
     <a href="#/provider/${provider.id}">${esc(provider.name)}</a></p>`
    : `<p><a class="btn btn-primary" href="#/admin/provider/new?from_application=${a.id}">
         Создать карточку из заявки</a></p>
       <p class="hint">Откроется форма новой записи с заполненными данными.
          Карточка появится в каталоге только после нажатия «Сохранить».</p>`}

  <form class="admin-form" id="application-admin-form" data-id="${a.id}">
    <div class="field">
      <label for="a-status">Статус</label>
      <select id="a-status" name="status">
        ${optionList(Object.entries(APPLICATION_STATUSES), a.status, "")}
      </select>
    </div>
    <div class="field field-wide">
      <label for="a-note">Заметка администратора</label>
      <textarea id="a-note" name="admin_note" rows="4" maxlength="2000"
                placeholder="Что проверили, что запросили, о чём договорились">${esc(a.admin_note)}</textarea>
    </div>
    <div class="filter-actions">
      <button type="submit" class="btn btn-primary">Сохранить</button>
    </div>
  </form>

  <div class="row-actions">
    <button type="button" class="btn btn-small btn-danger"
            data-action="delete-application" data-id="${a.id}">Удалить заявку</button>
  </div>
</article>`;
}

function adminProvidersView() {
  const rows = [...state.providers]
    .sort((a, b) => a.city.localeCompare(b.city, "ru") || a.name.localeCompare(b.name, "ru"))
    .map((p) => `
<tr>
  <td><div class="table-name">${logoHtml(p, "xs")}
    <div><a href="#/provider/${p.id}">${esc(p.name)}</a>
      ${p.is_test ? '<span class="chip chip-test">тест</span>' : ""}
      ${p.specialty ? `<div class="muted">${esc(p.specialty)}</div>` : ""}</div>
  </div></td>
  <td>${esc(PROVIDER_TYPES[p.provider_type] || p.provider_type)}</td>
  <td>${esc(p.city)}</td>
  <td>${esc(PRICING[p.pricing] || p.pricing)}</td>
  <td>${ratingHtml(p.id)}</td>
  <td class="row-actions">
    <a class="btn btn-small" href="#/admin/provider/${p.id}">Изменить</a>
    <button class="btn btn-small btn-danger" data-action="delete-provider"
            data-id="${p.id}">Удалить</button>
  </td>
</tr>`).join("");

  return `
<h1>Где заниматься</h1>
${adminNav()}
${moderationBlock()}
<h2>Все записи каталога</h2>
<p class="admin-summary">Всего записей: ${state.providers.length} ·
  Методов в справочнике: <a href="#/admin/methods">${state.methods.length}</a></p>
<p class="row-actions">
  <a class="btn btn-primary" href="#/admin/provider/new">Добавить место занятий</a>
  <button class="btn btn-small" data-action="reset-demo">Сбросить демо-данные</button>
</p>
<div class="table-wrap">
  <table class="admin-table">
    <thead><tr><th>Название</th><th>Где заниматься</th><th>Город</th><th>Оплата</th>
      <th>Оценка</th><th>Действия</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
</div>`;
}

function providerFormView(id, fromApplication) {
  const isNew = id === "new";
  const p = isNew ? null : providerById(Number(id));
  if (!isNew && !p) return '<p class="empty">Запись не найдена.</p>';

  // Значения полей: у существующей записи свои, у новой - заготовка из заявки.
  const application = isNew && fromApplication
    ? applicationById(Number(fromApplication)) : null;
  const fd = p || (application ? {
    provider_type: application.provider_type
      || (application.applicant_kind === "specialist" ? "specialist" : "center"),
    name: application.name,
    specialty: application.specialty,
    city: application.city,
    district: "",
    address: application.address,
    phone: application.phone,
    whatsapp: application.whatsapp,
    website: application.link,
    instagram: "",
    age_from: application.age_from,
    age_to: application.age_to,
    price_from: application.price_from,
    price_to: application.price_to,
    pricing: application.pricing,
    has_state_funding: 0,
    description: application.comment,
    is_test: 0,
  } : null);

  const selected = p
    ? new Set(providerMethods(p.id).map((m) => m.id))
    : new Set(application ? applicationMethods(application).map((m) => m.id) : []);
  const value = (key) => fd && fd[key] !== null && fd[key] !== undefined ? esc(fd[key]) : "";

  return `
<h1>${isNew ? "Новое место занятий" : "Редактирование места занятий"}</h1>
${adminNav()}
${application ? `<p class="notice notice-ok">Форма заполнена по заявке
   № ${application.id}. Карточка появится в каталоге только после нажатия
   «Сохранить», заявка при этом станет одобренной.</p>` : ""}
<form class="admin-form" id="provider-form" data-id="${isNew ? "new" : p.id}"
      data-application="${application ? application.id : ""}">
  <div class="field">
    <label for="p-type">Где заниматься</label>
    <select id="p-type" name="provider_type">
      ${optionList(Object.entries(PROVIDER_TYPES), fd ? fd.provider_type : "clinic", "")}
    </select>
  </div>
  <div class="field">
    <label for="p-specialty">Специальность (для врачей и специалистов)</label>
    <select id="p-specialty" name="specialty">
      ${optionList(SPECIALTIES.map((s) => [s, s]), fd ? fd.specialty : "", "Не указана")}
    </select>
  </div>
  <div class="field field-wide">
    <label for="p-name">Название или ФИО *</label>
    <input type="text" id="p-name" name="name" required value="${value("name")}">
  </div>
  <div class="field">
    <label for="p-city">Город *</label>
    <input type="text" id="p-city" name="city" required value="${value("city")}">
  </div>
  <div class="field">
    <label for="p-district">Район</label>
    <input type="text" id="p-district" name="district" value="${value("district")}">
  </div>
  <div class="field field-wide">
    <label for="p-address">Адрес</label>
    <input type="text" id="p-address" name="address" value="${value("address")}">
  </div>
  <div class="field">
    <label for="p-phone">Телефон</label>
    <input type="text" id="p-phone" name="phone" placeholder="+7 7xx xxx xx xx" value="${value("phone")}">
  </div>
  <div class="field">
    <label for="p-whatsapp">WhatsApp</label>
    <input type="text" id="p-whatsapp" name="whatsapp" placeholder="+7 7xx xxx xx xx" value="${value("whatsapp")}">
  </div>
  <div class="field">
    <label for="p-website">Сайт</label>
    <input type="text" id="p-website" name="website" placeholder="example.kz" value="${value("website")}">
  </div>
  <div class="field">
    <label for="p-instagram">Instagram</label>
    <input type="text" id="p-instagram" name="instagram" placeholder="@account" value="${value("instagram")}">
  </div>
  <div class="field">
    <label for="p-age-from">Возраст детей от</label>
    <input type="number" id="p-age-from" name="age_from" min="0" max="18" value="${value("age_from")}">
  </div>
  <div class="field">
    <label for="p-age-to">Возраст детей до</label>
    <input type="number" id="p-age-to" name="age_to" min="0" max="18" value="${value("age_to")}">
  </div>
  <div class="field">
    <label for="p-price-from">Цена за занятие от, ₸</label>
    <input type="number" id="p-price-from" name="price_from" min="0" step="500" value="${value("price_from")}">
  </div>
  <div class="field">
    <label for="p-price-to">Цена за занятие до, ₸</label>
    <input type="number" id="p-price-to" name="price_to" min="0" step="500" value="${value("price_to")}">
  </div>
  <div class="field">
    <label for="p-pricing">Оплата</label>
    <select id="p-pricing" name="pricing">
      ${optionList(Object.entries(PRICING), fd ? fd.pricing : "paid", "")}
    </select>
  </div>
  <div class="field field-check">
    <label class="switch-row">
      <span class="switch">
        <input type="checkbox" name="has_state_funding"${fd && fd.has_state_funding ? " checked" : ""}>
        <span class="switch-track"></span>
      </span>
      <span class="switch-label">Есть гос. финансирование</span>
    </label>
    <label class="switch-row">
      <span class="switch">
        <input type="checkbox" name="is_test"${!p || p.is_test ? " checked" : ""}>
        <span class="switch-track"></span>
      </span>
      <span class="switch-label">Тестовая запись</span>
    </label>
  </div>
  <div class="field field-wide logo-field">
    <label for="p-logo">Фото или логотип</label>
    <div class="logo-field-row">
      ${p ? logoHtml(p, "md") : ""}
      <div class="logo-field-controls">
        <input type="file" id="p-logo" name="logo" accept="image/png,image/jpeg,image/webp,image/gif">
        <p class="hint">PNG, JPEG, WebP или GIF, до 1 МБ. Если не выбирать файл,
           текущее изображение останется. Без изображения показываются инициалы.</p>
        ${p && p.logo_path ? `<label class="switch-row">
          <span class="switch"><input type="checkbox" name="remove_logo">
            <span class="switch-track"></span></span>
          <span class="switch-label">Удалить текущее изображение</span></label>` : ""}
        <p class="notice notice-warn" id="logo-error" hidden></p>
      </div>
    </div>
  </div>

  <div class="field field-wide">
    <label for="p-description">Описание</label>
    <textarea id="p-description" name="description" rows="5">${value("description")}</textarea>
  </div>
  <fieldset class="field field-wide methods-picker">
    <legend>Методы</legend>
    ${sortedMethods().map((m) => `<label class="checkbox">
      <input type="checkbox" name="methods" value="${m.id}"${selected.has(m.id) ? " checked" : ""}>
      ${esc(m.name)}
      <span class="badge ${EVIDENCE[m.evidence_level].css}">${esc(EVIDENCE[m.evidence_level].label)}</span>
    </label>`).join("")}
  </fieldset>
  <div class="filter-actions">
    <button type="submit" class="btn btn-primary">Сохранить</button>
    <a class="btn btn-ghost" href="#/admin">Отмена</a>
  </div>
</form>`;
}

function reviewBlock(r, buttons) {
  const provider = providerById(r.provider_id);
  return `
<li class="review">
  <div class="review-head"><strong>${esc(r.author_name)}</strong>
    <span class="review-rating">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</span>
    <span class="review-date">${esc(r.created_at.slice(0, 10))}</span></div>
  <p class="muted">Место занятий: <a href="#/provider/${r.provider_id}">${esc(provider ? provider.name : "-")}</a></p>
  <p>${esc(r.text)}</p>
  <div class="row-actions">${buttons}</div>
</li>`;
}

function adminReviewsView() {
  const pending = reviewsByStatus("pending");
  const published = reviewsByStatus("published");
  const rejected = reviewsByStatus("rejected");

  const approve = (id) => `<button class="btn btn-small btn-primary"
    data-action="review" data-status="published" data-id="${id}">Одобрить</button>`;
  const reject = (id, label) => `<button class="btn btn-small btn-danger"
    data-action="review" data-status="rejected" data-id="${id}">${label}</button>`;

  return `
<h1>Отзывы</h1>
${adminNav()}
<h2>На модерации (${pending.length})</h2>
${pending.length
    ? `<ul class="admin-reviews">${pending.map((r) => reviewBlock(r, approve(r.id) + reject(r.id, "Отклонить"))).join("")}</ul>`
    : '<p class="empty">Новых отзывов нет.</p>'}
<h2>Опубликованные (${published.length})</h2>
${published.length
    ? `<ul class="admin-reviews">${published.map((r) => reviewBlock(r, reject(r.id, "Снять с публикации"))).join("")}</ul>`
    : '<p class="empty">Опубликованных отзывов нет.</p>'}
<h2>Отклонённые (${rejected.length})</h2>
${rejected.length
    ? `<ul class="admin-reviews">${rejected.map((r) => reviewBlock(r, approve(r.id).replace("Одобрить", "Опубликовать"))).join("")}</ul>`
    : '<p class="empty">Отклонённых отзывов нет.</p>'}`;
}

function adminMethodsView(editId) {
  const method = editId ? methodById(Number(editId)) : null;
  const rows = sortedMethods().map((m) => `
<tr>
  <td>${m.sort_order}</td>
  <td><code>${esc(m.code)}</code></td>
  <td>${esc(m.name)}<div class="muted">${esc(m.description.slice(0, 120))}${m.description.length > 120 ? "…" : ""}</div></td>
  <td><span class="badge ${EVIDENCE[m.evidence_level].css}">${esc(EVIDENCE[m.evidence_level].label)}</span></td>
  <td class="row-actions">
    <a class="btn btn-small" href="#/admin/methods/${m.id}">Изменить</a>
    <button class="btn btn-small btn-danger" data-action="delete-method" data-id="${m.id}">Удалить</button>
  </td>
</tr>`).join("");

  return `
<h1>Справочник методов</h1>
${adminNav()}
<div class="table-wrap">
  <table class="admin-table">
    <thead><tr><th>Порядок</th><th>Код</th><th>Название</th>
      <th>Уровень доказательности</th><th>Действия</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
</div>
<h2>${method ? "Изменить метод" : "Добавить метод"}</h2>
<form class="admin-form" id="method-form" data-id="${method ? method.id : "new"}">
  <div class="field">
    <label for="m-code">Код *</label>
    <input type="text" id="m-code" name="code" required
           value="${method ? esc(method.code) : ""}" placeholder="например aba">
  </div>
  <div class="field">
    <label for="m-name">Название *</label>
    <input type="text" id="m-name" name="name" required value="${method ? esc(method.name) : ""}">
  </div>
  <div class="field">
    <label for="m-level">Уровень доказательности</label>
    <select id="m-level" name="evidence_level">
      ${optionList(Object.entries(EVIDENCE).map(([code, info]) => [code, info.label]),
    method ? method.evidence_level : "limited", "")}
    </select>
  </div>
  <div class="field">
    <label for="m-order">Порядок вывода</label>
    <input type="number" id="m-order" name="sort_order" min="1"
           value="${method ? method.sort_order : 100}">
  </div>
  <div class="field field-wide">
    <label for="m-description">Описание простым языком</label>
    <textarea id="m-description" name="description" rows="4">${method ? esc(method.description) : ""}</textarea>
  </div>
  <div class="filter-actions">
    <button type="submit" class="btn btn-primary">Сохранить</button>
    ${method ? '<a class="btn btn-ghost" href="#/admin/methods">Отмена</a>' : ""}
  </div>
</form>`;
}

// --- маршрутизация ----------------------------------------------------------

function headerAuth() {
  // Кнопки «Вход» в шапке нет: админка открывается по адресу #/login.
  const admin = isAdmin
    ? `<a class="auth-link auth-link-quiet" href="#/admin">Админка</a>
       <a class="auth-link auth-link-quiet" href="#/" data-action="logout">Выйти</a>`
    : "";
  return `<a class="btn-outline" href="#/dlya-specialistov">Разместиться в каталоге</a>${admin}`;
}

function render() {
  const raw = (location.hash || "#/").slice(1);
  const [path, queryString] = raw.split("?");
  const query = new URLSearchParams(queryString || "");
  const parts = path.split("/").filter(Boolean);
  const guard = '<p class="empty">Нужен вход в админку. <a href="#/login">Войти</a></p>';

  let html;
  if (!parts.length) html = catalogView();
  else if (parts[0] === "provider") html = providerView(Number(parts[1]), query.get("review"));
  else if (parts[0] === "methods") html = methodsView();
  else if (parts[0] === "free-help") html = freeHelpView();
  else if (parts[0] === "privacy") html = privacyView();
  else if (parts[0] === "dlya-specialistov") {
    html = parts[1] === "sent" ? applicationSentView() : applicationFormView(null);
  }
  else if (parts[0] === "login") html = isAdmin ? adminProvidersView() : loginView(query.get("error"));
  else if (parts[0] === "admin") {
    if (!isAdmin) html = guard;
    else if (parts[1] === "reviews") html = adminReviewsView();
    else if (parts[1] === "methods") html = adminMethodsView(parts[2]);
    else if (parts[1] === "applications") html = adminApplicationsView(query.get("status") || "");
    else if (parts[1] === "application") html = adminApplicationView(parts[2]);
    else if (parts[1] === "provider") {
      html = providerFormView(parts[2], query.get("from_application"));
    }
    else html = adminProvidersView();
  } else html = '<p class="empty">Страница не найдена. <a href="#/">В каталог</a></p>';

  document.getElementById("header-auth").innerHTML = headerAuth();
  document.getElementById("view").innerHTML = html;
  wire();
  if (path.startsWith("/provider/") && query.get("review")) {
    document.getElementById("reviews")?.scrollIntoView({ behavior: "smooth" });
  } else {
    window.scrollTo({ top: 0 });
  }
}

function readFilters(form) {
  const data = new FormData(form);
  filters = {
    q: data.get("q") || "",
    city: data.get("city") || "",
    provider_type: data.get("provider_type") || "",
    specialty: data.get("specialty") || "",
    method: data.get("method") || "",
    age: data.get("age") || "",
    proven_only: form.querySelector('[name="proven_only"]').checked,
  };
}

function armOrRun(button, run) {
  if (button.dataset.armed === "1") { run(); return; }
  button.dataset.armed = "1";
  button.dataset.label = button.textContent;
  button.textContent = "Точно удалить?";
  setTimeout(() => {
    if (button.dataset.armed === "1") {
      button.dataset.armed = "0";
      button.textContent = button.dataset.label;
    }
  }, 4000);
}

const MAX_LOGO_BYTES = 1024 * 1024;

// Возвращает путь к изображению, либо null, если файл не подошёл.
async function readLogo(form, current) {
  const remove = form.querySelector('[name="remove_logo"]');
  if (remove && remove.checked) return "";

  const file = form.querySelector('[name="logo"]').files[0];
  if (!file) return current;

  const error = form.querySelector("#logo-error");
  const fail = (message) => {
    if (error) { error.textContent = message; error.hidden = false; }
    return null;
  };
  if (file.size > MAX_LOGO_BYTES) {
    return fail("Файл больше 1 МБ - выберите изображение поменьше.");
  }
  // Тип из браузера берётся по расширению, поэтому проверяем сигнатуру файла.
  const bytes = new Uint8Array(await file.slice(0, 16).arrayBuffer());
  const startsWith = (...signature) => signature.every((byte, i) => bytes[i] === byte);
  const isImage = startsWith(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
    || startsWith(0xff, 0xd8, 0xff)
    || startsWith(0x47, 0x49, 0x46, 0x38)
    || (startsWith(0x52, 0x49, 0x46, 0x46)
      && [0x57, 0x45, 0x42, 0x50].every((byte, i) => bytes[8 + i] === byte));
  if (!isImage) {
    return fail("Это не изображение. Подойдут PNG, JPEG, WebP и GIF.");
  }
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => resolve(fail("Не удалось прочитать файл."));
    reader.readAsDataURL(file);
  });
}

function wire() {
  const filtersForm = document.getElementById("filters");
  if (filtersForm) {
    const apply = () => {
      readFilters(filtersForm);
      document.getElementById("results").innerHTML = resultsView();
    };
    filtersForm.addEventListener("submit", (e) => { e.preventDefault(); apply(); });
    filtersForm.addEventListener("change", apply);
    filtersForm.querySelector("#f-q").addEventListener("input", apply);
  }

  document.querySelectorAll('[data-action="reset-filters"]').forEach((el) =>
    el.addEventListener("click", () => {
      filters = { q: "", city: "", provider_type: "", specialty: "", method: "",
        age: "", proven_only: false };
      render();
    }));

  document.querySelectorAll('[data-action="filter-method"]').forEach((el) =>
    el.addEventListener("click", () => {
      filters.method = el.dataset.method;
      location.hash = "#/";
    }));

  document.querySelectorAll('[data-action="logout"]').forEach((el) =>
    el.addEventListener("click", () => { writeAdmin(false); location.hash = "#/"; render(); }));

  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const data = new FormData(loginForm);
      const ok = (data.get("login") || "").trim() === ADMIN_LOGIN
        && (data.get("password") || "") === ADMIN_PASSWORD;
      if (ok) { writeAdmin(true); location.hash = "#/admin"; render(); }
      else location.hash = "#/login?error=1";
    });
  }

  const applicationForm = document.getElementById("application-form");
  if (applicationForm) {
    applicationForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const data = new FormData(applicationForm);
      const get = (key) => (data.get(key) || "").toString().trim();
      const num = (key) => (get(key) === "" ? null : Number(get(key)));

      // Всё введённое держим в черновике: страница перерисовывается целиком.
      applicationDraft = {
        applicant_kind: get("applicant_kind"),
        org_name: get("org_name"), person_name: get("person_name"),
        provider_type: get("provider_type"), specialty: get("specialty"),
        city: get("city"), address: get("address"),
        methods: data.getAll("methods"),
        age_from: get("age_from"), age_to: get("age_to"),
        price_from: get("price_from"), price_to: get("price_to"),
        pricing_free: !!data.get("pricing_free"),
        link: get("link"), contact_person: get("contact_person"),
        phone: get("phone"), whatsapp: get("whatsapp"), email: get("email"),
        comment: get("comment"), consent: !!data.get("consent"),
      };
      const f = applicationDraft;

      // Ловушка для ботов: заполнено - молча показываем благодарность.
      if (get("company_site")) { location.hash = "#/dlya-specialistov/sent"; return; }

      const errors = [];
      if (!APPLICANT_KINDS[f.applicant_kind]) {
        errors.push("Выберите, кто вы: организация или частный специалист.");
      }
      const name = f.applicant_kind === "organization" ? f.org_name : f.person_name;
      if (f.applicant_kind && !name) {
        errors.push(f.applicant_kind === "organization"
          ? "Укажите название организации."
          : "Укажите фамилию, имя и отчество.");
      }
      if (!f.city) errors.push("Укажите город.");
      if (!f.contact_person) errors.push("Укажите контактное лицо.");

      const phone = normalizePhone(f.phone);
      if (!phone) {
        errors.push("Телефон должен быть казахстанским номером, например +7 701 234 56 78.");
      }
      const whatsapp = f.whatsapp ? normalizePhone(f.whatsapp) : "";
      if (f.whatsapp && !whatsapp) {
        errors.push("WhatsApp должен быть казахстанским номером или остаться пустым.");
      }
      if (f.email && !looksLikeEmail(f.email)) errors.push("Проверьте адрес электронной почты.");
      if (!f.consent) {
        errors.push("Без согласия на обработку персональных данных заявку принять нельзя.");
      }
      const ageFrom = num("age_from"), ageTo = num("age_to");
      if (ageFrom !== null && ageTo !== null && ageFrom > ageTo) {
        errors.push("Возраст «от» больше, чем «до».");
      }
      const pricing = f.pricing_free ? "free" : "paid";
      const priceFrom = pricing === "free" ? null : num("price_from");
      const priceTo = pricing === "free" ? null : num("price_to");
      if (priceFrom !== null && priceTo !== null && priceFrom > priceTo) {
        errors.push("Стоимость «от» больше, чем «до».");
      }

      // На сервере лимит считается по IP, здесь - по этому браузеру.
      const hourAgo = Date.now() - 60 * 60 * 1000;
      state.application_times = (state.application_times || []).filter((t) => t > hourAgo);
      if (!errors.length && state.application_times.length >= MAX_APPLICATIONS_PER_HOUR) {
        errors.push("С одного устройства принимаем не больше трёх заявок в час."
          + " Попробуйте позже или напишите нам другим способом.");
      }

      if (errors.length) {
        document.getElementById("view").innerHTML = applicationFormView(errors);
        wire();
        window.scrollTo({ top: 0 });
        return;
      }

      const known = new Set(state.methods.map((m) => m.code));
      const now = new Date().toISOString().slice(0, 19);
      state.applications.push({
        id: nextId(state.applications),
        applicant_kind: f.applicant_kind,
        name: name.slice(0, 160),
        provider_type: f.applicant_kind === "organization" ? f.provider_type : "",
        specialty: f.applicant_kind === "specialist" ? f.specialty : "",
        city: f.city.slice(0, 80),
        address: f.address.slice(0, 200),
        method_codes: f.methods.filter((code) => known.has(code)),
        age_from: ageFrom, age_to: ageTo,
        price_from: priceFrom, price_to: priceTo, pricing,
        link: f.link.slice(0, 200),
        contact_person: f.contact_person.slice(0, 120),
        phone, whatsapp: whatsapp || "", email: f.email.slice(0, 120),
        comment: f.comment.slice(0, 2000),
        status: "new", admin_note: "", provider_id: null,
        consent_at: now, created_at: now, updated_at: now,
      });
      state.application_times.push(Date.now());
      saveState();
      applicationDraft = {};
      location.hash = "#/dlya-specialistov/sent";
      render();
    });
  }

  const applicationAdminForm = document.getElementById("application-admin-form");
  if (applicationAdminForm) {
    applicationAdminForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const data = new FormData(applicationAdminForm);
      const application = applicationById(Number(applicationAdminForm.dataset.id));
      if (!application) return;
      application.status = data.get("status");
      application.admin_note = (data.get("admin_note") || "").toString().trim().slice(0, 2000);
      application.updated_at = new Date().toISOString().slice(0, 19);
      saveState();
      render();
    });
  }

  document.querySelectorAll('[data-action="delete-application"]').forEach((el) =>
    el.addEventListener("click", () => armOrRun(el, () => {
      const id = Number(el.dataset.id);
      state.applications = state.applications.filter((a) => a.id !== id);
      saveState();
      location.hash = "#/admin/applications";
      render();
    })));

  const reviewForm = document.getElementById("review-form");
  if (reviewForm) {
    reviewForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const providerId = Number(reviewForm.dataset.provider);
      const data = new FormData(reviewForm);
      const name = (data.get("author_name") || "").trim();
      const text = (data.get("text") || "").trim();
      const rating = Number(data.get("rating"));
      if (!name || !text || !(rating >= 1 && rating <= 5)) {
        location.hash = `#/provider/${providerId}?review=invalid`;
        return;
      }
      const dayAgo = Date.now() - 24 * 60 * 60 * 1000;
      state.submissions = state.submissions || {};
      if ((state.submissions[providerId] || 0) > dayAgo) {
        location.hash = `#/provider/${providerId}?review=limit`;
        return;
      }
      state.reviews.push({
        id: nextId(state.reviews), provider_id: providerId, author_name: name.slice(0, 80),
        rating, text: text.slice(0, 2000), status: "pending",
        created_at: new Date().toISOString().slice(0, 19),
      });
      state.submissions[providerId] = Date.now();
      saveState();
      location.hash = `#/provider/${providerId}?review=ok`;
      render();
    });
  }

  document.querySelectorAll('[data-action="review"]').forEach((el) =>
    el.addEventListener("click", () => {
      const review = state.reviews.find((r) => r.id === Number(el.dataset.id));
      if (review) { review.status = el.dataset.status; saveState(); render(); }
    }));

  document.querySelectorAll('[data-action="delete-provider"]').forEach((el) =>
    el.addEventListener("click", () => armOrRun(el, () => {
      const id = Number(el.dataset.id);
      state.providers = state.providers.filter((p) => p.id !== id);
      state.provider_methods = state.provider_methods.filter((l) => l.provider_id !== id);
      state.reviews = state.reviews.filter((r) => r.provider_id !== id);
      saveState();
      render();
    })));

  document.querySelectorAll('[data-action="delete-method"]').forEach((el) =>
    el.addEventListener("click", () => armOrRun(el, () => {
      const id = Number(el.dataset.id);
      state.methods = state.methods.filter((m) => m.id !== id);
      state.provider_methods = state.provider_methods.filter((l) => l.method_id !== id);
      saveState();
      render();
    })));

  document.querySelectorAll('[data-action="reset-demo"]').forEach((el) =>
    el.addEventListener("click", () => armOrRun(el, () => { resetDemo(); render(); })));

  const providerForm = document.getElementById("provider-form");
  if (providerForm) {
    providerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = new FormData(providerForm);
      const num = (key) => {
        const raw = (data.get(key) || "").toString().trim();
        return raw === "" ? null : Number(raw);
      };
      const fields = {
        provider_type: data.get("provider_type"),
        name: (data.get("name") || "").trim(),
        specialty: (data.get("specialty") || "").trim(),
        city: (data.get("city") || "").trim(),
        district: (data.get("district") || "").trim(),
        address: (data.get("address") || "").trim(),
        phone: (data.get("phone") || "").trim(),
        whatsapp: (data.get("whatsapp") || "").trim(),
        website: (data.get("website") || "").trim(),
        instagram: (data.get("instagram") || "").trim(),
        age_from: num("age_from"), age_to: num("age_to"),
        price_from: num("price_from"), price_to: num("price_to"),
        pricing: data.get("pricing"),
        has_state_funding: providerForm.querySelector('[name="has_state_funding"]').checked ? 1 : 0,
        description: (data.get("description") || "").trim(),
        is_test: providerForm.querySelector('[name="is_test"]').checked ? 1 : 0,
      };
      if (!fields.name || !fields.city) return;

      const methodIds = data.getAll("methods").map(Number);
      const isNew = providerForm.dataset.id === "new";
      const id = isNew ? nextId(state.providers) : Number(providerForm.dataset.id);

      const logo = await readLogo(providerForm, isNew ? "" : (providerById(id).logo_path || ""));
      if (logo === null) return;
      fields.logo_path = logo;

      if (isNew) {
        state.providers.push({ id, ...fields, created_at: new Date().toISOString().slice(0, 19) });
        const application = applicationById(Number(providerForm.dataset.application));
        if (application) {
          application.status = "approved";
          application.provider_id = id;
          application.updated_at = new Date().toISOString().slice(0, 19);
        }
      } else {
        const existing = providerById(id);
        Object.assign(existing, fields);
      }
      state.provider_methods = state.provider_methods.filter((l) => l.provider_id !== id);
      methodIds.forEach((methodId) =>
        state.provider_methods.push({ provider_id: id, method_id: methodId }));
      saveState();
      const application = applicationById(Number(providerForm.dataset.application));
      location.hash = application && isNew
        ? `#/admin/application/${application.id}` : "#/admin";
      render();
    });
  }

  const methodForm = document.getElementById("method-form");
  if (methodForm) {
    methodForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const data = new FormData(methodForm);
      const fields = {
        code: (data.get("code") || "").trim(),
        name: (data.get("name") || "").trim(),
        description: (data.get("description") || "").trim(),
        evidence_level: data.get("evidence_level"),
        sort_order: Number(data.get("sort_order")) || 100,
      };
      if (!fields.code || !fields.name) return;
      if (methodForm.dataset.id === "new") {
        state.methods.push({ id: nextId(state.methods), ...fields });
      } else {
        Object.assign(methodById(Number(methodForm.dataset.id)), fields);
      }
      saveState();
      location.hash = "#/admin/methods";
      render();
    });
  }
}

window.addEventListener("hashchange", render);
render();
