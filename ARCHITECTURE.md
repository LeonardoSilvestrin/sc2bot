# ARES STRATEGIC ARCHITECTURE

## 1. Visão Geral

Esta arquitetura define uma camada estratégica acima do Ares.

Objetivos:

- Separar decisão de execução
- Permitir preempção limpa (ex: cancelar drop para defender)
- Manter macro estável sob pressão
- Ser auditável via logs
- Escalar para adaptação estatística futura
- Não reinventar funcionalidades já fornecidas pelo Ares

Ares continua responsável por:
- Pathfinding
- Unit control básico
- Worker selection
- Build order execution
- Placement
- Squad system

Nossa arquitetura controla:
- Decisão estratégica
- Prioridades
- Seleção de missões
- Preempção
- Orquestração de domínios

---

## 2. Princípios Fundamentais

1. Policy calcula. Não executa.
2. Director orquestra. Não microgerencia.
3. Mission executa com lifecycle formal.
4. Coordinator arbitra conflitos.
5. Macro é serviço contínuo, não entra em leilão.
6. Ownership de unidades é explícito via roles.
7. Toda missão possui abort protocol.
8. Toda decisão relevante é logável.

---

## 3. Componentes do Sistema

### 3.1 Policies (Avaliação Pura)

Características:
- Stateless ou quase.
- Não emitem comandos.
- Produzem sinais derivados do estado.

Principais Policies:

#### ThreatPolicy
Produz:
- ThreatZones
- ThreatIntent (harass / push / all-in)
- DefenseUrgency (por base)

#### StrategicPolicy
Produz:
- StrategicState (AHEAD / EVEN / BEHIND)
- Confidence

#### BudgetPolicy
Produz:
- ScanBudget
- HarassBudget
- RiskTolerance

---

### 3.2 Directors (Orquestradores Stateful)

Características:
- Mantêm estado local
- Propõem missões candidatas
- Aplicam cooldowns
- Não definem modo global

Domínios:

#### StrategyDirector
- Define modo atual
- Define pesos por domínio
- Define budgets
- Define política de preempção

Não cria missões diretamente.

#### DefenseDirector
Propõe:
- HoldBaseMission
- StaticDefenseMission
- PullWorkersEmergencyMission

#### IntelDirector
Propõe:
- WorkerScoutMission
- TacticalScanMission
- SpotterMission

#### MapControlDirector
Propõe:
- ScreenLaneMission
- CreepDenyMission
- ExpansionCheckMission

#### HarassDirector
Propõe:
- DropMission
- RunbyMission
- MultiProngMission (futuro)

#### ProductionDirector
Não usa missões.
Produz:
- ProductionGoals
- CompositionTargets
- TransitionRequests

---

### 3.3 Coordinator

Responsável por:

1. Receber missões candidatas
2. Aplicar pesos definidos pelo StrategyDirector
3. Selecionar missões ativas
4. Resolver conflitos de unidades (roles)
5. Aplicar preempção
6. Garantir mínimos globais

Não decide estratégia.
Não executa micro.

---

## 4. Mission Model

### 4.1 Estrutura

Toda missão possui:

- mission_id
- domain
- priority_base
- commitment_level (LOW / MED / HIGH)
- required_roles
- timeout
- cooldown
- pause_capable
- abort_protocol
- report_schema

---

### 4.2 Lifecycle

Estados:

- PLANNING
- ACTIVE
- PAUSED
- ABORTING
- DONE

---

### 4.3 Commitment Levels

LOW:
- Scout
- Map control
Sempre preemptável.

MED:
- Harass em trânsito
Preemptável dependendo da urgência.

HIGH:
- Engage ativo
- All-in commit
Abortável apenas sob urgência crítica.

---

### 4.4 Abort Protocol

Toda missão deve definir:

- Como liberar roles
- Como dissolver squad
- Para onde redirecionar unidades
- Como reportar motivo de término

---

### 4.5 Mission Report

Toda missão gera:

- start_time
- end_time
- outcome (success / abort / timeout)
- resources_used
- units_lost
- damage_done
- intel_gained

Permite adaptação futura.

---

## 5. State Global (Blackboard + Signals)

### 5.1 IntelState

- LastKnownEnemyArmyPosition
- KnownEnemyTechFlags
- KnownEnemyBases
- Staleness
- Confidence

---

### 5.2 ThreatZones

Para cada base/região:

- enemy_count
- enemy_power_estimate
- severity_score

---

### 5.3 DefenseUrgency

Para cada base:

- severity (0–100)
- time_to_impact
- threat_type
- confidence

---

### 5.4 StrategicState

- AHEAD
- EVEN
- BEHIND
- confidence

---

## 6. Modos Globais

### OPENING
- BuildRunner dominante
- Defense médio
- Harass baixo

### SAFE_MACRO
- Growth ativo
- MapControl médio
- Harass moderado

### PRESSURE
- Harass alto
- MapControl alto
- Defense médio

### DEFEND
- Defense alto
- Harass baixo
- MapControl reduzido

### EMERGENCY_DEFENSE
- Defense máximo
- Harass pausado
- MapControl mínimo
- Preempção agressiva

### CLOSE_OUT (futuro)
- Negar bases
- Conter inimigo
- Finalizar jogo

Cada modo define:
- Pesos por domínio
- Budgets
- Política de preempção

---

## 7. Macro Model

Macro é contínua e dividida em camadas.

### Vital Loop (sempre ativo)
- Supply safety
- Worker mínimo
- Estruturas essenciais

### Growth Loop
- Expandir
- Saturar
- Upgrades

### Greed Loop
- Expansão agressiva
- Tech pesado

Modos podem desabilitar Growth/Greed.
Vital nunca é totalmente desativado.

---

## 8. Preempção

### Soft Preempt
- Pausa missão
- Reavalia quando urgência cair

### Hard Preempt
- Aborta missão
- Libera roles
- Ativa defesa

### Sem Preempção
- Defesa local suficiente disponível

---

## 9. Integração com Ares

Não reimplementar:

- Pathfinding
- Worker selection
- Unit grouping
- Build order logic
- Placement

Missões devem:

- Usar UnitRole para ownership
- Usar squads do Ares
- Usar mediator
- Usar BuildRunner

---

## 10. Logging Obrigatório

Registrar:

- Modo atual
- DefenseUrgency
- Top mission candidates (score)
- Missões selecionadas
- Preempções
- Motivo de término de missão

---

## 11. Ordem Recomendada de Implementação

1. MissionRegistry + Coordinator + DefenseUrgency
2. DefenseDirector MVP
3. IntelDirector MVP
4. MapControlDirector MVP
5. HarassDirector MVP
6. Production refinement
7. Adaptação estatística