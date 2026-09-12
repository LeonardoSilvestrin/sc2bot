// Decision Timeline view: horizontal tracks synchronized on one selected
// time, an inspector of the world state at that time, and the nearest
// spatial SVG snapshot. Builds DOM only through createElement/textContent.
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

  // Events that are periodic telemetry, not decisions: kept out of the
  // "events around t" list (they still feed the tracks).
  const NOISY_EVENTS = new Set([
    "behavior.assessed", "spatial.perf", "territory.perf", "knowledge.updated", "awareness.updated",
    "observation.updated", "attention.world_state", "attention.snapshot", "knowledge.territory",
    "knowledge.enemy_model", "knowledge.enemy_intel", "awareness.world_belief", "standing.updated",
    "macro.status", "debug.spatial_snapshot_written", "proposal_created", "proposal_rejected",
    "squad_membership_changed", "standing_mission_updated", "economic_proposal_created",
    "economic_proposal_deferred", "economic_proposal_rejected", "economic_action_admitted",
    "economic_action_pending", "economic_action_dispatched", "economic_action_confirmed",
    "strategy.updated",
  ]);

  const TONES = {
    bad: new Set(["DEFENSE", "TURTLE", "BEHIND", "STABILIZE", "RETREAT", "HOLDING_HOME", "UNSAFE", "FAILED", "CANCELLED", "EVADE", "CRITICAL"]),
    warn: new Set(["RECOVER", "RECOVERY", "BLOCKED", "QUEUED", "PROPOSED", "UNKNOWN", "WAITING", "REPOSITION", "ASSEMBLE"]),
    ok: new Set(["GREED", "PRESSURE", "AHEAD", "TAKE_MAP_CONTROL", "SAFE", "COMPLETED", "STRIKE"]),
  };

  function tone(value) {
    for (const [name, values] of Object.entries(TONES)) if (values.has(value)) return name;
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

  function diagnosticCount() {
    return view.diagnostics.length;
  }

  // --- layout ------------------------------------------------------------------

  function laneCount(items) {
    const ends = [];
    for (const item of [...items].sort((a, b) => a.start - b.start)) {
      let lane = ends.findIndex((end) => end <= item.start);
      if (lane < 0) {
        lane = ends.length;
        ends.push(item.end);
      } else {
        ends[lane] = item.end;
      }
      item.lane = lane;
    }
    return Math.max(1, ends.length);
  }

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

    group("Diagnostics");
    const lanes = laneCount(view.diagnostics);
    rows.push({ type: "diagnostics", label: view.diagnostics.length ? "contradictions" : "none detected", h: lanes * LANE_H + 6 });

    const strategy = model.strategy;
    group(strategy.available ? `Strategy${strategy.shadow ? " · shadow (not executed)" : ""}` : "Strategy");
    if (strategy.available) {
      track("strategy.objective", { label: strategy.shadow ? "Objective [shadow]" : "Objective" });
      track("strategy.confidence");
    } else {
      rows.push({ type: "na", label: "Objective", text: "N/A — this log has no strategy.updated telemetry", h: STATE_H });
    }

    group("Posture");
    track("posture.macro");
    track("posture.combat");

    group("Knowledge");
    track("belief.army");
    track("belief.economy");
    track("map_control.safe");

    group("Threat");
    track("threat.relative_strength");
    track("threat.own_supply", { overlay: "threat.enemy_supply", label: "Army supply own / enemy" });
    track("threat.enemy_force_strength");
    track("threat.enemy_near_base");

    if (model.missionTracks.length) group("Missions");
    for (const item of model.missionTracks) {
      rows.push({ type: "intervals", track: item, label: item.label, h: item.lanes * LANE_H + 6, missions: true });
    }
    if (model.behaviorTracks.length) group("Behavior");
    for (const item of model.behaviorTracks) {
      rows.push({ type: "intervals", track: item, label: item.label, h: item.lanes * LANE_H + 6 });
    }

    group("Territory");
    track("territory.base_security");
    track("territory.friendly_regions", { overlay: "territory.enemy_regions", label: "Regions friendly / enemy" });

    group("Economy");
    track("economy.supply");
    track("economy.minerals");
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
    view.refs.labels = labels;
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
    button(diagnostics, "◀ ⚠", () => stepDiagnostic(-1), "previous diagnostic");
    button(diagnostics, "⚠ ▶", () => stepDiagnostic(1), "next diagnostic");
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
    const strategy = view.model.strategy;
    add(bar, "span", `dt-badge ${strategy.available ? (strategy.shadow ? "shadow" : "live") : "missing"}`,
      strategy.available ? (strategy.shadow ? "strategy: shadow" : "strategy: live") : "strategy: no telemetry");
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
    view.refs.plot = plot;
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
      withTitle(mark, `SVG snapshot ${snapshot.name} @ ${fmtTime(snapshot.t)}${snapshot.file ? "" : " (file not loaded)"}`);
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
    const shadow = row.track.key === "strategy.objective" && view.model.strategy.shadow;
    for (const segment of T.segments(row.track, view.model.endTime)) {
      const reason = segment.point.record?.data?.reason;
      drawSegment(g, {
        start: segment.start,
        end: segment.end,
        top: 3,
        height: row.h - 6,
        value: segment.value,
        className: `dt-seg tone-${tone(segment.value)}${shadow ? " shadow" : ""}`,
        title: `${row.label}: ${segment.value}${shadow ? " [shadow]" : ""}\n${fmtTime(segment.start)} – ${fmtTime(segment.end)}${reason ? `\nreason: ${reason}` : ""}`,
      }, width);
    }
  }

  function seriesRange(track, overlay) {
    const values = [...track.points, ...(overlay?.points ?? [])].map((point) => point.v);
    let min = track.min ?? Math.min(...values);
    let max = track.max ?? Math.max(...values);
    if (track.min !== undefined && values.length) min = Math.min(min, ...values);
    if (track.max !== undefined && values.length) max = Math.max(max, ...values);
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
    if (row.track.zero !== undefined && range.min < 0 && range.max > 0) {
      const y = main.yOf(0);
      g.appendChild(svg("line", { x1: 0, x2: width, y1: y, y2: y }, "dt-zero"));
    }
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
      const statuses = item.statuses.filter((status) => status.t < end || status.t === item.start);
      statuses.forEach((status, index) => {
        const start = Math.max(item.start, status.t);
        const segmentEnd = index + 1 < statuses.length ? Math.max(start, statuses[index + 1].t) : end;
        if (segmentEnd <= start && index + 1 < statuses.length) return;
        const units = item.unitTypes?.size ? ` · ${[...item.unitTypes].join(",")}` : "";
        const label = row.missions
          ? (status.value === "ACTIVE" ? `${item.id.replace("mission-", "#")}${units}` : status.value)
          : status.value;
        drawSegment(g, {
          start,
          end: Math.max(segmentEnd, start + 0.01),
          top,
          height: LANE_H - 2,
          label,
          className: `dt-seg tone-${tone(status.value)}`,
          title: `${item.id}${item.kind ? ` ${item.kind}` : ""}${item.target ? ` → ${item.target}` : ""}${units}\n${status.value} ${fmtTime(start)} – ${fmtTime(segmentEnd)}${status.reason ? `\nreason: ${status.reason}` : ""}`,
        }, width);
      });
      if (item.finalStatus === "FAILED" || item.finalStatus === "CANCELLED") {
        const x = xOf(item.end, width);
        g.appendChild(withTitle(svg("path", { d: `M ${x - 3} ${top} L ${x + 3} ${top + LANE_H - 2} M ${x + 3} ${top} L ${x - 3} ${top + LANE_H - 2}` }, "dt-fail"), `${item.id} ${item.finalStatus}`));
      }
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
        title: `⚠ ${item.label}\n${item.title}\n${fmtTime(item.start)} – ${fmtTime(item.end)}\n${item.evidence.join("\n")}`,
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
    // From between two snapshots, "previous" means the one before the nearest
    // only when we already sit on the nearest one.
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

  function since(point, time) {
    return point ? ` (since ${fmtTime(point.t)}, ${fmtDelta(point.t - time)})` : "";
  }

  function renderInspector() {
    const root_ = view.refs.inspector;
    if (!root_) return;
    const model = view.model;
    const time = view.selectedTime;
    const state = T.snapshotAt(model, time);
    root_.replaceChildren();
    add(root_, "div", "dt-inspector-title", `World state at ${fmtTime(time)}`);
    const grid = add(root_, "div", "dt-inspector-grid");

    const strategy = section(grid, model.strategy.available && model.strategy.shadow ? "Strategy · shadow" : "Strategy");
    if (!model.strategy.available) {
      kv(strategy, "objective", "N/A");
      add(strategy, "div", "dt-hint", "No strategy.updated events: Strategy runs in shadow mode with no producer yet.");
    } else if (!state.strategy) {
      kv(strategy, "objective", "N/A");
    } else {
      const s = state.strategy;
      kv(strategy, "objective", `${s.objective}${s.shadow ? " [shadow]" : ""}`);
      kv(strategy, "since", `${fmtTime(s.since)} (${fmtDelta(s.since - time)})`);
      kv(strategy, "confidence", na(s.confidence, 2));
      if (s.leader) kv(strategy, "leader", s.leader);
      for (const [name, value] of Object.entries(s.inputs)) kv(strategy, name, na(Number(value), 2), "dt-sub");
    }

    const posture = section(grid, "Posture");
    kv(posture, "macro", state.macroPosture);
    kv(posture, "combat", state.combatPosture);
    kv(posture, "map control safe?", state.mapControlSafe);

    const knowledge = section(grid, "Knowledge");
    const army = state.armyBelief;
    kv(knowledge, "army belief", army ? `${army.value}${since(army, time)}` : undefined);
    if (army?.detail) kv(knowledge, "army raw / adv / conf", `${army.lastDetail?.raw ?? army.detail.raw} / ${na(army.lastDetail?.advantage ?? army.detail.advantage, 2)} / ${na(army.lastDetail?.confidence ?? army.detail.confidence, 2)}`, "dt-sub");
    const economy = state.economyBelief;
    kv(knowledge, "economy belief", economy ? `${economy.value}${since(economy, time)}` : undefined);

    const threat = section(grid, "Threat");
    kv(threat, "relative strength", na(state.relativeStrength, 2));
    kv(threat, "army supply own / enemy", `${na(state.ownSupply, 0)} / ${na(state.enemySupply, 0)}`);
    kv(threat, "enemy force strength", na(state.enemyForceStrength, 0));
    kv(threat, "enemy near base", na(state.enemyNearBase, 0));

    const territory = section(grid, "Territory & economy");
    kv(territory, "min base security", na(state.baseSecurity, 2));
    kv(territory, "regions friendly / enemy", `${na(state.friendlyRegions, 0)} / ${na(state.enemyRegions, 0)}`);
    kv(territory, "supply / minerals", `${na(state.supplyUsed, 0)} / ${na(state.minerals, 0)}`);

    const missions = section(grid, `Missions open (${state.missions.length})`);
    if (!state.missions.length) add(missions, "div", "dt-hint", "none");
    for (const { item, status } of state.missions) {
      const behavior = T.behaviorStateOfMission(model, item.id, time);
      const units = item.unitTypes.size ? ` · ${[...item.unitTypes].join(",")}` : "";
      kv(missions, `${item.id.replace("mission-", "#")} ${item.kind}`, `${status ?? "?"}${behavior ? ` → ${behavior.value}` : ""}${units}`);
    }

    const behaviors = section(grid, `Behavior phases (${state.behaviors.length})`);
    if (!state.behaviors.length) add(behaviors, "div", "dt-hint", "none");
    for (const { item, state: phase } of state.behaviors) {
      kv(behaviors, `${item.component.replace(/^behavior\./, "")} ${item.missionId}`, `${phase.value}${since(phase, time)}`);
      if (phase.reason) add(behaviors, "div", "dt-hint", `reason: ${phase.reason}`);
    }

    const active = D.diagnosticsAt(view.diagnostics, time);
    const diagnostics = section(root_, `Diagnostics at this time (${active.length})`);
    diagnostics.classList.add("dt-wide");
    if (!active.length) add(diagnostics, "div", "dt-hint", "no contradiction rule matches");
    for (const item of active) {
      add(diagnostics, "div", `dt-diag-line sev-${item.severity}`, `⚠ ${item.title}  (${fmtTime(item.start)} – ${fmtTime(item.end)})`);
      add(diagnostics, "div", "dt-hint", item.evidence.join(" · "));
    }

    renderNearbyEvents(root_, time);
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
    if (data.mission_kind) parts.push(data.mission_kind);
    if (data.mission_id) parts.push(data.mission_id);
    if (data.state) parts.push(`state=${data.state}`);
    if (data.reason) parts.push(`why=${data.reason}`);
    if (data.message) parts.push(data.message);
    if (data.decision) parts.push(`decision=${data.decision}`);
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
    view.refs.snapshotGo = button(nav, "go to snapshot", () => {
      const snapshot = S.nearest(view.snapshots, view.selectedTime);
      if (snapshot) select(snapshot.t);
    }, "move the selected time onto this snapshot");
    button(nav, "next ▶", () => stepSnapshot(1), "next snapshot (])");
    view.refs.snapshotNotice = add(parent, "div", "dt-hint", "");
    view.refs.snapshotAdd = button(parent, "Add SVG files…", () => view.requestSvgFiles?.(), "select the game's spatial/territory-*.svg files");
    const frame = add(parent, "div", "dt-snapshot-frame");
    const image = add(frame, "img", "dt-snapshot-image");
    image.alt = "territory snapshot";
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
      refs.snapshotTitle.textContent = "No spatial snapshots";
      refs.snapshotNotice.textContent = "This log recorded no SVG snapshot (run with --spatial-snapshot), and none were added.";
      refs.snapshotImage.hidden = true;
      return;
    }
    const delta = snapshot.t - view.selectedTime;
    refs.snapshotTitle.textContent = `${snapshot.name} @ ${fmtTime(snapshot.t)} (${fmtDelta(delta)} from selected) · ${loaded}/${snapshots.length} loaded`;
    if (!snapshot.file) {
      refs.snapshotNotice.textContent = "SVG not loaded: open the whole game folder, or add the spatial/territory-*.svg files.";
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

  // --- side panel: diagnostics and decision changes --------------------------------------

  function renderSide(sideEl) {
    sideEl.replaceChildren();
    add(sideEl, "h2", "", `Diagnostics (${view.diagnostics.length})`);
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
      const heading = add(card, "div", "id", `${fmtTime(transition.t)}  ${transition.label}`);
      if (transition.shadow) add(heading, "span", "status-pill dt-shadow-pill", "shadow");
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
    add(block, "div", "dt-cause-title", `${fmtTime(transition.t)} — ${transition.from ?? "∅"} → ${transition.to}${cause.shadow ? " [shadow]" : ""}`);
    if (cause.reason) add(block, "div", "", `reason: ${cause.reason}`);
    if (cause.confidence !== undefined) add(block, "div", "", `confidence: ${na(cause.confidence, 2)}`);
    for (const line of cause.signals) {
      add(block, "div", line.changed ? "dt-changed" : "dt-unchanged",
        line.changed ? `${line.signal}: ${line.before} → ${line.after}` : `${line.signal}: ${line.after}`);
    }
    if (cause.strategyInputs.length) add(block, "div", "dt-cause-title", "strategy inputs");
    for (const input of cause.strategyInputs) add(block, "div", "", `${input.signal}: ${input.value}`);
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
    diagnosticCount,
    setSvgFileRequester: (callback) => {
      view.requestSvgFiles = callback;
    },
    get selectedTime() {
      return view.selectedTime;
    },
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
