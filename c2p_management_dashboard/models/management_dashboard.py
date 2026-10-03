"""Aggregation service behind the management dashboard.

Every figure returned here is read from live records with the ORM, under the
calling user's own rights (no sudo) and restricted to the companies they have
selected. Nothing is estimated or hard-coded: where a database has no data for
a panel, the panel reports zero and says what it looked for.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _

AGEING_BUCKETS = [
    ('not_due', 'Not due'),
    ('b1_30', '1-30 days'),
    ('b31_60', '31-60 days'),
    ('b61_90', '61-90 days'),
    ('b90_plus', '90+ days'),
]


class C2pManagementDashboard(models.AbstractModel):
    _name = 'c2p.management.dashboard'
    _description = 'Management Dashboard Data'
    _inherit = ['c2p.dashboard.compat']

    # ==================================================================
    # entry point
    # ==================================================================
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        date_from, date_to = self._coerce_range(date_from, date_to)
        company = self.env.company
        return {
            'range': {'date_from': str(date_from), 'date_to': str(date_to)},
            'currency': {
                'id': company.currency_id.id,
                'symbol': company.currency_id.symbol or '',
                'position': company.currency_id.position,
                'decimals': company.currency_id.decimal_places,
            },
            'companies': self.env.companies.mapped('name'),
            'profitability': self._panel_profitability(date_from, date_to),
            'retainers': self._panel_retainers(date_from, date_to),
            'utilisation': self._panel_utilisation(date_from, date_to),
            'pipeline': self._panel_pipeline(date_from, date_to),
            'receivables': self._panel_receivables(date_to),
            'creative': self._panel_creative(date_from, date_to),
        }

    @api.model
    def _coerce_range(self, date_from, date_to):
        today = fields.Date.context_today(self)
        date_to = fields.Date.to_date(date_to) or today
        date_from = fields.Date.to_date(date_from) or date_to.replace(day=1) - timedelta(days=90)
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    def _company_domain(self):
        """Restrict to the user's companies, keeping company-less records.

        A project or an employee may legitimately carry no company, and such a
        record belongs to every company rather than none. Matches the shape of
        the multi-company domain on the ir.access grants.
        """
        return ['|', ('company_id', '=', False),
                ('company_id', 'in', self.env.companies.ids)]

    # ==================================================================
    # shared building blocks
    # ==================================================================
    def _timesheet_cost(self, date_from, date_to):
        """Hours and cost per project and per employee, from timesheet lines.

        Cost is hours x the employee's hourly cost, computed here rather than
        read off the analytic line's own amount so the figure matches the
        definition the dashboard states.
        """
        hours_by_project = defaultdict(float)
        cost_by_project = defaultdict(float)
        hours_by_employee = defaultdict(float)
        cost_by_employee = defaultdict(float)

        if 'account.analytic.line' not in self.env:
            return {
                'hours_by_project': hours_by_project, 'cost_by_project': cost_by_project,
                'hours_by_employee': hours_by_employee, 'cost_by_employee': cost_by_employee,
            }

        domain = [
            ('project_id', '!=', False),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ] + self._company_domain()
        groups = self._group(
            'account.analytic.line', domain,
            groupby=['project_id', 'employee_id'],
            aggregates=['unit_amount:sum'])

        employee_ids = {employee.id for _p, employee, _h in groups if employee}
        employees = self.env['hr.employee'].browse(sorted(employee_ids)).exists()
        costs = self._employee_hourly_cost(employees)

        for project, employee, hours in groups:
            hours = hours or 0.0
            rate = costs.get(employee.id, 0.0) if employee else 0.0
            cost = hours * rate
            if project:
                hours_by_project[project.id] += hours
                cost_by_project[project.id] += cost
            if employee:
                hours_by_employee[employee.id] += hours
                cost_by_employee[employee.id] += cost
        return {
            'hours_by_project': hours_by_project, 'cost_by_project': cost_by_project,
            'hours_by_employee': hours_by_employee, 'cost_by_employee': cost_by_employee,
        }

    def _revenue_lines_domain(self, date_from, date_to):
        return [
            ('parent_state', '=', 'posted'),
            ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
            ('account_id.internal_group', '=', 'income'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ] + self._company_domain()

    def _revenue(self, date_from, date_to):
        """Invoiced revenue in the period, by client and by project.

        Read from posted customer invoice lines on income accounts. ``balance``
        is used rather than ``price_subtotal`` so credit notes net off on their
        own. Project attribution follows the invoice line back to its sale order
        line; lines with no sale origin still count towards the client.
        """
        revenue_by_partner = defaultdict(float)
        revenue_by_project = defaultdict(float)
        unattributed = 0.0
        if 'account.move.line' not in self.env:
            return {'by_partner': revenue_by_partner, 'by_project': revenue_by_project,
                    'unattributed_to_project': unattributed}

        lines = self.env['account.move.line'].search(
            self._revenue_lines_domain(date_from, date_to))
        sale_link = self._first_field('account.move.line', 'sale_line_ids')
        for line in lines:
            amount = -(line.balance or 0.0)
            revenue_by_partner[line.move_id.partner_id.commercial_partner_id.id] += amount
            projects = self.env['project.project']
            if sale_link:
                sale_lines = line[sale_link]
                projects = sale_lines.mapped('project_id') if \
                    self._first_field('sale.order.line', 'project_id') else projects
                if not projects and sale_lines:
                    projects = sale_lines.mapped('order_id').mapped('project_ids') \
                        if self._first_field('sale.order', 'project_ids') else projects
            if projects:
                share = amount / len(projects)
                for project in projects:
                    revenue_by_project[project.id] += share
            else:
                unattributed += amount
        return {'by_partner': revenue_by_partner, 'by_project': revenue_by_project,
                'unattributed_to_project': unattributed}

    def _media_pass_through(self, date_from, date_to):
        """Vendor media cost and what was re-billed on it.

        ``purchase`` is not a dependency of this module, so the panel reads it
        only when the database has it. Re-billed media is taken from sale order
        lines flagged as expenses (the lines Odoo creates when a purchase is
        re-invoiced); margin is re-billed minus vendor cost.
        """
        result = {
            'cost_by_partner': defaultdict(float), 'cost_by_project': defaultdict(float),
            'rebill_by_partner': defaultdict(float), 'rebill_by_project': defaultdict(float),
            'available': False, 'cost_attributed_to_project': True,
        }
        if not self._has_model('purchase.order.line'):
            return result
        result['available'] = True

        date_field = self._first_field('purchase.order.line', 'date_order', 'date_planned')
        domain = [('state', 'in', ('purchase', 'done'))] + self._company_domain()
        if date_field:
            domain += [(date_field, '>=', datetime.combine(date_from, time.min)),
                       (date_field, '<=', datetime.combine(date_to, time.max))]
        project_field = self._first_field('purchase.order.line', 'project_id')
        groupby = ['partner_id'] + ([project_field] if project_field else [])
        groups = self._group('purchase.order.line', domain, groupby=groupby,
                             aggregates=['price_subtotal:sum'])
        for row in groups:
            partner = row[0]
            project = row[1] if project_field else None
            amount = row[-1] or 0.0
            if partner:
                result['cost_by_partner'][partner.id] += amount
            if project:
                result['cost_by_project'][project.id] += amount
        result['cost_attributed_to_project'] = bool(project_field)

        expense_flag = self._first_field('sale.order.line', 'is_expense')
        if expense_flag:
            sol_project = self._first_field('sale.order.line', 'project_id')
            sol_domain = [(expense_flag, '=', True), ('state', 'in', ('sale', 'done'))] \
                + self._company_domain()
            groupby = ['order_partner_id'] + ([sol_project] if sol_project else [])
            for row in self._group('sale.order.line', sol_domain, groupby=groupby,
                                   aggregates=['price_subtotal:sum']):
                partner = row[0]
                project = row[1] if sol_project else None
                amount = row[-1] or 0.0
                if partner:
                    result['rebill_by_partner'][partner.commercial_partner_id.id] += amount
                if project:
                    result['rebill_by_project'][project.id] += amount
        return result

    # ==================================================================
    # panel: profitability
    # ==================================================================
    def _panel_profitability(self, date_from, date_to):
        timesheets = self._timesheet_cost(date_from, date_to)
        revenue = self._revenue(date_from, date_to)
        media = self._media_pass_through(date_from, date_to)

        projects = self.env['project.project'].browse(sorted(
            set(revenue['by_project']) | set(timesheets['cost_by_project'])
            | set(media['cost_by_project']))).exists()
        by_job = []
        for project in projects:
            rev = revenue['by_project'].get(project.id, 0.0)
            cost = timesheets['cost_by_project'].get(project.id, 0.0)
            media_cost = media['cost_by_project'].get(project.id, 0.0)
            media_rebill = media['rebill_by_project'].get(project.id, 0.0)
            by_job.append({
                'id': project.id,
                'name': project.display_name,
                'partner': project.partner_id.display_name or '',
                'revenue': rev,
                'hours': timesheets['hours_by_project'].get(project.id, 0.0),
                'cost': cost,
                'media_cost': media_cost,
                'media_rebill': media_rebill,
                'media_margin': media_rebill - media_cost,
                'gross_margin': rev - cost + (media_rebill - media_cost),
            })
        by_job.sort(key=lambda row: row['gross_margin'], reverse=True)

        partner_ids = sorted(set(revenue['by_partner']) | set(media['cost_by_partner']))
        partners = self.env['res.partner'].browse(partner_ids).exists()
        cost_by_partner = defaultdict(float)
        hours_by_partner = defaultdict(float)
        for project in self.env['project.project'].browse(
                sorted(timesheets['cost_by_project'])).exists():
            key = project.partner_id.commercial_partner_id.id or 0
            cost_by_partner[key] += timesheets['cost_by_project'].get(project.id, 0.0)
            hours_by_partner[key] += timesheets['hours_by_project'].get(project.id, 0.0)

        by_client = []
        for partner in partners:
            rev = revenue['by_partner'].get(partner.id, 0.0)
            cost = cost_by_partner.get(partner.id, 0.0)
            media_cost = media['cost_by_partner'].get(partner.id, 0.0)
            media_rebill = media['rebill_by_partner'].get(partner.id, 0.0)
            by_client.append({
                'id': partner.id,
                'name': partner.display_name,
                'revenue': rev,
                'hours': hours_by_partner.get(partner.id, 0.0),
                'cost': cost,
                'media_cost': media_cost,
                'media_rebill': media_rebill,
                'media_margin': media_rebill - media_cost,
                'gross_margin': rev - cost + (media_rebill - media_cost),
            })
        by_client.sort(key=lambda row: row['revenue'], reverse=True)
        # rank is sent rather than derived in the template, so the league table
        # holds no arithmetic
        for position, row in enumerate(by_client, start=1):
            row['rank'] = position
        for position, row in enumerate(by_job, start=1):
            row['rank'] = position

        total_revenue = sum(row['revenue'] for row in by_client)
        total_cost = sum(row['cost'] for row in by_client)
        total_media_margin = sum(row['media_margin'] for row in by_client)
        return {
            'by_client': by_client,
            'by_job': by_job,
            'totals': {
                'revenue': total_revenue,
                'cost': total_cost,
                'media_margin': total_media_margin,
                'gross_margin': total_revenue - total_cost + total_media_margin,
                'margin_pct': ((total_revenue - total_cost + total_media_margin)
                               / total_revenue * 100.0) if total_revenue else 0.0,
                'hours': sum(row['hours'] for row in by_client),
            },
            'notes': {
                'media_available': media['available'],
                'media_attributed_to_project': media['cost_attributed_to_project'],
                'revenue_unattributed_to_project': revenue['unattributed_to_project'],
            },
        }

    # ==================================================================
    # panel: retainer burn
    # ==================================================================
    def _panel_retainers(self, date_from, date_to):
        """Hours and cost consumed against the monthly fee held on the project.

        The fee is read from ``project.project.c2p_monthly_fee``; a project with
        no fee recorded is not guessed at, it is listed as unconfigured.
        """
        projects = self.env['project.project'].search(
            [('c2p_is_retainer', '=', True)] + self._company_domain())
        timesheets = self._timesheet_cost(date_from, date_to)
        months = max(self._months_between(date_from, date_to), 1)
        rows = []
        for project in projects:
            fee = (project.c2p_monthly_fee or 0.0) * months
            cost = timesheets['cost_by_project'].get(project.id, 0.0)
            hours = timesheets['hours_by_project'].get(project.id, 0.0)
            rows.append({
                'id': project.id,
                'name': project.display_name,
                'partner': project.partner_id.display_name or '',
                'monthly_fee': project.c2p_monthly_fee or 0.0,
                'fee_for_period': fee,
                'hours': hours,
                'cost': cost,
                'burn_pct': (cost / fee * 100.0) if fee else 0.0,
                'configured': bool(project.c2p_monthly_fee),
            })
        rows.sort(key=lambda row: row['burn_pct'], reverse=True)
        return {
            'months_in_range': months,
            'rows': rows,
            'unconfigured': [row['name'] for row in rows if not row['configured']],
            'totals': {
                'fee_for_period': sum(row['fee_for_period'] for row in rows),
                'cost': sum(row['cost'] for row in rows),
                'hours': sum(row['hours'] for row in rows),
            },
        }

    @api.model
    def _months_between(self, date_from, date_to):
        return (date_to.year - date_from.year) * 12 + (date_to.month - date_from.month) + 1

    # ==================================================================
    # panel: utilisation
    # ==================================================================
    def _panel_utilisation(self, date_from, date_to):
        """Logged vs planned vs contracted capacity, per employee and department."""
        timesheets = self._timesheet_cost(date_from, date_to)
        employees = self.env['hr.employee'].search(self._company_domain())
        planned = self._planned_hours(employees, date_from, date_to)

        rows = []
        for employee in employees:
            logged = timesheets['hours_by_employee'].get(employee.id, 0.0)
            capacity = self._capacity_hours(employee, date_from, date_to)
            if not (logged or planned.get(employee.id) or capacity):
                continue
            rows.append({
                'id': employee.id,
                'name': employee.display_name,
                'department': employee.department_id.display_name or _('Unassigned'),
                'department_id': employee.department_id.id or 0,
                'logged': logged,
                'planned': planned.get(employee.id, 0.0),
                'capacity': capacity,
                'utilisation_pct': (logged / capacity * 100.0) if capacity else 0.0,
            })
        rows.sort(key=lambda row: row['utilisation_pct'], reverse=True)

        departments = defaultdict(lambda: {'logged': 0.0, 'planned': 0.0, 'capacity': 0.0})
        for row in rows:
            bucket = departments[(row['department_id'], row['department'])]
            bucket['logged'] += row['logged']
            bucket['planned'] += row['planned']
            bucket['capacity'] += row['capacity']
        by_department = [{
            'id': key[0], 'name': key[1],
            'logged': value['logged'], 'planned': value['planned'],
            'capacity': value['capacity'],
            'utilisation_pct': (value['logged'] / value['capacity'] * 100.0)
                               if value['capacity'] else 0.0,
        } for key, value in departments.items()]
        by_department.sort(key=lambda row: row['utilisation_pct'], reverse=True)

        total_logged = sum(row['logged'] for row in rows)
        total_capacity = sum(row['capacity'] for row in rows)
        return {
            'by_employee': rows,
            'by_department': by_department,
            'totals': {
                'logged': total_logged,
                'planned': sum(row['planned'] for row in rows),
                'capacity': total_capacity,
                'utilisation_pct': (total_logged / total_capacity * 100.0)
                                   if total_capacity else 0.0,
            },
            'notes': {'planning_available': self._has_model('planning.slot')},
        }

    def _planned_hours(self, employees, date_from, date_to):
        """Allocated planning hours per employee in the window.

        ``planning.slot`` links to resources, and on Odoo 20 it does so through
        a many2many (``resource_ids``), so the slots are summed in Python rather
        than grouped in SQL.
        """
        planned = defaultdict(float)
        if not self._has_model('planning.slot'):
            return planned
        resource_field = self._slot_resource_field()
        if not resource_field:
            return planned
        hours_field = self._first_field('planning.slot', 'allocated_hours', 'effective_hours')
        if not hours_field:
            return planned

        employee_by_resource = {
            employee.resource_id.id: employee.id
            for employee in employees if employee.resource_id
        }
        domain = [
            ('start_datetime', '<=', datetime.combine(date_to, time.max)),
            ('end_datetime', '>=', datetime.combine(date_from, time.min)),
            (resource_field, 'in', list(employee_by_resource)),
        ] + self._company_domain()
        for slot in self.env['planning.slot'].search(domain):
            resources = slot[resource_field]
            resources = resources if hasattr(resources, 'ids') else resources
            resource_ids = resources.ids if resources else []
            if not resource_ids:
                continue
            share = (slot[hours_field] or 0.0) / len(resource_ids)
            for resource_id in resource_ids:
                employee_id = employee_by_resource.get(resource_id)
                if employee_id:
                    planned[employee_id] += share
        return planned

    def _capacity_hours(self, employee, date_from, date_to):
        """Working hours the employee's calendar holds for the window."""
        calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id
        if not calendar:
            return 0.0
        # resource.calendar dropped its tz field in Odoo 20; fall back to the
        # user's timezone, then UTC.
        tz_field = self._first_field('resource.calendar', 'tz')
        tz_name = (tz_field and calendar[tz_field]) or self.env.user.tz or 'UTC'
        tz = pytz.timezone(tz_name)
        start = tz.localize(datetime.combine(date_from, time.min)).astimezone(pytz.utc)
        end = tz.localize(datetime.combine(date_to, time.max)).astimezone(pytz.utc)
        if hasattr(calendar, 'get_work_hours_count'):
            return calendar.get_work_hours_count(start, end) or 0.0
        # Fall back to the calendar's nominal day across weekdays in the window.
        days = sum(1 for offset in range((date_to - date_from).days + 1)
                   if (date_from + timedelta(days=offset)).weekday() < 5)
        return days * (calendar.hours_per_day or 0.0)

    # ==================================================================
    # panel: pipeline
    # ==================================================================
    def _panel_pipeline(self, date_from, date_to):
        if 'crm.lead' not in self.env:
            return {'by_stage': [], 'totals': {}, 'available': False}
        open_domain = [('type', '=', 'opportunity'), ('active', '=', True)] \
            + self._company_domain()
        by_stage = []
        for stage, count, expected in self._group(
                'crm.lead', open_domain, groupby=['stage_id'],
                aggregates=['__count', 'expected_revenue:sum']):
            leads = self.env['crm.lead'].search(
                open_domain + [('stage_id', '=', stage.id if stage else False)])
            weighted = sum(
                (lead.expected_revenue or 0.0) * (lead.probability or 0.0) / 100.0
                for lead in leads)
            by_stage.append({
                'id': stage.id if stage else 0,
                'name': stage.display_name if stage else _('Unassigned'),
                'count': count,
                'expected': expected or 0.0,
                'weighted': weighted,
            })
        by_stage.sort(key=lambda row: row['expected'], reverse=True)

        closed_domain = [('type', '=', 'opportunity'),
                         ('date_closed', '>=', datetime.combine(date_from, time.min)),
                         ('date_closed', '<=', datetime.combine(date_to, time.max))] \
            + self._company_domain()
        won = self.env['crm.lead'].with_context(active_test=False).search_count(
            closed_domain + [('stage_id.is_won', '=', True)])
        lost = self.env['crm.lead'].with_context(active_test=False).search_count(
            closed_domain + [('probability', '=', 0), ('active', '=', False)])
        decided = won + lost
        return {
            'available': True,
            'by_stage': by_stage,
            'totals': {
                'count': sum(row['count'] for row in by_stage),
                'expected': sum(row['expected'] for row in by_stage),
                'weighted': sum(row['weighted'] for row in by_stage),
                'won': won,
                'lost': lost,
                'win_rate_pct': (won / decided * 100.0) if decided else 0.0,
            },
        }

    # ==================================================================
    # panel: receivables
    # ==================================================================
    def _panel_receivables(self, as_of):
        """Open customer balances, bucketed on due date as at the range end."""
        domain = [
            ('parent_state', '=', 'posted'),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('full_reconcile_id', '=', False),
            ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
        ] + self._company_domain()
        lines = self.env['account.move.line'].search(domain)
        buckets = {key: 0.0 for key, _label in AGEING_BUCKETS}
        by_partner = defaultdict(lambda: {key: 0.0 for key, _label in AGEING_BUCKETS})
        overdue = []
        total = 0.0
        for line in lines:
            residual = line.amount_residual or 0.0
            if not residual:
                continue
            total += residual
            due = line.date_maturity or line.date
            days = (as_of - due).days if due else 0
            if days <= 0:
                key = 'not_due'
            elif days <= 30:
                key = 'b1_30'
            elif days <= 60:
                key = 'b31_60'
            elif days <= 90:
                key = 'b61_90'
            else:
                key = 'b90_plus'
            buckets[key] += residual
            partner = line.move_id.partner_id.commercial_partner_id
            by_partner[(partner.id, partner.display_name)][key] += residual
            if key != 'not_due':
                overdue.append({
                    'move_id': line.move_id.id,
                    'name': line.move_id.name or '',
                    'partner': partner.display_name,
                    'due': str(due) if due else '',
                    'days_overdue': days,
                    'residual': residual,
                })
        overdue.sort(key=lambda row: row['days_overdue'], reverse=True)
        return {
            'buckets': [{'key': key, 'label': label, 'amount': buckets[key]}
                        for key, label in AGEING_BUCKETS],
            'by_partner': [dict({'id': key[0], 'name': key[1],
                                 'total': sum(value.values())}, **value)
                           for key, value in by_partner.items()],
            'overdue': overdue,
            'totals': {
                'total': total,
                'overdue': total - buckets['not_due'],
                'overdue_pct': ((total - buckets['not_due']) / total * 100.0) if total else 0.0,
            },
        }

    # ==================================================================
    # panel: creative studio
    # ==================================================================
    def _panel_creative(self, date_from, date_to):
        briefs = self.env['c2p.creative.brief']
        by_stage = []
        selection = dict(briefs._fields['state'].selection)
        for state, count in self._group(
                'c2p.creative.brief', self._company_domain(),
                groupby=['state'], aggregates=['__count']):
            by_stage.append({'key': state, 'name': selection.get(state, state),
                             'count': count})
        by_stage.sort(key=lambda row: list(selection).index(row['key'])
                      if row['key'] in selection else 99)

        assets = self.env['c2p.creative.asset'].search(self._company_domain())
        approved = assets.filtered(lambda a: a.turnaround_days > 0)
        reviews = self.env['c2p.creative.review'].search(
            [('date', '>=', datetime.combine(date_from, time.min)),
             ('date', '<=', datetime.combine(date_to, time.max))] + self._company_domain())
        awaiting = assets.filtered(lambda a: a.state == 'review')
        return {
            'briefs_by_stage': by_stage,
            'brief_count': sum(row['count'] for row in by_stage),
            'asset_count': len(assets),
            'review_count': len(reviews),
            'rounds_per_asset': (sum(assets.mapped('review_count')) / len(assets))
                                if assets else 0.0,
            'avg_turnaround_days': (sum(approved.mapped('turnaround_days')) / len(approved))
                                   if approved else 0.0,
            'awaiting_review': len(awaiting),
            'awaiting_review_rows': [{
                'id': asset.id,
                'name': asset.display_name,
                'brief': asset.brief_id.display_name,
                'designer': asset.designer_id.display_name or '',
                'rounds': asset.review_count,
            } for asset in awaiting[:20]],
        }

    # ==================================================================
    # drill-through
    # ==================================================================
    @api.model
    def action_drill(self, kind, record_id=None, date_from=None, date_to=None):
        """Open the records behind a figure. Everything the dashboard shows is
        a real recordset, so every tile can be opened."""
        date_from, date_to = self._coerce_range(date_from, date_to)
        builders = {
            'client_revenue': self._drill_client_revenue,
            'job_timesheets': self._drill_job_timesheets,
            'employee_timesheets': self._drill_employee_timesheets,
            'pipeline_stage': self._drill_pipeline_stage,
            'receivables': self._drill_receivables,
            'overdue_invoice': self._drill_overdue_invoice,
            'briefs': self._drill_briefs,
            'assets_awaiting': self._drill_assets_awaiting,
            'reviews': self._drill_reviews,
        }
        builder = builders.get(kind)
        if not builder:
            raise ValueError(_('Unknown drill-through target: %s') % kind)
        return builder(record_id, date_from, date_to)

    def _act_window(self, name, model, domain, view_mode='list,form', context=None):
        """Build an act_window the Odoo 20 action service will accept.

        ``views`` is required: the client's _preprocessAction maps over it and
        does not derive it from ``view_mode``, so a dict carrying only
        ``view_mode`` fails with "action.views is undefined". ``view_mode`` is
        kept alongside it because some callers still read it.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'domain': domain,
            'views': [[False, mode] for mode in view_mode.split(',')],
            'view_mode': view_mode,
            'context': context or {},
            'target': 'current',
        }

    def _drill_client_revenue(self, partner_id, date_from, date_to):
        return self._act_window(
            _('Invoiced Revenue'), 'account.move.line',
            self._revenue_lines_domain(date_from, date_to)
            + [('move_id.partner_id.commercial_partner_id', '=', partner_id)])

    def _drill_job_timesheets(self, project_id, date_from, date_to):
        return self._act_window(
            _('Timesheets'), 'account.analytic.line',
            [('project_id', '=', project_id), ('date', '>=', date_from),
             ('date', '<=', date_to)] + self._company_domain())

    def _drill_employee_timesheets(self, employee_id, date_from, date_to):
        return self._act_window(
            _('Timesheets'), 'account.analytic.line',
            [('employee_id', '=', employee_id), ('date', '>=', date_from),
             ('date', '<=', date_to)] + self._company_domain())

    def _drill_pipeline_stage(self, stage_id, date_from, date_to):
        return self._act_window(
            _('Opportunities'), 'crm.lead',
            [('type', '=', 'opportunity'), ('stage_id', '=', stage_id or False)]
            + self._company_domain(), view_mode='list,kanban,form')

    def _drill_receivables(self, bucket, date_from, date_to):
        return self._act_window(
            _('Open Receivables'), 'account.move.line',
            [('parent_state', '=', 'posted'),
             ('account_id.account_type', '=', 'asset_receivable'),
             ('full_reconcile_id', '=', False),
             ('move_id.move_type', 'in', ('out_invoice', 'out_refund'))]
            + self._company_domain())

    def _drill_overdue_invoice(self, move_id, date_from, date_to):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice'),
            'res_model': 'account.move',
            'res_id': move_id,
            'views': [[False, 'form']],
            'view_mode': 'form',
            'target': 'current',
        }

    def _drill_briefs(self, state, date_from, date_to):
        domain = self._company_domain()
        if state:
            domain = [('state', '=', state)] + domain
        return self._act_window(_('Creative Briefs'), 'c2p.creative.brief', domain,
                                view_mode='kanban,list,form')

    def _drill_assets_awaiting(self, record_id, date_from, date_to):
        return self._act_window(
            _('Assets Awaiting Review'), 'c2p.creative.asset',
            [('state', '=', 'review')] + self._company_domain(),
            view_mode='kanban,list,form')

    def _drill_reviews(self, record_id, date_from, date_to):
        return self._act_window(
            _('Review Rounds'), 'c2p.creative.review',
            [('date', '>=', datetime.combine(date_from, time.min)),
             ('date', '<=', datetime.combine(date_to, time.max))] + self._company_domain())
