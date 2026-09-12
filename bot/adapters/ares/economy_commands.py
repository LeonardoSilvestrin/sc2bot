from __future__ import annotations

from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.engine.economy.models import (
    EconomicAction,
    EconomicActionKind,
    EconomicFeedback,
    EconomicFeedbackKind,
)


class AresEconomyCommands:
    """Translate one funded economic action into an Ares macro operation.

    The Ares side of ``bot.ports.EconomyCommands``. Behaviors are executed
    here, after Ares updated its managers for the frame, so the economy
    controller receives truthful dispatch feedback. Strategic decisions
    (``bot.macro``) and resource arbitration (``bot.engine.economy``) remain
    outside this adapter. So does unit ownership: the SCV an Ares behavior
    picks to lay a structure is its builder selection, not a mission lease.

    Ares' own macro behaviors (``SpawnController``, ``BuildStructure``, ...)
    are built to be invoked every frame until their goal is met -- one call
    only ever produces one unit of progress (one train order, one worker sent
    to build). ``EconomyController.step`` therefore calls ``dispatch`` again
    on every tick while an action is pending. Once the adapter accepts a
    command the action becomes in-flight and is not issued again -- except a
    train order, which is confirmed outright (see ``dispatch``). A ``False``
    return here means "nothing to do this frame". It is
    acknowledged as ``WAITING`` with the most useful operational reason we
    can observe; silence is reserved for an adapter that genuinely supplied
    no feedback, and is what the controller's dispatch timeout watches.
    """

    def __init__(self, bot) -> None:
        self._bot = bot

    def dispatch(self, action: EconomicAction) -> EconomicFeedback | None:
        try:
            dispatched = self._execute(action)
        except Exception as error:
            return EconomicFeedback(
                action_id=action.action_id,
                kind=EconomicFeedbackKind.FAILED,
                reason=f"ares_dispatch_error:{type(error).__name__}:{error}",
            )

        if not dispatched:
            return EconomicFeedback(
                action_id=action.action_id,
                kind=EconomicFeedbackKind.WAITING,
                reason=self._waiting_reason(action),
            )

        if action.proposal.kind in {
            EconomicActionKind.PRODUCE_WORKER,
            EconomicActionKind.PRODUCE_UNIT,
        }:
            # `SpawnController` only reports progress after calling `train()`,
            # so the purchase has already happened. Left in flight, the action
            # would wait for Attention to count `target_count`, which never
            # happens if a unit of that type dies first -- and until the
            # confirmation timeout it blocks every further unit of that type,
            # exactly when the army needs replacing.
            return EconomicFeedback(
                action_id=action.action_id,
                kind=EconomicFeedbackKind.CONFIRMED,
                reason="ares_train_order_issued",
            )

        return EconomicFeedback(
            action_id=action.action_id,
            kind=EconomicFeedbackKind.DISPATCHED,
            reason="ares_command_accepted",
        )

    def _execute(self, action: EconomicAction) -> bool:
        from ares.behaviors.macro import (
            BuildStructure,
            ExpansionController,
            GasBuildingController,
            SpawnController,
            UpgradeController,
        )

        proposal = action.proposal
        bot = self._bot
        mediator = bot.mediator
        config = bot.config

        if proposal.kind is EconomicActionKind.PRODUCE_WORKER:
            return bool(
                SpawnController(
                    {
                        bot.worker_type: {
                            "proportion": 1.0,
                            "priority": 0,
                        }
                    },
                    freeflow_mode=True,
                    maximum=1,
                ).execute(bot, config, mediator)
            )

        if proposal.kind is EconomicActionKind.PRODUCE_UNIT:
            unit_type = self._unit_type(proposal.target)
            return bool(
                SpawnController(
                    {unit_type: {"proportion": 1.0, "priority": 0}},
                    freeflow_mode=True,
                    maximum=1,
                ).execute(bot, config, mediator)
            )

        if proposal.kind is EconomicActionKind.PRODUCE_SUPPLY:
            structure_type = self._unit_type(proposal.target or "SUPPLYDEPOT")
            return bool(
                BuildStructure(
                    base_location=bot.start_location,
                    structure_id=structure_type,
                    to_count=proposal.target_count or 0,
                    supply_depot=True,
                    production=False,
                ).execute(bot, config, mediator)
            )

        if proposal.kind is EconomicActionKind.EXPAND:
            return bool(
                ExpansionController(
                    to_count=proposal.target_count or (len(bot.townhalls) + 1),
                    can_afford_check=True,
                    check_location_is_safe=True,
                    max_pending=1,
                ).execute(bot, config, mediator)
            )

        if proposal.kind is EconomicActionKind.BUILD_GAS:
            return bool(
                GasBuildingController(
                    to_count=proposal.target_count or 1,
                    max_pending=1,
                ).execute(bot, config, mediator)
            )

        if proposal.kind is EconomicActionKind.BUILD_PRODUCTION:
            structure_type = self._unit_type(proposal.target)
            return bool(
                BuildStructure(
                    base_location=bot.start_location,
                    structure_id=structure_type,
                    to_count=proposal.target_count or 0,
                    production=True,
                ).execute(bot, config, mediator)
            )

        if proposal.kind is EconomicActionKind.BUILD_ADDON:
            return self._build_addon(self._unit_type(proposal.target))

        if proposal.kind is EconomicActionKind.RESEARCH_UPGRADE:
            upgrade = self._upgrade(proposal.target)
            return bool(
                UpgradeController(
                    [upgrade],
                    base_location=bot.start_location,
                    auto_tech_up_enabled=True,
                ).execute(bot, config, mediator)
            )

        raise ValueError(f"unsupported economic action: {proposal.kind.name}")

    def _waiting_reason(self, action: EconomicAction) -> str:
        """Explain a quiet Ares behavior without duplicating its policy.

        These are execution facts only. Whether to keep reserving, expire or
        abandon the action remains an ``EconomyController`` decision.
        Classification is deliberately defensive because this method is
        diagnostic: failure to inspect an Ares detail must not turn an
        ordinary retry into a failed economic action.
        """

        proposal = action.proposal
        bot = self._bot

        try:
            if bot.minerals < proposal.cost.minerals:
                return "minerals_unavailable_at_dispatch"
            if bot.vespene < proposal.cost.vespene:
                return "vespene_unavailable_at_dispatch"
            if bot.supply_left < proposal.cost.supply:
                return "supply_unavailable_at_dispatch"

            if proposal.kind in {
                EconomicActionKind.PRODUCE_WORKER,
                EconomicActionKind.PRODUCE_UNIT,
            }:
                unit_type = (
                    bot.worker_type
                    if proposal.kind is EconomicActionKind.PRODUCE_WORKER
                    else self._unit_type(proposal.target)
                )
                if not bot.tech_ready_for_unit(unit_type):
                    return "unit_tech_not_ready"
                trained_from = UNIT_TRAINED_FROM.get(unit_type, set())
                if not self._has_ready_producer(trained_from):
                    return "compatible_producer_not_ready"
                return "compatible_producer_busy"

            if proposal.kind in {
                EconomicActionKind.PRODUCE_SUPPLY,
                EconomicActionKind.BUILD_PRODUCTION,
            }:
                structure_type = self._unit_type(proposal.target)
                if bot.tech_requirement_progress(structure_type) < 0.85:
                    return "structure_tech_not_ready"
                return "worker_or_placement_unavailable"

            if proposal.kind is EconomicActionKind.EXPAND:
                return "safe_expansion_location_or_worker_unavailable"
            if proposal.kind is EconomicActionKind.BUILD_GAS:
                return "geyser_or_worker_unavailable"
            if proposal.kind is EconomicActionKind.BUILD_ADDON:
                return self._addon_waiting_reason(
                    self._unit_type(proposal.target)
                )
            if proposal.kind is EconomicActionKind.RESEARCH_UPGRADE:
                return "upgrade_prerequisite_or_researcher_unavailable"
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            pass
        return "ares_no_progress_this_frame"

    def _has_ready_producer(self, producer_types: set[UnitTypeId]) -> bool:
        structures = self._bot.mediator.get_own_structures_dict
        return any(
            structure.is_ready
            for producer_type in producer_types
            for structure in structures[producer_type]
        )

    def _addon_waiting_reason(self, addon_type: UnitTypeId) -> str:
        parent_type = self._addon_parent_type(addon_type)
        structures = self._bot.mediator.get_own_structures_dict[parent_type]
        available = tuple(
            structure
            for structure in structures
            if structure.is_ready
            and not bool(getattr(structure, "has_add_on", False))
        )
        if not available:
            return "addon_parent_unavailable"
        return "addon_parent_busy"

    def _build_addon(self, addon_type: UnitTypeId) -> bool:
        parent_type = self._addon_parent_type(addon_type)

        structures = self._bot.mediator.get_own_structures_dict[parent_type]
        parent = next(
            (
                structure
                for structure in structures
                if structure.is_ready
                and structure.is_idle
                and not bool(getattr(structure, "has_add_on", False))
            ),
            None,
        )
        if parent is None:
            return False
        parent.build(addon_type)
        return True

    @staticmethod
    def _addon_parent_type(addon_type: UnitTypeId) -> UnitTypeId:
        parent_by_addon = {
            UnitTypeId.BARRACKSREACTOR: UnitTypeId.BARRACKS,
            UnitTypeId.BARRACKSTECHLAB: UnitTypeId.BARRACKS,
            UnitTypeId.FACTORYREACTOR: UnitTypeId.FACTORY,
            UnitTypeId.FACTORYTECHLAB: UnitTypeId.FACTORY,
            UnitTypeId.STARPORTREACTOR: UnitTypeId.STARPORT,
            UnitTypeId.STARPORTTECHLAB: UnitTypeId.STARPORT,
        }
        parent_type = parent_by_addon.get(addon_type)
        if parent_type is None:
            raise ValueError(f"unsupported addon target: {addon_type.name}")
        return parent_type

    @staticmethod
    def _unit_type(target: str | None) -> UnitTypeId:
        if target is None:
            raise ValueError("economic action requires a unit-type target")
        try:
            return UnitTypeId[target]
        except KeyError as error:
            raise ValueError(f"unknown UnitTypeId target: {target}") from error

    @staticmethod
    def _upgrade(target: str | None) -> UpgradeId:
        if target is None:
            raise ValueError("research action requires an upgrade target")
        try:
            return UpgradeId[target]
        except KeyError as error:
            raise ValueError(f"unknown UpgradeId target: {target}") from error
