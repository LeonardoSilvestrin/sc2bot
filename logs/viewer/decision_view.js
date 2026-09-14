// Decision Timeline view: horizontal tracks grouped by layer and synchronized
// on one selected time, an inspector of every layer at that time, and the
// nearest SVG field snapshot. Builds DOM only through createElement/textContent.
(function (root) {
  "use strict";

  const T = root.SC2Timeline;
  const D = root.SC2Diagnostics;
  const S = root.SC2Snapshots;
  const SVG_NS = "http://www.w3.org/2000/svg";

  const RULER_H = 26;
  const GROUP_H = 18;
  const STATE_H = 20;
  const SERIES_H = 34;
  const LANE_H = 13;
  const PAD = 8;
  const EVENT_WINDOW = 6;
  const EVENT_LIMIT = 40;

  // Periodic summaries, not decisions: kept out of "events around t".
  const NOISY_EVENTS = new Set([
    "attention.observed", "awareness.updated", "behavior.proposed", "engine.granted",
    "logs.frame_perf", "logs.snapshot_written",
  ]);

  const TONES = {
    bad: new Set(["STABILIZE", "emergency_threat", "base_under_threat", "base_under_pressure", "air_attack_on_base", "stabilize_spend_on_army"]),
    warn: new Set(["ATTACK", "opening_runs"]),
    ok: new Set(["BUILD_ADVANTAGE", "HOLD", "no_immediate_threat", "mineral_lines_saturated", "build_economy"]),
  };

  function tone(value) {
    const head = String(value ?? "").split(" ")[0];
    for (const [name, values] of Object.entries(TONES)) if (values.has(head)) return name;
    if (head.startsWith("hold_rally")) return "ok";
    return "neutral";
  }

  const view = {
    model: null,
    diagnostics: [],
    transitions: [],
    snapshots: [],
    files: [],
    urls: new Map(),
    selectedTime: 0,
    zoom: 1,
    refs: {},
    rows: [],
    requestSvgFiles: null,
  };

  // --- small DOM helpers ------------------------------------------------------

  function fmtTime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value)) return "--:--";
    const clamped = Math.max(0, value);
    const minutes = Math.floor(clamped / 60);
    const rest = (clamped - minutes * 60).toFixed(1).padStart(4, "0");
    return `${String(minutes).padStart(2, "0")}:${rest}`;
  }

  function fmtDelta(seconds) {
    const sign = seconds < 0 ? "−" : "+";
    return `${sign}${Math.abs(seconds).toFixed(1)}s`;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function add(parent, tag, className, text) {
    return parent.appendChild(el(tag, className, text));
  }

  function svg(tag, attrs = {}, className) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (className) node.setAttribute("class", className);
    return node;
  }

  function withTitle(node, text) {
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = text;
    node.appendChild(title);
    return node;
  }

  function button(parent, label, onClick, title) {
    const node = add(parent, "button", "dt-button", label);
    node.type = "button";
    if (title) node.title = title;
    node.addEventListener("click", onClick);
    return node;
  }

  function na(value, digits) {
    return T.formatValue(value, digits);
  }

  function xy(point) {
    return Array.isArray(point) ? `(${na(Number(point[0]), 1)}, ${na(Number(point[1]), 1)})` : "N/A";
  }

  // --- lifecycle ---------------------------------------------------------------

  function revokeUrls() {
    for (const url of view.urls.values()) URL.revokeObjectURL(url);
    view.urls.clear();
  }

  function load(records, files = []) {
    revokeUrls();
    view.model = T.buildDecisionTimeline(records);
    view.diagnostics = D.runDiagnostics(view.model);
    view.transitions = T.transitions(view.model);
    view.files = [...files];
    view.snapshots = S.buildSnapshotIndex(view.model.records, view.files);
    view.zoom = 1;
    const firstWarning = view.diagnostics.find((item) => item.severity === "warning");
    view.selectedTime = firstWarning ? firstWarning.start : view.model.startTime;
  }

  function attachSnapshotFiles(files) {
    if (!view.model) return;
    const known = new Set(view.files.map((file) => file.name));
    for (const file of files) if (!known.has(file.name)) view.files.push(file);
    view.snapshots = S.buildSnapshotIndex(view.model.records, view.files);
  }

  function focus(time) {
    if (!view.model) return;
    view.selectedTime = clampTime(time);
  }

  function clampTime(time) {
    const model = view.model;
    return Math.min(model.endTime, Math.max(model.startTime, Number(time) || 0));
  }

  // --- layout ------------------------------------------------------------------

  function rowsFor(model) {
    const rows = [{ type: "ruler", label: "time", h: RULER_H }];
    const group = (label) => rows.push({ type: "group", label, h: GROUP_H });
    const track = (key, extra = {}) => {
      const item = model.byKey.get(key);
      if (!T.hasData(item)) return;
      const overlay = extra.overlay ? model.byKey.get(extra.overlay) : undefined;
      rows.push({
        type: item.kind,
        track: item,
        overlay: T.hasData(overlay) ? overlay : undefined,
        label: extra.label || item.label,
        h: item.kind === "series" ? SERIES_H : STATE_H,
      });
    };
    const intervalRows = (tracks) => {
      for (const item of tracks) rows.push({ type: "intervals", track: item, label: item.label, h: item.lanes * LANE_H + 6 });
    };

    group("Diagnostics");
    rows.push({ type: "diagnostics", label: view.diagnostics.length ? "hints" : "none detected", h: Math.max(1, ...view.diagnostics.map((item) => item.lane + 1)) * LANE_H + 6 });

    group("Strategy");
    if (!model.strategy.available) rows.push({ type: "na", label: "Objective", text: "N/A — no strategy.decided events", h: STATE_H });
    track("strategy.objective");
    track("strategy.defense");
    track("strategy.army");
    track("strategy.risk");

    group("Awareness");
    track("awareness.danger");
    track("awareness.own_power", { overlay: "awareness.enemy_power", label: "Power own / enemy" });
    track("awareness.contacts");

    group("Behaviors · proposals");
    intervalRows(model.proposalTracks);
    track("behaviors.economy");

    group("Engine · commands");
    intervalRows(model.commandTracks);
    track("engine.units.core_army", { overlay: "engine.units.defense", label: "Units core / defense" });
    track("engine.unassigned");

    group("Attention");
    track("attention.supply");
    track("attention.minerals");
    track("attention.visible_enemies");

    group("Logs");
    track("logs.frame_ms");
    return rows;
  }

  // --- render --------------------------------------------------------------------

  function render(mainEl, sideEl) {
    const model = view.model;
    mainEl.replaceChildren();
    mainEl.className = "decision-view";
    if (!model || !model.records.length) {
      add(mainEl, "div", "notice", "No records in this log.");
      sideEl.replaceChildren();
      return;
    }
    view.refs = {};
    renderToolbar(mainEl);

    const tracks = add(mainEl, "section", "dt-tracks");
    const labels = add(tracks, "div", "dt-labels");
    const scroll = add(tracks, "div", "dt-plot");
    view.refs.scroll = scroll;
    view.rows = rowsFor(model);
    for (const row of view.rows) {
      const label = add(labels, "div", `dt-label dt-label-${row.type}`, row.label);
      label.style.height = `${row.h}px`;
      if (row.type === "series") {
        const range = seriesRange(row.track, row.overlay);
        add(label, "span", "dt-range", `${na(range.min, row.track.format)}..${na(range.max, row.track.format)}`);
      }
    }
    drawTracks();

    const bottom = add(mainEl, "section", "dt-bottom");
    view.refs.inspector = add(bottom, "div", "dt-inspector");
    view.refs.snapshot = add(bottom, "div", "dt-snapshot");
    buildSnapshotPanel(view.refs.snapshot);

    renderSide(sideEl);
    select(view.selectedTime);
  }

  function renderToolbar(parent) {
    const bar = add(parent, "div", "dt-toolbar");
    add(bar, "span", "dt-toolbar-label", "selected");
    view.refs.timeLabel = add(bar, "span", "dt-time", fmtTime(view.selectedTime));
    const nav = add(bar, "span", "dt-group");
    button(nav, "−10s", () => select(view.selectedTime - 10), "Shift+←");
    button(nav, "−1s", () => select(view.selectedTime - 1), "←");
    button(nav, "+1s", () => select(view.selectedTime + 1), "→");
    button(nav, "+10s", () => select(view.selectedTime + 10), "Shift+→");
    const changes = add(bar, "span", "dt-group");
    button(changes, "◀ change", () => stepTransition(-1), "previous decision change (,)");
    button(changes, "change ▶", () => stepTransition(1), "next decision change (.)");
    const diagnostics = add(bar, "span", "dt-group");
    button(diagnostics, "◀ ⚠", () => stepDiagnostic(-1), "previous hint");
    button(diagnostics, "⚠ ▶", () => stepDiagnostic(1), "next hint");
    const zoom = add(bar, "span", "dt-group");
    for (const factor of [1, 2, 4, 8]) {
      const node = button(zoom, `${factor}×`, () => {
        view.zoom = factor;
        for (const sibling of zoom.children) sibling.classList.toggle("active", sibling === node);
        const center = view.selectedTime;
        drawTracks();
        scrollToTime(center);
      }, "zoom");
      node.classList.toggle("active", factor === view.zoom);
    }
    add(bar, "span", `dt-badge${view.snapshots.length ? " live" : ""}`, `${view.snapshots.length} SVG snapshot${view.snapshots.length === 1 ? "" : "s"}`);
  }

  function plotWidth() {
    const available = view.refs.scroll?.clientWidth || 900;
    return Math.max(480, available - 2) * view.zoom;
  }

  function xOf(time, width) {
    const model = view.model;
    const span = Math.max(1, model.endTime - model.startTime);
    return PAD + ((time - model.startTime) / span) * (width - 2 * PAD);
  }

  function timeOf(x, width) {
    const model = view.model;
    const span = Math.max(1, model.endTime - model.startTime);
    return clampTime(model.startTime + ((x - PAD) / (width - 2 * PAD)) * span);
  }

  function drawTracks() {
    const scroll = view.refs.scroll;
    if (!scroll) return;
    const width = plotWidth();
    const height = view.rows.reduce((total, row) => total + row.h, 0);
    const plot = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}` }, "dt-svg");
    let y = 0;
    for (const row of view.rows) {
      const g = svg("g", { transform: `translate(0 ${y})` }, `dt-row dt-row-${row.type}`);
      if (row.type !== "group") g.appendChild(svg("line", { x1: 0, x2: width, y1: row.h - 0.5, y2: row.h - 0.5 }, "dt-rowline"));
      if (row.type === "ruler") drawRuler(g, width, row.h);
      else if (row.type === "group") g.appendChild(svg("rect", { x: 0, y: 0, width, height: row.h }, "dt-group-bg"));
      else if (row.type === "state") drawState(g, row, width);
      else if (row.type === "series") drawSeries(g, row, width);
      else if (row.type === "intervals") drawIntervals(g, row, width);
      else if (row.type === "diagnostics") drawDiagnostics(g, width);
      else if (row.type === "na") {
        const text = svg("text", { x: PAD, y: row.h - 6 }, "dt-na");
        text.textContent = row.text;
        g.appendChild(text);
      }
      plot.appendChild(g);
      y += row.h;
    }
    const cursor = svg("line", { x1: 0, x2: 0, y1: 0, y2: height }, "dt-cursor");
    plot.appendChild(cursor);
    plot.addEventListener("click", (event) => {
      const rect = plot.getBoundingClientRect();
      select(timeOf(event.clientX - rect.left, width));
    });
    view.refs.cursor = cursor;
    view.refs.width = width;
    scroll.replaceChildren(plot);
    moveCursor();
  }

  function drawRuler(g, width, height) {
    const model = view.model;
    const span = Math.max(1, model.endTime - model.startTime);
    const pxPerSecond = (width - 2 * PAD) / span;
    const step = [5, 10, 15, 30, 60, 120, 300, 600].find((candidate) => candidate * pxPerSecond >= 56) ?? 600;
    for (let time = Math.ceil(model.startTime / step) * step; time <= model.endTime; time += step) {
      const x = xOf(time, width);
      g.appendChild(svg("line", { x1: x, x2: x, y1: height - 8, y2: height }, "dt-tick"));
      const label = svg("text", { x: x + 2, y: 11 }, "dt-tick-label");
      label.textContent = fmtTime(time).slice(0, 5);
      g.appendChild(label);
    }
    for (const snapshot of view.snapshots) {
      const x = xOf(snapshot.t, width);
      const mark = svg("path", { d: `M ${x - 4} ${height - 1} L ${x + 4} ${height - 1} L ${x} ${height - 8} Z` },
        `dt-snap-mark${snapshot.file ? " loaded" : ""}`);
      withTitle(mark, `SVG ${snapshot.name} @ ${fmtTime(snapshot.t)}${snapshot.trigger ? ` (${snapshot.trigger})` : ""}${snapshot.file ? "" : " — file not loaded"}`);
      mark.addEventListener("click", (event) => {
        event.stopPropagation();
        select(snapshot.t);
      });
      g.appendChild(mark);
    }
  }

  function drawSegment(g, { start, end, top, height, value, className, title, label }, width) {
    const x1 = xOf(start, width);
    const x2 = Math.max(x1 + 1, xOf(end, width));
    const rect = svg("rect", { x: x1, y: top, width: x2 - x1, height }, className);
    withTitle(rect, title);
    g.appendChild(rect);
    const text = label ?? value;
    const fits = Math.floor((x2 - x1 - 6) / 6.2);
    if (text && fits >= 3) {
      const node = svg("text", { x: x1 + 3, y: top + height - 3.5 }, "dt-seg-label");
      node.textContent = text.length <= fits ? text : `${text.slice(0, fits - 1)}…`;
      g.appendChild(node);
    }
  }

  function drawState(g, row, width) {
    for (const segment of T.segments(row.track, view.model.endTime)) {
      const reason = segment.point.record?.data?.reason;
      drawSegment(g, {
        start: segment.start,
        end: segment.end,
        top: 3,
        height: row.h - 6,
        value: segment.value,
        className: `dt-seg tone-${tone(segment.value)}`,
        title: `${row.label}: ${segment.value}\n${fmtTime(segment.start)} – ${fmtTime(segment.end)}${reason ? `\nreason: ${reason}` : ""}`,
      }, width);
    }
  }

  function seriesRange(track, overlay) {
    const values = [...track.points, ...(overlay?.points ?? [])].map((point) => point.v);
    let min = track.min ?? Math.min(...values);
    let max = track.max ?? Math.max(...values);
    if (values.length) {
      min = Math.min(min, ...values);
      max = Math.max(max, ...values);
    }
    if (!(max > min)) max = min + 1;
    return { min, max };
  }

  function stepPath(points, width, height, range) {
    const yOf = (value) => 3 + (1 - (value - range.min) / (range.max - range.min)) * (height - 6);
    let d = "";
    points.forEach((point, index) => {
      const x = xOf(point.t, width).toFixed(1);
      const y = yOf(point.v).toFixed(1);
      d += index === 0 ? `M ${x} ${y}` : ` H ${x} V ${y}`;
    });
    if (points.length) d += ` H ${xOf(view.model.endTime, width).toFixed(1)}`;
    return { d, yOf };
  }

  function drawSeries(g, row, width) {
    const range = seriesRange(row.track, row.overlay);
    const main = stepPath(row.track.points, width, row.h, range);
    if (row.overlay) {
      g.appendChild(withTitle(svg("path", { d: stepPath(row.overlay.points, width, row.h, range).d }, "dt-series overlay"), row.overlay.label));
    }
    g.appendChild(withTitle(svg("path", { d: main.d }, "dt-series"), row.track.label));
  }

  function drawIntervals(g, row, width) {
    const endTime = view.model.endTime;
    for (const item of row.track.items) {
      const end = item.end ?? endTime;
      const top = 3 + item.lane * LANE_H;
      item.statuses.forEach((status, index) => {
        const start = Math.max(item.start, status.t);
        const segmentEnd = index + 1 < item.statuses.length ? Math.max(start, item.statuses[index + 1].t) : end;
        drawSegment(g, {
          start,
          end: Math.max(segmentEnd, start + 0.01),
          top,
          height: LANE_H - 2,
          label: `${item.id} · ${status.value}`,
          className: `dt-seg tone-${tone(status.value)}`,
          title: `${item.id}\n${status.value} ${fmtTime(start)} – ${fmtTime(segmentEnd)}${status.reason ? `\nreason: ${status.reason}` : ""}`,
        }, width);
      });
    }
  }

  function drawDiagnostics(g, width) {
    for (const item of view.diagnostics) {
      drawSegment(g, {
        start: item.start,
        end: item.end,
        top: 3 + (item.lane ?? 0) * LANE_H,
        height: LANE_H - 2,
        label: `⚠ ${item.title}`,
        className: `dt-diag sev-${item.severity}`,
        title: `⚠ ${item.title}\n${fmtTime(item.start)} – ${fmtTime(item.end)}\n${item.evidence.join("\n")}`,
      }, width);
    }
  }

  function moveCursor() {
    const { cursor, width } = view.refs;
    if (!cursor) return;
    const x = xOf(view.selectedTime, width);
    cursor.setAttribute("x1", x);
    cursor.setAttribute("x2", x);
  }

  function scrollToTime(time) {
    const scroll = view.refs.scroll;
    if (!scroll || view.zoom === 1) return;
    const x = xOf(time, view.refs.width);
    if (x < scroll.scrollLeft + 40 || x > scroll.scrollLeft + scroll.clientWidth - 40) {
      scroll.scrollLeft = Math.max(0, x - scroll.clientWidth / 2);
    }
  }

  // --- selection -------------------------------------------------------------------

  function select(time) {
    if (!view.model) return;
    view.selectedTime = clampTime(time);
    if (view.refs.timeLabel) view.refs.timeLabel.textContent = fmtTime(view.selectedTime);
    moveCursor();
    scrollToTime(view.selectedTime);
    renderInspector();
    renderSnapshot();
  }

  function stepTransition(direction) {
    const time = view.selectedTime;
    const list = view.transitions;
    const target = direction > 0
      ? list.find((item) => item.t > time + 1e-6)
      : [...list].reverse().find((item) => item.t < time - 1e-6);
    if (target) select(target.t);
  }

  function stepDiagnostic(direction) {
    const time = view.selectedTime;
    const list = view.diagnostics;
    const target = direction > 0
      ? list.find((item) => item.start > time + 1e-6)
      : [...list].reverse().find((item) => item.start < time - 1e-6);
    if (target) select(target.start);
  }

  function stepSnapshot(direction) {
    const index = S.nearestIndex(view.snapshots, view.selectedTime);
    if (index < 0) return;
    const current = view.snapshots[index];
    let next = S.stepIndex(view.snapshots, index, direction);
    if (Math.abs(current.t - view.selectedTime) > 1e-6 && Math.sign(current.t - view.selectedTime) === direction) next = index;
    select(view.snapshots[next].t);
  }

  function handleKey(event) {
    if (!view.model) return false;
    const tag = event.target?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return false;
    const step = event.shiftKey ? 10 : 1;
    const actions = {
      ArrowLeft: () => select(view.selectedTime - step),
      ArrowRight: () => select(view.selectedTime + step),
      ",": () => stepTransition(-1),
      ".": () => stepTransition(1),
      "[": () => stepSnapshot(-1),
      "]": () => stepSnapshot(1),
    };
    const action = actions[event.key];
    if (!action) return false;
    event.preventDefault();
    action();
    return true;
  }

  // --- inspector ---------------------------------------------------------------------

  function section(parent, title) {
    const node = add(parent, "div", "dt-section");
    add(node, "div", "dt-section-title", title);
    return node;
  }

  function kv(parent, key, value, className = "") {
    const row = add(parent, "div", `dt-kv ${className}`.trim());
    add(row, "span", "dt-k", key);
    const text = value === undefined || value === null || value === "" ? "N/A" : String(value);
    add(row, "span", `dt-v tone-text-${tone(text)}${text === "N/A" ? " dt-missing" : ""}`, text);
    return row;
  }

  function renderInspector() {
    const container = view.refs.inspector;
    if (!container) return;
    const model = view.model;
    const time = view.selectedTime;
    const state = T.snapshotAt(model, time);
    container.replaceChildren();
    add(container, "div", "dt-inspector-title", `Every layer at ${fmtTime(time)}`);
    const grid = add(container, "div", "dt-inspector-grid");

    const strategy = section(grid, "Strategy");
    if (!state.strategy) {
      kv(strategy, "objective", "N/A");
    } else {
      const s = state.strategy;
      kv(strategy, "objective", s.objective);
      kv(strategy, "since", `${fmtTime(s.since)} (${fmtDelta(s.since - time)})`);
      kv(strategy, "reason", s.reason);
      kv(strategy, "defense / army / risk", `${na(s.defense)} / ${na(s.army)} / ${na(s.risk)}`);
      for (const [name, value] of Object.entries(s.inputs ?? {})) kv(strategy, name, na(Number(value), 2), "dt-sub");
      for (const [name, value] of Object.entries(s.scores ?? {})) kv(strategy, `score ${name}`, na(Number(value), 2), "dt-sub");
    }

    const awareness = section(grid, "Awareness");
    kv(awareness, "danger", na(state.danger, 2));
    kv(awareness, "power own / enemy", `${na(state.ownPower, 1)} / ${na(state.enemyPower, 1)}`);
    kv(awareness, "contacts", na(state.contacts, 0));
    for (const base of state.awarenessRecord?.data?.bases ?? []) {
      kv(awareness, `${base.is_main ? "main" : "base"} ${base.base_id}`, `thr ${na(base.threat)} p ${na(base.pressure, 1)} c ${na(base.cover, 1)}`, "dt-sub");
    }

    const behaviors = section(grid, `Behaviors · proposals (${state.proposals.length})`);
    if (!state.proposals.length) add(behaviors, "div", "dt-hint", "none");
    for (const { item, status } of state.proposals) {
      const proposal = (status?.record?.data?.proposals ?? []).find((entry) => entry.proposal_id === item.id);
      kv(behaviors, item.id, proposal ? `p ${na(proposal.priority)} · ${proposal.count ?? "all"} · ${proposal.command}` : status?.value);
      if (proposal?.reason) add(behaviors, "div", "dt-hint", `reason: ${proposal.reason}`);
    }
    if (state.economy) kv(behaviors, "economy", state.economy.value);

    const engine = section(grid, `Engine · commands (${state.commands.length})`);
    if (!state.commands.length) add(engine, "div", "dt-hint", "none");
    for (const { item, status } of state.commands) {
      const data = status?.record?.data ?? {};
      kv(engine, item.id, `${status?.value ?? "?"} → ${xy(data.target)}`);
      if (data.types) add(engine, "div", "dt-hint", Object.entries(data.types).map(([type, count]) => `${count}×${type}`).join(", "));
    }
    kv(engine, "units core / defense", `${na(state.coreUnits, 0)} / ${na(state.defenseUnits, 0)}`);
    kv(engine, "unassigned", na(state.unassigned, 0));

    const attention = section(grid, "Attention");
    const observed = state.attentionRecord?.data ?? {};
    kv(attention, "supply / minerals", `${na(state.supply, 0)} / ${na(state.minerals, 0)}`);
    kv(attention, "workers / army", `${na(observed.workers, 0)} / ${na(observed.army_units, 0)}`);
    kv(attention, "visible enemies", na(state.visibleEnemies, 0));

    const logs = section(grid, "Logs");
    kv(logs, "frame max ms", na(state.frameMs, 1));

    const active = D.diagnosticsAt(view.diagnostics, time);
    const diagnostics = section(container, `Hints at this time (${active.length})`);
    diagnostics.classList.add("dt-wide");
    if (!active.length) add(diagnostics, "div", "dt-hint", "no rule matches");
    for (const item of active) {
      add(diagnostics, "div", `dt-diag-line sev-${item.severity}`, `⚠ ${item.title}  (${fmtTime(item.start)} – ${fmtTime(item.end)})`);
      add(diagnostics, "div", "dt-hint", item.evidence.join(" · "));
    }

    renderNearbyEvents(container, time);
  }

  function lowerBound(records, time) {
    let low = 0;
    let high = records.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (records[mid].game_time < time) low = mid + 1;
      else high = mid;
    }
    return low;
  }

  function describe(record) {
    const data = record.data || {};
    const parts = [];
    for (const key of ["objective", "proposal_id", "command", "owner"]) if (data[key]) parts.push(`${key}=${data[key]}`);
    if (Array.isArray(data.tags)) parts.push(`${data.tags.length} units`);
    if (data.reason) parts.push(`why=${data.reason}`);
    if (!parts.length) parts.push(JSON.stringify(data).slice(0, 160));
    return parts.join("  ");
  }

  function renderNearbyEvents(parent, time) {
    const records = view.model.records;
    const events = section(parent, `Decision events ${fmtDelta(-EVENT_WINDOW)} .. ${fmtDelta(EVENT_WINDOW)}`);
    events.classList.add("dt-wide");
    const list = [];
    for (let index = lowerBound(records, time - EVENT_WINDOW); index < records.length; index += 1) {
      const record = records[index];
      if (record.game_time > time + EVENT_WINDOW || list.length >= EVENT_LIMIT) break;
      if (!NOISY_EVENTS.has(record.event)) list.push(record);
    }
    if (!list.length) add(events, "div", "dt-hint", "no decision events in this window");
    let markerShown = false;
    for (const record of list) {
      if (!markerShown && record.game_time > time) {
        add(events, "div", "dt-now", `── ${fmtTime(time)} ──`);
        markerShown = true;
      }
      const row = add(events, "div", "dt-event");
      add(row, "span", "dt-event-time", fmtTime(record.game_time));
      add(row, "span", "dt-event-name", record.event);
      add(row, "span", "dt-event-fields", describe(record));
      row.addEventListener("click", () => {
        const open = row.querySelector("pre");
        if (open) {
          open.remove();
          return;
        }
        add(row, "pre", "", JSON.stringify(record, null, 2));
      });
    }
  }

  // --- snapshot panel ------------------------------------------------------------------

  function buildSnapshotPanel(parent) {
    const header = add(parent, "div", "dt-snapshot-header");
    view.refs.snapshotTitle = add(header, "span", "dt-snapshot-title", "");
    const nav = add(header, "span", "dt-group");
    button(nav, "◀ prev", () => stepSnapshot(-1), "previous snapshot ([)");
    button(nav, "go to snapshot", () => {
      const snapshot = S.nearest(view.snapshots, view.selectedTime);
      if (snapshot) select(snapshot.t);
    }, "move the selected time onto this snapshot");
    button(nav, "next ▶", () => stepSnapshot(1), "next snapshot (])");
    view.refs.snapshotNotice = add(parent, "div", "dt-hint", "");
    view.refs.snapshotAdd = button(parent, "Add SVG files…", () => view.requestSvgFiles?.(), "select the game's spatial/field-*.svg files");
    const frame = add(parent, "div", "dt-snapshot-frame");
    const image = add(frame, "img", "dt-snapshot-image");
    image.alt = "influence field snapshot";
    view.refs.snapshotImage = image;
    view.refs.snapshotName = null;
  }

  function urlFor(snapshot) {
    if (!view.urls.has(snapshot.name)) view.urls.set(snapshot.name, URL.createObjectURL(snapshot.file));
    return view.urls.get(snapshot.name);
  }

  function renderSnapshot() {
    const refs = view.refs;
    if (!refs.snapshotTitle) return;
    const snapshots = view.snapshots;
    const loaded = snapshots.filter((item) => item.file).length;
    const snapshot = S.nearest(snapshots, view.selectedTime);
    refs.snapshotAdd.hidden = snapshots.length > 0 && loaded === snapshots.length;
    if (!snapshot) {
      refs.snapshotTitle.textContent = "No field snapshots";
      refs.snapshotNotice.textContent = "This log recorded no SVG snapshot (run with --spatial-snapshot), and none were added.";
      refs.snapshotImage.hidden = true;
      return;
    }
    const delta = snapshot.t - view.selectedTime;
    refs.snapshotTitle.textContent = `${snapshot.name} @ ${fmtTime(snapshot.t)} (${fmtDelta(delta)}) · ${loaded}/${snapshots.length} loaded`;
    if (!snapshot.file) {
      refs.snapshotNotice.textContent = "SVG not loaded: open the whole game folder, or add the spatial/field-*.svg files.";
      refs.snapshotImage.hidden = true;
      refs.snapshotName = null;
      return;
    }
    refs.snapshotNotice.textContent = Math.abs(delta) > 20 ? "Nearest snapshot is more than 20s away from the selected time." : "";
    refs.snapshotImage.hidden = false;
    if (refs.snapshotName !== snapshot.name) {
      refs.snapshotImage.src = urlFor(snapshot);
      refs.snapshotName = snapshot.name;
    }
  }

  // --- side panel: hints and decision changes --------------------------------------

  function renderSide(sideEl) {
    sideEl.replaceChildren();
    add(sideEl, "h2", "", `Hints (${view.diagnostics.length})`);
    add(sideEl, "div", "notice", "Hints for debugging, not verdicts.");
    for (const item of view.diagnostics) {
      const card = add(sideEl, "div", `entity-card summary-alert clickable${item.severity === "warning" ? " bad" : ""}`);
      add(card, "div", "id", `⚠ ${item.title}`);
      add(card, "div", "meta", `${fmtTime(item.start)} – ${fmtTime(item.end)}${item.openAtEnd ? " (until end)" : ""} · ${item.rule}`);
      card.addEventListener("click", () => {
        select(item.start);
        toggleDetail(card, () => {
          const block = el("div", "dt-cause");
          for (const line of item.evidence) add(block, "div", "", line);
          return block;
        });
      });
    }

    add(sideEl, "h2", "", `Decision changes (${view.transitions.length})`);
    for (const transition of view.transitions) {
      const card = add(sideEl, "div", "entity-card dt-transition");
      add(card, "div", "id", `${fmtTime(transition.t)}  ${transition.label}`);
      add(card, "div", "meta", `${transition.from ?? "∅"} → ${transition.to}${transition.reason ? ` · ${transition.reason}` : ""}`);
      card.addEventListener("click", () => {
        select(transition.t);
        toggleDetail(card, () => causeBlock(transition));
      });
    }
  }

  function toggleDetail(card, build) {
    const open = card.querySelector(".dt-cause");
    if (open) {
      open.remove();
      return;
    }
    card.appendChild(build());
  }

  function causeBlock(transition) {
    const cause = T.causeOf(view.model, transition);
    const block = el("div", "dt-cause");
    add(block, "div", "dt-cause-title", `${fmtTime(transition.t)} — ${transition.from ?? "∅"} → ${transition.to}`);
    if (cause.reason) add(block, "div", "", `reason: ${cause.reason}`);
    for (const line of cause.signals) {
      add(block, "div", line.changed ? "dt-changed" : "dt-unchanged",
        line.changed ? `${line.signal}: ${line.before} → ${line.after}` : `${line.signal}: ${line.after}`);
    }
    if (cause.inputs.length) add(block, "div", "dt-cause-title", "inputs");
    for (const input of cause.inputs) add(block, "div", "", `${input.signal}: ${input.value}`);
    if (cause.scores.length) add(block, "div", "dt-cause-title", "scores");
    for (const score of cause.scores) add(block, "div", "", `${score.objective}: ${score.value}`);
    return block;
  }

  root.DecisionView = {
    load,
    attachSnapshotFiles,
    render,
    focus,
    select,
    handleKey,
    redraw: () => {
      drawTracks();
      moveCursor();
    },
    diagnosticCount: () => view.diagnostics.length,
    model: () => view.model,
    setSvgFileRequester: (callback) => {
      view.requestSvgFiles = callback;
    },
    get selectedTime() {
      return view.selectedTime;
    },
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
