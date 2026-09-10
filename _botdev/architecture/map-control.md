# Persistent map control

`MapControlPlanner` declares a standing `map_control` squad once at least six
eligible Marines exist. Its desired count is `ceil(eligible * 0.20)` by default;
`desired_units` remains an optional fixed override for experiments.

The proposal uses `MissionKind.MAP_CONTROL`, priority 40,
`MissionMode.STANDING`, dedup key `map_control:patrol`, and
`squad_id="map_control"`. It is declared even during danger because this is a
persistent responsibility, not a one-shot opportunity. Priority arbitration
allows `DEFENSE` to preempt it, while the executor itself retreats during
defensive/recovery posture, a base threat, nearby enemies, or low squad health.

`MapControlExecutor` cycles through four deterministic points on the friendly
side and center using `safe_path_to`. On reaching safety it remains active and
holds home rather than completing/recreating the mission. With zero units it
waits for its persistent members to return.
