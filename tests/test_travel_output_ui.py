import unittest

from eqquest.travel_output_ui import _result_prefix


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _Frame:
    def __init__(self, mode, source="Stone Hive", target="West Freeport"):
        self._everquestie_result_mode = mode
        self.from_var = _Var(source)
        self.to_var = _Var(target)


class TravelOutputUiTests(unittest.TestCase):
    def test_route_result_is_explicit(self):
        self.assertEqual(
            _result_prefix(_Frame("route")),
            "ROUTE RESULT | Stone Hive → West Freeport",
        )

    def test_zone_context_is_explicit(self):
        self.assertEqual(
            _result_prefix(_Frame("zone")),
            "SOURCE ZONE CONTEXT | Stone Hive",
        )

    def test_pending_route_cannot_look_like_zone_context(self):
        self.assertEqual(
            _result_prefix(_Frame("pending_route")),
            "ROUTE REQUEST PENDING | Stone Hive → West Freeport",
        )


if __name__ == "__main__":
    unittest.main()
