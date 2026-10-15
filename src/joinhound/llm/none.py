# SPDX-License-Identifier: Apache-2.0

"""A judge that does not call a model."""

from joinhound.core.models import Candidate


class NoneJudge:
    """Leave proposed relationships for a person to review."""

    def review(self, candidate: Candidate) -> None:
        """Do not decide the candidate."""
        del candidate
        return None
