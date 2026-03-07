# Intel Bus

Este documento define o contrato da camada `Intel`: como fatos do tick em `Attention` viram inferencia persistente em `Awareness`.

Pipeline oficial:

```text
Attention (tick) -> Intel (derive_*) -> Awareness.mem (persistente)
```

Intel:
- le `Attention`
- pode ler `Awareness`
- escreve inferencia em `Awareness`
- nao comanda unidades

---

## Ordem de execucao por tick

Fonte: `bot/mind/self.py` (`RuntimeApp.on_step`)

Ordem atual:
1. `derive_opening_contract_intel(...)`
2. `derive_attention(...)`
3. `derive_enemy_opening_intel(...)`
4. `derive_enemy_build_intel(...)`
5. `derive_my_army_composition_intel(...)`
6. `derive_game_parity_intel(...)`

Racional:
- opening e rush alimentam macro mode
- enemy build e weak points alimentam planners de harass e scan
- macro desired e parity fecham o contexto para planners macro

---

## Modulos e contratos

### Opening Contract Intel

Arquivo:
- `bot/intel/enemy/opening_contract.py`

Responsabilidade:
- publicar status contratual do opening para sensores, planners e controls

Escreve:
- `macro:opening:done`
- `macro:opening:done_reason`
- `macro:opening:done_owner`

### Enemy Opening Intel

Arquivo:
- `bot/intel/opening_intel.py`

Entradas principais:
- `attention.enemy_build.*`
- estado previo em `enemy:rush:*` e `enemy:opening:*`

Saidas:
- `enemy:opening:*`
- `enemy:rush:*`
- `enemy:aggression:*`
- `intel:opening:last_emit_t`

Regras importantes:
- `rush_state` pode virar `SUSPECTED` ou `HOLDING` por evidencia estrutural
- apos o fim da janela early, rush ativo e forcado para `ENDED`

### Enemy Build e Weak Points Intel

Arquivo:
- `bot/intel/enemy_build_intel.py`

Responsabilidade:
- consolidar visao de composicao e estrutura inimiga
- atualizar weak points

Escreve:
- `enemy:build:*`
- `enemy:army:*`
- `enemy:weak_points:*`

### My Army Composition Intel

Arquivo:
- `bot/intel/my_army_composition_intel.py`

Responsabilidade:
- gerar objetivo macro desejado para controladores e planners

Sub-modulos:
- `derive_macro_mode_intel(...)`
- `derive_army_comp_intel(...)`
- `derive_tech_intel(...)`

Escreve:
- `macro:desired:*`
- `intel:my_comp:last_emit_t`

### Game Parity Intel

Arquivo:
- `bot/intel/game_parity_intel.py`

Responsabilidade:
- estimar paridade economica e militar
- produzir bias estrategico

Escreve:
- `enemy:parity:*`
- `strategy:parity:*`

---

## Ownership de chaves

Owners atuais:
- `enemy:opening:*`, `enemy:rush:*`, `enemy:aggression:*` -> `intel.opening`
- `enemy:build:*`, `enemy:army:*` -> `intel.enemy_build`
- `enemy:weak_points:*` -> `intel.weak_points`
- `macro:desired:*` -> `intel.my_comp`
- `enemy:parity:*`, `strategy:parity:*` -> `intel.game_parity`
- `macro:opening:done*` -> `intel.opening_contract`

Se outro modulo escrever no mesmo prefixo, o override deve ser explicito e documentado.

---

## Invariantes

1. Intel nao emite comando de unidade.
2. Intel escreve em `Awareness.mem` com TTL adequado ao sinal.
3. Sinais persistentes ficam em Awareness, nao em Attention.
4. `last_update_t` e `*_last_emit_t` ficam sem TTL.
5. Violacao de contrato deve falhar rapido.

---

## Checklist para novo intel

1. Le apenas `Attention` e `Awareness`?
2. Publica chaves namespaceadas com owner claro?
3. Define TTL para sinais volateis?
4. Evita duplicar inferencia existente?
5. Tem observabilidade minima?
6. Consumidores estao documentados?
