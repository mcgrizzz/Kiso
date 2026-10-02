// ==UserScript==
// @name         AnkiWeb upload helper
// @namespace    https://github.com/mcgrizzz/Kiso
// @version      0.3.0
// @description  Fills AnkiWeb's add-on upload form from the add-on's ankiweb.md and latest GitHub release. You still press Save.
// @match        https://ankiweb.net/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      api.github.com
// @connect      github.com
// @connect      objects.githubusercontent.com
// @connect      release-assets.githubusercontent.com
// @downloadURL  https://raw.githubusercontent.com/mcgrizzz/Kiso/main/userscripts/ankiweb-upload-helper.user.js
// @updateURL    https://raw.githubusercontent.com/mcgrizzz/Kiso/main/userscripts/ankiweb-upload-helper.user.js
// ==/UserScript==

/* On an add-on's edit page (https://ankiweb.net/shared/upload?id=...), the first
   time: paste a link to the add-on's ankiweb.md on GitHub. From then on, opening
   the page fills Title, Tags, Support Page, the branches' versions and the
   Description from that file, and attaches the .ankiaddon from the repo's latest
   release. Nothing is sent until you press Save.

   A new add-on (https://ankiweb.net/shared/upload, no id yet) can be linked and
   filled the same way. Its link waits until the add-on has an id: the first
   AnkiWeb page with one after the Save (the edit page, or the add-on's info page)
   takes it, if that add-on has no link yet and it's within an hour.

   The description gets a "what's new" link to that release ({{version}} and
   {{release_url}} in ankiweb.md place it; without them it goes at the end).
   AnkiWeb keeps no version itself, so that link is how the helper knows which
   release is on AnkiWeb: if it's already the latest, no file is attached.

   ankiweb.md: one "## <field>" section per form field, its value in the first
   fenced block under it (Title, Tags, Support page, Branches, Description).
   Branches lines look like "Supports: [ 26.08.0 ] - [ 26.09.3 ]", one per branch.
   The file is read from the branch or tag in the link, not the release. */

(function () {
  "use strict";

  // -- ankiweb.md --------------------------------------------------------------

  /** {title, tags, support, branches: [[min, max]], description} from the file's text. */
  function parseListing(markdown) {
    const sections = {};
    let name = null;
    let fence = null;
    let block = [];
    for (const line of markdown.split(/\r?\n/)) {
      if (fence) {
        if (line.trim() === fence) {
          if (name && !(name in sections)) sections[name] = block.join("\n");
          fence = null;
        } else block.push(line);
      } else if (/^##\s+/.test(line)) {
        name = line.replace(/^##\s+/, "").trim().toLowerCase();
      } else {
        const open = line.match(/^\s*(`{3,}|~{3,})/);
        if (open) { fence = open[1]; block = []; }
      }
    }
    const branches = [];
    for (const m of (sections.branches || "").matchAll(/\[\s*(-?[\d.]+)\s*\]\s*-\s*\[\s*(-?[\d.]+)\s*\]/g)) {
      branches.push([m[1], m[2]]);
    }
    return {
      title: sections.title, tags: sections.tags, support: sections["support page"],
      branches, description: sections.description,
    };
  }

  /** {owner, repo, ref, path} from a github.com blob link or a raw.githubusercontent.com link. */
  function parseLink(url) {
    let m = url.trim().match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)\/blob\/([^/]+)\/(.+?)(?:[?#].*)?$/);
    if (!m) m = url.trim().match(/^https:\/\/raw\.githubusercontent\.com\/([^/]+)\/([^/]+)\/(?:refs\/heads\/)?([^/]+)\/(.+?)(?:[?#].*)?$/);
    return m ? { owner: m[1], repo: m[2], ref: m[3], path: m[4] } : null;
  }

  // -- which version is on AnkiWeb ----------------------------------------------
  // AnkiWeb keeps no version, and cleans hidden text out of descriptions when it
  // saves them. So the description carries a visible "what's new" link to the
  // release, and the version on AnkiWeb is read back from that link.

  /** The release tag the saved description links to, or null. */
  function linkedVersion(description, link) {
    const prefix = `github.com/${link.owner}/${link.repo}/releases/tag/`.toLowerCase();
    const at = description.toLowerCase().indexOf(prefix);
    const tag = at < 0 ? null : description.slice(at + prefix.length).match(/^[^\s)"'<>\]]+/);
    return tag ? decodeURIComponent(tag[0]) : null;
  }

  /** The description with {{version}} and {{release_url}} filled in; with neither, a what's-new line goes at the end. */
  function withRelease(description, tag, url) {
    if (!/\{\{\s*(version|release_url)\s*\}\}/.test(description)) {
      description += "\n\n[What's new in {{version}}]({{release_url}})";
    }
    return description.replace(/\{\{\s*version\s*\}\}/g, () => tag).replace(/\{\{\s*release_url\s*\}\}/g, () => url);
  }

  // -- which page --------------------------------------------------------------

  /** {kind: "edit", id} on an add-on's edit page, {kind: "new"} on the new add-on page,
      {kind: "info", id} on an add-on's page; otherwise null. */
  function pageOf(pathname, search) {
    const path = pathname.replace(/\/+$/, "");
    if (path === "/shared/upload") {
      const id = new URLSearchParams(search).get("id");
      return id ? (/^\d+$/.test(id) ? { kind: "edit", id } : null) : { kind: "new" };
    }
    const info = path.match(/^\/shared\/info\/(\d+)$/);
    return info ? { kind: "info", id: info[1] } : null;
  }

  // A new add-on's link, waiting for its id: taken within this long of linking it.
  const PENDING_MS = 60 * 60 * 1000;

  /** The links with a waiting new add-on's link given to `id`, or null when it shouldn't be:
      none waiting, too old, or `id` already linked. */
  function claim(links, pending, id, now) {
    if (!pending || !id || links[id] || now - pending.at > PENDING_MS) return null;
    return { ...links, [id]: pending.link };
  }

  if (typeof window === "undefined") {   // loaded by the parser test in Node
    module.exports = { parseListing, parseLink, linkedVersion, withRelease, pageOf, claim };
    return;
  }

  // -- GitHub ------------------------------------------------------------------

  function request(url, { accept, binary } = {}) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: "GET", url,
        headers: accept ? { Accept: accept } : {},
        responseType: binary ? "arraybuffer" : "text",
        onload: (r) => (r.status >= 200 && r.status < 300 ? resolve(r.response)
          : reject(new Error(`${r.status} from ${url.split("?")[0]}`))),
        onerror: () => reject(new Error(`couldn't reach ${url.split("?")[0]}`)),
      });
    });
  }

  function readListing(link) {
    // The contents API, not raw.githubusercontent.com: that one caches for minutes.
    const url = `https://api.github.com/repos/${link.owner}/${link.repo}/contents/${link.path}?ref=${encodeURIComponent(link.ref)}`;
    return request(url, { accept: "application/vnd.github.raw" });
  }

  async function latestAddon(link) {
    const release = JSON.parse(await request(`https://api.github.com/repos/${link.owner}/${link.repo}/releases/latest`));
    const asset = release.assets.find((a) => a.name.endsWith(".ankiaddon"));
    if (!asset) throw new Error(`release ${release.tag_name} has no .ankiaddon`);
    const data = await request(asset.browser_download_url, { binary: true });
    const sum = release.assets.find((a) => a.name === asset.name + ".sha256");
    if (sum) {
      const want = (await request(sum.browser_download_url)).trim().split(/\s+/)[0].toLowerCase();
      const got = [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))]
        .map((b) => b.toString(16).padStart(2, "0")).join("");
      if (got !== want) throw new Error(`${asset.name} doesn't match its .sha256`);
    }
    return { tag: release.tag_name, url: release.html_url,
             file: new File([data], asset.name, { type: "application/octet-stream" }) };
  }

  // -- the page ----------------------------------------------------------------

  const links = () => GM_getValue("links", {});
  const NEW = "new";   // the panel's key on the new add-on page

  /** The link for a panel: an add-on's own, or on the new add-on page the one waiting. */
  function linkFor(key) {
    if (key !== NEW) return links()[key];
    const pending = GM_getValue("pending", null);
    return pending && Date.now() - pending.at <= PENDING_MS ? pending.link : undefined;
  }

  function saveLink(key, link) {
    if (key === NEW) GM_setValue("pending", { link, at: Date.now() });
    else GM_setValue("links", { ...links(), [key]: link });
  }

  /** On a page with an add-on's id: give it the new add-on's waiting link. True if it did. */
  function claimPending(id) {
    const updated = claim(links(), GM_getValue("pending", null), id, Date.now());
    if (!updated) return false;
    GM_setValue("links", updated);
    GM_setValue("pending", null);
    return true;
  }

  function set(el, value, event = "input") {
    el.value = value;
    el.dispatchEvent(new Event(event, { bubbles: true }));
  }

  function inputLabelled(form, text) {
    const label = [...form.querySelectorAll("label")].find((l) => l.textContent.trim() === text);
    return label && (label.htmlFor ? document.getElementById(label.htmlFor) : null)
      || label?.parentElement.querySelector("input");
  }

  // The rows "Branch N: Supports: [min] - [max]".
  function branchRows(form) {
    return [...form.querySelectorAll("input[maxlength='9']")].reduce((rows, el, i, all) =>
      (i % 2 ? rows : [...rows, [el, all[i + 1]]]), []);
  }

  /** Fill the form. `live`: the version on AnkiWeb, read before the first fill.
      The file is attached only if the latest release isn't already there, or with `attach`. */
  async function fill(form, link, say, live, attach = false) {
    const warnings = [];
    say(`Reading ${link.path} (${link.ref}) and the latest release...`);
    const [text, release] = await Promise.all([readListing(link), latestAddon(link).catch((e) => e)]);
    const listing = parseListing(text);
    const failed = release instanceof Error;
    if (failed) warnings.push(`couldn't get the latest release: ${release.message}`);

    for (const [label, value] of [["Title", listing.title], ["Tags", listing.tags], ["Support Page", listing.support]]) {
      const el = inputLabelled(form, label);
      if (value === undefined) warnings.push(`no "${label}" section`);
      else if (!el) warnings.push(`couldn't find the ${label} box`);
      else set(el, value.trim());
    }

    if (listing.branches.length) {
      // Never clicks "Add New Branch": it's a button inside the form, and the page
      // shows no sign of stopping it from submitting.
      const rows = branchRows(form);
      if (listing.branches.length > rows.length) {
        warnings.push(`ankiweb.md has ${listing.branches.length} branches and the page ${rows.length}: ` +
                      'press "Add New Branch", then "Fill again"');
      } else if (listing.branches.length < rows.length) {
        warnings.push(`the page has ${rows.length} branches and ankiweb.md ${listing.branches.length}; ` +
                      "only the first ones were filled");
      }
      listing.branches.slice(0, rows.length).forEach(([min, max], i) => {
        set(rows[i][0], min, "change");
        set(rows[i][1], max, "change");
      });
    } else warnings.push('no branches in the "Branches" section');

    const description = form.querySelector("textarea");
    if (listing.description === undefined) warnings.push('no "Description" section');
    else if (failed) warnings.push("Description not filled: its what's-new link needs the release");
    else set(description, withRelease(listing.description.trim(), release.tag, release.url));

    const same = !failed && live === release.tag;
    let attached = "";
    if (!failed && (!same || attach)) {
      const fileInput = form.querySelector("input[type='file']");
      const branch = fileInput?.parentElement.querySelector("select");
      if (!fileInput) warnings.push("couldn't find the file picker");
      else {
        if (branch && branch.options.length) set(branch, branch.options[branch.options.length - 1].value, "change");
        const files = new DataTransfer();
        files.items.add(release.file);
        fileInput.files = files.files;
        fileInput.dispatchEvent(new Event("change", { bubbles: true }));
        attached = ` Attached ${release.file.name}${branch ? " to the last branch" : ""}.`;
      }
    }
    const onAnkiWeb = live ? `On AnkiWeb: ${live}.` : "On AnkiWeb: unknown (no what's-new link yet).";
    const latest = failed ? "" : same && !attach
      ? ` The latest release, ${release.tag}, is already there: no file attached.`
      : ` Latest release: ${release.tag}.`;
    say(`${onAnkiWeb}${latest} Filled from ${link.path} (${link.ref}).${attached} Check it, then press Save.`, warnings);
    return same;
  }

  // -- the panel ---------------------------------------------------------------

  function panel(key, form, note = "") {
    document.getElementById("awuh-panel")?.remove();
    const box = document.createElement("div");
    box.id = "awuh-panel";
    Object.assign(box.style, {
      position: "fixed", right: "16px", bottom: "16px", zIndex: 9999, width: "340px", padding: "12px",
      background: "#fff", color: "#222", border: "1px solid #ccc", borderRadius: "8px",
      boxShadow: "0 4px 16px #0003", font: "13px/1.4 system-ui, sans-serif",
    });
    const status = document.createElement("div");
    const say = (message, warnings = []) => {
      status.replaceChildren(document.createTextNode(message));
      for (const w of warnings) {
        const line = document.createElement("div");
        line.style.color = "#b00020";
        line.textContent = "• " + w;
        status.append(line);
      }
    };
    const button = (text, onclick) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      Object.assign(b.style, { marginTop: "8px", marginRight: "6px", cursor: "pointer" });
      b.onclick = onclick;
      return b;
    };
    const title = document.createElement("b");
    title.textContent = key === NEW ? "Upload helper (new add-on)" : "Upload helper";
    title.style.display = "block";
    box.append(title);
    if (note) {
      const line = document.createElement("div");
      line.style.color = "#1b6e2b";
      line.textContent = note;
      box.append(line);
    }
    box.append(status);

    const link = linkFor(key);
    if (link) {
      // Read before filling replaces the description: the version AnkiWeb has now.
      const live = linkedVersion(form.querySelector("textarea").value, link);
      const anyway = button("Attach file anyway", () => run(true));
      anyway.hidden = true;
      const run = (attach = false) => fill(form, link, say, live, attach)
        .then((same) => { anyway.hidden = !same || attach; })
        .catch((e) => say(`Couldn't fill: ${e.message}`));
      box.append(button("Fill again", () => run()), anyway, button("Change link", () => ask(link)));
      run();
    } else ask(null);
    document.body.append(box);

    function ask(current) {
      say("Link this add-on to its ankiweb.md on GitHub (the file's page, or its raw link):");
      const field = document.createElement("input");
      Object.assign(field.style, { width: "100%", marginTop: "6px", boxSizing: "border-box" });
      field.placeholder = "https://github.com/you/addon/blob/main/docs/ankiweb.md";
      if (current) field.value = `https://github.com/${current.owner}/${current.repo}/blob/${current.ref}/${current.path}`;
      const save = button("Link and fill", () => {
        const parsed = parseLink(field.value);
        if (!parsed) return say("That isn't a GitHub file link. Open the file on GitHub and copy the address.");
        saveLink(key, parsed);
        panel(key, form);
      });
      status.append(field, save);
      field.focus();
    }
  }

  // A short note, for a page with no form (the add-on's page after a new add-on's Save).
  function toast(message) {
    document.getElementById("awuh-panel")?.remove();
    const box = document.createElement("div");
    box.id = "awuh-panel";
    Object.assign(box.style, {
      position: "fixed", right: "16px", bottom: "16px", zIndex: 9999, width: "340px", padding: "12px",
      background: "#fff", color: "#222", border: "1px solid #ccc", borderRadius: "8px",
      boxShadow: "0 4px 16px #0003", font: "13px/1.4 system-ui, sans-serif",
    });
    box.textContent = message;
    document.body.append(box);
    setTimeout(() => box.remove(), 8000);
  }

  // AnkiWeb is a single-page app: watch for the form on each page it shows. A page
  // with an add-on's id first takes a new add-on's waiting link.
  let shown = null;
  let claimed = null;
  setInterval(() => {
    const page = pageOf(location.pathname, location.search);
    let note = "";
    if (page?.id && claimed !== page.id && claimPending(page.id)) {
      claimed = page.id;
      note = `Linked add-on ${page.id} to the ankiweb.md you chose for it.`;
      if (page.kind === "info") toast(`Upload helper: ${note}`);
    }
    const key = page?.kind === "edit" ? page.id : page?.kind === "new" ? NEW : null;
    const form = key && document.querySelector("form textarea")?.closest("form");
    if (!form) {
      if (!key && page?.kind !== "info") { shown = null; document.getElementById("awuh-panel")?.remove(); }
      return;
    }
    if (shown === form) return;
    shown = form;
    panel(key, form, note);
  }, 500);
})();
