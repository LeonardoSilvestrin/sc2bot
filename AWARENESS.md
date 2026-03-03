# Awareness Bus

Este documento define o contrato da **Awareness**: memoria persistente entre ticks.

Awareness e o blackboard do runtime:
- recebe inferencias de Intel
- recebe estado operacional de Ego/Planners/Tasks/Controls
- serve de fonte para decisao no tick atual

---

# Modelo de Dados

Fonte: `bot/mind/awareness.py`

Tipos centrais:

```text
Key = tuple[str, ...]
Fact = { value, t, confidence, ttl }
MemoryStore._facts: dict[Key, Fact]
```

Semantica:
- `t`: timestamp em segundos de jogo (`bot.time`)
- `ttl`: validade do fact em segundos; `None` = sem expiracao automatica
- `confidence`: metadado opcional (padrao `1.0`)

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
- item expirado nao e removido imediatamente; apenas deixa de ser retornado
- limpeza fisica ocorre em `prune(...)`

---

# Formato de Chave

Construtor oficial:
- `K("a", "b", "c") -> ("a","b","c")`

Representacao textual para debug/snapshot:
- `a:b:c`

Regra:
- evitar chaves string "achatadas" no write path
- sempre usar tupla via `K(...)`

---

# Namespaces Atuais (Contrato Vivo)

## 1) `enemy:*` (intel de inimigo)

Writers principais: `intel.opening`, `intel.enemy_build`, `intel.weak_points`, `intel.game_parity`.

Chaves relevantes:
- `enemy:opening:*`
- `enemy:rush:*`
- `enemy:aggression:*`
- `enemy:build:*`
- `enemy:army:*`
- `enemy:weak_points:*`
- `enemy:parity:*`

---

## 2) `strategy:*` (sintese estrategica)

Writer principal: `intel.game_parity`.

Chaves:
- `strategy:parity:*`

---

## 3) `macro:*` (estado desejado e execucao macro)

Writers principais:
- Intel: `macro:desired:*`, `macro:opening:done*`
- Runtime bootstrap: `macro:opening:selected`, `macro:opening:transition_target`
- Planners/tasks: `macro:exec:*`, `macro:plan:*`, `macro:morph:*`, `macro:mules:*`

Subgrupos:
- `macro:opening:*`
- `macro:desired:*`
- `macro:exec:*`
- `macro:plan:*`
- `macro:morph:*`
- `macro:mules:*`

---

## 4) `ops:*` (lifecycle operacional)

Writers principais: `ego`, planners e tasks.

Subgrupos:
- `ops:mission:<mission_id>:*`
- `ops:cooldown:<proposal_id>:*`
- `ops:proposal_running:*` (leitura helper)
- `ops:harass:*`
- `ops:macro:*`

Missoes registram:
- `status`, `domain`, `proposal_id`, `started_at`, `expires_at`, `assigned_tags`
- `original_assigned_tags`, `original_type_counts`
- encerramento: `reason`, `ended_at`

---

## 5) `intel:*` (bookkeeping e telemetria da camada)

Writers: tasks/scout/intel.

Chaves comuns:
- `intel:scv:*`
- `intel:scan:*`
- `intel:scan:by_label:*`
- `intel:reaper:scout:*`
- `intel:opening:last_emit_t`
- `intel:my_comp:last_emit_t`

---

## 6) `control:*` e `tech:*`

Writers: controls/planners/tasks.

Chaves:
- `control:priority:*`
- `control:phase`
- `control:pressure:*`
- `tech:exec:*`

---

## 7) `ego:*`

Writer: `ego`.

Chaves:
- `ego:exec_budget:*`

---

# Eventos de Awareness

`Awareness.emit(name, now, data)`:
- salva evento em buffer interno (`_events`, cap 200)
- envia para logger como `awareness_event` quando log ativo

Leitura:
- `tail_events(n=10)`

Uso recomendado:
- eventos discretos de lifecycle
- nao usar como stream de telemetria de alta frequencia

---

# Politica de Retencao e Prune

`MemoryStore.prune(...)` executa tres limpezas:

1. Remove facts expirados por TTL.
2. Remove arvores `ops:mission:<id>:*` apos `mission_retention_s` desde `ended_at`.
3. Remove arvores `ops:cooldown:<proposal_id>:*` apos `until + cooldown_retention_s`.

Observacao:
- sem `prune`, chaves sem TTL podem crescer indefinidamente.

---

# Invariantes de Contrato

1. Awareness e persistente entre ticks; Attention nao e.
2. Escritas devem ser idempotentes no mesmo tick (sobrescrever mesma chave e aceitavel).
3. Prefixo de chave deve ter owner unico.
4. Chaves com timestamp devem usar segundos de jogo (`bot.time`).
5. Consumidores devem tratar ausencia de chave como estado valido (fallback explicito).

---

# Anti-patterns

1. Gravar blobs gigantes sem necessidade em `value`.
2. Reusar prefixo de outro modulo sem owner definido.
3. Depender de fact expirado sem `max_age`/fallback.
4. Usar Awareness como substituto de schema tipado quando o dado e estritamente de tick (deveria estar em Attention).

---

# Checklist para Nova Chave

1. Prefixo e owner estao definidos?
2. Tipo de `value` e estavel para consumidores?
3. TTL esta correto para volatilidade do sinal?
4. Precisa de `last_update_t` sem TTL?
5. Existe risco de crescimento infinito? Se sim, ha prune/retention?
6. Existe consumidor real documentado?
