"""Build policy, organized vertically: one folder per named opening.

Each build owns the declarations that answer what army to produce, which
production structures and add-ons to grow into, and which milestones unlock
that growth.  The planners in the sibling macro packages only interpret these
declarations; they do not name composition members themselves.

The Ares build runner still requires ``terran_builds.yml`` at the repository
root.  That file is the opening-script adapter; post-opening policy lives here.
"""

from .banshee_cloak import banshee_cloak
from .battle_mech import battle_mech
from .bio_three_one_one import bio_three_one_one

__all__ = ["banshee_cloak", "battle_mech", "bio_three_one_one"]
