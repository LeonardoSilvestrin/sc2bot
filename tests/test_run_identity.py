"""A run records exactly which code, configuration and seed decided it."""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from sc2.ids.unit_typeid import UnitTypeId

from bot.app.composition import compose_bot
from bot.app.run_identity import (
    UNKNOWN_BUILD,
    BuildIdentity,
    canonical,
    describe_build,
    fingerprint,
)
from bot.strategy import MissionPolicyConfig
from tests.fakes import FakeLogger


class FingerprintTests(unittest.TestCase):
    def test_sets_and_mappings_do_not_depend_on_insertion_order(self):
        first = {"b": frozenset({UnitTypeId.MARINE, UnitTypeId.REAPER}), "a": 1.5}
        second = {"a": 1.5, "b": frozenset({UnitTypeId.REAPER, UnitTypeId.MARINE})}

        self.assertEqual(fingerprint(first), fingerprint(second))

    def test_a_changed_decision_number_changes_the_fingerprint(self):
        self.assertEqual(
            fingerprint(MissionPolicyConfig()), fingerprint(MissionPolicyConfig())
        )
        self.assertNotEqual(
            fingerprint(MissionPolicyConfig()),
            fingerprint(MissionPolicyConfig(minimum_viable_utility=0.1)),
        )

    def test_unsupported_values_are_refused_not_stringified(self):
        with self.assertRaises(TypeError):
            canonical({"logger": object()})
        with self.assertRaises(ValueError):
            canonical(float("nan"))

    def test_every_default_decision_configuration_is_fingerprinted(self):
        composition = compose_bot(logger=FakeLogger(), rng_seed=7)

        self.assertLessEqual(
            {
                "strategy",
                "intent",
                "spatial_policy",
                "mission_policy",
                "allocator",
                "map_control",
                "standing",
                "defense",
            },
            set(composition.decision_configs),
        )
        self.assertEqual(
            fingerprint(composition.decision_configs),
            fingerprint(compose_bot(logger=FakeLogger()).decision_configs),
        )


class SeedTests(unittest.TestCase):
    def test_a_configured_seed_is_recorded(self):
        composition = compose_bot(logger=FakeLogger(), rng_seed=7)

        self.assertEqual(
            (composition.rng_seed, composition.rng_seed_source), (7, "configured")
        )

    def test_without_a_seed_the_application_generates_and_records_one(self):
        composition = compose_bot(logger=FakeLogger())

        self.assertEqual(composition.rng_seed_source, "generated")
        self.assertIsInstance(composition.rng_seed, int)

    def test_an_injected_generator_is_recorded_as_external(self):
        composition = compose_bot(logger=FakeLogger(), rng=random.Random(3))

        self.assertIsNone(composition.rng_seed)
        self.assertEqual(composition.rng_seed_source, "external")

    def test_a_generator_and_a_seed_are_exclusive(self):
        with self.assertRaises(ValueError):
            compose_bot(logger=FakeLogger(), rng=random.Random(3), rng_seed=3)


class BuildIdentityTests(unittest.TestCase):
    COMMIT = "0123456789abcdef0123456789abcdef01234567"

    def test_a_branch_resolves_to_its_loose_ref(self):
        with tempfile.TemporaryDirectory() as directory:
            git = Path(directory) / ".git"
            (git / "refs" / "heads").mkdir(parents=True)
            (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            (git / "refs" / "heads" / "main").write_text(self.COMMIT, encoding="utf-8")

            build = describe_build(Path(directory))

        self.assertEqual(build, BuildIdentity(commit=self.COMMIT, branch="main"))
        self.assertEqual(build.log_fields()["source"], "git")

    def test_a_packed_ref_resolves(self):
        with tempfile.TemporaryDirectory() as directory:
            git = Path(directory) / ".git"
            git.mkdir()
            (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            (git / "packed-refs").write_text(
                f"# pack-refs\n{self.COMMIT} refs/heads/main\n", encoding="utf-8"
            )

            self.assertEqual(describe_build(Path(directory)).commit, self.COMMIT)

    def test_a_detached_head_is_its_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            git = Path(directory) / ".git"
            git.mkdir()
            (git / "HEAD").write_text(self.COMMIT + "\n", encoding="utf-8")

            self.assertEqual(
                describe_build(Path(directory)),
                BuildIdentity(commit=self.COMMIT, branch=None),
            )

    def test_a_worktree_follows_its_git_file_to_the_common_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = root / "main" / ".git"
            worktree_git = common / "worktrees" / "feature"
            worktree_git.mkdir(parents=True)
            (common / "refs" / "heads").mkdir(parents=True)
            (common / "refs" / "heads" / "feature").write_text(
                self.COMMIT, encoding="utf-8"
            )
            (worktree_git / "HEAD").write_text(
                "ref: refs/heads/feature\n", encoding="utf-8"
            )
            (worktree_git / "commondir").write_text("../..\n", encoding="utf-8")
            checkout = root / "feature"
            checkout.mkdir()
            (checkout / ".git").write_text(
                f"gitdir: {worktree_git}\n", encoding="utf-8"
            )

            build = describe_build(checkout)

        self.assertEqual(build, BuildIdentity(commit=self.COMMIT, branch="feature"))

    def test_no_repository_is_an_explicitly_unknown_build(self):
        with tempfile.TemporaryDirectory() as directory:
            build = describe_build(Path(directory))

        self.assertIs(build, UNKNOWN_BUILD)
        self.assertEqual(
            build.log_fields(), {"commit": None, "branch": None, "source": "unknown"}
        )


if __name__ == "__main__":
    unittest.main()
