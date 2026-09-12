"""What the army is meant to be made of.

    doctrine.py  CompositionDoctrine -- the unit types a composition intends
                 to produce, tiered core / support / specialized; BIO, MECH

Every `MacroGoalSet` buys within one doctrine. A doctrine answers "what do we
produce?", never "who does what": missions score whatever units exist against
the job they need, so a doctrine change reaches the army only through what
gets built.
"""

from .doctrine import BIO, MECH, CompositionDoctrine

__all__ = ["BIO", "MECH", "CompositionDoctrine"]
