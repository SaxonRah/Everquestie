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

    def test_combat_ability_exposes_ability_identity_and_spell_mechanics(self):
        text = '\n'.join(
            render_structured_local_detail(
                'combat_ability',
                {
                    'abilityId': '700',
                    'spellId': '9001',
                    'spellName': 'Exact Discipline',
                    'endurance': 440,
                    'recastTime': 12000,
                    'classes': {'Warrior': 80},
                    'effects': ['Increase melee damage'],
                    'identityJoin': {
                        'method': 'exact_case_insensitive_name',
                        'matchedSpellId': '9001',
                    },
                },
            )
        )
        self.assertIn('Combat ability ID: 700', text)
        self.assertIn('Spell ID: 9001', text)
        self.assertIn('Endurance: 440', text)
        self.assertIn('Recast: 12000', text)
        self.assertIn('Warrior=80', text)
        self.assertIn('Increase melee damage', text)
        self.assertIn('exact_case_insensitive_name', text)
