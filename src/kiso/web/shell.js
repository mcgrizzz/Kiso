/* Kiso's settings shell. No build step: plain DOM through h(), and text always
   goes through textContent.

   The add-on's script calls Kiso.setup({...}) with its pages; the shell owns
   the sidebar, the footer (Save keeps the window open, Cancel drops unsaved
   edits, only X or Esc closes and asks first), unsaved-change dots, per-page
   Revert and Restore defaults, and save errors that jump to their field.

   Globals the add-on's pages use: S (the state from op_state), saved and draft
   (the config as saved and as edited), page (the current page id), and the
   helpers below: call, h, icon, ICONS, clone, same, changed, render, pageHead,
   radio, slider, help, disclosure, openModal, closeModal, confirmDialog. */

let S = null;
let saved = null;
let draft = null;
let page = null;

const Kiso = {
  options: null,
  pages: [],
  // How a page reaches Python: the bridge's prefix, without the colon.
  prefix: "kiso",
};

const ICONS = { close: "M6 6l12 12M18 6L6 18" };

function call(op, arg) {
  return new Promise((resolve) => pycmd(Kiso.prefix + ":" + JSON.stringify({ op, arg }), resolve));
}

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k in el && k !== "list" && k !== "form") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {   // children may come in nested arrays
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

const clone = (x) => JSON.parse(JSON.stringify(x));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// -- pages ----------------------------------------------------------------
// A page: {id, title, icon (an ICONS key), render() -> elements,
//          slice(cfg) -> the part of the config it edits (for its unsaved dot),
//          revert(draft)? (Revert this page: put its part of the draft back as saved),
//          restore(draft)? (Restore defaults; none when there's nothing sensible to restore),
//          restoreLabel? (the Restore button's text, naming what it resets),
//          restoreTitle? (what Restore does, as a tooltip)}

const pageOf = (id) => Kiso.pages.find((p) => p.id === id);
const pageChanged = (id) => !same(pageOf(id).slice(draft), pageOf(id).slice(saved));

// Each action shows only when it would change something; both wait for Save.
function pageActions() {
  const p = pageOf(page);
  const restore = p.restore;
  const wouldRestore = restore && (() => { const d = clone(draft); restore(d); return !same(p.slice(d), p.slice(draft)); })();
  return h("div", { className: "head-actions" },
    pageChanged(page) && p.revert && h("button", { type: "button", className: "quiet", id: "revertPage",
      title: "Undo unsaved changes on this page only. Other pages keep theirs.",
      onclick: () => { p.revert(draft); changed(true); } }, "Revert this page"),
    wouldRestore && h("button", { type: "button", className: "quiet", id: "restorePage",
      title: p.restoreTitle || "Back to this page's defaults. Nothing changes until Save.",
      onclick: () => { restore(draft); changed(true); } }, p.restoreLabel || "Restore defaults"));
}

function pageHead(title, lead) {
  return [h("header", { className: "page-head" }, h("h1", {}, title), pageActions()),
          lead && h("p", { className: "lead" }, lead)];
}

// -- change tracking --------------------------------------------------------

function changed(rerender) {
  const dirtyPages = Kiso.pages.filter((p) => pageChanged(p.id)).length;
  const dirty = !same(draft, saved);
  // Neither Save nor Cancel closes the window; only X or Esc does (asking first when there are unsaved edits).
  document.getElementById("save").disabled = !dirty;
  document.getElementById("cancel").disabled = !dirty;
  const pages = `${dirtyPages || 1} page${dirtyPages > 1 ? "s" : ""}`;
  const status = document.getElementById("status");
  status.textContent = dirty ? (Kiso.options.unsaved ? Kiso.options.unsaved(pages) : `Unsaved changes on ${pages}`) : "";
  status.classList.toggle("dirty", dirty);
  document.getElementById("errors").textContent = "";
  call("dirty", dirty);
  if (rerender) render();
  else {
    // Cheap, so it runs on every edit without rebuilding the page (and losing the field's focus).
    renderNav();
    const actions = document.querySelector(".head-actions");
    if (actions) actions.replaceWith(pageActions());
  }
  if (Kiso.options.onChange) Kiso.options.onChange(dirty);
}

// -- shell ----------------------------------------------------------------

function renderNav() {
  document.getElementById("nav").replaceChildren(
    ...(Kiso.options.brand ? [h("div", { className: "brand" }, Kiso.options.brand())] : []),
    ...Kiso.pages.map((p) =>
      h("button", { type: "button", "data-page": p.id, "aria-current": page === p.id ? "true" : "false",
                    onclick: () => { page = p.id; render(); } }, icon(p.icon), p.title,
        draft && pageChanged(p.id) && h("span", { className: "dot", title: "Unsaved changes" }, "•"))));
}

function render() {
  renderNav();
  if (Kiso.options.beforeRender) Kiso.options.beforeRender(page);
  const main = document.getElementById("main");
  // Redrawing the same page keeps its scroll position; another page starts at the top.
  const top = main.dataset.page === page ? main.scrollTop : 0;
  main.replaceChildren(...[pageOf(page).render()].flat(Infinity).filter(Boolean));
  main.dataset.page = page;
  main.scrollTop = top;
  if (Kiso.options.afterRender) Kiso.options.afterRender(page);
}

// -- small controls -----------------------------------------------------------

function radio(name, checked, label, onchange) {
  return h("label", { className: "check" }, h("input", { type: "radio", name, checked, onchange }), label);
}

function slider(label, value, min, max, unit, set) {
  const out = h("output", {}, value + unit);
  return h("div", { className: "field" }, h("label", {}, label),
    h("div", { className: "slider" },
      h("input", { type: "range", min, max, value, "aria-label": label,
                   oninput: (e) => { set(Number(e.target.value)); out.textContent = e.target.value + unit; changed(); } }),
      out));
}

// Short help, with the rest a click away: the (i) button shows or hides the longer text.
// What's open stays open when the page redraws.
const openHelp = new Set();
function help(short, more) {
  if (!more) return h("div", { className: "help-block" }, h("p", { className: "help" }, short));
  const extra = h("p", { className: "help more", hidden: !openHelp.has(more) }, more);
  const button = h("button", { type: "button", className: "info", title: "More about this", "aria-label": "More about this",
                               "aria-expanded": String(openHelp.has(more)), onclick: () => {
    extra.hidden = !extra.hidden;
    if (extra.hidden) openHelp.delete(more); else openHelp.add(more);
    button.setAttribute("aria-expanded", String(!extra.hidden));
  } }, "i");
  return h("div", { className: "help-block" }, h("p", { className: "help" }, short, " ", button), extra);
}

// A section that opens and closes (<details>), remembered by its key across redraws.
const sections = new Map();
function disclosure(key, summary, kids, startOpen = false) {
  const el = h("details", { className: "disclosure", open: sections.has(key) ? sections.get(key) : startOpen,
                            ontoggle: () => sections.set(key, el.open) }, h("summary", {}, summary), kids);
  return el;
}

// Modals stack: a confirmation can open over a dialog, and closing takes off the top one.
function openModal(dialog) {
  const overlay = h("div", { className: "overlay", onclick: (e) => { if (e.target === overlay) closeModal(); } }, dialog);
  document.getElementById("modal").append(overlay);
  const first = dialog.querySelector("[data-focus]") || dialog.querySelector("button.primary") || dialog.querySelector("button");
  if (first) first.focus();
}

function closeModal() {
  const top = document.getElementById("modal").lastElementChild;
  if (top) top.remove();
}

// Ask before doing something; resolves true only for `yes`. With `danger`, the yes
// button is red and focus starts on `no`, so Enter can't destroy anything.
function confirmDialog({ title, text = "", yes = "OK", no = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const answer = (ok) => { closeModal(); resolve(ok); };
    openModal(h("div", { className: "dialog small", role: "alertdialog", "aria-label": title },
      h("h2", {}, title),
      text && h("p", { className: "help" }, text),
      h("div", { className: "dialog-foot" },
        h("button", { type: "button", id: "confirmNo", "data-focus": danger, onclick: () => answer(false) }, no),
        h("button", { type: "button", id: "confirmYes", className: danger ? "primary danger" : "primary",
                      onclick: () => answer(true) }, yes))));
  });
}

// -- footer -----------------------------------------------------------------

async function save() {
  const res = await call("save", draft);
  if (res.errors) {
    const err = res.errors[0];
    document.getElementById("errors").textContent = err.message;
    if (Kiso.options.onSaveError) Kiso.options.onSaveError(err);
    if (err.page) page = err.page;   // a failure that isn't one field's (writing the config) stays put
    render();
    const el = document.querySelector(`[data-field="${err.field}"]`);
    if (el) el.focus();
    return false;
  }
  saved = clone(res.cfg);
  draft = clone(res.cfg);
  changed(true);
  document.getElementById("status").textContent = "Saved";
  return true;
}

window.askClose = () => {
  const titles = Kiso.pages.filter((p) => pageChanged(p.id)).map((p) => p.title);
  openModal(h("div", { className: "dialog small" },
    h("h2", {}, "Save your changes?"),
    h("p", { className: "help" }, titles.length ? `You have unsaved changes on: ${titles.join(", ")}.`
                                                : "Your edits haven't been saved."),
    h("div", { className: "dialog-foot" },
      h("button", { type: "button", id: "keepEditing", onclick: closeModal }, "Keep editing"),
      h("button", { type: "button", id: "discardClose", onclick: () => call("close") }, "Discard"),
      h("button", { type: "button", id: "saveClose", className: "primary",
                    onclick: async () => { if (await save()) call("close"); } }, "Save"))));
};

// -- screenshots (kiso shots, dev only: shots.py) -------------------------------
// Python resizes the dialog and calls Kiso.shots.run(): every page in turn, each grabbed from
// top to bottom (shot), or walked by the add-on's own tour for it: options.shots[pageId], an
// async function given { shot(label, {wait}?), wait(ms), page } that clicks through what it
// wants seen (each scene, a dialog) and calls shot() at each. Tours only look: they never
// add, delete or save. Python grabs the dialog at each step; nothing here is ever saved.

Kiso.shots = {
  // only: one tour by name, alone (kiso shots --tour); a tour that isn't a page's runs only so.
  async run(only = null) {
    const errors = [];
    const start = page;
    const tours = Kiso.options.shots || {};
    if (only && !tours[only]) errors.push(`no tour called ${only}`);
    const steps = !only ? Kiso.pages : tours[only] ? [Kiso.pages.find((p) => p.id === only) || { id: only, title: only }] : [];
    for (const p of steps) {
      if (Kiso.pages.includes(p)) {
        page = p.id;
        render();
      }
      try {
        const tour = tours[p.id];
        if (tour) await tour({ shot: (label, opts) => shotPage(p, label, opts), wait: settle, page: p });
        else await shotPage(p, p.title);
      } catch (e) {
        errors.push(`${p.id}: ${(e && e.message) || e}`);
      }
      while (document.getElementById("modal").firstChild) closeModal();
    }
    page = start;
    render();
    call("kiso_shots_done", { errors });
  },
};

// Two frames drawn, then `ms` more for what follows them (previews, fades). A window that isn't
// being drawn (covered by another, on Windows) gets no frames: after a second it goes on anyway.
function settle(ms = 300) {
  const frames = new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const late = new Promise((resolve) => setTimeout(resolve, 1000));
  return Promise.race([frames, late]).then(() => new Promise((resolve) => setTimeout(resolve, ms)));
}

// What scrolls: the top dialog's longest scrolling part when one is open, else the page.
function scroller() {
  const top = document.getElementById("modal").lastElementChild;
  if (top) {
    const parts = [top, ...top.querySelectorAll("*")].filter((el) => el.scrollHeight > el.clientHeight + 2
      && /(auto|scroll)/.test(getComputedStyle(el).overflowY));
    return parts.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0] || null;
  }
  return document.getElementById("main");
}

// Grabs from top to bottom, each overlapping the one before a little; numbered when there's more than one.
// whole: false grabs only what shows now, scrolled as it is.
async function shotPage(p, label, { wait = 700, whole = true } = {}) {
  if (!whole) {
    await settle(wait);
    await call("kiso_shot", { page: p.id, label, part: 0 });
    return;
  }
  const box = scroller();
  if (box) box.scrollTop = 0;
  for (let part = 1; ; part++) {
    await settle(part === 1 ? wait : 250);
    const more = !!box && box.scrollTop + box.clientHeight < box.scrollHeight - 2;
    await call("kiso_shot", { page: p.id, label, part: more || part > 1 ? part : 0 });
    if (!more) break;
    const before = box.scrollTop;
    box.scrollTop += Math.round(box.clientHeight * 0.85);
    if (box.scrollTop === before) break;
  }
  if (box) box.scrollTop = 0;
}

// -- start --------------------------------------------------------------------
// options: {prefix, pages, brand()? -> elements (atop the sidebar), footer()? -> elements (the footer's
//           left end, drawn once; the add-on updates them itself), first?, onLoad(state)?, onChange(dirty)?,
//           beforeRender(page)?, afterRender(page)?, onCancel()?, onSaveError(err)?, unsaved(pages)?,
//           shots? -> {pageId or name: async tour} for kiso shots (above)}

Kiso.setup = (options) => {
  Kiso.options = options;
  Kiso.prefix = options.prefix;
  Kiso.pages = options.pages;
  if (options.footer) document.getElementById("about").replaceChildren(...[options.footer()].flat(Infinity).filter(Boolean));
  document.getElementById("save").addEventListener("click", save);
  // Cancel: drop unsaved edits on every page and go back to what's saved (Revert this page is the per-page version).
  document.getElementById("cancel").addEventListener("click", () => {
    if (options.onCancel) options.onCancel();
    draft = clone(saved);
    changed(true);
    document.getElementById("status").textContent = "Unsaved changes discarded";
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.getElementById("modal").firstChild) { e.stopPropagation(); closeModal(); }
  }, true);
  (function start() {
    if (typeof pycmd !== "function") return setTimeout(start, 20);   // web channel not ready yet
    call("state").then((state) => {
      S = state;
      saved = clone(state.cfg);
      draft = clone(state.cfg);
      page = options.first || Kiso.pages[0].id;
      if (options.onLoad) options.onLoad(state);
      render();
      window.kisoReady = true;   // for real-Anki checks
    });
  })();
};
