/* EVE Diagnostics web client — plain JS, talks to the REST API with JWT. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const view = $("#view");
  const modal = $("#modal");
  const modalBody = $("#modal-body");
  const DEMO = Boolean(window.EVE && window.EVE.demoTools);

  // ---------------------------------------------------------------- helpers
  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
  const money = (v) => inr.format(Number(v));
  const fmtDate = (iso, opts) => new Date(iso).toLocaleString("en-IN", opts);
  const fmtFull = (iso) =>
    fmtDate(iso, { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

  const store = {
    get(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } },
    del(key) { try { localStorage.removeItem(key); } catch { /* storage unavailable */ } },
  };

  const icon = {
    pin: '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
    flask: '<svg viewBox="0 0 24 24"><path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7.5 15h9"/></svg>',
    calendar: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
    card: '<svg viewBox="0 0 24 24"><rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M2.5 10h19M6 15h4"/></svg>',
  };

  // ------------------------------------------------------------ auth state
  const auth = {
    get access() { return store.get("eve.access"); },
    get refresh() { return store.get("eve.refresh"); },
    get user() { return store.get("eve.user"); },
    get loggedIn() { return Boolean(this.access); },
    save({ access, refresh, user }) {
      if (access) store.set("eve.access", access);
      if (refresh) store.set("eve.refresh", refresh);
      if (user) store.set("eve.user", user);
    },
    clear() { ["eve.access", "eve.refresh", "eve.user"].forEach(store.del); },
  };

  // ------------------------------------------------------------ API client
  class ApiError extends Error {
    constructor(status, body) {
      const err = body && body.error;
      super((err && err.message) || `Request failed (${status})`);
      this.status = status;
      this.code = err && err.code;
      this.details = (err && err.details) || null;
    }
    /** Field errors flattened to {field: "message"}. */
    get fields() {
      const out = {};
      if (this.details && typeof this.details === "object") {
        for (const [key, val] of Object.entries(this.details)) {
          out[key] = Array.isArray(val) ? val.join(" ") : typeof val === "object" ? Object.values(val).flat().join(" ") : String(val);
        }
      }
      return out;
    }
    get friendly() {
      const fields = Object.values(this.fields);
      return this.message === "Invalid request." && fields.length ? fields[0] : this.message;
    }
  }

  async function refreshAccess() {
    if (!auth.refresh) return false;
    const res = await fetch("/auth/token/refresh/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: auth.refresh }),
    });
    if (!res.ok) return false;
    auth.save(await res.json());
    return true;
  }

  async function api(path, { method = "GET", body, headers = {}, retry = true } = {}) {
    const opts = { method, headers: { Accept: "application/json", ...headers } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    if (auth.access) opts.headers.Authorization = `Bearer ${auth.access}`;

    const res = await fetch(path, opts);
    if (res.status === 401 && auth.access && retry) {
      if (await refreshAccess()) return api(path, { method, body, headers, retry: false });
      auth.clear();
      renderSession();
      throw new ApiError(401, { error: { message: "Your session expired. Please log in again." } });
    }
    const data = res.status === 204 ? null : await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, data);
    return data;
  }

  // ------------------------------------------------------------ UI chrome
  function toast(message, { type = "info", detail = "" } = {}) {
    const el = document.createElement("div");
    el.className = `toast toast--${type}`;
    const ic = type === "success" ? icon.check : type === "error" ? icon.x : icon.info;
    el.innerHTML = `${ic}<div>${esc(message)}${detail ? `<small>${esc(detail)}</small>` : ""}</div>`;
    const box = $("#toasts");
    box.appendChild(el);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => el.remove(), 3500);
  }

  function openModal(html) {
    modalBody.innerHTML = html;
    if (!modal.open) modal.showModal();
  }
  function closeModal() { modal.close(); }
  modal.addEventListener("click", (e) => {
    if (e.target === modal || e.target.closest("[data-close]")) closeModal();
  });

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.label = button.innerHTML;
      button.disabled = true;
      button.innerHTML = `<span class="spinner"></span>${label ? esc(label) : ""}`;
    } else {
      button.disabled = false;
      if (button.dataset.label) button.innerHTML = button.dataset.label;
    }
  }

  const badge = (status) => `<span class="badge badge--${esc(status)}">${esc(status.charAt(0) + status.slice(1).toLowerCase())}</span>`;

  function emptyState({ ic = icon.flask, title, text, action = "" }) {
    return `<div class="card empty"><div class="empty__icon">${ic}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
  }

  function renderSession() {
    const box = $("#session");
    const user = auth.user;
    document.querySelectorAll("[data-auth]").forEach((a) => (a.hidden = !auth.loggedIn));
    if (auth.loggedIn && user) {
      const initials = (user.full_name || user.email).split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
      box.innerHTML = `
        <span class="avatar" title="${esc(user.email)}">${esc(initials)}</span>
        <span class="session__name">${esc(user.full_name)}</span>
        <button class="btn btn--ghost btn--sm" id="logout">Log out</button>`;
      $("#logout").onclick = () => {
        auth.clear();
        renderSession();
        toast("You've been logged out.");
        location.hash = "#/centres";
      };
    } else {
      box.innerHTML = `
        <button class="btn btn--ghost btn--sm" data-auth-open="login">Log in</button>
        <button class="btn btn--primary btn--sm" data-auth-open="signup">Sign up</button>`;
      box.querySelectorAll("[data-auth-open]").forEach((b) => (b.onclick = () => openAuth(b.dataset.authOpen)));
    }
  }

  // ------------------------------------------------------------ auth modal
  function openAuth(mode = "login", onDone) {
    const isSignup = mode === "signup";
    openModal(`
      <h2>${isSignup ? "Create your account" : "Welcome back"}</h2>
      <p class="lead">${isSignup ? "Book diagnostic tests and track results in one place." : "Log in to book and manage your tests."}</p>
      <div class="seg">
        <button type="button" data-mode="login" class="${isSignup ? "" : "active"}">Log in</button>
        <button type="button" data-mode="signup" class="${isSignup ? "active" : ""}">Sign up</button>
      </div>
      <form id="auth-form" novalidate>
        <div id="auth-error"></div>
        ${isSignup ? field("full_name", "Full name", "text", "Asha Rao", "name") : ""}
        ${field("email", "Email", "email", "you@example.com", "email")}
        ${isSignup ? field("phone", "Phone (optional)", "tel", "+919876543210", "tel") : ""}
        ${field("password", "Password", "password", isSignup ? "At least 8 characters" : "••••••••", isSignup ? "new-password" : "current-password")}
        <button class="btn btn--primary btn--block" type="submit">${isSignup ? "Create account" : "Log in"}</button>
      </form>`);

    modalBody.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => openAuth(b.dataset.mode, onDone)));
    const form = $("#auth-form");
    form.querySelector("input").focus();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = form.querySelector("[type=submit]");
      const body = Object.fromEntries(new FormData(form));
      if (!body.phone) delete body.phone;
      clearErrors(form);
      setBusy(btn, true);
      try {
        const data = await api(isSignup ? "/auth/signup/" : "/auth/login/", { method: "POST", body });
        auth.save(data);
        renderSession();
        closeModal();
        toast(isSignup ? `Welcome, ${data.user.full_name}!` : `Logged in as ${data.user.full_name}.`, { type: "success" });
        if (onDone) onDone();
        else route();
      } catch (err) {
        showErrors(form, err, "#auth-error");
      } finally {
        setBusy(btn, false);
      }
    };
  }

  function field(name, label, type, placeholder, autocomplete) {
    return `<div class="field" data-field="${name}">
      <label for="f-${name}">${esc(label)}</label>
      <input class="input" id="f-${name}" name="${name}" type="${type}" placeholder="${esc(placeholder)}" autocomplete="${autocomplete}">
    </div>`;
  }

  function clearErrors(form) {
    form.querySelectorAll(".field__error, .form-error").forEach((el) => el.remove());
  }

  function showErrors(form, err, generalSel) {
    const fields = err instanceof ApiError ? err.fields : {};
    let placed = false;
    for (const [name, msg] of Object.entries(fields)) {
      const wrap = form.querySelector(`[data-field="${name}"]`);
      if (wrap) {
        wrap.insertAdjacentHTML("beforeend", `<span class="field__error">${esc(msg)}</span>`);
        placed = true;
      }
    }
    if (!placed) {
      const msg = err instanceof ApiError ? err.friendly : "Something went wrong. Please try again.";
      $(generalSel, form).innerHTML = `<div class="form-error">${esc(msg)}</div>`;
    }
  }

  // ------------------------------------------------------------ centres page
  let catalogCache = null; // {cities, tests}

  async function loadCatalog() {
    if (catalogCache) return catalogCache;
    const [centres, tests] = await Promise.all([api("/centres/?page_size=100"), api("/tests/?page_size=100")]);
    const cities = [...new Set(centres.results.map((c) => c.city))].sort();
    catalogCache = { cities, tests: tests.results };
    return catalogCache;
  }

  async function renderCentres() {
    view.innerHTML = `
      <section class="hero">
        <h1>Book a diagnostic test</h1>
        <p>Compare prices across our centres, pick a time that suits you, and pay securely in a few taps.</p>
        <div class="filters">
          <div class="search">${icon.search}<input class="input" id="q" placeholder="Search centres by name" autocomplete="off"></div>
          <select class="input" id="city"><option value="">All cities</option></select>
          <select class="input" id="test"><option value="">All tests</option></select>
        </div>
      </section>
      <div class="section-head"><h2>Diagnostic centres</h2><span class="muted small" id="result-count"></span></div>
      <div class="grid" id="centres">${'<div class="skeleton"></div>'.repeat(3)}</div>`;

    let catalog;
    try {
      catalog = await loadCatalog();
    } catch (err) {
      $("#centres").outerHTML = emptyState({ title: "Couldn't load centres", text: err.message });
      return;
    }
    $("#city").insertAdjacentHTML("beforeend", catalog.cities.map((c) => `<option>${esc(c)}</option>`).join(""));
    $("#test").insertAdjacentHTML("beforeend", catalog.tests.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join(""));

    let timer;
    const load = async () => {
      const params = new URLSearchParams({ page_size: 100 });
      const q = $("#q").value.trim();
      const city = $("#city").value;
      const test = $("#test").value;
      if (q) params.set("search", q);
      if (city) params.set("city", city);
      if (test) params.set("test", test);
      try {
        const data = await api(`/centres/?${params}`);
        drawCentres(data.results, test ? Number(test) : null);
        $("#result-count").textContent = `${data.count} centre${data.count === 1 ? "" : "s"}`;
      } catch (err) {
        $("#centres").innerHTML = emptyState({ title: "Couldn't load centres", text: err.message });
      }
    };
    $("#q").oninput = () => { clearTimeout(timer); timer = setTimeout(load, 250); };
    $("#city").onchange = load;
    $("#test").onchange = load;
    load();
  }

  function drawCentres(centres, highlightTest) {
    const box = $("#centres");
    if (!centres.length) {
      box.innerHTML = `<div style="grid-column:1/-1">${emptyState({
        ic: icon.search, title: "No centres match", text: "Try a different city, test or search term.",
      })}</div>`;
      return;
    }
    box.innerHTML = centres.map((c) => `
      <article class="card centre">
        <div class="centre__head">
          <h3>${esc(c.name)}</h3>
          <div class="centre__loc">${icon.pin}<span>${esc(c.address)}, ${esc(c.city)}${c.pincode ? ` ${esc(c.pincode)}` : ""}</span></div>
          <span class="chip">${c.tests.length} test${c.tests.length === 1 ? "" : "s"} available</span>
        </div>
        <ul class="tests">
          ${c.tests.map((o) => `
            <li class="test-row ${o.test.id === highlightTest ? "highlight" : ""}">
              <div class="test-row__info">
                <div class="test-row__name">${esc(o.test.name)}</div>
                <div class="test-row__code">${esc(o.test.code)}${o.test.description ? ` · ${esc(o.test.description)}` : ""}</div>
              </div>
              <span class="price">${money(o.price)}</span>
              <button class="btn btn--primary btn--sm" data-book='${esc(JSON.stringify({
                centre: { id: c.id, name: c.name, city: c.city }, test: o.test, price: o.price,
              }))}'>Book</button>
            </li>`).join("")}
        </ul>
      </article>`).join("");

    box.querySelectorAll("[data-book]").forEach((btn) => {
      btn.onclick = () => {
        const item = JSON.parse(btn.dataset.book);
        if (!auth.loggedIn) openAuth("login", () => openBooking(item));
        else openBooking(item);
      };
    });
  }

  // ------------------------------------------------------------ booking flow
  function defaultSlot() {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 30, 0, 0);
    return d;
  }
  const toLocalInput = (d) => {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const steps = (n) => `<div class="steps">${[1, 2, 3].map((i) => `<span class="${i <= n ? "done" : ""}"></span>`).join("")}</div>`;

  function openBooking(item) {
    const now = new Date();
    const max = new Date(now.getTime() + 90 * 864e5);
    openModal(`
      ${steps(1)}
      <h2>Book ${esc(item.test.name)}</h2>
      <p class="lead">at ${esc(item.centre.name)}, ${esc(item.centre.city)}</p>
      <form id="book-form" novalidate>
        <div id="book-error"></div>
        <div class="field" data-field="appointment_at">
          <label for="slot">Appointment date &amp; time</label>
          <input class="input" type="datetime-local" id="slot" required
                 min="${toLocalInput(now)}" max="${toLocalInput(max)}" value="${toLocalInput(defaultSlot())}">
        </div>
        <div class="summary">
          <div class="summary__row"><span>Test</span><span>${esc(item.test.name)}</span></div>
          <div class="summary__row"><span>Centre</span><span>${esc(item.centre.name)}</span></div>
          <div class="summary__row summary__total"><span>Amount</span><span>${money(item.price)}</span></div>
        </div>
        <button class="btn btn--primary btn--block" type="submit">Continue to payment</button>
      </form>`);

    const form = $("#book-form");
    form.onsubmit = async (e) => {
      e.preventDefault();
      clearErrors(form);
      const value = $("#slot").value;
      if (!value) {
        form.querySelector('[data-field="appointment_at"]').insertAdjacentHTML("beforeend", '<span class="field__error">Please choose a date and time.</span>');
        return;
      }
      const btn = form.querySelector("[type=submit]");
      setBusy(btn, true);
      try {
        const booking = await api("/bookings/", {
          method: "POST",
          body: { centre_id: item.centre.id, test_id: item.test.id, appointment_at: new Date(value).toISOString() },
        });
        toast("Booking created — complete payment to confirm it.", { type: "success" });
        openPayment(booking);
      } catch (err) {
        showErrors(form, err, "#book-error");
      } finally {
        setBusy(btn, false);
      }
    };
  }

  function openPayment(booking) {
    openModal(`
      ${steps(2)}
      <h2>Payment</h2>
      <p class="lead">${esc(booking.test.name)} · ${esc(fmtFull(booking.appointment_at))}</p>
      <div class="summary">
        <div class="summary__row"><span>Booking</span><span>#${booking.id}</span></div>
        <div class="summary__row"><span>Centre</span><span>${esc(booking.centre.name)}</span></div>
        <div class="summary__row summary__total"><span>Total</span><span>${money(booking.amount)}</span></div>
      </div>
      <form id="pay-form">
        <div id="pay-error"></div>
        <p class="small muted" style="margin:0 0 8px">Simulated gateway <span class="demo-tag">Demo</span> — choose how the payment should behave:</p>
        <div class="options">
          ${payOption("SUCCESS", "Payment succeeds", "Card is charged and the booking is confirmed.", true)}
          ${payOption("FAILED", "Card is declined", "The payment fails; you can retry afterwards.")}
          ${payOption("PENDING", "Provider confirms later", "Payment stays pending until the provider's webhook arrives.")}
          ${payOption("", "Random outcome", "Let the mock gateway decide (80% success).")}
        </div>
        <button class="btn btn--primary btn--block" type="submit">${icon.card} Pay ${money(booking.amount)}</button>
      </form>`);

    const form = $("#pay-form");
    const idempotencyKey = uuid(); // same key if the user double-clicks or retries this submit
    form.onsubmit = async (e) => {
      e.preventDefault();
      clearErrors(form);
      const btn = form.querySelector("[type=submit]");
      const outcome = new FormData(form).get("outcome");
      setBusy(btn, true, "Processing…");
      try {
        const payment = await api("/payments/", {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey },
          body: outcome ? { booking_id: booking.id, simulate_outcome: outcome } : { booking_id: booking.id },
        });
        showPaymentResult(booking, payment);
      } catch (err) {
        showErrors(form, err, "#pay-error");
        setBusy(btn, false);
      }
    };
  }

  function payOption(value, title, desc, checked = false) {
    return `<label class="option">
      <input type="radio" name="outcome" value="${value}" ${checked ? "checked" : ""}>
      <div><div class="option__title">${esc(title)}</div><div class="option__desc">${esc(desc)}</div></div>
    </label>`;
  }

  function showPaymentResult(booking, payment) {
    const copy = {
      SUCCESS: ["Booking confirmed", `We've received ${money(payment.amount)}. See you on ${fmtFull(booking.appointment_at)}.`, icon.check],
      FAILED: ["Payment failed", payment.failure_reason || "The payment was declined.", icon.x],
      PENDING: ["Waiting for confirmation", "The provider hasn't confirmed this payment yet. Your booking updates as soon as it does.", icon.clock],
    }[payment.status];

    const actions = {
      SUCCESS: `<button class="btn btn--primary" data-go="bookings">View my bookings</button>`,
      FAILED: `<button class="btn btn--ghost" data-go="bookings">Later</button><button class="btn btn--primary" id="retry">Try again</button>`,
      PENDING: DEMO
        ? `<button class="btn btn--ghost" data-hook="failed">Provider: decline</button><button class="btn btn--primary" data-hook="succeeded">Provider: approve</button>`
        : `<button class="btn btn--primary" data-go="bookings">View my bookings</button>`,
    }[payment.status];

    openModal(`
      ${steps(3)}
      <div class="result">
        <div class="result__icon result__icon--${payment.status}">${copy[2]}</div>
        <h2>${esc(copy[0])}</h2>
        <p class="lead">${esc(copy[1])}</p>
        ${payment.status === "PENDING" && DEMO ? '<p class="small muted" style="margin-top:-8px">Simulate the payment provider\'s webhook <span class="demo-tag">Demo</span></p>' : ""}
        <div class="btn-row">${actions}</div>
        <p class="small muted mono" style="margin:16px 0 0">Ref ${esc(payment.provider_reference)}</p>
      </div>`);

    modalBody.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { closeModal(); go(b.dataset.go); }));
    const retry = $("#retry");
    if (retry) retry.onclick = () => openPayment({ ...booking, status: "FAILED" });
    modalBody.querySelectorAll("[data-hook]").forEach((b) => {
      b.onclick = async () => {
        setBusy(b, true);
        const result = await sendWebhook(payment.provider_reference, b.dataset.hook);
        if (result) showPaymentResult(booking, { ...payment, status: result.payment_status });
        else setBusy(b, false);
      };
    });
  }

  // Remembers the last event id per payment so it can be replayed (idempotency demo).
  const lastEvent = store.get("eve.lastEvent") || {};

  async function sendWebhook(reference, outcome, eventId) {
    try {
      const result = await api("/payments/dev/simulate-webhook/", {
        method: "POST",
        body: eventId ? { provider_reference: reference, outcome, event_id: eventId } : { provider_reference: reference, outcome },
      });
      lastEvent[reference] = { id: result.event_id, outcome };
      store.set("eve.lastEvent", lastEvent);
      if (result.duplicate) {
        toast("Duplicate webhook ignored", { detail: `Event ${result.event_id} was already processed — nothing changed.` });
      } else if (result.status === "IGNORED") {
        toast("Webhook ignored", { detail: result.note });
      } else {
        toast(`Webhook processed: ${result.note}`, { type: result.payment_status === "SUCCESS" ? "success" : "error" });
      }
      return result;
    } catch (err) {
      toast(err.message, { type: "error" });
      return null;
    }
  }

  // ------------------------------------------------------------ bookings page
  let bookingFilter = "ALL";

  async function renderBookings() {
    if (!auth.loggedIn) return requireLogin("Log in to see your bookings.");
    view.innerHTML = `
      <div class="section-head"><h2>My bookings</h2><a class="btn btn--primary btn--sm" href="#/centres">Book a test</a></div>
      <div class="tabs" id="tabs"></div>
      <div id="bookings"><div class="skeleton" style="height:96px"></div></div>`;

    let bookings, payments;
    try {
      [bookings, payments] = await Promise.all([api("/bookings/?page_size=100"), api("/payments/?page_size=100")]);
    } catch (err) {
      $("#bookings").innerHTML = emptyState({ title: "Couldn't load bookings", text: err.message });
      return;
    }
    const pendingPayment = {};
    payments.results.forEach((p) => { if (p.status === "PENDING") pendingPayment[p.booking_id] = p; });

    const counts = { ALL: bookings.results.length };
    bookings.results.forEach((b) => (counts[b.status] = (counts[b.status] || 0) + 1));
    const tabs = ["ALL", "PENDING", "CONFIRMED", "FAILED", "CANCELLED"];
    $("#tabs").innerHTML = tabs.map((t) => `
      <button class="tab ${t === bookingFilter ? "active" : ""}" data-tab="${t}">
        ${t === "ALL" ? "All" : t.charAt(0) + t.slice(1).toLowerCase()}<span class="count">${counts[t] || 0}</span>
      </button>`).join("");
    $("#tabs").querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { bookingFilter = b.dataset.tab; renderBookings(); }));

    const list = bookings.results.filter((b) => bookingFilter === "ALL" || b.status === bookingFilter);
    if (!list.length) {
      $("#bookings").innerHTML = emptyState({
        ic: icon.calendar,
        title: bookingFilter === "ALL" ? "No bookings yet" : "Nothing here",
        text: bookingFilter === "ALL" ? "Find a centre near you and book your first test." : "You have no bookings with this status.",
        action: bookingFilter === "ALL" ? '<a class="btn btn--primary" href="#/centres">Find a test</a>' : "",
      });
      return;
    }

    const now = Date.now();
    $("#bookings").innerHTML = list.map((b) => {
      const d = new Date(b.appointment_at);
      const upcoming = d.getTime() > now;
      const pending = pendingPayment[b.id];
      const canPay = upcoming && !pending && (b.status === "PENDING" || b.status === "FAILED");
      const canCancel = upcoming && (b.status === "PENDING" || b.status === "CONFIRMED");
      return `
        <article class="card booking">
          <div class="date-badge">
            <div class="date-badge__month">${esc(fmtDate(b.appointment_at, { month: "short" }).toUpperCase())}</div>
            <div class="date-badge__day">${d.getDate()}</div>
            <div class="date-badge__time">${esc(fmtDate(b.appointment_at, { hour: "numeric", minute: "2-digit" }))}</div>
          </div>
          <div>
            <div class="booking__title">${esc(b.test.name)} ${badge(b.status)}</div>
            <div class="booking__meta">${esc(b.centre.name)}, ${esc(b.centre.city)} · ${money(b.amount)} · Booking #${b.id}${upcoming ? "" : " · past"}</div>
          </div>
          <div class="booking__actions">
            ${canPay ? `<button class="btn btn--primary btn--sm" data-pay="${b.id}">${b.status === "FAILED" ? "Retry payment" : "Pay now"}</button>` : ""}
            ${canCancel ? `<button class="btn btn--danger btn--sm" data-cancel="${b.id}">Cancel</button>` : ""}
          </div>
          ${pending ? `
            <div class="booking__note">${icon.clock} Payment awaiting provider confirmation.
              ${DEMO ? `<span class="demo-tag">Demo</span>
                <button class="btn btn--ghost btn--sm" data-hook="succeeded" data-ref="${esc(pending.provider_reference)}">Approve</button>
                <button class="btn btn--ghost btn--sm" data-hook="failed" data-ref="${esc(pending.provider_reference)}">Decline</button>` : ""}
            </div>` : ""}
        </article>`;
    }).join("");

    const byId = Object.fromEntries(bookings.results.map((b) => [b.id, b]));
    view.querySelectorAll("[data-pay]").forEach((btn) => (btn.onclick = () => openPayment(byId[btn.dataset.pay])));
    view.querySelectorAll("[data-cancel]").forEach((btn) => (btn.onclick = () => confirmCancel(byId[btn.dataset.cancel])));
    view.querySelectorAll("[data-hook]").forEach((btn) => {
      btn.onclick = async () => {
        setBusy(btn, true);
        if (await sendWebhook(btn.dataset.ref, btn.dataset.hook)) renderBookings();
        else setBusy(btn, false);
      };
    });
  }

  function confirmCancel(booking) {
    const refund = booking.status === "CONFIRMED";
    openModal(`
      <h2>Cancel this booking?</h2>
      <p class="lead">${esc(booking.test.name)} at ${esc(booking.centre.name)} on ${esc(fmtFull(booking.appointment_at))}.
        ${refund ? "Your payment of " + money(booking.amount) + " will be refunded." : ""}</p>
      <div class="btn-row">
        <button class="btn btn--ghost" data-close>Keep booking</button>
        <button class="btn btn--primary" id="do-cancel" style="background:var(--danger)">Yes, cancel</button>
      </div>`);
    $("#do-cancel").onclick = async (e) => {
      setBusy(e.currentTarget, true);
      try {
        await api(`/bookings/${booking.id}/cancel/`, { method: "POST" });
        closeModal();
        toast("Booking cancelled.", { type: "success" });
        renderBookings();
      } catch (err) {
        closeModal();
        toast(err.message, { type: "error" });
      }
    };
  }

  // ------------------------------------------------------------ payments page
  async function renderPayments() {
    if (!auth.loggedIn) return requireLogin("Log in to see your payments.");
    view.innerHTML = `
      <div class="section-head"><h2>Payments</h2><span class="muted small">Every attempt, including failed ones</span></div>
      <div class="card" id="payments"><div class="skeleton" style="height:160px;border:0"></div></div>`;
    let data;
    try {
      data = await api("/payments/?page_size=100");
    } catch (err) {
      $("#payments").outerHTML = emptyState({ title: "Couldn't load payments", text: err.message });
      return;
    }
    if (!data.results.length) {
      $("#payments").outerHTML = emptyState({ ic: icon.card, title: "No payments yet", text: "Payments appear here once you pay for a booking." });
      return;
    }
    $("#payments").innerHTML = `
      <div class="table-wrap"><table>
        <thead><tr><th>Date</th><th>Booking</th><th>Amount</th><th>Status</th><th>Reference</th>${DEMO ? "<th></th>" : ""}</tr></thead>
        <tbody>${data.results.map((p) => {
          const replay = lastEvent[p.provider_reference];
          return `<tr>
            <td>${esc(fmtDate(p.created_at, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }))}</td>
            <td>#${p.booking_id} <span class="muted small">(${esc(p.booking_status.toLowerCase())})</span></td>
            <td class="num">${money(p.amount)}</td>
            <td>${badge(p.status)}${p.failure_reason ? `<div class="small muted">${esc(p.failure_reason)}</div>` : ""}</td>
            <td class="mono muted">${esc(p.provider_reference)}</td>
            ${DEMO ? `<td>${replay ? `<button class="btn btn--ghost btn--sm" data-replay="${esc(p.provider_reference)}"
                 title="Send event ${esc(replay.id)} again to show the webhook is idempotent">Replay webhook</button>` : ""}</td>` : ""}
          </tr>`;
        }).join("")}</tbody>
      </table></div>`;
    view.querySelectorAll("[data-replay]").forEach((btn) => {
      btn.onclick = async () => {
        const ev = lastEvent[btn.dataset.replay];
        setBusy(btn, true);
        await sendWebhook(btn.dataset.replay, ev.outcome, ev.id);
        renderPayments();
      };
    });
  }

  function requireLogin(text) {
    view.innerHTML = emptyState({
      ic: icon.info, title: "Please log in", text,
      action: '<button class="btn btn--primary" id="login-cta">Log in</button>',
    });
    $("#login-cta").onclick = () => openAuth("login");
  }

  // ------------------------------------------------------------ router
  const routes = { centres: renderCentres, bookings: renderBookings, payments: renderPayments };

  function route() {
    const name = (location.hash.replace(/^#\/?/, "").split("/")[0]) || "centres";
    const render = routes[name] || renderCentres;
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
    render();
  }

  function go(name) {
    if (location.hash === `#/${name}`) route();
    else location.hash = `#/${name}`; // hashchange triggers route()
  }

  window.addEventListener("hashchange", route);
  renderSession();
  route();
})();
