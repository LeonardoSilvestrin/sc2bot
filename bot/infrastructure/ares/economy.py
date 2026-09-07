from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.contracts.economy import (
    EconomicAction,
    EconomicActionKind,
    EconomicFeedback,
    EconomicFeedbackKind,
)


class AresEconomyCommands:
    """Translate one funded economic action into an Ares macro operation.

    Behaviors are executed here, after Ares updated its managers for the frame,
    so the economy controller receives truthful dispatch feedback.  Strategic
    decisions and resource arbitration remain outside this adapter.
    """

    def __init__(self, bot) -> None:
        self._bot = bot

    def dispatch(self, action: EconomicAction) -> EconomicFeedback:
        try:
            dispatched = self._execute(action)
        except Exception as error:
            return EconomicFeedback(
                action_id=action.action_id,
                kind=EconomicFeedbackKind.FAILED,
                reason=f"ares_dispatch_error:{type(error).__name__}:{error}",
            )

        return EconomicFeedback(
            action_id=action.action_id,
            kind=(
                EconomicFeedbackKind.DISPATCHED
                if dispatched
                else EconomicFeedbackKind.FAILED
            ),
            reason=(
                "ares_command_accepted" if dispatched else "ares_no_action_available"
            ),
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

    def _build_addon(self, addon_type: UnitTypeId) -> bool:
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
