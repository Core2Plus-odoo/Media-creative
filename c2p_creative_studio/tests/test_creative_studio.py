from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestCreativeStudio(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.env['res.partner'].create({'name': 'Test Client'})
        cls.user_creative = cls._make_user(
            'Studio User', 'c2p_studio_user', 'group_creative_user')
        cls.user_art_director = cls._make_user(
            'Art Director', 'c2p_art_director', 'group_art_director')
        cls.user_creative_director = cls._make_user(
            'Creative Director', 'c2p_creative_director', 'group_creative_director')

    @classmethod
    def _make_user(cls, name, login, group):
        users = cls.env['res.users'].with_context(no_reset_password=True)
        # res.users has carried both names for this field across recent versions.
        field = 'group_ids' if 'group_ids' in users._fields else 'groups_id'
        return users.create({
            'name': name,
            'login': login,
            field: [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('c2p_creative_studio.%s' % group).id,
            ])],
        })

    def _brief(self, **vals):
        return self.env['c2p.creative.brief'].create(dict({
            'name': 'Digital Savings Launch',
            'partner_id': self.client.id,
            'state': 'review',
        }, **vals))

    def _concept(self, brief, name, **vals):
        return self.env['c2p.creative.concept'].create(dict({
            'name': name,
            'brief_id': brief.id,
        }, **vals))

    def _asset(self, brief, name='Master Key Visual'):
        return self.env['c2p.creative.asset'].create({
            'name': name,
            'brief_id': brief.id,
        })

    # ------------------------------------------------------------------
    # approval
    # ------------------------------------------------------------------
    def test_approval_blocked_without_selected_route(self):
        brief = self._brief()
        self._concept(brief, 'Pehla Qadam')
        self._concept(brief, 'Numbers with a Face')
        self.assertFalse(brief.selected_concept_id)
        with self.assertRaises(UserError):
            brief.with_user(self.user_creative_director).action_approve()
        self.assertEqual(brief.state, 'review')

    def test_approval_succeeds_with_selected_route(self):
        brief = self._brief()
        concept = self._concept(brief, 'Pehla Qadam')
        concept.with_user(self.user_art_director).action_select()
        self.assertEqual(brief.selected_concept_id, concept)
        brief.with_user(self.user_creative_director).action_approve()
        self.assertEqual(brief.state, 'approved')
        self.assertTrue(brief.approval_date)

    def test_approval_requires_creative_director(self):
        brief = self._brief()
        concept = self._concept(brief, 'Pehla Qadam')
        concept.with_user(self.user_art_director).action_select()
        with self.assertRaises(UserError):
            brief.with_user(self.user_creative).action_approve()
        self.assertEqual(brief.state, 'review')

    def test_send_for_review_requires_a_route(self):
        brief = self._brief(state='concepting')
        with self.assertRaises(UserError):
            brief.action_send_review()

    # ------------------------------------------------------------------
    # review rounds
    # ------------------------------------------------------------------
    def test_review_rounds_auto_number(self):
        asset = self._asset(self._brief())
        reviews = self.env['c2p.creative.review']
        for _index in range(3):
            reviews |= reviews.create({'asset_id': asset.id, 'decision': 'changes'})
        self.assertEqual(reviews.sorted('id').mapped('round'), [1, 2, 3])

    def test_review_rounds_auto_number_within_one_batch(self):
        asset = self._asset(self._brief())
        reviews = self.env['c2p.creative.review'].create([
            {'asset_id': asset.id, 'decision': 'changes'},
            {'asset_id': asset.id, 'decision': 'changes'},
        ])
        self.assertEqual(reviews.sorted('id').mapped('round'), [1, 2])

    def test_review_round_number_not_reused_after_delete(self):
        asset = self._asset(self._brief())
        model = self.env['c2p.creative.review']
        first = model.create({'asset_id': asset.id, 'decision': 'changes'})
        second = model.create({'asset_id': asset.id, 'decision': 'changes'})
        self.assertEqual(second.round, 2)
        second.unlink()
        third = model.create({'asset_id': asset.id, 'decision': 'changes'})
        self.assertEqual(third.round, 3, 'a deleted round must not hand its number back')
        self.assertEqual(first.round, 1)

    def test_review_decision_drives_asset_state(self):
        asset = self._asset(self._brief())
        model = self.env['c2p.creative.review']
        model.create({'asset_id': asset.id, 'decision': 'changes'})
        self.assertEqual(asset.state, 'changes')
        model.create({'asset_id': asset.id, 'decision': 'approved'})
        self.assertEqual(asset.state, 'approved')

    def test_turnaround_spans_first_review_to_approval(self):
        asset = self._asset(self._brief())
        model = self.env['c2p.creative.review']
        model.create({
            'asset_id': asset.id, 'decision': 'changes',
            'date': '2026-01-01 09:00:00',
        })
        model.create({
            'asset_id': asset.id, 'decision': 'approved',
            'date': '2026-01-03 09:00:00',
        })
        self.assertAlmostEqual(asset.turnaround_days, 2.0, places=2)

    # ------------------------------------------------------------------
    # routes
    # ------------------------------------------------------------------
    def test_only_one_route_selected_per_brief(self):
        brief = self._brief()
        first = self._concept(brief, 'Pehla Qadam')
        second = self._concept(brief, 'Numbers with a Face')
        first.with_user(self.user_art_director).action_select()
        second.with_user(self.user_art_director).action_select()
        self.assertEqual(first.state, 'shortlisted')
        self.assertEqual(second.state, 'selected')
        self.assertEqual(brief.selected_concept_id, second)

    def test_select_requires_art_director(self):
        brief = self._brief()
        concept = self._concept(brief, 'Pehla Qadam')
        with self.assertRaises(UserError):
            concept.with_user(self.user_creative).action_select()

    def test_combine_routes_records_its_sources(self):
        brief = self._brief()
        first = self._concept(brief, 'Pehla Qadam')
        third = self._concept(brief, 'Numbers with a Face')
        action = (first | third).with_user(self.user_art_director).action_combine()
        combined = self.env['c2p.creative.concept'].browse(action['res_id'])
        self.assertEqual(combined.source_ids, first | third)
        self.assertEqual(combined.brief_id, brief)

    def test_combine_needs_two_routes(self):
        brief = self._brief()
        concept = self._concept(brief, 'Pehla Qadam')
        with self.assertRaises(UserError):
            concept.action_combine()

    def test_score_is_the_average_of_the_three_criteria(self):
        concept = self._concept(
            self._brief(), 'Numbers with a Face',
            originality='5', brand_fit='3', feasibility='4')
        self.assertAlmostEqual(concept.score, 4.0, places=2)

    def test_refine_keeps_lineage_and_bumps_version(self):
        concept = self._concept(self._brief(), 'Pehla Qadam')
        action = concept.action_refine()
        refined = self.env['c2p.creative.concept'].browse(action['res_id'])
        self.assertEqual(refined.version, 2)
        self.assertEqual(refined.parent_id, concept)
        self.assertEqual(concept.child_count, 1)

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------
    def test_brief_gets_a_sequence_reference(self):
        brief = self._brief()
        self.assertTrue(brief.reference)
        self.assertNotEqual(brief.reference, 'New')

    def test_state_group_expand_lists_every_stage(self):
        expanded = self.env['c2p.creative.brief']._group_expand_state(None, None)
        self.assertEqual(len(expanded), 6)
        self.assertIn('approved', expanded)
