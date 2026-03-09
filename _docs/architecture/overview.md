# Arquitetura Atual

Arquitetura oficial do bot com base no codigo atual de `bot/mind/self.py`.

Modelo:

`Sensors -> Attention -> Intel -> Awareness -> Planners -> Ego -> Tasks -> Ares/python-sc2`

O ponto novo e a pilha espacial:

`pathing/presence/frontline -> world compression -> operational geometry -> territorial control -> army posture`

---

## Principios

1. `Sensors` so leem estado do jogo.
2. `Attention` e snapshot imutavel do tick.
3. `Intel` escreve inferencia persistente em `Awareness`.
4. `OperationalGeometry` decide a forma espacial ativa, nao micro por unidade.
5. `TerritorialControl` transforma linhas defensivas em zonas e slots funcionais.
6. `Planners` propoem missoes; nao comandam unidades.
7. `Ego` continua sendo o arbitro unico de admissao, claims e lifecycle.
8. `Tasks` sao a unica camada que emite comandos no jogo.

---

## Topologia

Entradas principais:
- `run.py`
- `bot/main.py`
- `bot/mind/self.py`

Componentes centrais:
- `Sensors`: `bot/sensors/*`
- `Attention`: `bot/mind/attention.py`
- `Intel`: `bot/intel/*`
- `Awareness`: `bot/mind/awareness.py`
- `Planners`: `bot/planners/*`
- `Ego`: `bot/mind/ego.py`
- `Tasks`: `bot/tasks/*`
- `Body/Leases`: `bot/mind/body.py`

Planners registrados no runtime:
- `DefensePlanner`
- `HarassPlanner`
- `ReinforceMissionPlanner`
- `IntelPlanner`
- `MapControlPlanner`
- `WallPlanner`
- `HousekeepingPlanner`
- `OpeningPlanner` inline no runtime
- `PushPlanner` inline no runtime
- `MacroOrchestratorPlanner`

---

## Fluxo Por Tick

Sequencia em `RuntimeApp.on_step`:

1. `derive_opening_contract_intel(...)`
2. `publish_ground_avoidance_sensor(...)`
3. `attention = derive_attention(...)`
4. `derive_enemy_opening_intel(...)`
5. `apply_opening_request(...)` e sync com build runner
6. `derive_enemy_build_intel(...)`
7. `derive_my_army_composition_intel(...)`
8. `derive_game_parity_intel(...)`
9. `derive_pathing_flow_intel(...)`
10. `derive_pathing_route_intel(...)`
11. `derive_enemy_presence_intel(...)`
12. `derive_map_control_intel(...)`
13. `derive_frontline_intel(...)`
14. `derive_world_compression(...)`
15. `derive_operational_geometry(...)`
16. `derive_territorial_control_intel(...)`
17. `derive_army_posture_intel(...)`
18. `derive_mission_unit_threat_intel(...)`
19. `derive_mission_value_intel(...)`
20. `advantage_game_status_intel.derive(...)`
21. `ego.tick(...)`

Dentro de `Ego.tick`:
1. limpa leases e commitments expirados
2. coleta propostas de todos planners
3. valida `Proposal`
4. ordena por `score`
5. tenta admissao e claim de unidades
6. executa tasks ativas
7. persiste estado operacional em `Awareness`

---

## Camadas Espaciais

### 1. Frontline Intel

Responsabilidade:
- publicar estado das frentes principais
- main e natural viram snapshots com `ground_state`, `forward_anchor`, `fallback_anchor`, poder aliado e inimigo

Uso:
- insumo para geometria, defesa e anchors territoriais

### 2. World Compression

Arquivo:
- `bot/intel/geometry/i1_world_compression_intel.py`

Responsabilidade:
- condensar `frontline`, rush, parity, map control e route pressure em um vetor compacto

Saida principal:
- `intel:geometry:world:compression`

Sinais principais:
- `pressure_main`
- `pressure_nat`
- `pressure_outer`
- `expansion_commit`
- `push_commit`
- `mobility_need`
- `map_presence_need`
- `army_strength_rel`
- `drop_risk`
- `air_risk`

### 3. Operational Geometry

Arquivo:
- `bot/intel/geometry/i2_operational_geometry_intel.py`

Responsabilidade:
- escolher o template espacial ativo
- derivar setores operacionais do mapa
- calcular `actual_power`, `target_power`, `bulk_sector`, `max_detach_supply` e `reserved_zones`

Templates atuais:
- `HOLD_MAIN`
- `TURTLE_NAT`
- `STABILIZE_AND_EXPAND`
- `CONTAIN`
- `PREP_PUSH`

Setores atuais:
- `HOME_CORE`
- `MAIN_RAMP`
- `RETREAT_BUFFER`
- `NAT_FOOTPRINT`
- `NAT_RING`
- `NAT_CHOKE`
- `MID_APPROACH`
- `WATCH_AREA`
- `THIRD_ENTRY`
- `PUSH_STAGING`

Invariantes operacionais:
- `NAT_FOOTPRINT` reservado nao deve receber bulk
- o bulk pertence a um unico setor `MASS_HOLD`
- `max_detach_supply` limita quanto a defesa local pode recrutar fora do bulk
- histerese temporal e de urgencia evitam pinga-ponga de template

### 4. Territorial Control

Arquivo:
- `bot/intel/locations/i6_territorial_control_intel.py`

Responsabilidade:
- elevar a defesa de "base" para "linha -> zona -> slot funcional"
- publicar `control_score`, `threat_score`, `missing_roles`, `active_slots` e `active_line`

Linhas atuais:
- `main_ramp_line`
- `natural_line`
- `third_line`

Zonas atuais:
- `main_ramp`
- `natural_front`
- `third_front`

Slots funcionais:
- `siege_anchor`
- `fallback_anchor`
- `screen_front`
- `screen_left`
- `screen_right`
- `rear_support`
- `vision_spot`

### 5. Army Posture

Arquivo:
- `bot/intel/strategy/i3_army_posture_intel.py`

Responsabilidade:
- manter compatibilidade com o sistema legado
- traduzir template geometrico em `ArmyPosture`
- publicar `anchor`, `secondary_anchor`, `max_detach_supply` e `min_bulk_supply`

Hoje a postura e derivada da geometria sempre que ela existe.

---

## Planners No Modelo Atual

### MapControlPlanner

Responsabilidade:
- dono do bulk do exercito
- ler `intel:geometry:operational:snapshot`
- propor `HoldAnchorTask` para o setor `MASS_HOLD`
- propor `SecureBaseTask` para destacamentos locais
- usar anchors territoriais da natural quando disponiveis

Limitacao atual:
- continua parcialmente NAT-centric para `SecureBaseTask`
- a iteracao completa por todos os `sector_states` ativos ainda nao foi concluida

### DefensePlanner

Responsabilidade:
- respostas reativas por ameaca
- propor `DefendBaseTask`, `ScvDefensivePullTask`, `ScvRepairTask`, `HoldRampTask`, `DefenseBunkerTask`, `LiftNaturalTask`
- preferir anchors territoriais e respeitar a geometria

Guardrails atuais:
- budget sempre deriva de `max_detach_supply`
- unidades dentro do raio de exclusao do `bulk_anchor_pos` nao entram no pick defensivo
- `defense_overflow` amplia budget, mas nao remove a protecao espacial do bulk

### MacroOrchestratorPlanner

Responsabilidade:
- centralizar `macro:plan:*`, `macro:exec:*`, `tech:exec:*` e `control:*`
- virar o writer principal da camada de execucao macro

---

## Invariantes

1. `Attention` nao persiste estado entre ticks.
2. `Intel` nao emite comandos.
3. `Planners` nao executam micro.
4. `Ego` arbitra ownership, cooldown e admissao.
5. `MapControlPlanner` e dono do bulk; `DefensePlanner` e reativo.
6. `Tasks` sao a unica camada que comanda unidades.
7. Mudancas de contrato em `Attention` ou `Awareness` exigem atualizar `_docs`.
