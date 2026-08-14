import unittest
from eqquest.detail_renderers import render_structured_local_detail

class DetailRendererTests(unittest.TestCase):
    def test_aa_fields_are_structured(self):
        text = '\n'.join(render_structured_local_detail('aa', {'id': 12, 'maxRank': 5, 'cost': 3, 'classes': ['WAR', 'PAL']}))
        self.assertIn('ID: 12', text)
        self.assertIn('Max rank: 5', text)
        self.assertIn('WAR', text)

    def test_zone_fields_are_structured(self):
        text = '\n'.join(render_structured_local_detail('zone', {'zoneId': 100, 'shortName': 'stonehive', 'expansion': 'The Serpent Spine'}))
        self.assertIn('Zone ID: 100', text)
        self.assertIn('Short name: stonehive', text)
