from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.macro.reference_build import (
    ReferenceBuild,
    ReferenceBuildPoint,
    bio_three_one_one_reference,
)


class ReferenceBuildTests(unittest.TestCase):
    def test_target_holds_the_last_checkpoint_at_or_before_now(self):
        build = ReferenceBuild(
            name="test",
            source="test",
            points=(
                ReferenceBuildPoint(0.0, {UnitTypeId.BARRACKS: 0}),
                ReferenceBuildPoint(50.0, {UnitTypeId.BARRACKS: 1}),
                ReferenceBuildPoint(150.0, {UnitTypeId.BARRACKS: 3}),
            ),
        )

        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 0.0), 0)
        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 49.9), 0)
        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 50.0), 1)
        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 149.9), 1)
        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 150.0), 3)
        # Past the last point the floor holds steady rather than dropping
        # back to zero or extrapolating further.
        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 10_000.0), 3)

    def test_target_defaults_to_zero_for_an_untracked_type(self):
        build = bio_three_one_one_reference()

        self.assertEqual(build.target_for(UnitTypeId.ENGINEERINGBAY, 1000.0), 0)

    def test_points_must_be_sorted_by_time(self):
        with self.assertRaises(ValueError):
            ReferenceBuild(
                name="test",
                source="test",
                points=(
                    ReferenceBuildPoint(50.0, {UnitTypeId.BARRACKS: 1}),
                    ReferenceBuildPoint(0.0, {UnitTypeId.BARRACKS: 0}),
                ),
            )

    def test_a_point_time_must_not_be_negative(self):
        with self.assertRaises(ValueError):
            ReferenceBuildPoint(-1.0, {UnitTypeId.BARRACKS: 1})

    def test_bio_three_one_one_reference_reaches_the_opening_floor(self):
        build = bio_three_one_one_reference()

        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 137.0), 3)
        self.assertEqual(build.target_for(UnitTypeId.FACTORY, 274.0), 1)
        self.assertEqual(build.target_for(UnitTypeId.STARPORT, 372.0), 1)
        # Before the first checkpoint, nothing is expected yet.
        self.assertEqual(build.target_for(UnitTypeId.BARRACKS, 0.0), 0)


if __name__ == "__main__":
    unittest.main()
