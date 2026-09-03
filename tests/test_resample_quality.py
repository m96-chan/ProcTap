"""
Tests for Issue #25: ResampleQuality type alias should be defined in a single
location (DRY) and imported everywhere instead of redefined per module.
"""

import typing

from proctap.backends import base


class TestResampleQualitySingleSource:
    """The ResampleQuality alias must have exactly one definition."""

    def test_defined_in_base(self):
        """base.py owns the canonical ResampleQuality alias."""
        assert hasattr(base, "ResampleQuality")
        # It is a typing.Literal['best', 'medium', 'fast']
        assert typing.get_args(base.ResampleQuality) == ("best", "medium", "fast")

    def test_core_reuses_base_alias(self):
        """core.py must import the alias, not redefine it."""
        from proctap import core

        assert core.ResampleQuality is base.ResampleQuality

    def test_backends_init_reuses_base_alias(self):
        """backends/__init__.py must import the alias, not redefine it."""
        from proctap import backends

        assert backends.ResampleQuality is base.ResampleQuality

    def test_converter_reuses_base_alias(self):
        """converter.py must import the alias, not redefine it."""
        from proctap.backends import converter

        assert converter.ResampleQuality is base.ResampleQuality
