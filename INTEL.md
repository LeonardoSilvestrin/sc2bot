# Intel Bus

Este documento define o contrato da camada **Intel**: como fatos do tick (Attention) viram inferencia persistente (Awareness).

Pipeline oficial:

```text
Attention (tick) -> Intel (derive_*) -> Awareness.mem (persistente)
```

Intel:
- le `Attention` e, quando necessario, le `Awareness`
- escreve inferencia/sinais em `Awareness`
- NAO comanda unidades (sem `move/attack/train/register_behavior`)

---

# Ordem de Execucao por Tick

Fonte: `bot/mind/self.py` (`RuntimeApp.on_step`).

Ordem atual:
1. `derive_opening_contract_intel(...)`
2. `derive_attention(...)`
3. `derive_enemy_opening_intel(...)`
4. `derive_enemy_build_intel(...)` (inclui weak points)
5. `derive_my_army_composition_intel(...)`
6. `derive_game_parity_intel(...)`

Racional da ordem:
- opening/rush/aggression alimenta macro mode
- enemy build/weak points alimenta planners de harass/scan
- macro desired e parity fecham o contexto estrategico para planners de macro

---

# Modulos Intel e Contratos

## 1) Opening Contract Intel

Arquivo: `bot/intel/enemy/opening_contract.py`

Responsabilidade:
- publicar status contratual do opening para sensores/planners/controls

Escreve (TTL curto ~5s):
- `macro:opening:done`
- `macro:opening:done_reason`
- `macro:opening:done_owner`

Observacao:
- pode completar o opening por assinatura de composicao/estrutura (nao so por BuildOrderRunner).

---

## 2) Enemy Opening Intel

Arquivo: `bot/intel/opening_intel.py`

Entradas principais:
- `attention.enemy_build.*`
- estado previo em `enemy:rush:*` e `enemy:opening:*`

Saidas:
- opening:
  - `enemy:opening:first_seen_t` (sem TTL)
  - `enemy:opening:kind` (TTL)
  - `enemy:opening:confidence` (TTL)
  - `enemy:opening:signals` (TTL)
  - `enemy:opening:last_update_t` (sem TTL)
- rush:
  - `enemy:rush:state` (TTL dinamico)
  - `enemy:rush:confidence` (TTL dinamico)
  - `enemy:rush:score` (TTL dinamico)
  - `enemy:rush:evidence` (TTL dinamico)
  - `enemy:rush:last_seen_pressure_t` (sem TTL)
  - `enemy:rush:last_update_t` (sem TTL)
  - `enemy:rush:last_confirmed_t` (sem TTL)
  - `enemy:rush:ended_t` (sem TTL)
  - `enemy:rush:ended_reason` (sem TTL)
  - `enemy:rush:workers_peak_seen` (sem TTL)
- aggression:
  - `enemy:aggression:state` (TTL)
  - `enemy:aggression:confidence` (TTL)
  - `enemy:aggression:source` (TTL)
- observabilidade:
  - `intel:opening:last_emit_t` (sem TTL)

Regras importantes:
- `rush_state` pode ser ajustado para `SUSPECTED/HOLDING` por evidencia estrutural e janela temporal.
- apos fim da janela early, rush ativo e forçado para `ENDED`.

---

## 3) Enemy Build + Weak Points Intel

Arquivo: `bot/intel/enemy_build_intel.py`

Responsabilidade:
- consolidar visao de composicao/estrutura inimiga observada
- calcular resumo de army comp
- atualizar weak points via `derive_enemy_weak_points_intel(...)`

Escreve (TTL tipico ~15s, exceto timestamps):
- `enemy:build:snapshot`
- `enemy:build:units`
- `enemy:build:structures`
- `enemy:build:units_main`
- `enemy:build:structures_main`
- `enemy:build:structures_progress`
- `enemy:army:comp_summary`
- `enemy:army:last_update_t` (sem TTL)
- `enemy:build:last_seen_t` (sem TTL)
- `enemy:build:last_seen_main_t` (sem TTL, quando houver observacao main)

Weak points (via `bot/intel/weak_points_intel.py` + `state_store.py`):
- `enemy:weak_points:snapshot` (TTL)
- `enemy:weak_points:points` (TTL)
- `enemy:weak_points:primary` (TTL)
- `enemy:weak_points:bases_visible` (TTL)
- `enemy:weak_points:last_update_t` (sem TTL)

---

## 4) My Army Composition Intel

Arquivo: `bot/intel/my_army_composition_intel.py`

Responsabilidade:
- gerar objetivo macro desejado (mode + comp + tech) para controladores/planners

Executa sub-modulos:
- `derive_macro_mode_intel(...)`
- `derive_army_comp_intel(...)`
- `derive_tech_intel(...)`

### 4.1 Macro Mode
Arquivo: `bot/intel/macro_mode_intel.py`

Escreve:
- `macro:desired:mode` (TTL)
- `macro:desired:signals` (TTL)
- `macro:desired:last_update_t` (sem TTL)

Modes atuais:
- `RUSH_RESPONSE`
- `DEFENSIVE`
- `STANDARD`
- `PUNISH`

### 4.2 Army Comp
Arquivo: `bot/intel/army_comp_intel.py`

Escreve:
- `macro:desired:comp`
- `macro:desired:controller_comp`
- `macro:desired:army_comp`
- `macro:desired:priority_units`
- `macro:desired:reserve_unit`
- `macro:desired:reserve_minerals`
- `macro:desired:reserve_gas`
- `macro:desired:bank_target_minerals`
- `macro:desired:bank_target_gas`
- `macro:desired:pid_tuning`
- `macro:desired:army_supply_milestones`
- `macro:desired:unit_count_milestones`
- `macro:desired:timing_attacks`

Todos com TTL do modulo.

### 4.3 Tech
Arquivo: `bot/intel/tech_intel.py`

Escreve:
- `macro:desired:production_structure_targets`
- `macro:desired:production_scale`
- `macro:desired:tech_structure_targets`
- `macro:desired:tech_timing_milestones`
- `macro:desired:tech_targets`
- `macro:desired:construction_targets`

Todos com TTL do modulo.

### 4.4 Emissao de log do bloco
Arquivo: `bot/intel/my_army_composition_intel.py`

Escreve:
- `intel:my_comp:last_emit_t` (sem TTL)

---

## 5) Game Parity Intel

Arquivo: `bot/intel/game_parity_intel.py`

Responsabilidade:
- estimar paridade econ/army e produzir bias estrategico

Requisitos de contrato:
- `bot.mediator.get_own_army_dict`
- `bot.mediator.get_enemy_army_dict`

Escreve:
- estimativas inimigas (TTL):
  - `enemy:parity:workers_est`
  - `enemy:parity:bases_est`
  - `enemy:parity:army_power_est`
- estrategia/paridade (TTL, exceto last_update):
  - `strategy:parity:overall`
  - `strategy:parity:econ`
  - `strategy:parity:army`
  - `strategy:parity:expand_bias`
  - `strategy:parity:army_bias`
  - `strategy:parity:severity:army_behind`
  - `strategy:parity:severity:army_ahead`
  - `strategy:parity:severity:econ_behind`
  - `strategy:parity:severity:econ_ahead`
  - `strategy:parity:state`
  - `strategy:parity:signals`
  - `strategy:parity:last_update_t` (sem TTL)

---

# Ownership de Chaves (Intel)

Regra: cada prefixo deve ter owner explicito.

Owners atuais:
- `enemy:opening:*`, `enemy:rush:*`, `enemy:aggression:*` -> `intel.opening`
- `enemy:build:*`, `enemy:army:*` -> `intel.enemy_build`
- `enemy:weak_points:*` -> `intel.weak_points`
- `macro:desired:*` -> `intel.my_comp` (subowners: macro_mode/army_comp/tech)
- `enemy:parity:*`, `strategy:parity:*` -> `intel.game_parity`
- `macro:opening:done*` -> `intel.opening_contract`

Se outro modulo precisar escrever no mesmo prefixo, documentar override explicitamente.

---

# Invariantes

1. Intel nao emite comando de unidade.
2. Intel escreve em `Awareness.mem` com TTL adequado ao sinal.
3. Sinais de decisao persistente ficam em Awareness, nao em Attention.
4. Chaves `last_update_t` e `*_last_emit_t` devem ficar sem TTL.
5. Violacao de contrato deve falhar rapido; nao mascarar com fallback implicito.

---

# Checklist para Novo Intel

1. Le apenas `Attention` + `Awareness` (sem side effects externos)?
2. Publica chaves namespaceadas e com owner claro?
3. Define TTL para sinais volateis e sem TTL para marcos historicos?
4. Evita duplicar inferencia que ja existe em outro intel?
5. Tem observabilidade minima (chave de tempo ou evento/log)?
6. Consumidores (planners/controls/tasks) estao documentados?
