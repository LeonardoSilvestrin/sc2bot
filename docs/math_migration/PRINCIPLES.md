# Principles

The rules the mathematical migration keeps. Short on purpose; the component
docs under `docs/` carry the detail. Progress lives in [STATUS.md](STATUS.md).

## Facts, beliefs, prescriptions

| Kind | Layer | Examples | Never |
| --- | --- | --- | --- |
| Fact | Attention | flying, worker, can attack ground/air, health, readiness, position, supply cost | remembered, inferred or subjective |
| Belief | Awareness | enemy memory, army/economy estimates with confidence, base security, spatial field, territory | desired state, objective, intent, priority, policy, controller state |
| Prescription | Strategy | objective, `StrategicIntent`, `ControlObjective` | a unit, a target point for a unit, a mission priority |

A subjective number ("mobility = 0.8", "siege = 0.7") is policy. It lives
with the decision that uses it, never beside the facts.

## Pipeline and owners

```text
Game / Ares -> Attention -> Awareness -> Strategy -> StrategicContext
            -> behavior planners (concrete candidates, local evidence)
            -> Mission Policy (cross-behavior value, viability)
            -> viable MissionProposal -> MissionController (lifecycle, admission)
            -> UnitAllocator (leases, preemption) -> executors (leased units only)

Attention + Awareness + explicit macro context -> MacroPlanner
            -> EconomyController -> EconomyCommands
```

| Decision | Sole owner |
| --- | --- |
| what is observable now | Attention |
| what is believed, and how surely | Awareness |
| what matters, what state is wanted | Strategy |
| tactical target, supported units, local evidence | the behavior |
| worth against other missions, viability | Mission Policy |
| mission lifecycle | `MissionController` |
| unit leases | `UnitAllocator` |
| commands | executors, through ports |
| wiring, context transport | `bot.app` |

The engine stays blind to Strategy and to behavior concepts. Changing a
boundary needs the reason and the replacement invariant in STATUS.md first.

## Units are requested concretely

A behavior names the unit types its planner and executor actually know how
to use, with a local per-type preference when it needs one. The allocator
enforces the requirement (types, counts, supply, health, readiness,
ownership); it never infers tactical meaning from a global capability sheet.
A new unit type joins a behavior by an explicit roster decision.

## One price per factor

Every factor -- risk, urgency, information, strategic desirability, a control
objective's importance and gap -- is priced once per decision. A planner may
weigh them all to choose its target; it then reports the target's local value
as opportunity, and the factors as their own signals. Target selection and
cross-mission valuation are separate decisions, each with its own documented
terms.

## Explanations are the evaluation

A decision's calculation returns an immutable, model-specific record: result,
components, machine-readable reason. Logs serialize that record, exactly.
Nothing recomputes an explanation after deciding.

## Replace implementations, not the architecture

A mathematical model replaces the calculation inside an owner, behind the
same seam. Keep calculations local and pure; lock their behavior with
relational invariants and small replay fixtures before swapping them.

## No framework without repeated evidence

No universal Score, Feature, Rule, Capability, Explanation or decision-node
type; no rule engine, behavior tree, event sourcing or "AI brain". Strategy,
the Mission Policy, spatial selection, macro and each behavior keep their own
evaluation types until the same shape is demonstrably needed several times.
