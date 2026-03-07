# Ownership de Namespaces

Mapa de ownership de prefixes da Awareness.

---

## Prefix ownership atual

### `macro.desired.*`

- writer: `bot/intel/macro/desired_intel.py`
- readers: strategy, planners, macro tasks

### `macro.control.*`

- writer: `bot/intel/strategy/i2_CTRL_advantage_game_status_intel.py`
- readers: prioritization intel, macro orchestrator planner

### `strategy.parity.*`

- writer: `bot/intel/strategy/i1_game_parity_intel.py`
- readers: strategy, planner, runtime diagnostics

### `control.priority.*`

- writers:
  - `bot/intel/ego/i1_PI_prioritization_intel.py`
  - `bot/planners/macro_orchestrator_planner.py`
  - `bot/mind/ego.py`
- readers: prioritization intel, planner, runtime diagnostics

### `macro.exec.*`

- writers:
  - `bot/planners/macro_orchestrator_planner.py`
  - `bot/tasks/macro/tasks/macro_ares_executor_tick.py`
- readers: planner, task, prioritization intel

### `tech.exec.*`

- writers:
  - `bot/planners/macro_orchestrator_planner.py`
  - `bot/tasks/tech/tasks/tech_ares_executor_tick.py`
- readers: planner, tech task

### `macro.opening.*`

- writers:
  - `bot/intel/enemy/opening_intel.py`
  - `bot/mind/self.py`
- readers: desired intels, planner, sensors

### `strategy.advantage.*`

- writer: none found in repository
- readers: `bot/intel/strategy/i2_CTRL_advantage_game_status_intel.py`

---

## Hotspots

- `macro.exec.*` tem 2 writers
- `tech.exec.*` tem 2 writers
- `macro.opening.*` tem 2 writers
- `control.priority.*` mistura policy, lag metrics e errors
- `strategy.advantage.*` nao tem writer no repositorio

---

## Regra de organizacao recomendada

Organizar por namespace escrito:
- modulos que escrevem `macro.desired.*` ficam juntos
- planners e tasks devem ser agrupados pelo namespace que possuem como writer
- ownership deve ser explicito antes de expandir qualquer prefixo

---

## Cleanup recomendado

1. Tornar `macro.exec.*` single-writer no planner.
2. Tornar `tech.exec.*` single-writer no planner.
3. Tornar `macro.opening.*` single-writer em `intel/enemy/opening_intel.py`.
4. Separar `control.priority.*` em namespaces mais precisos.
5. Adicionar writer real para `strategy.advantage.*` ou remover seu uso.
