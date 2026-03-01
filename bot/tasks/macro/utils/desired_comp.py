from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.awareness import K


def normalize_unit_comp(comp: dict[U, float]) -> dict[U, float]:
    total = float(sum(float(v) for v in comp.values()))
    if total <= 0.0:
        return dict(comp)
    return {k: float(v) / total for k, v in comp.items()}


def desired_comp_units(*, awareness, now: float) -> dict[U, float]:
    raw = awareness.mem.get(K("macro", "desired", "comp"), now=now, default=None)

    comp: dict[U, float] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if not isinstance(k, str):
                continue
            try:
                uid = getattr(U, k)
                fv = float(v)
            except Exception:
                continue
            if fv > 0.0:
                comp[uid] = fv

    return normalize_unit_comp(comp)


def desired_comp_names(*, awareness, now: float) -> dict[str, float]:
    comp = desired_comp_units(awareness=awareness, now=now)
    return {str(uid.name): float(v) for uid, v in comp.items()}


def desired_priority_units(*, awareness, now: float) -> list[U]:
    raw = awareness.mem.get(K("macro", "desired", "priority_units"), now=now, default=None)
    out: list[U] = []
    if not isinstance(raw, list):
        return out
    for name in raw:
        if not isinstance(name, str):
            continue
        try:
            out.append(getattr(U, name))
        except Exception:
            continue
    return out


def unit_comp_to_controller_dict(comp: dict[U, float], *, priority_units: list[U] | None = None) -> dict[U, dict[str, float | int]]:
    ordered = sorted(comp.items(), key=lambda kv: kv[1], reverse=True)
    if priority_units:
        p_index = {u: i for i, u in enumerate(priority_units)}
        ordered.sort(key=lambda kv: (p_index.get(kv[0], 999), -kv[1]))
    out: dict[U, dict[str, float | int]] = {}
    for idx, (uid, proportion) in enumerate(ordered):
        out[uid] = {"proportion": float(proportion), "priority": int(idx)}
    return out
