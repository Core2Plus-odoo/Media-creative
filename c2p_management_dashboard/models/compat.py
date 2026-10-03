"""Small compatibility helpers.

Odoo has renamed or moved several of the fields this dashboard reads
(``hr.employee.hourly_cost`` now lives on ``hr.version``, ``planning.slot``
moved from ``resource_id`` to ``resource_ids``, ``read_group`` was respecified
as ``_read_group``). Every such lookup goes through this module so the
version-dependent part of the dashboard sits in one place.
"""

from odoo import models


class C2pDashboardCompat(models.AbstractModel):
    _name = 'c2p.dashboard.compat'
    _description = 'Dashboard compatibility helpers'

    # ------------------------------------------------------------------
    # field resolution
    # ------------------------------------------------------------------
    def _first_field(self, model_name, *candidates):
        """Return the first of ``candidates`` that ``model_name`` actually has."""
        if model_name not in self.env:
            return None
        fields_ = self.env[model_name]._fields
        for candidate in candidates:
            if candidate in fields_:
                return candidate
        return None

    def _has_model(self, model_name):
        return model_name in self.env

    # ------------------------------------------------------------------
    # grouping
    # ------------------------------------------------------------------
    def _group(self, model_name, domain, groupby, aggregates):
        """Grouped read that works with both the old and the new signature.

        Returns a list of tuples, newest-signature style: one entry per group,
        holding the groupby values followed by the aggregate values.
        """
        model = self.env[model_name]
        if hasattr(model, '_read_group'):
            return model._read_group(domain, groupby=groupby, aggregates=aggregates)
        # Legacy read_group: rebuild the tuple shape from the returned dicts.
        plain_aggregates = [a.split(':')[0] for a in aggregates if a != '__count']
        rows = model.read_group(domain, plain_aggregates, groupby, lazy=False)
        result = []
        for row in rows:
            key = []
            for group in groupby:
                value = row.get(group.split(':')[0])
                key.append(value if not isinstance(value, tuple) else
                           self.env[model._fields[group.split(':')[0]].comodel_name].browse(value[0]))
            for aggregate in aggregates:
                if aggregate == '__count':
                    key.append(row.get('__count') or 0)
                else:
                    key.append(row.get(aggregate.split(':')[0]) or 0)
            result.append(tuple(key))
        return result

    # ------------------------------------------------------------------
    # employee cost
    # ------------------------------------------------------------------
    def _employee_hourly_cost(self, employees):
        """Map employee id -> hourly cost, wherever this version keeps it.

        Odoo 18 moved the contract-ish employee data onto ``hr.version``; older
        versions kept ``hourly_cost`` (and before that ``timesheet_cost``) on the
        employee itself.
        """
        costs = dict.fromkeys(employees.ids, 0.0)
        if not employees:
            return costs

        direct = self._first_field('hr.employee', 'hourly_cost', 'timesheet_cost')
        if direct:
            for employee in employees:
                costs[employee.id] = employee[direct] or 0.0
            return costs

        version_link = self._first_field('hr.employee', 'version_id', 'current_version_id')
        if version_link:
            version_cost = self._first_field('hr.version', 'hourly_cost', 'timesheet_cost')
            if version_cost:
                for employee in employees:
                    version = employee[version_link]
                    costs[employee.id] = (version and version[version_cost]) or 0.0
                return costs

        # Last resort: read the employee's current version straight off hr.version.
        if self._has_model('hr.version'):
            version_cost = self._first_field('hr.version', 'hourly_cost', 'timesheet_cost')
            employee_link = self._first_field('hr.version', 'employee_id')
            if version_cost and employee_link:
                versions = self.env['hr.version'].search(
                    [(employee_link, 'in', employees.ids)], order='id desc')
                for version in versions:
                    employee_id = version[employee_link].id
                    if not costs.get(employee_id):
                        costs[employee_id] = version[version_cost] or 0.0
        return costs

    # ------------------------------------------------------------------
    # planning
    # ------------------------------------------------------------------
    def _slot_resource_field(self):
        """``resource_ids`` on Odoo 20, ``resource_id`` before it."""
        return self._first_field('planning.slot', 'resource_ids', 'resource_id')
