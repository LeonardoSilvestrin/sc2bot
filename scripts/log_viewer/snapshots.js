// Spatial SVG snapshots: when each one was taken and which one belongs to a
// selected instant. Pure: files are opaque handles supplied by the page.
(function (root) {
  "use strict";

  // territory-0246.svg -> 246, territory-0246-500.svg -> 246.5
  const SNAPSHOT_NAME = /territory-(\d+)(?:-(\d{1,3}))?\.svg$/i;

  function baseName(path) {
    return String(path ?? "").split(/[\\/]/).pop();
  }

  function timeFromName(name) {
    const match = SNAPSHOT_NAME.exec(baseName(name));
    if (!match) return undefined;
    const millis = match[2] ? Number(match[2].padEnd(3, "0")) : 0;
    return Number(match[1]) + millis / 1000;
  }

  // Joins the times the log recorded with the SVG files actually available.
  // `files` are objects with a `name` (e.g. File); logged times win.
  function buildSnapshotIndex(records, files = []) {
    const byName = new Map();
    for (const record of records) {
      if (record.event !== "debug.spatial_snapshot_written") continue;
      const name = baseName(record.data?.path);
      if (!name) continue;
      byName.set(name, { t: record.game_time, name, file: null, logged: true });
    }
    for (const file of files) {
      const name = baseName(file.name);
      const time = timeFromName(name);
      if (time === undefined) continue;
      const entry = byName.get(name);
      if (entry) entry.file = file;
      else byName.set(name, { t: time, name, file, logged: false });
    }
    return [...byName.values()].sort((a, b) => a.t - b.t || a.name.localeCompare(b.name));
  }

  // Index of the snapshot closest in time; ties go to the earlier snapshot,
  // i.e. what the bot already knew rather than what it was about to learn.
  function nearestIndex(snapshots, time) {
    if (!snapshots.length || !Number.isFinite(time)) return -1;
    let low = 0;
    let high = snapshots.length - 1;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (snapshots[mid].t < time) low = mid + 1;
      else high = mid;
    }
    if (low > 0 && Math.abs(snapshots[low - 1].t - time) <= Math.abs(snapshots[low].t - time)) return low - 1;
    return low;
  }

  function nearest(snapshots, time) {
    const index = nearestIndex(snapshots, time);
    return index < 0 ? undefined : snapshots[index];
  }

  function stepIndex(snapshots, index, delta) {
    if (!snapshots.length) return -1;
    return Math.min(snapshots.length - 1, Math.max(0, index + delta));
  }

  const api = { timeFromName, buildSnapshotIndex, nearestIndex, nearest, stepIndex, baseName };
  root.SC2Snapshots = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
