from datetime import timedelta

from odoo import _, api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    c2p_is_retainer = fields.Boolean(
        string='Retainer',
        help='Bill this job as a monthly retainer. The dashboard then tracks the '
             'hours and cost consumed against the fee below.')
    c2p_monthly_fee = fields.Monetary(
        string='Monthly Retainer Fee', currency_field='currency_id',
        help='Agreed monthly fee for this retainer. The burn panel reports the fee '
             'for the selected range as this amount times the months in the range.')
    c2p_is_pitch = fields.Boolean(
        string='Pitch / New Business',
        help='Unpaid new-business work. Time booked here is counted as pitch cost '
             'rather than client delivery.')
    c2p_opportunity_id = fields.Many2one(
        'crm.lead', string='Opportunity', domain="[('type', '=', 'opportunity')]",
        help='Links pitch time to the opportunity it was spent on, so pitch cost can '
             'be set against what the pitch won.')
    c2p_burn_alert_period = fields.Char(
        string='Last Burn Alert', readonly=True, copy=False,
        help='Month, as YYYY-MM, in which the 80% retainer burn alert was last raised. '
             'Keeps the alert to one per month per retainer.')

    # ------------------------------------------------------------------
    # retainer burn alert
    # ------------------------------------------------------------------
    def _c2p_month_bounds(self, today=None):
        today = today or fields.Date.context_today(self)
        start = today.replace(day=1)
        next_month = (start + timedelta(days=31)).replace(day=1)
        return start, next_month - timedelta(days=1)

    def _c2p_month_cost(self, date_from, date_to):
        """Timesheet cost booked to this project in the window, hours x hourly cost."""
        self.ensure_one()
        helper = self.env['c2p.dashboard.compat']
        groups = helper._group(
            'account.analytic.line',
            [('project_id', '=', self.id), ('date', '>=', date_from), ('date', '<=', date_to)],
            groupby=['employee_id'], aggregates=['unit_amount:sum'])
        employees = self.env['hr.employee'].browse(
            sorted({employee.id for employee, _h in groups if employee})).exists()
        costs = helper._employee_hourly_cost(employees)
        return sum((hours or 0.0) * costs.get(employee.id, 0.0)
                   for employee, hours in groups if employee)

    @api.model
    def _cron_c2p_retainer_burn_alert(self, threshold=0.8):
        """Warn on retainers that have burned through 80% of the month's fee.

        Posts on the project and gives the account manager an activity to act on.
        Raises at most one alert per retainer per month.
        """
        start, end = self._c2p_month_bounds()
        period = start.strftime('%Y-%m')
        retainers = self.search([('c2p_is_retainer', '=', True),
                                 ('c2p_monthly_fee', '>', 0)])
        alerted = self.browse()
        for project in retainers:
            if project.c2p_burn_alert_period == period:
                continue
            fee = project.c2p_monthly_fee
            cost = project._c2p_month_cost(start, end)
            if fee <= 0 or cost < fee * threshold:
                continue
            burn_pct = cost / fee * 100.0
            body = _(
                'Retainer burn alert: %(pct).0f%% of this month\'s fee is consumed '
                '(%(cost)s of %(fee)s). Review scope before further hours are booked.',
                pct=burn_pct,
                cost=self._c2p_format_money(cost),
                fee=self._c2p_format_money(fee))
            project.message_post(body=body)
            manager = project.user_id or project.create_uid
            if manager:
                project.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=fields.Date.context_today(self),
                    summary=_('Retainer at %.0f%% burn', burn_pct),
                    note=body,
                    user_id=manager.id)
            project.c2p_burn_alert_period = period
            alerted |= project
        return alerted

    def _c2p_format_money(self, amount):
        currency = self.env.company.currency_id
        return '%s %s' % (currency.symbol or currency.name, '{:,.0f}'.format(amount or 0.0))
