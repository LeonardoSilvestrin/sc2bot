# Awareness Bus

`Awareness` e a memoria persistente entre ticks.

Fonte:
- `bot/mind/awareness.py`

Ela guarda:
- inferencias de intel
- estado operacional de planners, ego e tasks
- cooldowns
- indices de missoes em execucao

---

## Modelo De Dados

Tipos centrais:

```text
Key = tuple[str, ...]
Fact = { value, t, confidence, ttl }
MemoryStore._facts: dict[Key, Fact]
```

Semantica:
- `t`: segundos de jogo (`bot.time`)
- `ttl`: validade opcional em segundos
- `confidence`: metadado numerico opcional

API principal:
- `set(key, value, now, ttl=None, confidence=1.0)`
- `get(key, now, default=None, max_age=None)`
- `has(key, now, max_age=None)`
- `age(key, now)`
- `is_stale(key, now, max_age)`
- `snapshot(now, prefix=None, max_age=None)`
- `prune(now, mission_retention_s=120, cooldown_retention_s=60)`

---

## Formato De Chave

Construtor oficial:
- `K("a", "b", "c") -> ("a", "b", "c")`

Representacao textual:
- `a:b:c`

Regra:
- usar sempre tupla no write path
- evitar strings achatadas como chave canonica

---

## Recursos Extras Da Classe `Awareness`

### Eventos

API:
- `emit(name, now, data=None)`
- `tail_events(n=10)`

Uso:
- lifecycle discreto
- observabilidade

Nao usar para stream de alta frequencia.

### Indice De Proposals Em Execucao

Metodos:
- `ops_proposal_running(...)`
- `mark_mission_running(...)`
- `mark_mission_ended(...)`

Objetivo:
- evitar scan completo do namespace `ops:mission:*` a cada tick

### Helpers De Scout

Helpers embutidos:
- `intel_scv_dispatched`
- `intel_scv_arrived_main`
- `intel_scanned_enemy_main`
- `mark_scv_dispatched`
- `mark_scv_arrived_main`
- `mark_scanned_enemy_main`
- `intel_reaper_scout_dispatched`
- `mark_reaper_scout_dispatched`
- `mark_reaper_scout_done`

---

## Namespaces Mais Importantes

### Enemy e estrategia

- `enemy:opening:*`
- `enemy:rush:*`
- `enemy:aggression:*`
- `enemy:build:*`
- `enemy:army:*`
- `enemy:weak_points:*`
- `strategy:parity:*`
- `strategy:army:*`

### Geometria e territorio

- `intel:frontline:*`
- `intel:geometry:world:*`
- `intel:geometry:operational:*`
- `intel:geometry:sector:*`
- `intel:territory:defense:*`

### Macro

- `macro:opening:*`
- `macro:desired:*`
- `macro:control:*`
- `macro:plan:*`
- `macro:exec:*`
- `macro:gas:*`
- `macro:morph:*`
- `macro:mules:*`
- `tech:exec:*`

### Operacional

- `ops:mission:<mission_id>:*`
- `ops:cooldown:<proposal_id>:*`
- `ops:proposal_running:*`
- `ops:defense:*`
- `ops:map_control:*`
- `ops:harass:*`
- `ops:wall:*`
- `ops:macro:*`

### Utilitarios e scouting

- `intel:scan:*`
- `intel:scan:by_label:*`
- `intel:worker_scout:*`
- `intel:reaper:scout:*`
- `intel:scv:*`

---

## Politica De Retencao

`prune(...)` remove:

1. facts expirados por TTL
2. arvores `ops:mission:<id>:*` apos `mission_retention_s`
3. entradas `ops:cooldown:<proposal_id>:*` apos `until + cooldown_retention_s`

Sem `prune`, chaves sem TTL crescem indefinidamente.

---

## Invariantes

1. `Awareness` persiste entre ticks; `Attention` nao.
2. Prefixo deve ter writer principal claro.
3. Leitura de sinal velho deve usar `max_age` quando relevante.
4. Chaves sem TTL precisam de controle explicito de crescimento.
5. Estado estritamente do tick nao deve ir para `Awareness`.
