# Awareness Bus

Este documento define o contrato da `Awareness`, memoria persistente entre ticks.

Awareness e o blackboard do runtime:
- recebe inferencias de Intel
- recebe estado operacional de Ego, Planners, Tasks e Controls
- serve como fonte para decisao no tick atual

---

## Modelo de dados

Fonte: `bot/mind/awareness.py`

Tipos centrais:

```text
Key = tuple[str, ...]
Fact = { value, t, confidence, ttl }
MemoryStore._facts: dict[Key, Fact]
```

Semantica:
- `t`: timestamp em segundos de jogo (`bot.time`)
- `ttl`: validade do fact em segundos
- `confidence`: metadado opcional

API principal:
- `set(key, value, now, ttl=None, confidence=1.0)`
- `get(key, now, default=None, max_age=None)`
- `has(key, now, max_age=None)`
- `age(key, now)`
- `is_stale(key, now, max_age)`
- `snapshot(now, prefix=None, max_age=None)`
- `prune(now, mission_retention_s=120, cooldown_retention_s=60)`

Importante:
- `get(...)` respeita `ttl` e `max_age`
- item expirado pode continuar armazenado ate `prune(...)`

---

## Formato de chave

Construtor oficial:
- `K("a", "b", "c") -> ("a", "b", "c")`

Representacao textual:
- `a:b:c`

Regra:
- evitar chaves achatadas em string no write path
- sempre usar tupla via `K(...)`

---

## Namespaces atuais

### `enemy:*`

Writers principais:
- `intel.opening`
- `intel.enemy_build`
- `intel.weak_points`
- `intel.game_parity`

Chaves relevantes:
- `enemy:opening:*`
- `enemy:rush:*`
- `enemy:aggression:*`
- `enemy:build:*`
- `enemy:army:*`
- `enemy:weak_points:*`
- `enemy:parity:*`

### `strategy:*`

Writer principal:
- `intel.game_parity`

Chaves:
- `strategy:parity:*`

### `macro:*`

Writers principais:
- Intel: `macro:desired:*`, `macro:opening:done*`
- bootstrap: `macro:opening:selected`, `macro:opening:transition_target`
- planners e tasks: `macro:exec:*`, `macro:plan:*`, `macro:morph:*`, `macro:mules:*`

Subgrupos:
- `macro:opening:*`
- `macro:desired:*`
- `macro:exec:*`
- `macro:plan:*`
- `macro:morph:*`
- `macro:mules:*`

### `ops:*`

Writers principais:
- `ego`
- planners
- tasks

Subgrupos:
- `ops:mission:<mission_id>:*`
- `ops:cooldown:<proposal_id>:*`
- `ops:proposal_running:*`
- `ops:harass:*`
- `ops:macro:*`

### `intel:*`

Writers:
- tasks
- scout
- intel

Chaves comuns:
- `intel:scv:*`
- `intel:scan:*`
- `intel:scan:by_label:*`
- `intel:reaper:scout:*`
- `intel:opening:last_emit_t`
- `intel:my_comp:last_emit_t`

### `control:*` e `tech:*`

Writers:
- controls
- planners
- tasks

Chaves:
- `control:priority:*`
- `control:phase`
- `control:pressure:*`
- `tech:exec:*`

### `ego:*`

Writer:
- `ego`

Chaves:
- `ego:exec_budget:*`

---

## Eventos

`Awareness.emit(name, now, data)`:
- salva evento em buffer interno
- envia para logger como `awareness_event` quando log ativo

Leitura:
- `tail_events(n=10)`

Uso recomendado:
- eventos discretos de lifecycle
- nao usar como stream de telemetria de alta frequencia

---

## Politica de retencao

`MemoryStore.prune(...)` executa:
1. remocao de facts expirados por TTL
2. remocao de `ops:mission:<id>:*` apos `mission_retention_s`
3. remocao de `ops:cooldown:<proposal_id>:*` apos `until + cooldown_retention_s`

Sem `prune`, chaves sem TTL podem crescer indefinidamente.

---

## Invariantes

1. Awareness e persistente entre ticks; Attention nao e.
2. Escritas devem ser idempotentes no mesmo tick.
3. Prefixo de chave deve ter owner unico.
4. Timestamps usam segundos de jogo.
5. Ausencia de chave e estado valido e deve ter fallback explicito.

---

## Anti-patterns

1. Gravar blobs gigantes em `value`.
2. Reusar prefixo de outro modulo sem owner definido.
3. Depender de fact expirado sem `max_age`.
4. Usar Awareness para dado estritamente de tick.

---

## Checklist para nova chave

1. Prefixo e owner estao definidos?
2. Tipo de `value` e estavel?
3. TTL esta coerente?
4. Precisa de `last_update_t` sem TTL?
5. Existe risco de crescimento infinito?
6. Existe consumidor real?
