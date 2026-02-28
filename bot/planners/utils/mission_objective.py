from __future__ import annotations

from sc2.position import Point2


def mission_objective_from_alive_tags(bot, mission) -> Point2:
    points: list[Point2] = []
    for tag in mission.alive_tags:
        unit = bot.units.find_by_tag(int(tag))
        if unit is not None:
            points.append(unit.position)
    if points:
        x = sum(float(p.x) for p in points) / float(len(points))
        y = sum(float(p.y) for p in points) / float(len(points))
        return Point2((x, y))
    if getattr(bot, "enemy_start_locations", None):
        return bot.enemy_start_locations[0]
    return bot.start_location
