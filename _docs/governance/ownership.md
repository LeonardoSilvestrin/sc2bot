# Ownership de Namespaces

Mapa de ownership dos prefixes mais importantes em `Awareness.mem`.

Regra base:
- um prefixo deve ter writer principal claro
- reader multiplo e normal
- multi-writer so deve existir quando o contrato explicita isso

---

## Prefix Ownership Atual

### `enemy:opening:*`, `enemy:rush:*`, `enemy:aggression:*`

- writer principal: `bot/intel/enemy/opening_intel.py`
- readers: planners, runtime chat, macro intel, defense

### `enemy:build:*`, `enemy:army:*`

- writer principal: `bot/intel/enemy/enemy_build_intel.py`
- readers: `IntelPlanner`, `HarassPlanner`, macro intel, runtime diagnostics

### `enemy:weak_points:*`

- writer principal: `bot/intel/enemy/weak_points_intel.py`
- readers: `HarassPlanner`

### `enemy:pathing:*`

- writers: `i1_pathing_flow_intel`, `i2_pathing_route_intel`
- readers: world compression, intel planner, runtime clock

### `intel:frontline:*`

- writer principal: `i5_frontline_intel`
- readers: geometry, posture, defense, territorial control

### `intel:geometry:world:*`

- writer principal: `i1_world_compression_intel`
- readers: `i2_operational_geometry_intel`

### `intel:geometry:operational:*`

- writer principal: `i2_operational_geometry_intel`
- readers: `MapControlPlanner`, `DefensePlanner`, `ArmyPostureIntel`, territorial control

### `intel:geometry:sector:*`

- writer principal: `i2_operational_geometry_intel`
- readers: planners e ferramentas de debug

### `intel:territory:defense:*`

- writer principal: `i6_territorial_control_intel`
- readers: `DefendBaseTask`, `SecureBaseTask`, `DefensePlanner`, `MapControlPlanner`

### `strategy:army:*`

- writer principal: `i3_army_posture_intel`
- readers: `MapControlPlanner`, `DefensePlanner`, runtime chat

### `strategy:parity:*`

- writer principal: `i1_game_parity_intel`
- readers: world compression, macro orchestrator, runtime diagnostics

### `macro:desired:*`

- writer principal: `bot/intel/macro/desired_intel.py`
- readers: `MacroOrchestratorPlanner`, `HarassPlanner`, runtime push planner

### `macro:plan:*`

- writer principal: `bot/planners/macro_orchestrator_planner.py`
- readers: housekeeping, runtime diagnostics

### `macro:exec:*`

- writer principal desejado: `bot/planners/macro_orchestrator_planner.py`
- readers: macro executor task, runtime diagnostics

### `tech:exec:*`

- writer principal desejado: `bot/planners/macro_orchestrator_planner.py`
- readers: tech executor task

### `macro:opening:*`

- writers atuais:
  - `bot/intel/enemy/opening_contract.py`
  - `bot/mind/opening_state.py`
  - runtime sync com build runner
- readers: sensors, macro intel, runtime chat

### `control:phase`, `control:pressure:*`, `control:priority:*`

- writer principal atual: `bot/planners/macro_orchestrator_planner.py`
- readers: runtime clock, macro control, possiveis intels de prioridade

### `ops:mission:*`, `ops:cooldown:*`, `ops:proposal_running:*`

- writer principal: `bot/mind/ego.py`
- readers: mission sensor, planners, runtime diagnostics

### `ops:map_control:*`, `ops:defense:*`, `ops:harass:*`, `ops:wall:*`

- writers: planners e tasks do dominio correspondente
- readers: o proprio dominio e debug

---

## Hotspots

### `macro:opening:*`

Ainda e prefixo com ownership espalhado.

Sintoma:
- opening contractual
- opening selecionada
- opening request/transition target

Recomendacao:
- separar contrato (`macro:opening:done*`) de selecao/request (`macro:opening:selected*`)

### `macro:exec:*`

O planner macro e o writer principal, mas tasks executoras ainda podem refletir estado operacional no mesmo grupo.

Recomendacao:
- manter `planner` como source de decisao
- usar subprefixo claro para status de task, se crescer

### `control:priority:*`

Virou namespace de metricas e controle macro.

Recomendacao:
- manter apenas sinais de arbitragem/prioridade
- mover telemetria excessiva para prefixo proprio se o grupo crescer mais

---

## Regra Operacional

Antes de criar novo prefixo:

1. defina writer principal
2. defina shape estavel do `value`
3. defina TTL
4. documente consumidores
5. evite reaproveitar prefixo sem relacao semantica
