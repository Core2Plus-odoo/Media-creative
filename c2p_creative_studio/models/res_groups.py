from odoo import api, models


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _c2p_describe_groups(self, heading, descriptions):
        """Give our groups their own heading and help text on the user form.

        Set from Python rather than in the XML record because Odoo keeps moving
        these fields: Odoo 20 replaced ``res.groups.category_id`` with a link to
        ``res.groups.privilege``, and older versions grouped by
        ``ir.module.category``. Whichever this database has is used; if it has
        neither, the groups still work, they just sit under the generic heading.

        :param heading: label for the group of groups
        :param descriptions: {xml_id: help text}
        """
        groups = self.browse()
        for xml_id, comment in descriptions.items():
            group = self.env.ref(xml_id, raise_if_not_found=False)
            if not group:
                continue
            groups |= group
            if 'comment' in self._fields:
                group.comment = comment

        if not groups:
            return groups

        if 'privilege_id' in self._fields and 'res.groups.privilege' in self.env:
            privilege = self.env['res.groups.privilege'].search(
                [('name', '=', heading)], limit=1)
            if not privilege:
                privilege = self.env['res.groups.privilege'].create({'name': heading})
            groups.privilege_id = privilege
        elif 'category_id' in self._fields:
            category = self.env['ir.module.category'].search(
                [('name', '=', heading)], limit=1)
            if not category:
                category = self.env['ir.module.category'].create({'name': heading})
            groups.category_id = category
        return groups
