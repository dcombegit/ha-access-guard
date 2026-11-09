/* Access Guard – admin panel "Zugriffe" */

const STRINGS = {
  de: {
    title: "Zugriffe",
    refresh: "Aktualisieren",
    settings: "Einschränkungen bearbeiten",
    tabLog: "Protokoll",
    tabDevices: "Geräte",
    tabUsers: "Benutzer",
    allUsers: "Alle Benutzer",
    allEvents: "Alle Ereignisse",
    logins: "Anmeldungen",
    failed: "Fehlversuche",
    sessions: "Sitzungen",
    denied: "Gesperrte Zugriffe",
    colTime: "Zeit",
    colUser: "Benutzer",
    colEvent: "Ereignis",
    colDevice: "Gerät",
    colIp: "IP",
    colDetails: "Dauer / Details",
    evLogin: "Anmeldung",
    evFailed: "Anmeldung fehlgeschlagen",
    evSession: "Sitzung",
    evDenied: "Gesperrt",
    active: "aktiv",
    unknownEnd: "Ende unbekannt",
    tried: "versucht als",
    times: "×",
    empty: "Keine Einträge für diese Auswahl.",
    clearLog: "Protokoll löschen",
    clearConfirm: "Das gesamte Protokoll unwiderruflich löschen?",
    noDevices: "Keine angemeldeten Geräte.",
    since: "angemeldet seit",
    lastUsed: "zuletzt aktiv",
    never: "nie",
    thisDevice: "dieses Gerät",
    rename: "Umbenennen",
    renamePrompt: "Name für dieses Gerät (leer = automatisch):",
    revoke: "Abmelden",
    revokeConfirm: "Dieses Gerät abmelden? Der Benutzer muss sich dort neu anmelden.",
    admin: "Administrator",
    owner: "Besitzer",
    inactive: "deaktiviert",
    localOnly: "nur lokal",
    noRestrictions: "Keine Einschränkungen",
    blockedAreas: "Gesperrt",
    blockedDashboards: "Gesperrte Dashboards",
    hiddenPanels: "Ausgeblendet",
    hiddenEntities: "Ausgeblendete Entitäten",
    adminHint: "Bei Administratoren greifen Einschränkungen nur teilweise.",
    logSettings: "Protokoll",
    on: "an",
    off: "aus",
    retention: "Aufbewahrung",
    days: "Tage",
    lastActivity: "Letzte Aktivität",
    error: "Fehler beim Laden",
    kinds: { app: "Companion-App", browser: "Browser", token: "API-Token", unknown: "Unbekannt" },
    dashboard: "Dashboard",
  },
  en: {
    title: "Access",
    refresh: "Refresh",
    settings: "Edit restrictions",
    tabLog: "Log",
    tabDevices: "Devices",
    tabUsers: "Users",
    allUsers: "All users",
    allEvents: "All events",
    logins: "Sign-ins",
    failed: "Failed sign-ins",
    sessions: "Sessions",
    denied: "Blocked access",
    colTime: "Time",
    colUser: "User",
    colEvent: "Event",
    colDevice: "Device",
    colIp: "IP",
    colDetails: "Duration / details",
    evLogin: "Sign-in",
    evFailed: "Sign-in failed",
    evSession: "Session",
    evDenied: "Blocked",
    active: "active",
    unknownEnd: "end unknown",
    tried: "tried as",
    times: "×",
    empty: "No entries for this selection.",
    clearLog: "Clear log",
    clearConfirm: "Permanently delete the whole log?",
    noDevices: "No signed-in devices.",
    since: "signed in since",
    lastUsed: "last active",
    never: "never",
    thisDevice: "this device",
    rename: "Rename",
    renamePrompt: "Name for this device (empty = automatic):",
    revoke: "Sign out",
    revokeConfirm: "Sign this device out? The user has to sign in again there.",
    admin: "Administrator",
    owner: "Owner",
    inactive: "deactivated",
    localOnly: "local only",
    noRestrictions: "No restrictions",
    blockedAreas: "Blocked",
    blockedDashboards: "Blocked dashboards",
    hiddenPanels: "Hidden",
    hiddenEntities: "Hidden entities",
    adminHint: "Restrictions only partly apply to administrators.",
    logSettings: "Log",
    on: "on",
    off: "off",
    retention: "Retention",
    days: "days",
    lastActivity: "Last activity",
    error: "Error while loading",
    kinds: { app: "Companion app", browser: "Browser", token: "API token", unknown: "Unknown" },
    dashboard: "Dashboard",
  },
};

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);

class AccessGuardPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._error = null;
    this._tab = "log";
    this._userFilter = "";
    this._typeFilter = "";
    this._loading = false;
    this._rendered = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.hass = hass;
    if (first) {
      this._render();
      this._load();
    }
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.narrow = narrow;
  }

  connectedCallback() {
    this._timer = window.setInterval(() => {
      if (document.visibilityState === "visible") this._load();
    }, 30000);
  }

  disconnectedCallback() {
    window.clearInterval(this._timer);
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").toLowerCase();
    return lang.startsWith("de") ? STRINGS.de : STRINGS.en;
  }

  get _lang() {
    return this._hass?.locale?.language || this._hass?.language || "en";
  }

  async _load() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    try {
      this._data = await this._hass.callWS({ type: "access_guard/overview", limit: 2000 });
      this._error = null;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._loading = false;
    this._render();
  }

  async _ws(message) {
    try {
      await this._hass.callWS(message);
    } catch (err) {
      window.alert(err?.message || String(err));
    }
    await this._load();
  }

  _fmtTime(iso) {
    if (!iso) return "–";
    const date = new Date(iso);
    return new Intl.DateTimeFormat(this._lang, {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(date);
  }

  _fmtRelative(iso) {
    if (!iso) return this._t.never;
    const diff = (new Date(iso).getTime() - Date.now()) / 1000;
    const rtf = new Intl.RelativeTimeFormat(this._lang, { numeric: "auto" });
    const abs = Math.abs(diff);
    if (abs < 60) return rtf.format(Math.round(diff), "second");
    if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    return rtf.format(Math.round(diff / 86400), "day");
  }

  _fmtDuration(startIso, endIso) {
    const end = endIso ? new Date(endIso) : new Date();
    const seconds = Math.max(0, (end - new Date(startIso)) / 1000);
    if (seconds < 60) return "< 1 min";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    return `${hours} h ${minutes % 60} min`;
  }

  _areaLabel(area) {
    if (!area) return "";
    if (area.startsWith("dashboard:")) {
      const path = area.slice(10);
      return `${this._t.dashboard} ${this._data?.panels?.[path] || path}`;
    }
    return this._data?.areas?.[area] || area;
  }

  _deviceName(entry) {
    const label = entry.token_id && this._data?.labels?.[entry.token_id];
    return label ? `${label} (${entry.device})` : entry.device;
  }

  _render() {
    const t = this._t;
    const root = this.shadowRoot;
    if (!this._rendered) {
      root.innerHTML = `<style>${STYLE}</style>
        <div class="toolbar">
          <ha-menu-button></ha-menu-button>
          <div class="title">${esc(t.title)}</div>
          <button class="flat" id="refresh" title="${esc(t.refresh)}">⟳ <span class="hide-narrow">${esc(t.refresh)}</span></button>
        </div>
        <div class="content" id="content"></div>`;
      const menu = root.querySelector("ha-menu-button");
      menu.hass = this._hass;
      menu.narrow = this._narrow;
      root.getElementById("refresh").addEventListener("click", () => this._load());
      root.getElementById("content").addEventListener("click", (ev) => this._onClick(ev));
      root.getElementById("content").addEventListener("change", (ev) => this._onChange(ev));
      this._rendered = true;
    }
    const content = root.getElementById("content");
    if (this._error) {
      content.innerHTML = `<div class="card error">${esc(t.error)}: ${esc(this._error)}</div>`;
      return;
    }
    if (!this._data) {
      content.innerHTML = `<div class="card muted">…</div>`;
      return;
    }
    const tabs = [
      ["log", t.tabLog],
      ["devices", t.tabDevices],
      ["users", t.tabUsers],
    ]
      .map(([key, label]) => `<button class="tab ${this._tab === key ? "active" : ""}" data-tab="${key}">${esc(label)}</button>`)
      .join("");
    let body = "";
    if (this._tab === "log") body = this._renderLog();
    if (this._tab === "devices") body = this._renderDevices();
    if (this._tab === "users") body = this._renderUsers();
    content.innerHTML = `<div class="tabs">${tabs}</div>${body}`;
  }

  _renderLog() {
    const t = this._t;
    const data = this._data;
    const userOptions = [`<option value="">${esc(t.allUsers)}</option>`]
      .concat(
        data.users.map(
          (u) => `<option value="${esc(u.id)}" ${this._userFilter === u.id ? "selected" : ""}>${esc(u.name)}</option>`
        )
      )
      .join("");
    const types = [
      ["", t.allEvents],
      ["login", t.logins],
      ["login_failed", t.failed],
      ["session", t.sessions],
      ["denied", t.denied],
    ]
      .map(([v, l]) => `<option value="${v}" ${this._typeFilter === v ? "selected" : ""}>${esc(l)}</option>`)
      .join("");

    const entries = data.entries.filter(
      (e) => (!this._userFilter || e.user_id === this._userFilter) && (!this._typeFilter || e.type === this._typeFilter)
    );

    const rows = entries
      .slice(0, 500)
      .map((e) => {
        let event = "";
        let details = "";
        let badge = "";
        if (e.type === "login") {
          badge = "ok";
          event = t.evLogin;
        } else if (e.type === "login_failed") {
          badge = "bad";
          event = t.evFailed;
          details = e.username ? `${t.tried} „${e.username}“` : "";
        } else if (e.type === "session") {
          badge = "neutral";
          event = t.evSession;
          details = e.open
            ? `${this._fmtDuration(e.time, null)} · ${t.active}`
            : e.end_unknown
              ? t.unknownEnd
              : this._fmtDuration(e.time, e.end);
        } else if (e.type === "denied") {
          badge = "warn";
          event = `${t.evDenied}: ${this._areaLabel(e.area)}`;
          details = `${e.count}${t.times}${e.count > 1 ? ` · ${t.lastActivity} ${this._fmtTime(e.last)}` : ""}`;
        }
        const user = e.user || e.username || "–";
        const title = [e.ua, ...(e.details || [])].filter(Boolean).join("\n");
        return `<tr>
          <td class="c-time nowrap">${esc(this._fmtTime(e.time))}</td>
          <td class="c-user">${esc(user)}</td>
          <td class="c-event"><span class="badge ${badge}">${esc(event)}</span>${e.open ? ' <span class="dot" title="online"></span>' : ""}</td>
          <td class="c-device" title="${esc(title)}">${esc(this._deviceName(e))}</td>
          <td class="c-ip nowrap mono">${esc(e.ip || "–")}</td>
          <td class="c-details muted">${esc(details)}</td>
        </tr>`;
      })
      .join("");

    const s = data.settings;
    const settingsLine = `${esc(t.logSettings)}: ${esc(t.logins)} ${s.log_logins ? t.on : t.off} · ${esc(t.sessions)} ${
      s.log_sessions ? t.on : t.off
    } · ${esc(t.denied)} ${s.log_denied ? t.on : t.off} · ${esc(t.retention)} ${esc(s.retention_days)} ${esc(t.days)}`;

    return `<div class="filters">
        <select data-filter="user">${userOptions}</select>
        <select data-filter="type">${types}</select>
      </div>
      <div class="card table-wrap">
        ${
          rows
            ? `<table><thead><tr>
                <th>${esc(t.colTime)}</th><th>${esc(t.colUser)}</th><th>${esc(t.colEvent)}</th>
                <th>${esc(t.colDevice)}</th><th>${esc(t.colIp)}</th><th>${esc(t.colDetails)}</th>
              </tr></thead><tbody>${rows}</tbody></table>`
            : `<div class="muted pad">${esc(t.empty)}</div>`
        }
      </div>
      <div class="footer">
        <span class="muted">${settingsLine}</span>
        <span class="spacer"></span>
        <a href="/config/integrations/integration/access_guard">${esc(t.settings)}</a>
        <button class="flat danger" data-action="clear">${esc(t.clearLog)}</button>
      </div>`;
  }

  _renderDevices() {
    const t = this._t;
    const cards = this._data.users
      .map((u) => {
        const tokens = u.tokens
          .map((tok) => {
            const name = tok.label ? `${tok.label}` : tok.device;
            const kind = t.kinds[tok.kind] || tok.kind;
            const base = tok.label ? tok.device : "";
            const sub = [base, tok.device.startsWith(kind) || base.startsWith(kind) ? "" : kind].filter(Boolean).join(" · ");
            return `<div class="device">
              <div class="device-main">
                <div class="device-name">${esc(name)}${tok.current ? ` <span class="badge neutral">${esc(t.thisDevice)}</span>` : ""}</div>
                <div class="muted small">${esc(sub)}</div>
                <div class="muted small">${esc(t.since)} ${esc(this._fmtTime(tok.created_at))} · ${esc(t.lastUsed)} ${esc(
                  this._fmtRelative(tok.last_used_at)
                )}${tok.last_used_ip ? ` · <span class="mono">${esc(tok.last_used_ip)}</span>` : ""}</div>
              </div>
              <div class="device-actions">
                <button class="flat" data-action="rename" data-token="${esc(tok.id)}" data-label="${esc(tok.label || "")}">${esc(t.rename)}</button>
                <button class="flat danger" data-action="revoke" data-token="${esc(tok.id)}">${esc(t.revoke)}</button>
              </div>
            </div>`;
          })
          .join("");
        return `<div class="card">
          <div class="card-head"><span class="user-name">${esc(u.name)}</span>${this._roleBadges(u)}</div>
          ${tokens || `<div class="muted pad">${esc(t.noDevices)}</div>`}
        </div>`;
      })
      .join("");
    return cards;
  }

  _roleBadges(u) {
    const t = this._t;
    const badges = [];
    if (u.is_owner) badges.push(t.owner);
    else if (u.is_admin) badges.push(t.admin);
    if (!u.is_active) badges.push(t.inactive);
    if (u.local_only) badges.push(t.localOnly);
    return badges.map((b) => ` <span class="badge neutral">${esc(b)}</span>`).join("");
  }

  _renderUsers() {
    const t = this._t;
    const cards = this._data.users
      .map((u) => {
        const r = u.restrictions;
        const chips = (items, cls, fmt = (x) => x) =>
          items.map((x) => `<span class="chip ${cls}">${esc(fmt(x))}</span>`).join("");
        const groups = [];
        if (r.areas.length) groups.push(`<div><span class="label">${esc(t.blockedAreas)}</span>${chips(r.areas, "bad", (a) => this._areaLabel(a))}</div>`);
        const panelName = (p) => this._data.panels?.[p] || p;
        if (r.dashboards.length) groups.push(`<div><span class="label">${esc(t.blockedDashboards)}</span>${chips(r.dashboards, "bad", panelName)}</div>`);
        if (r.panels.length) groups.push(`<div><span class="label">${esc(t.hiddenPanels)}</span>${chips(r.panels, "neutral", panelName)}</div>`);
        if (r.entities.length) groups.push(`<div><span class="label">${esc(t.hiddenEntities)}</span>${chips(r.entities, "neutral")}</div>`);
        const lastSession = this._data.entries.find((e) => e.user_id === u.id && e.type === "session");
        const hint = groups.length && u.is_admin ? `<div class="warn-text small">${esc(t.adminHint)}</div>` : "";
        return `<div class="card">
          <div class="card-head"><span class="user-name">${esc(u.name)}</span>${this._roleBadges(u)}
            <span class="spacer"></span>
            <span class="muted small">${esc(t.lastActivity)}: ${esc(lastSession ? this._fmtRelative(lastSession.end || lastSession.time) : t.never)}</span>
          </div>
          <div class="pad restrictions">${groups.join("") || `<span class="muted">${esc(t.noRestrictions)}</span>`}${hint}</div>
        </div>`;
      })
      .join("");
    return `${cards}<div class="footer"><span class="spacer"></span><a href="/config/integrations/integration/access_guard">${esc(t.settings)}</a></div>`;
  }

  _onChange(ev) {
    const filter = ev.target?.dataset?.filter;
    if (filter === "user") this._userFilter = ev.target.value;
    if (filter === "type") this._typeFilter = ev.target.value;
    if (filter) this._render();
  }

  _onClick(ev) {
    const target = ev.target.closest("button, a");
    if (!target) return;
    if (target.dataset.tab) {
      this._tab = target.dataset.tab;
      this._render();
      return;
    }
    const t = this._t;
    const action = target.dataset.action;
    if (action === "revoke") {
      if (window.confirm(t.revokeConfirm)) this._ws({ type: "access_guard/revoke_token", token_id: target.dataset.token });
    } else if (action === "rename") {
      const label = window.prompt(t.renamePrompt, target.dataset.label || "");
      if (label !== null) this._ws({ type: "access_guard/set_label", token_id: target.dataset.token, label: label.trim() || null });
    } else if (action === "clear") {
      if (window.confirm(t.clearConfirm)) this._ws({ type: "access_guard/clear_log" });
    } else if (target.tagName === "A" && target.getAttribute("href")?.startsWith("/")) {
      ev.preventDefault();
      history.pushState(null, "", target.getAttribute("href"));
      window.dispatchEvent(new CustomEvent("location-changed"));
    }
  }
}

const STYLE = `
  :host {
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    font-size: 14px;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 4px;
    height: var(--header-height, 56px);
    padding: 0 12px 0 4px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, #fff);
    border-bottom: var(--app-header-border-bottom, none);
    box-sizing: border-box;
  }
  .toolbar .title { flex: 1; font-size: 20px; margin-left: 12px; }
  .toolbar .flat { color: inherit; }
  .content { padding: 16px; max-width: 1200px; margin: 0 auto; box-sizing: border-box; }
  .tabs { display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid var(--divider-color); overflow-x: auto; }
  .tab {
    background: none; border: none; color: var(--secondary-text-color); padding: 10px 14px; cursor: pointer;
    font: inherit; font-weight: 500; border-bottom: 2px solid transparent; white-space: nowrap;
  }
  .tab.active { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .card {
    background: var(--card-background-color, var(--ha-card-background, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    border: 1px solid var(--divider-color);
    margin-bottom: 12px;
    overflow: hidden;
  }
  .card-head { display: flex; align-items: center; gap: 6px; padding: 12px 16px; border-bottom: 1px solid var(--divider-color); flex-wrap: wrap; }
  .user-name { font-weight: 500; font-size: 15px; }
  .pad { padding: 12px 16px; }
  .error { padding: 16px; color: var(--error-color); }
  .muted { color: var(--secondary-text-color); }
  .small { font-size: 12px; }
  .mono { font-family: var(--code-font-family, monospace); font-size: 12px; }
  .nowrap { white-space: nowrap; }
  .spacer { flex: 1; }
  .filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  select {
    font: inherit; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--divider-color);
    background: var(--card-background-color, #fff); color: var(--primary-text-color); min-width: 180px; max-width: 100%;
  }
  .table-wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--divider-color); vertical-align: top; }
  th { font-weight: 500; color: var(--secondary-text-color); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  tbody tr:last-child td { border-bottom: none; }
  .badge, .chip { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; line-height: 18px; }
  .badge.ok, .chip.ok { background: rgba(var(--rgb-success-color, 67,160,71), .15); color: var(--success-color, #43a047); }
  .badge.bad, .chip.bad { background: rgba(var(--rgb-error-color, 219,68,55), .15); color: var(--error-color, #db4437); }
  .badge.warn { background: rgba(var(--rgb-warning-color, 255,166,0), .18); color: var(--warning-color, #ffa600); }
  .badge.neutral, .chip.neutral { background: rgba(var(--rgb-primary-text-color, 33,33,33), .08); color: var(--secondary-text-color); }
  .chip { margin: 2px 4px 2px 0; }
  .label { display: inline-block; min-width: 150px; color: var(--secondary-text-color); font-size: 12px; }
  .restrictions > div { margin-bottom: 6px; }
  .warn-text { color: var(--warning-color, #ffa600); margin-top: 6px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--success-color, #43a047); vertical-align: middle; }
  .device { display: flex; gap: 12px; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--divider-color); flex-wrap: wrap; }
  .device:last-child { border-bottom: none; }
  .device-main { flex: 1; min-width: 220px; }
  .device-name { font-weight: 500; margin-bottom: 2px; }
  .device-actions { display: flex; gap: 4px; }
  button.flat {
    background: none; border: none; color: var(--primary-color); font: inherit; font-weight: 500;
    padding: 8px 10px; border-radius: 8px; cursor: pointer;
  }
  button.flat:hover { background: rgba(var(--rgb-primary-color, 3,169,244), .1); }
  button.flat.danger { color: var(--error-color, #db4437); }
  .footer { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 4px 0 24px; }
  .footer a { color: var(--primary-color); text-decoration: none; font-weight: 500; }
  @media (max-width: 600px) {
    .content { padding: 12px 16px; }
    .hide-narrow { display: none; }
    .label { display: block; min-width: 0; margin-bottom: 2px; }
    select { flex: 1; min-width: 0; }
    .table-wrap { overflow: visible; }
    table, tbody, tr, td { display: block; }
    thead { display: none; }
    tr {
      display: grid; grid-template-columns: 1fr auto; gap: 4px 8px; padding: 10px 14px;
      border-bottom: 1px solid var(--divider-color);
    }
    tbody tr:last-child { border-bottom: none; }
    td { border: none; padding: 0; }
    .c-user { grid-column: 1; grid-row: 1; font-weight: 500; }
    .c-time { grid-column: 2; grid-row: 1; font-size: 12px; color: var(--secondary-text-color); }
    .c-event, .c-device, .c-details { grid-column: 1 / -1; }
    .c-ip { grid-column: 1 / -1; color: var(--secondary-text-color); }
    .c-device, .c-details { font-size: 12px; color: var(--secondary-text-color); }
    .c-details:empty { display: none; }
  }
`;

customElements.define("access-guard-panel", AccessGuardPanel);
