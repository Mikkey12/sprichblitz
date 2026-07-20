// Sprichblitz Konsole (d2) – Lese- + Schreib-Screens über Session-Cookie + X-Sb-Console.
// Vanilla-JS, kein Build/Framework (auditierbar). Strikte CSP verbietet inline.
// Kein persistenter Browser-Speicher, kein Cache (per Test-Guard erzwungen).

// --- fetch-Wrapper: setzt X-Sb-Console + no-store; Fehler → verständliche Message ---
async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      ...opts,
      cache: "no-store",
      headers: { "X-Sb-Console": "1", ...(opts.headers || {}) }, // NACH ...opts → erzwungen
    });
  } catch (_e) {
    throw new Error("Backend nicht erreichbar.");
  }
  if (res.status === 401) {
    throw new Error("Session abgelaufen – Konsole aus dem Sprichblitz-Client neu öffnen.");
  }
  if (!res.ok) {
    let msg = `Fehler (HTTP ${res.status}).`;
    try {
      const body = await res.json();
      if (body && body.error) msg = body.error; // Backend liefert deutsche Meldungen
    } catch (_e) {
      /* kein JSON-Body */
    }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

// JSON-Schreib-Helfer (PUT/PATCH).
function write(path, method, payload) {
  return api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// --- DOM-Helfer (textContent statt innerHTML → kein HTML-Injection-Risiko) ---
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

// Beschriftung ÜBER dem Feld (siehe style.css): nebeneinander wird es auf
// schmalen Screens unlesbar. Das <label> umschliesst das Feld weiterhin, damit
// ein Klick auf die Beschriftung fokussiert – ganz ohne IDs.
function row(labelText, inputEl) {
  const lab = el("label");
  lab.append(el("span", labelText), inputEl);
  const div = el("div", null, "field");
  div.append(lab);
  return div;
}

// Button-Zeile. Genau EINE primäre Aktion pro Karte – der Rest bleibt neutral.
function actions(...nodes) {
  const div = el("div", null, "actions");
  div.append(...nodes);
  return div;
}

function primaryButton(text) {
  const b = el("button", text, "primary");
  b.type = "button";
  return b;
}

function plainButton(text, cls) {
  const b = el("button", text, cls);
  b.type = "button";
  return b;
}

// --- Übersicht (read) ---
async function renderOverview(box) {
  box.replaceChildren(el("h2", "Übersicht"));
  try {
    const cfg = await api("/config");
    box.append(el("p", `Backend-Version ${cfg.version}`, "muted"));
    const card = el("div", null, "card");
    card.append(el("strong", "Provider"));
    for (const p of [...cfg.stt_providers, ...cfg.llm_providers]) {
      const line = el("div", null, "row");
      line.append(el("span", `${p.name} (${p.type})`));
      line.append(
        el("span", p.healthy ? "erreichbar" : "offline", p.healthy ? "ok" : "muted")
      );
      card.append(line);
    }
    box.append(card);
  } catch (e) {
    box.append(el("p", e.message, "error"));
  }
}

// --- Einstellungen (write: processing_location, sofort + revert-on-failure) ---
async function renderSettings(box) {
  box.replaceChildren(el("h2", "Einstellungen"));
  try {
    const me = await api("/me");
    const select = el("select");
    for (const loc of ["online", "local"]) {
      const opt = el("option", loc);
      opt.value = loc;
      if (loc === me.processing_location) opt.selected = true;
      select.append(opt);
    }
    const status = el("span", "", "muted");
    select.addEventListener("change", async () => {
      try {
        await write("/me/settings", "PATCH", { processing_location: select.value });
        status.textContent = "gespeichert ✓";
        status.className = "ok";
      } catch (e) {
        // revert-on-failure: echten Backend-Wert zurücksetzen statt ungespeicherte Auswahl zu behaupten
        const real = await api("/me")
          .then((m) => m.processing_location)
          .catch(() => me.processing_location);
        select.value = real;
        status.textContent = e.message;
        status.className = "error";
      }
    });
    const card = el("div", null, "card");
    card.append(row("Verarbeitungsort", select), status);
    box.append(card);
  } catch (e) {
    box.append(el("p", e.message, "error"));
  }
}

// --- Modi (write: voll editierbarer Override pro Modus; roher Override aus d2a) ---
async function renderModes(box) {
  box.replaceChildren(el("h2", "Modi"));
  try {
    const [modes, cfg] = await Promise.all([api("/me/modes"), api("/config")]);
    for (const m of modes) box.append(buildModeForm(box, m, cfg.stt_providers, cfg.llm_providers));
    box.append(
      el(
        "p",
        "Hinweis: STT-/LLM-Provider gelten online; im local-Modus läuft immer der lokale Provider (Cloud-Wahl wird still ignoriert).",
        "muted"
      )
    );
  } catch (e) {
    box.append(el("p", e.message, "error"));
  }
}

// Provider-Dropdown mit „(Default: …)"-Option und lokal/online-Badge.
function providerSelect(providers, current, defaultLabel) {
  const sel = el("select");
  const def = el("option", `(Default: ${defaultLabel})`);
  def.value = "";
  sel.append(def);
  for (const p of providers) {
    const badge = p.local ? " · lokal" : " · online";
    const o = el("option", p.name + badge);
    o.value = p.name;
    sel.append(o);
  }
  sel.value = current || "";
  return sel;
}

// LLM-Modell-Feld: Dropdown aus available_models des Providers, sonst Textfeld
// (z. B. LM Studio offline). Ein gespeicherter Wert bleibt immer wählbar.
function buildModelInput(models, current, defLabel) {
  if (models && models.length) {
    const sel = el("select");
    const def = el("option", `(Default: ${defLabel})`);
    def.value = "";
    sel.append(def);
    let found = false;
    for (const mdl of models) {
      const o = el("option", mdl);
      o.value = mdl;
      if (mdl === current) found = true;
      sel.append(o);
    }
    if (current && !found) {
      const o = el("option", current + " (gespeichert)");
      o.value = current;
      sel.append(o);
    }
    sel.value = current || "";
    return sel;
  }
  const inp = el("input");
  inp.type = "text";
  inp.placeholder = `Default: ${defLabel}`;
  inp.value = current || "";
  return inp;
}

function buildModeForm(box, m, sttProviders, llmProviders) {
  const ov = m.override; // roher Override oder null (d2a) – verhindert das Einfrieren der Defaults
  const card = el("div", null, "card");
  card.append(el("strong", m.display_name));
  card.append(el("div", m.is_overridden ? "dein Override" : "Default", "meta"));
  if (m.mode_key === "exact_swiss") {
    card.append(
      el(
        "p",
        "Standard: validierte lokale Mundart-Pipeline (WhisperKit → Qwen, ohne Cloud-Fallback). Änderungen auf eigenes Risiko.",
        "muted"
      )
    );
  }

  const name = el("input");
  name.type = "text";
  name.placeholder = `Default: ${m.default_display_name}`;
  name.value = ov && ov.display_name ? ov.display_name : "";
  card.append(row("Anzeigename", name));

  const enabled = el("input");
  enabled.type = "checkbox";
  enabled.checked = ov ? ov.enabled : true;
  card.append(row("Aktiv", enabled));

  const stt = providerSelect(sttProviders, ov && ov.stt_provider, m.default_stt);
  card.append(row("Spracherkennung (STT)", stt));

  const llm = providerSelect(llmProviders, ov && ov.llm_provider, m.default_llm || "–");
  card.append(row("LLM-Provider", llm));

  // LLM-Modell hängt vom gewählten LLM-Provider ab → bei Wechsel neu aufbauen.
  const modelWrap = el("div", null, "field");
  let modelField;
  function rebuildModel() {
    const provName = llm.value || m.default_llm;
    const prov = llmProviders.find((p) => p.name === provName);
    const models = prov ? prov.available_models : [];
    const current = ov && ov.llm_model ? ov.llm_model : "";
    const defLabel = m.default_llm_model || (prov && prov.default_model) || "–";
    modelField = buildModelInput(models, current, defLabel);
    const lab = el("label", "LLM-Modell: ");
    lab.append(modelField);
    modelWrap.replaceChildren(lab);
  }
  rebuildModel();
  llm.addEventListener("change", rebuildModel);
  card.append(modelWrap);

  // Nachbearbeitung (apply_llm) als Tri-State: Default / An / Aus.
  const applySel = el("select");
  const optD = el("option", `Default (${m.default_apply_llm ? "an" : "aus"})`);
  optD.value = "";
  applySel.append(optD);
  const optOn = el("option", "An");
  optOn.value = "true";
  applySel.append(optOn);
  const optOff = el("option", "Aus");
  optOff.value = "false";
  applySel.append(optOff);
  applySel.value = ov && ov.apply_llm != null ? String(ov.apply_llm) : "";
  card.append(row("Nachbearbeitung (LLM)", applySel));

  const prompt = el("textarea");
  prompt.rows = 3;
  prompt.placeholder = "leer = Default-Prompt";
  prompt.value = ov && ov.system_prompt ? ov.system_prompt : "";
  card.append(row("System-Prompt", prompt));

  const status = el("span", "", "muted");
  const save = primaryButton("Speichern");
  save.addEventListener("click", async () => {
    const applyVal = applySel.value === "" ? null : applySel.value === "true";
    try {
      await write(`/me/modes/${m.mode_key}`, "PUT", {
        enabled: enabled.checked,
        display_name: name.value.trim() || null,
        system_prompt: prompt.value.trim() || null,
        stt_provider: stt.value || null,
        llm_provider: llm.value || null,
        llm_model: (modelField.value || "").trim() || null,
        apply_llm: applyVal,
      });
      renderModes(box); // neu rendern → aktualisierte Herkunft/Effektiv
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });
  const reset = plainButton("Zurücksetzen");
  reset.addEventListener("click", async () => {
    try {
      await api(`/me/modes/${m.mode_key}`, { method: "DELETE" });
      renderModes(box);
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });
  card.append(actions(save, reset, status));
  return card;
}

// --- Konto & Keys (write: API-Keys; Key bleibt LOKAL, Feld wird IMMER geleert) ---
async function renderKeys(box) {
  box.replaceChildren(el("h2", "Konto & Keys"));
  try {
    const me = await api("/me");
    const spans = {}; // provider → "konfiguriert"-Span (surgical refresh, kein Re-Render)
    for (const provider of Object.keys(me.keys)) {
      const card = el("div", null, "card");
      card.append(el("strong", provider));
      const cfg = el("div", me.keys[provider] ? "konfiguriert" : "kein Key", "meta");
      spans[provider] = cfg;
      card.append(cfg);

      const input = el("input");
      input.type = "password";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.autocapitalize = "off";

      const status = el("span", "", "muted");
      const save = primaryButton("Speichern");
      save.addEventListener("click", () => saveKey(provider, input, status, spans));
      const del = plainButton("Entfernen");
      del.addEventListener("click", () => deleteKey(provider, status, spans));

      card.append(row("API-Key", input));
      card.append(actions(save, del, status));
      box.append(card);
    }
  } catch (e) {
    box.append(el("p", e.message, "error"));
  }
}

async function refreshConfigured(spans) {
  const me = await api("/me");
  for (const [provider, span] of Object.entries(spans)) {
    span.textContent = me.keys[provider] ? "konfiguriert" : "kein Key";
  }
}

async function saveKey(provider, input, status, spans) {
  const key = input.value; // EINZIGE Referenz, lokal, lebt nur in diesem Aufruf
  let saved = false;
  try {
    await write(`/me/keys/${provider}`, "PUT", { key });
    saved = true;
  } catch (e) {
    status.textContent = e.message; // z.B. "Key darf nicht leer sein" (422)
    status.className = "error";
  } finally {
    input.value = ""; // Feld IMMER leeren – Erfolg, Fehler ODER Netz-Wurf
  }
  if (saved) {
    // Save-Erfolg getrennt vom Refresh: ein Refresh-Fehler darf den Save NICHT als Fehler zeigen.
    status.textContent = "gespeichert ✓";
    status.className = "ok";
    try {
      await refreshConfigured(spans);
    } catch (_e) {
      /* Save ist durch; Boolean-Refresh ist best-effort */
    }
  }
}

async function deleteKey(provider, status, spans) {
  if (!confirm(`API-Key für ${provider} entfernen?`)) return;
  let removed = false;
  try {
    await api(`/me/keys/${provider}`, { method: "DELETE" });
    removed = true;
  } catch (e) {
    status.textContent = e.message;
    status.className = "error";
  }
  if (removed) {
    status.textContent = "entfernt";
    status.className = "ok";
    try {
      await refreshConfigured(spans);
    } catch (_e) {
      /* Delete ist durch; Refresh best-effort */
    }
  }
}

// --- Statistik (read) ---
async function renderStats(box) {
  box.replaceChildren(el("h2", "Statistik"));
  try {
    const stats = await api("/stats");
    const table = el("table");
    const head = el("tr");
    for (const c of ["Modus", "Anfragen", "Fehler", "Audio (s)"]) head.append(el("th", c));
    table.append(head);
    for (const [mode, s] of Object.entries(stats.per_mode)) {
      const tr = el("tr");
      tr.append(el("td", mode));
      tr.append(el("td", String(s.requests)));
      tr.append(el("td", String(s.errors)));
      tr.append(el("td", s.total_audio_seconds.toFixed(1)));
      table.append(tr);
    }
    // Die Tabelle scrollt in IHREM Container – der Body nie horizontal.
    const wrap = el("div", null, "table-wrap");
    wrap.append(table);
    box.append(wrap);
  } catch (e) {
    box.append(el("p", e.message, "error"));
  }
}

// --- Verwaltung (admin: Nutzer + Tokens) ---
// Sichtbar nur mit admin_scope (Rolle UND Admin-Session). Das Backend entscheidet
// ohnehin; das Ausblenden ist reine UX, kein Schutz.
async function renderAdmin(box) {
  box.replaceChildren(el("h2", "Verwaltung"));
  try {
    const [users, me, modes, cfg] = await Promise.all([
      api("/admin/users"),
      api("/me"),
      api("/admin/modes"),
      api("/config"),
    ]);

    box.append(el("h3", "Nutzer"));
    box.append(buildCreateUserForm(box));
    for (const u of users) box.append(buildUserCard(box, u, me.name));

    box.append(el("h3", "Globale Modi"));
    box.append(
      el(
        "p",
        "Gilt für alle Nutzer. Jeder kann sich das unter „Modi“ persönlich überschreiben.",
        "muted"
      )
    );
    box.append(buildCreateModeForm(box, cfg));
    for (const m of modes) box.append(buildGlobalModeCard(box, m, cfg));
  } catch (e) {
    box.append(el("p", e.message, "error"));
  }
}

// Provider-Dropdown für globale Modi. Anders als bei den User-Overrides gibt es
// hier keinen „(Default)"-Eintrag für die STT eines DB-Modus – der hat keinen.
function adminProviderSelect(providers, current, { allowEmpty, emptyLabel }) {
  const sel = el("select");
  if (allowEmpty) {
    const def = el("option", emptyLabel);
    def.value = "";
    sel.append(def);
  }
  for (const p of providers) {
    const o = el("option", p.name + (p.local ? " · lokal" : " · online"));
    o.value = p.name;
    sel.append(o);
  }
  sel.value = current || "";
  return sel;
}

function buildCreateModeForm(box, cfg) {
  const card = el("div", null, "card");
  card.append(el("strong", "Neuen Modus anlegen"));
  card.append(
    el("p", "Lebt nur in der Datenbank – kein Eintrag in config.yml, kein Neustart.", "muted")
  );

  const key = el("input");
  key.type = "text";
  key.placeholder = "z. B. notiz (klein, a–z, Ziffern, _)";
  card.append(row("Schlüssel", key));

  const desc = el("input");
  desc.type = "text";
  desc.placeholder = "z. B. Kurznotiz";
  card.append(row("Anzeigename", desc));

  const stt = adminProviderSelect(cfg.stt_providers, "", { allowEmpty: false });
  card.append(row("Spracherkennung (STT)", stt));

  const llm = adminProviderSelect(cfg.llm_providers, "", {
    allowEmpty: true,
    emptyLabel: "(keine Nachbearbeitung)",
  });
  card.append(row("LLM-Provider", llm));

  const status = el("span", "", "muted");
  const create = primaryButton("Anlegen");
  create.addEventListener("click", async () => {
    try {
      await write(`/admin/modes/${encodeURIComponent(key.value.trim())}`, "PUT", {
        description: desc.value.trim() || null,
        stt: stt.value || null,
        llm: llm.value || null,
        apply_llm: Boolean(llm.value),
        enabled: true,
      });
      renderAdmin(box);
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });
  card.append(actions(create, status));
  return card;
}

function buildGlobalModeCard(box, m, cfg) {
  const card = el("div", null, "card");
  const head = el("div");
  head.append(el("strong", m.mode_key));
  if (!m.enabled) head.append(el("span", "deaktiviert", "badge"));
  card.append(head);
  // Die Herkunft entscheidet, ob löschen überhaupt möglich ist – also zeigen.
  card.append(
    el(
      "div",
      m.from_config
        ? "aus config.yml" + (m.has_global_override ? " · global überschrieben" : "")
        : "in der Konsole angelegt",
      "meta"
    )
  );

  const desc = el("input");
  desc.type = "text";
  desc.value = m.description || "";
  card.append(row("Anzeigename", desc));

  const stt = adminProviderSelect(cfg.stt_providers, m.stt, { allowEmpty: false });
  card.append(row("Spracherkennung (STT)", stt));

  const llm = adminProviderSelect(cfg.llm_providers, m.llm, {
    allowEmpty: true,
    emptyLabel: "(keine Nachbearbeitung)",
  });
  card.append(row("LLM-Provider", llm));

  const model = el("input");
  model.type = "text";
  model.placeholder = "leer = Provider-Default";
  model.value = m.llm_model || "";
  card.append(row("LLM-Modell", model));

  const prompt = el("textarea");
  prompt.rows = 3;
  prompt.placeholder = "leer = kein System-Prompt";
  prompt.value = m.system_prompt || "";
  card.append(row("System-Prompt", prompt));

  const status = el("span", "", "muted");
  const save = primaryButton("Speichern");
  save.addEventListener("click", async () => {
    try {
      await write(`/admin/modes/${encodeURIComponent(m.mode_key)}`, "PUT", {
        description: desc.value.trim() || null,
        stt: stt.value || null,
        llm: llm.value || null,
        llm_model: model.value.trim() || null,
        system_prompt: prompt.value.trim() || null,
        apply_llm: Boolean(llm.value),
        enabled: m.enabled,
      });
      status.textContent = "gespeichert ✓";
      status.className = "ok";
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });

  // Zwei Klassen: Config-Modi lassen sich nur ab- und wieder anschalten (die YAML
  // kann die API nicht anfassen), DB-Modi wirklich löschen. Der Knopf sagt, was er tut.
  const toggle = plainButton(m.enabled ? "Deaktivieren" : "Aktivieren", m.enabled ? "danger" : null);
  toggle.addEventListener("click", async () => {
    if (
      m.enabled &&
      !confirm(
        `„${m.mode_key}" für ALLE Nutzer deaktivieren?\n\n` +
          `Der Modus verschwindet überall – auch aus den Clients. ` +
          `Einstellungen und Statistik bleiben erhalten, du kannst ihn jederzeit wieder einschalten.`
      )
    )
      return;
    try {
      await write(`/admin/modes/${encodeURIComponent(m.mode_key)}`, "PUT", { enabled: !m.enabled });
      renderAdmin(box);
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });

  const buttons = [save, toggle];
  if (!m.from_config) {
    const del = plainButton("Löschen …", "danger");
    del.addEventListener("click", async () => {
      if (
        !confirm(
          `„${m.mode_key}" endgültig löschen?\n\n` +
            `Der Modus existiert nur in der Datenbank und ist danach weg. ` +
            `Persönliche Overrides der Nutzer darauf verlieren ihre Wirkung.`
        )
      )
        return;
      try {
        await api(`/admin/modes/${encodeURIComponent(m.mode_key)}`, { method: "DELETE" });
        renderAdmin(box);
      } catch (e) {
        status.textContent = e.message;
        status.className = "error";
      }
    });
    buttons.push(del);
  }
  card.append(actions(...buttons, status));
  return card;
}

function locationSelect(current) {
  const sel = el("select");
  for (const loc of ["online", "local"]) {
    const o = el("option", loc);
    o.value = loc;
    if (loc === current) o.selected = true;
    sel.append(o);
  }
  return sel;
}

function buildCreateUserForm(box) {
  const card = el("div", null, "card");
  card.append(el("strong", "Neuen Nutzer anlegen"));

  const name = el("input");
  name.type = "text";
  name.placeholder = "z. B. demo-device";
  card.append(row("Name", name));

  const display = el("input");
  display.type = "text";
  display.placeholder = "optional";
  card.append(row("Anzeigename", display));

  const loc = locationSelect("local");
  card.append(row("Verarbeitungsort", loc));

  const admin = el("input");
  admin.type = "checkbox";
  card.append(row("Admin", admin));

  const status = el("span", "", "muted");
  const create = primaryButton("Anlegen");
  create.addEventListener("click", async () => {
    if (!name.value.trim()) {
      status.textContent = "Name darf nicht leer sein.";
      status.className = "error";
      return;
    }
    try {
      await write("/admin/users", "POST", {
        name: name.value.trim(),
        display_name: display.value.trim() || null,
        processing_location: loc.value,
        is_admin: admin.checked,
      });
      renderAdmin(box); // neu rendern → neuer Nutzer erscheint in der Liste
    } catch (e) {
      status.textContent = e.message; // z. B. „User 'x' existiert bereits" (409)
      status.className = "error";
    }
  });
  card.append(actions(create, status));
  return card;
}

function buildUserCard(box, u, myName) {
  const isSelf = u.name === myName;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const card = el("div", null, "card");

  const head = el("div");
  head.append(el("strong", u.name));
  if (isSelf) head.append(el("span", "du", "badge"));
  card.append(head);

  // Eine ruhige Kennzahlen-Zeile statt vieler Badges – sie beantwortet auch
  // gleich, was ein Löschen kosten würde.
  const facts = [
    plural(u.token_count, "Token", "Tokens"),
    plural(u.usage_days, "Tag Statistik", "Tage Statistik"),
    u.processing_location,
  ];
  if (u.is_admin) facts.push("Admin");
  if (u.disabled) facts.push("deaktiviert");
  card.append(el("div", facts.join(" · "), "meta"));

  const display = el("input");
  display.type = "text";
  display.placeholder = "optional";
  display.value = u.display_name || "";
  card.append(row("Anzeigename", display));

  const loc = locationSelect(u.processing_location);
  card.append(row("Verarbeitungsort", loc));

  // Aussperr-Schutz: am eigenen Konto sind Rolle und Aktiv-Status gesperrt. Das
  // Backend weist es ohnehin ab (409 self_lockout) – hier nur, damit es gar nicht
  // erst anklickbar aussieht.
  const admin = el("input");
  admin.type = "checkbox";
  admin.checked = u.is_admin;
  admin.disabled = isSelf;
  card.append(row("Admin", admin));

  const active = el("input");
  active.type = "checkbox";
  active.checked = !u.disabled;
  active.disabled = isSelf;
  card.append(row("Aktiv", active));

  const status = el("span", "", "muted");
  const save = primaryButton("Speichern");
  save.addEventListener("click", async () => {
    const payload = {
      display_name: display.value.trim() || null,
      processing_location: loc.value,
    };
    if (!isSelf) {
      payload.is_admin = admin.checked;
      payload.disabled = !active.checked;
    }
    try {
      await write(`/admin/users/${u.id}`, "PATCH", payload);
      status.textContent = "gespeichert ✓";
      status.className = "ok";
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });

  // Tokens erst auf Klick laden – spart N+1-Requests beim Öffnen der Liste.
  const tokenBox = el("div");
  const tokensBtn = plainButton("Tokens …");
  tokensBtn.addEventListener("click", () => {
    if (tokenBox.hasChildNodes()) {
      tokenBox.replaceChildren();
      return;
    }
    renderTokens(tokenBox, u);
  });

  // Löschen ist unwiderruflich und nimmt die Statistik mit → die Bestätigung muss
  // beim Namen nennen, was verschwindet, und den sanften Weg (Aktiv abwählen) zeigen.
  const del = plainButton("Löschen …", "danger");
  del.disabled = isSelf;
  del.addEventListener("click", async () => {
    const ok = confirm(
      `„${u.name}" endgültig löschen?\n\n` +
        `Damit verschwinden auch: ${plural(u.token_count, "Token", "Tokens")}, ` +
        `${plural(u.usage_days, "Tag Statistik", "Tage Statistik")}, ` +
        `gespeicherte API-Keys und Modus-Overrides.\n\n` +
        `Das lässt sich nicht rückgängig machen. Willst du nur den Zugang sperren, ` +
        `brich ab und wähle stattdessen „Aktiv" ab – dabei bleiben alle Daten erhalten.`
    );
    if (!ok) return;
    try {
      await api(`/admin/users/${u.id}`, { method: "DELETE" });
      renderAdmin(box);
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });

  card.append(actions(save, tokensBtn, del, status), tokenBox);
  return card;
}

function tokenRow(box, u, t) {
  const line = el("div", null, "row");
  const used = t.last_used_at ? new Date(t.last_used_at).toLocaleString("de-CH") : "nie";
  const label = t.label || "(ohne Label)";
  line.append(el("span", `${label} · zuletzt genutzt: ${used}`, t.revoked ? "muted" : null));
  if (t.revoked) {
    line.append(el("span", "widerrufen", "muted"));
    return line;
  }
  const rev = plainButton("Widerrufen", "danger");
  rev.addEventListener("click", async () => {
    if (
      !confirm(
        `Token „${label}" widerrufen? Geräte mit diesem Token verlieren sofort den Zugriff – ` +
          `auch offene Konsolen-Sitzungen, die daraus entstanden sind.`
      )
    )
      return;
    try {
      await api(`/admin/tokens/${t.id}`, { method: "DELETE" });
      renderTokens(box, u);
    } catch (e) {
      box.append(el("p", e.message, "error"));
    }
  });
  line.append(rev);
  return line;
}

async function renderTokens(box, u) {
  box.replaceChildren(el("h3", `Tokens von ${u.name}`));
  try {
    const tokens = await api(`/admin/users/${u.id}/tokens`);
    const active = tokens.filter((t) => !t.revoked);
    const revoked = tokens.filter((t) => t.revoked);

    if (!active.length) box.append(el("p", "Keine aktiven Tokens.", "muted"));
    for (const t of active) box.append(tokenRow(box, u, t));

    // Widerrufene sind Archiv, kein Arbeitsmaterial: sie bleiben eingeklappt,
    // sonst ertrinkt das eine aktive Token in einer Liste alter Leichen.
    if (revoked.length) {
      const panel = el("div");
      const label = () => `${revoked.length} widerrufene anzeigen`;
      const toggle = plainButton(label());
      toggle.addEventListener("click", () => {
        if (panel.hasChildNodes()) {
          panel.replaceChildren();
          toggle.textContent = label();
        } else {
          for (const t of revoked) panel.append(tokenRow(box, u, t));
          toggle.textContent = "widerrufene ausblenden";
        }
      });
      box.append(actions(toggle), panel);
    }
    box.append(buildIssueTokenForm(box, u));
  } catch (e) {
    box.append(el("p", e.message, "error"));
  }
}

function buildIssueTokenForm(box, u) {
  const wrap = el("div");
  const label = el("input");
  label.type = "text";
  label.placeholder = "Label, z. B. android";

  const status = el("span", "", "muted");
  const issue = primaryButton("Neues Token");
  issue.addEventListener("click", async () => {
    try {
      const res = await write(`/admin/users/${u.id}/tokens`, "POST", {
        label: label.value.trim() || null,
      });
      label.value = "";
      // Klartext ist NUR JETZT sichtbar – prominent und kopierbar zeigen, statt ihn
      // in einer Statuszeile zu verstecken. Danach existiert nur noch der Hash.
      const secret = el("div", null, "card secret");
      secret.append(el("strong", "Token – nur jetzt sichtbar, jetzt kopieren"));
      const out = el("input");
      out.type = "text";
      out.readOnly = true;
      out.value = res.token;
      secret.append(row("Token", out));
      secret.append(
        el("p", "Sprichblitz speichert nur einen Hash. Verloren = neues Token ausstellen.", "muted")
      );
      // Reihenfolge zählt: renderTokens leert die Box (replaceChildren), der
      // Klartext muss also DANACH angehängt werden – sonst räumt das Re-Render ihn weg.
      await renderTokens(box, u);
      box.append(secret);
      out.focus();
      out.select();
    } catch (e) {
      status.textContent = e.message;
      status.className = "error";
    }
  });
  wrap.append(row("Label für das neue Token", label), actions(issue, status));
  return wrap;
}

const SECTIONS = {
  overview: renderOverview,
  keys: renderKeys,
  modes: renderModes,
  settings: renderSettings,
  stats: renderStats,
  admin: renderAdmin,
};

// --- Drift-Festigkeit ------------------------------------------------------
// index.html und app.js können auseinanderlaufen: alter Cache, halb gelandeter
// Deploy, ein Feature nur zur Hälfte da. Dann liefert getElementById/querySelector
// null, und ein direkter Property-Zugriff wirft. Deshalb hier durchgehend Guards:
// ein fehlendes Element kostet höchstens sein eigenes Detail – nie den ganzen
// Screen. Der Fall ist nicht theoretisch (altes index.html im Android-WebView),
// und ba27c4e musste denselben Drift schon serverseitig adressieren.
// Ein Test-Guard hält es fest.

function showSection(id) {
  for (const s of document.querySelectorAll("[data-section]")) {
    const active = s.dataset.section === id;
    s.hidden = !active;
    // Verlassene Section leeren – sonst bleibt z. B. der einmalig sichtbare
    // Token-Klartext im versteckten Admin-DOM liegen. Die Zielsektion wird
    // unten ohnehin frisch gerendert.
    if (!active) s.replaceChildren();
  }
  for (const b of document.querySelectorAll("[data-nav]")) {
    b.classList.toggle("active", b.dataset.nav === id);
  }
  // Drift in BEIDE Richtungen: eine Section ohne Render-Funktion (neues HTML,
  // altes JS) ist genauso möglich wie eine Render-Funktion ohne Section.
  const render = SECTIONS[id];
  const box = document.getElementById("section-" + id);
  if (render && box) render(box); // lazy: lädt erst beim Wechsel
}

async function init() {
  for (const b of document.querySelectorAll("[data-nav]")) {
    b.addEventListener("click", () => showSection(b.dataset.nav));
  }
  try {
    const me = await api("/me");
    const greeting = document.getElementById("greeting");
    if (greeting) greeting.textContent = `Angemeldet als ${me.name}`;
    // Verwaltungs-Tab nur bei admin_scope: Rolle allein genügt nicht, die Session
    // muss auch Admin-Scope tragen (siehe auth.has_admin_scope). Reine UX – das
    // Backend weist /admin/* unabhängig davon ab. Genau deshalb darf ein fehlender
    // Tab die Initialisierung nicht kippen: Kosmetik ist kein Grund für einen
    // toten Screen.
    const adminNav = document.querySelector('[data-nav="admin"]');
    if (adminNav) adminNav.hidden = !me.admin_scope;
    showSection("overview");
  } catch (e) {
    // Auch der Fehlerpfad selbst muss den Drift überleben – wirft ausgerechnet
    // der catch, sieht der Nutzer gar nichts mehr.
    const fatal = document.getElementById("fatal");
    if (fatal) {
      fatal.textContent = e.message;
      fatal.hidden = false;
    }
  }
}

init();
