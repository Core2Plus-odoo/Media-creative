"""The panels the agency director is actually buying: where margin leaks, what
pitching costs, who is overbooked, and one page per client.

Same rules as the rest of the dashboard: ORM only, the caller's own rights, the
caller's own companies, and no figure that is not read from a record.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import api, models, _


class C2pManagementDashboardLeaks(models.AbstractModel):
    _inherit = 'c2p.management.dashboard'

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        data = super().get_dashboard_data(date_from=date_from, date_to=date_to)
        date_from, date_to = self._coerce_range(date_from, date_to)
        data['margin_leaks'] = self._panel_margin_leaks(date_from, date_to)
        data['pitch'] = self._panel_pitch(date_from, date_to)
        data['overbooking'] = self._panel_overbooking(date_from, date_to)
        # Say plainly when figures rest on seeded records rather than real
        # trading activity. Two separate signals: Odoo's own demo flag (set on
        # development builds), and the presence of the Creative Studio seed
        # records, which install on every database including production.
        base_module = self.env.ref('base.module_base', raise_if_not_found=False)
        data['demo_data'] = bool(base_module and base_module.demo)
        data['seeded_records'] = bool(self.env.ref(
            'c2p_creative_studio.demo_brief_digital_savings', raise_if_not_found=False))
        return data

    # ==================================================================
    # panel 1: where margin leaks
    # ==================================================================
    def _panel_margin_leaks(self, date_from, date_to):
        """One headline figure, built from four leaks that each drill through.

        The four are kept separate rather than netted, because they are fixed by
        four different conversations: scope, pricing, collections and billing.
        """
        retainers = self._retainer_rows(date_from, date_to)
        over_scope = sum(max(row['cost'] - row['fee_for_period'], 0.0) for row in retainers)
        over_scope_hours = sum(
            row['hours'] * (1 - row['fee_for_period'] / row['cost'])
            for row in retainers if row['cost'] > row['fee_for_period'] > 0)
        at_risk_rows = [row for row in retainers if 80.0 <= row['burn_pct'] < 100.0]
        at_risk = sum(row['fee_for_period'] - row['cost'] for row in at_risk_rows)

        receivables = self._panel_receivables(date_to)
        overdue = receivables['totals']['overdue']

        unbilled = self._unbilled_delivered(date_from, date_to)

        parts = [
            {
                'key': 'over_scope',
                'label': _('Hours logged beyond retainer scope'),
                'amount': over_scope,
                'detail': _('%(hours).0f hours past the fee on %(count)s retainer(s)',
                            hours=over_scope_hours,
                            count=len([r for r in retainers
                                       if r['cost'] > r['fee_for_period'] > 0])),
                'drill': 'leak_over_scope',
            },
            {
                'key': 'at_risk',
                'label': _('Retainers past 80% burn'),
                'amount': max(at_risk, 0.0),
                'detail': _('%s retainer(s) with fee left but little month left',
                            len(at_risk_rows)),
                'drill': 'leak_at_risk',
            },
            {
                'key': 'overdue',
                'label': _('Overdue receivables'),
                'amount': overdue,
                'detail': _('%s overdue invoice(s)', len(receivables['overdue'])),
                'drill': 'leak_overdue',
            },
            {
                'key': 'unbilled',
                'label': _('Delivered but not invoiced'),
                'amount': unbilled['amount'],
                'detail': _('%s order line(s) delivered and billable now',
                            unbilled['line_count']),
                'drill': 'leak_unbilled',
            },
        ]
        return {
            'headline': sum(part['amount'] for part in parts),
            'parts': parts,
            'notes': {
                'unbilled_source': unbilled['source'],
            },
        }

    def _retainer_rows(self, date_from, date_to):
        return self._panel_retainers(date_from, date_to)['rows']

    def _unbilled_delivered(self, date_from, date_to):
        """Value delivered on sale orders but not yet invoiced.

        Prefers Odoo's own ``untaxed_amount_to_invoice``, which already accounts
        for milestone and delivered-quantity policies; falls back to
        (delivered - invoiced) x unit price where that field is absent.
        """
        model = 'sale.order.line'
        if model not in self.env:
            return {'amount': 0.0, 'line_count': 0, 'source': 'unavailable'}
        to_invoice = self._first_field(model, 'untaxed_amount_to_invoice')
        domain = [('state', 'in', ('sale', 'done'))] + self._company_domain()
        if to_invoice:
            lines = self.env[model].search(domain + [(to_invoice, '>', 0)])
            return {
                'amount': sum(lines.mapped(to_invoice)),
                'line_count': len(lines),
                'source': 'untaxed_amount_to_invoice',
            }
        lines = self.env[model].search(domain).filtered(
            lambda line: (line.qty_delivered or 0.0) > (line.qty_invoiced or 0.0))
        amount = sum(((line.qty_delivered or 0.0) - (line.qty_invoiced or 0.0))
                     * (line.price_unit or 0.0) for line in lines)
        return {'amount': amount, 'line_count': len(lines), 'source': 'qty_delivered'}

    # ==================================================================
    # panel 6: pitch cost vs win rate
    # ==================================================================
    def _panel_pitch(self, date_from, date_to):
        """What new business cost to chase, against what it brought in.

        Pitch time is time booked to a project flagged ``c2p_is_pitch``; where
        that project names an opportunity, the cost is attributed to it.
        """
        timesheets = self._timesheet_cost(date_from, date_to)
        pitch_projects = self.env['project.project'].search(
            [('c2p_is_pitch', '=', True)] + self._company_domain())
        rows = []
        total_cost = total_hours = 0.0
        for project in pitch_projects:
            hours = timesheets['hours_by_project'].get(project.id, 0.0)
            cost = timesheets['cost_by_project'].get(project.id, 0.0)
            if not (hours or cost):
                continue
            lead = project.c2p_opportunity_id
            total_cost += cost
            total_hours += hours
            rows.append({
                'id': project.id,
                'name': project.display_name,
                'opportunity': lead.display_name if lead else '',
                'opportunity_id': lead.id if lead else 0,
                'stage': lead.stage_id.display_name if lead else '',
                'won': bool(lead and lead.stage_id.is_won),
                'expected': lead.expected_revenue if lead else 0.0,
                'hours': hours,
                'cost': cost,
            })
        rows.sort(key=lambda row: row['cost'], reverse=True)

        won_value = sum(row['expected'] for row in rows if row['won'])
        won_count = len([row for row in rows if row['won']])
        decided = len([row for row in rows if row['opportunity_id']])
        return {
            'rows': rows,
            'configured': bool(pitch_projects),
            'totals': {
                'hours': total_hours,
                'cost': total_cost,
                'won_value': won_value,
                'won_count': won_count,
                'pitched_count': decided,
                'win_rate_pct': (won_count / decided * 100.0) if decided else 0.0,
                'cost_per_win': (total_cost / won_count) if won_count else 0.0,
                'return_multiple': (won_value / total_cost) if total_cost else 0.0,
            },
        }

    # ==================================================================
    # planning overbooking
    # ==================================================================
    def _panel_overbooking(self, date_from, date_to):
        """Employees planned above their weekly capacity, with a free peer to move work to.

        A peer is someone in the same job role with planned hours under their own
        capacity for the same week.
        """
        if not self._has_model('planning.slot'):
            return {'available': False, 'weeks': []}
        employees = self.env['hr.employee'].search(self._company_domain())
        weeks = []
        for week_start in self._week_starts(date_from, date_to):
            week_end = week_start + timedelta(days=6)
            planned = self._planned_hours(employees, week_start, week_end)
            if not planned:
                continue
            capacity = {}
            rows = []
            for employee in employees:
                hours = planned.get(employee.id, 0.0)
                if not hours:
                    continue
                capacity[employee.id] = self._capacity_hours(employee, week_start, week_end)
                rows.append((employee, hours, capacity[employee.id]))
            over = [(employee, hours, cap) for employee, hours, cap in rows
                    if cap and hours > cap]
            if not over:
                continue
            spare_by_role = defaultdict(list)
            for employee, hours, cap in rows:
                if cap and hours < cap:
                    spare_by_role[employee.job_id.id].append(
                        {'id': employee.id, 'name': employee.display_name,
                         'spare_hours': cap - hours})
            for bucket in spare_by_role.values():
                bucket.sort(key=lambda peer: peer['spare_hours'], reverse=True)
            weeks.append({
                'week_start': str(week_start),
                'week_end': str(week_end),
                'rows': [{
                    'id': employee.id,
                    'name': employee.display_name,
                    'role': employee.job_id.display_name or _('No role set'),
                    'planned': hours,
                    'capacity': cap,
                    'over_by': hours - cap,
                    'peers': spare_by_role.get(employee.job_id.id, [])[:3],
                } for employee, hours, cap in sorted(
                    over, key=lambda item: item[1] - item[2], reverse=True)],
            })
        return {'available': True, 'weeks': weeks,
                'overbooked_count': sum(len(week['rows']) for week in weeks)}

    @api.model
    def _week_starts(self, date_from, date_to):
        current = date_from - timedelta(days=date_from.weekday())
        starts = []
        while current <= date_to and len(starts) < 26:
            starts.append(current)
            current += timedelta(days=7)
        return starts

    # ==================================================================
    # client 360
    # ==================================================================
    @api.model
    def get_client_360(self, partner_id, date_from=None, date_to=None):
        """One page for one client: money, jobs, retainer burn, recent reviews."""
        date_from, date_to = self._coerce_range(date_from, date_to)
        partner = self.env['res.partner'].browse(int(partner_id)).exists()
        if not partner:
            return {}
        profitability = self._panel_profitability(date_from, date_to)
        client_row = next((row for row in profitability['by_client']
                           if row['id'] == partner.id), None)
        jobs = [row for row in profitability['by_job']
                if row['partner'] == partner.display_name]

        receivables = self._panel_receivables(date_to)
        open_invoices = self.env['account.move'].search(
            [('move_type', 'in', ('out_invoice', 'out_refund')),
             ('state', '=', 'posted'),
             ('payment_state', 'in', ('not_paid', 'partial')),
             ('partner_id.commercial_partner_id', '=', partner.id)]
            + self._company_domain(), order='invoice_date_due')

        projects = self.env['project.project'].search(
            [('partner_id.commercial_partner_id', '=', partner.id)]
            + self._company_domain())
        retainer_rows = [row for row in self._retainer_rows(date_from, date_to)
                         if row['id'] in projects.ids]

        reviews = self.env['c2p.creative.review'].search(
            [('brief_id.partner_id.commercial_partner_id', '=', partner.id)]
            + self._company_domain(), order='date desc', limit=10)
        briefs = self.env['c2p.creative.brief'].search(
            [('partner_id.commercial_partner_id', '=', partner.id)]
            + self._company_domain())
        decisions = dict(self.env['c2p.creative.review']._fields['decision'].selection)
        return {
            'partner': {'id': partner.id, 'name': partner.display_name},
            'range': {'date_from': str(date_from), 'date_to': str(date_to)},
            'money': client_row or {
                'revenue': 0.0, 'cost': 0.0, 'hours': 0.0,
                'media_margin': 0.0, 'gross_margin': 0.0,
            },
            'jobs': jobs,
            'active_jobs': [{
                'id': project.id,
                'name': project.display_name,
                'retainer': project.c2p_is_retainer,
                'task_count': len(project.task_ids),
            } for project in projects],
            'open_invoices': [{
                'id': move.id,
                'name': move.name or '',
                'date_due': str(move.invoice_date_due) if move.invoice_date_due else '',
                'residual': move.amount_residual,
                'overdue': bool(move.invoice_date_due and move.invoice_date_due < date_to),
            } for move in open_invoices],
            'receivables_total': sum(
                row['total'] for row in receivables['by_partner']
                if row['id'] == partner.id),
            'retainers': retainer_rows,
            'briefs': len(briefs),
            'recent_reviews': [{
                'id': review.id,
                'asset': review.asset_id.display_name,
                'round': review.round,
                'decision': decisions.get(review.decision, review.decision),
                'date': str(review.date) if review.date else '',
                'reviewer': review.reviewer_id.display_name or '',
            } for review in reviews],
        }

    # ==================================================================
    # extra drill-through targets
    # ==================================================================
    @api.model
    def action_drill(self, kind, record_id=None, date_from=None, date_to=None):
        date_from, date_to = self._coerce_range(date_from, date_to)
        extra = {
            'leak_over_scope': self._drill_retainers,
            'leak_at_risk': self._drill_retainers,
            'leak_overdue': self._drill_overdue_receivables,
            'leak_unbilled': self._drill_unbilled,
            'pitch_project': self._drill_job_timesheets,
            'opportunity': self._drill_opportunity,
            'employee_planning': self._drill_employee_planning,
        }
        builder = extra.get(kind)
        if builder:
            return builder(record_id, date_from, date_to)
        return super().action_drill(kind, record_id=record_id,
                                    date_from=date_from, date_to=date_to)

    def _drill_retainers(self, record_id, date_from, date_to):
        return self._act_window(
            _('Retainers'), 'project.project',
            [('c2p_is_retainer', '=', True)] + self._company_domain())

    def _drill_overdue_receivables(self, record_id, date_from, date_to):
        return self._act_window(
            _('Overdue Invoices'), 'account.move',
            [('move_type', 'in', ('out_invoice', 'out_refund')),
             ('state', '=', 'posted'),
             ('payment_state', 'in', ('not_paid', 'partial')),
             ('invoice_date_due', '<', date_to)] + self._company_domain())

    def _drill_unbilled(self, record_id, date_from, date_to):
        to_invoice = self._first_field('sale.order.line', 'untaxed_amount_to_invoice')
        domain = [('state', 'in', ('sale', 'done'))] + self._company_domain()
        if to_invoice:
            domain += [(to_invoice, '>', 0)]
        return self._act_window(_('Delivered, Not Invoiced'), 'sale.order.line', domain)

    def _drill_opportunity(self, lead_id, date_from, date_to):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Opportunity'),
            'res_model': 'crm.lead',
            'res_id': int(lead_id),
            'view_mode': 'form',
            'target': 'current',
        }

    def _drill_employee_planning(self, employee_id, date_from, date_to):
        employee = self.env['hr.employee'].browse(int(employee_id)).exists()
        resource_field = self._slot_resource_field()
        domain = self._company_domain()
        if employee and resource_field and employee.resource_id:
            domain = [(resource_field, 'in', employee.resource_id.ids)] + domain
        return self._act_window(
            _('Planning'), 'planning.slot',
            domain + [('start_datetime', '<=', datetime.combine(date_to, time.max)),
                      ('end_datetime', '>=', datetime.combine(date_from, time.min))],
            view_mode='list,form')
