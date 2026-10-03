from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestManagementDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env['c2p.management.dashboard']
        cls.compat = cls.env['c2p.dashboard.compat']
        cls.today = fields.Date.context_today(cls.dashboard)
        cls.date_from = cls.today.replace(day=1)
        cls.date_to = cls.today

        cls.client = cls.env['res.partner'].create({'name': 'Dashboard Test Client'})
        cls.employee = cls.env['hr.employee'].create({'name': 'Dashboard Test Designer'})
        cls._set_hourly_cost(cls.employee, 1000.0)

        cls.project = cls.env['project.project'].create({
            'name': 'Dashboard Test Retainer',
            'partner_id': cls.client.id,
            'allow_timesheets': True,
            'c2p_is_retainer': True,
            'c2p_monthly_fee': 100000.0,
        })

    @classmethod
    def _set_hourly_cost(cls, employee, amount):
        """Write the hourly cost wherever this version keeps it."""
        direct = cls.compat._first_field('hr.employee', 'hourly_cost', 'timesheet_cost')
        if direct:
            employee.write({direct: amount})
            return
        link = cls.compat._first_field('hr.employee', 'version_id', 'current_version_id')
        field = cls.compat._first_field('hr.version', 'hourly_cost', 'timesheet_cost')
        if link and field and employee[link]:
            employee[link].write({field: amount})

    def _log_hours(self, hours, project=None, date=None):
        return self.env['account.analytic.line'].create({
            'name': 'Dashboard test timesheet',
            'project_id': (project or self.project).id,
            'employee_id': self.employee.id,
            'unit_amount': hours,
            'date': date or self.today,
        })

    # ------------------------------------------------------------------
    # payload shape
    # ------------------------------------------------------------------
    def test_payload_carries_every_panel(self):
        data = self.dashboard.get_dashboard_data(self.date_from, self.date_to)
        for key in ('margin_leaks', 'profitability', 'retainers', 'utilisation',
                    'pipeline', 'pitch', 'receivables', 'creative', 'overbooking',
                    'currency', 'range'):
            self.assertIn(key, data, 'panel %s missing from the payload' % key)

    def test_range_is_ordered_and_defaulted(self):
        date_from, date_to = self.dashboard._coerce_range(self.date_to, self.date_from)
        self.assertLessEqual(date_from, date_to, 'a reversed range must be swapped')
        date_from, date_to = self.dashboard._coerce_range(None, None)
        self.assertLessEqual(date_from, date_to)

    # ------------------------------------------------------------------
    # timesheet cost: hours x hourly cost
    # ------------------------------------------------------------------
    def test_timesheet_cost_is_hours_times_hourly_cost(self):
        self._log_hours(10.0)
        costs = self.compat._employee_hourly_cost(self.employee)
        rate = costs[self.employee.id]
        result = self.dashboard._timesheet_cost(self.date_from, self.date_to)
        self.assertAlmostEqual(result['hours_by_project'][self.project.id], 10.0, places=2)
        self.assertAlmostEqual(result['cost_by_project'][self.project.id],
                               10.0 * rate, places=2)

    # ------------------------------------------------------------------
    # retainer burn
    # ------------------------------------------------------------------
    def test_retainer_burn_is_cost_over_fee(self):
        self._log_hours(50.0)
        panel = self.dashboard._panel_retainers(self.date_from, self.date_to)
        row = next(row for row in panel['rows'] if row['id'] == self.project.id)
        self.assertTrue(row['configured'])
        expected = row['cost'] / row['fee_for_period'] * 100.0
        self.assertAlmostEqual(row['burn_pct'], expected, places=2)

    def test_retainer_without_a_fee_is_reported_not_guessed(self):
        unpriced = self.env['project.project'].create({
            'name': 'Unpriced Retainer',
            'c2p_is_retainer': True,
            'allow_timesheets': True,
        })
        panel = self.dashboard._panel_retainers(self.date_from, self.date_to)
        row = next(row for row in panel['rows'] if row['id'] == unpriced.id)
        self.assertFalse(row['configured'])
        self.assertEqual(row['burn_pct'], 0.0, 'no fee means no invented burn figure')
        self.assertIn(unpriced.display_name, panel['unconfigured'])

    def test_months_between_counts_inclusively(self):
        self.assertEqual(
            self.dashboard._months_between(self.today.replace(month=1, day=1),
                                           self.today.replace(month=3, day=31)), 3)

    # ------------------------------------------------------------------
    # margin leaks
    # ------------------------------------------------------------------
    def test_headline_is_the_sum_of_its_parts(self):
        self._log_hours(200.0)
        panel = self.dashboard._panel_margin_leaks(self.date_from, self.date_to)
        self.assertAlmostEqual(
            panel['headline'], sum(part['amount'] for part in panel['parts']), places=2)
        self.assertEqual(len(panel['parts']), 4)

    def test_over_scope_leak_appears_once_the_fee_is_passed(self):
        # 200 hours at the seeded rate is far past a 100,000 fee.
        self._log_hours(200.0)
        panel = self.dashboard._panel_margin_leaks(self.date_from, self.date_to)
        over_scope = next(p for p in panel['parts'] if p['key'] == 'over_scope')
        rows = self.dashboard._panel_retainers(self.date_from, self.date_to)['rows']
        row = next(row for row in rows if row['id'] == self.project.id)
        if row['cost'] > row['fee_for_period']:
            self.assertGreater(over_scope['amount'], 0.0)
        else:
            self.assertEqual(over_scope['amount'], 0.0)

    # ------------------------------------------------------------------
    # utilisation and overbooking
    # ------------------------------------------------------------------
    def test_utilisation_counts_logged_hours(self):
        self._log_hours(8.0)
        panel = self.dashboard._panel_utilisation(self.date_from, self.date_to)
        row = next((row for row in panel['by_employee']
                    if row['id'] == self.employee.id), None)
        self.assertTrue(row, 'an employee with logged hours must appear')
        self.assertAlmostEqual(row['logged'], 8.0, places=2)

    def test_capacity_is_never_negative(self):
        capacity = self.dashboard._capacity_hours(
            self.employee, self.date_from, self.date_to)
        self.assertGreaterEqual(capacity, 0.0)

    def test_week_starts_land_on_monday(self):
        starts = self.dashboard._week_starts(self.date_from, self.date_to)
        self.assertTrue(starts)
        self.assertTrue(all(start.weekday() == 0 for start in starts))

    # ------------------------------------------------------------------
    # receivables
    # ------------------------------------------------------------------
    def test_receivables_buckets_add_up_to_the_total(self):
        panel = self.dashboard._panel_receivables(self.date_to)
        bucket_total = sum(bucket['amount'] for bucket in panel['buckets'])
        self.assertAlmostEqual(bucket_total, panel['totals']['total'], places=2)
        not_due = next(b['amount'] for b in panel['buckets'] if b['key'] == 'not_due')
        self.assertAlmostEqual(
            panel['totals']['overdue'], panel['totals']['total'] - not_due, places=2)

    # ------------------------------------------------------------------
    # creative studio panel
    # ------------------------------------------------------------------
    def test_creative_panel_reads_the_studio(self):
        brief = self.env['c2p.creative.brief'].create({
            'name': 'Dashboard Test Brief',
            'partner_id': self.client.id,
        })
        asset = self.env['c2p.creative.asset'].create({
            'name': 'Dashboard Test Asset', 'brief_id': brief.id, 'state': 'review',
        })
        self.env['c2p.creative.review'].create({
            'asset_id': asset.id, 'decision': 'changes',
            'date': fields.Datetime.now(),
        })
        panel = self.dashboard._panel_creative(self.date_from, self.date_to)
        self.assertGreaterEqual(panel['brief_count'], 1)
        self.assertGreaterEqual(panel['review_count'], 1)
        self.assertGreaterEqual(panel['rounds_per_asset'], 0.0)

    # ------------------------------------------------------------------
    # retainer burn alert
    # ------------------------------------------------------------------
    def test_burn_alert_fires_once_and_schedules_an_activity(self):
        self.project.user_id = self.env.user
        self._log_hours(95.0)
        start, end = self.project._c2p_month_bounds()
        cost = self.project._c2p_month_cost(start, end)
        if cost < self.project.c2p_monthly_fee * 0.8:
            self.skipTest('seeded hourly cost too low to cross the threshold')
        alerted = self.env['project.project']._cron_c2p_retainer_burn_alert()
        self.assertIn(self.project, alerted)
        self.assertEqual(self.project.c2p_burn_alert_period, start.strftime('%Y-%m'))
        self.assertTrue(self.project.activity_ids)
        again = self.env['project.project']._cron_c2p_retainer_burn_alert()
        self.assertNotIn(self.project, again, 'the alert must not repeat in the same month')

    def test_burn_alert_ignores_retainers_below_the_threshold(self):
        quiet = self.env['project.project'].create({
            'name': 'Quiet Retainer', 'c2p_is_retainer': True,
            'c2p_monthly_fee': 10000000.0, 'allow_timesheets': True,
        })
        self._log_hours(1.0, project=quiet)
        alerted = self.env['project.project']._cron_c2p_retainer_burn_alert()
        self.assertNotIn(quiet, alerted)

    # ------------------------------------------------------------------
    # client 360 and drill-through
    # ------------------------------------------------------------------
    def test_client_360_returns_the_client(self):
        data = self.dashboard.get_client_360(self.client.id, self.date_from, self.date_to)
        self.assertEqual(data['partner']['id'], self.client.id)
        for key in ('money', 'jobs', 'active_jobs', 'open_invoices', 'retainers',
                    'recent_reviews'):
            self.assertIn(key, data)

    def test_client_360_on_a_missing_partner_is_empty(self):
        self.assertEqual(self.dashboard.get_client_360(0), {})

    def test_every_drill_target_returns_an_action(self):
        targets = [
            ('client_revenue', self.client.id),
            ('job_timesheets', self.project.id),
            ('employee_timesheets', self.employee.id),
            ('receivables', None),
            ('briefs', 'draft'),
            ('assets_awaiting', None),
            ('reviews', None),
            ('leak_over_scope', None),
            ('leak_at_risk', None),
            ('leak_overdue', None),
            ('leak_unbilled', None),
            ('employee_planning', self.employee.id),
        ]
        for kind, record_id in targets:
            action = self.dashboard.action_drill(
                kind, record_id=record_id,
                date_from=self.date_from, date_to=self.date_to)
            self.assertEqual(action['type'], 'ir.actions.act_window',
                             'drill target %s returned no action' % kind)
            self.assertTrue(action.get('res_model'))

    def test_unknown_drill_target_is_rejected(self):
        with self.assertRaises(ValueError):
            self.dashboard.action_drill('not_a_target')

    # ------------------------------------------------------------------
    # compatibility helpers
    # ------------------------------------------------------------------
    def test_first_field_resolves_only_existing_fields(self):
        self.assertEqual(
            self.compat._first_field('res.partner', 'does_not_exist', 'name'), 'name')
        self.assertIsNone(self.compat._first_field('res.partner', 'does_not_exist'))
        self.assertIsNone(self.compat._first_field('not.a.model', 'name'))

    def test_group_helper_returns_tuples(self):
        self._log_hours(3.0)
        groups = self.compat._group(
            'account.analytic.line',
            [('project_id', '=', self.project.id)],
            groupby=['project_id'], aggregates=['unit_amount:sum'])
        self.assertTrue(groups)
        self.assertEqual(len(groups[0]), 2)

    def test_hourly_cost_lookup_returns_a_figure_per_employee(self):
        costs = self.compat._employee_hourly_cost(self.employee)
        self.assertIn(self.employee.id, costs)
        self.assertGreaterEqual(costs[self.employee.id], 0.0)

    def test_planning_slot_resource_field_is_resolved_when_planning_exists(self):
        if 'planning.slot' not in self.env:
            self.skipTest('planning is not installed')
        self.assertIn(self.compat._slot_resource_field(),
                      ('resource_ids', 'resource_id'))
