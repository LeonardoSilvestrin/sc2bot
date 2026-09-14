// Contradiction hints over the decision timeline. Each rule is an explicit
// condition over a few tracks, reported only while it holds long enough.
// Hints for debugging, not verdicts. Pure: no DOM.
(function (root) {
  "use strict";

  const T = root.SC2Timeline;

  function fmt(value, digits = 2) {
    return T.formatValue(value, digits);
  }

  const RULES = [
    {
      id: "threat_without_defense",
      title: "Base threatened, no defenders",
      severity: "warning",
      minDuration: 3,
      tracks: ["danger", "defenseUnits"],
      when: (v) => (v.danger ?? 0) >= 0.25 && !((v.defenseUnits ?? 0) > 0),
      evidence: (v) => [`danger ${fmt(v.danger)}`, `defense units ${fmt(v.defenseUnits, 0)}`],
    },
    {
      id: "unassigned_army",
      title: "Army units without an owner",
      severity: "warning",
      minDuration: 2,
      tracks: ["unassigned"],
      when: (v) => (v.unassigned ?? 0) > 0,
      evidence: (v) => [`unassigned ${fmt(v.unassigned, 0)}`],
    },
    {
      id: "stabilize_without_threat",
      title: "STABILIZE with no threat",
      severity: "note",
      minDuration: 20,
      tracks: ["objective", "danger"],
      when: (v) => v.objective === "STABILIZE" && (v.danger ?? 0) < 0.05,
      evidence: (v) => [`objective ${v.objective}`, `danger ${fmt(v.danger)}`],
    },
    {
      id: "slow_frames",
      title: "Slow frames",
      severity: "note",
      minDuration: 0,
      tracks: ["frameMs"],
      when: (v) => (v.frameMs ?? 0) > 45,
      evidence: (v) => [`frame max ${fmt(v.frameMs, 1)} ms`],
    },
  ];

  function changeTimes(model, names) {
    const times = new Set([model.startTime]);
    for (const name of names) for (const point of model.t[name].points) times.add(point.t);
    return [...times].sort((a, b) => a - b);
  }

  function runDiagnostics(model) {
    const result = [];
    for (const rule of RULES) {
      if (!rule.tracks.every((name) => T.hasData(model.t[name]))) continue;
      let start = null;
      let evidence = [];
      const close = (end, openAtEnd) => {
        if (end - start >= rule.minDuration) {
          result.push({
            rule: rule.id,
            title: rule.title,
            label: rule.id,
            severity: rule.severity,
            start,
            end: Math.max(end, start + 0.5),
            openAtEnd,
            evidence,
          });
        }
        start = null;
      };
      for (const time of changeTimes(model, rule.tracks)) {
        const values = {};
        for (const name of rule.tracks) values[name] = T.valueAt(model.t[name], time);
        const active = rule.when(values);
        if (active && start === null) {
          start = time;
          evidence = rule.evidence(values);
        } else if (!active && start !== null) {
          close(time, false);
        }
      }
      if (start !== null) close(model.endTime, true);
    }
    result.sort((a, b) => a.start - b.start || a.rule.localeCompare(b.rule));
    const laneEnds = [];
    for (const item of result) {
      let lane = laneEnds.findIndex((end) => end <= item.start);
      if (lane < 0) {
        lane = laneEnds.length;
        laneEnds.push(item.end);
      } else {
        laneEnds[lane] = item.end;
      }
      item.lane = lane;
    }
    return result;
  }

  function diagnosticsAt(diagnostics, time) {
    return diagnostics.filter((item) => item.start <= time && time <= item.end);
  }

  const api = { RULES, runDiagnostics, diagnosticsAt };
  root.SC2Diagnostics = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
