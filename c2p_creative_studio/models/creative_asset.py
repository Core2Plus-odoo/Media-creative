from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CreativeAsset(models.Model):
    _name = 'c2p.creative.asset'
    _description = 'Creative Asset / Deliverable'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'brief_id, id'

    name = fields.Char(string='Asset', required=True, tracking=True)
    brief_id = fields.Many2one('c2p.creative.brief', required=True, ondelete='cascade', index=True)
    concept_id = fields.Many2one('c2p.creative.concept', string='Route',
                                 domain="[('brief_id', '=', brief_id)]")
    task_id = fields.Many2one('project.task', string='Project Task', check_company=True)
    designer_id = fields.Many2one('hr.employee', string='Designer / Creative', tracking=True,
                                  check_company=True)
    asset_type = fields.Selection([
        ('key_visual', 'Key Visual'),
        ('film', 'Film / Video'),
        ('social', 'Social Content'),
        ('ooh', 'OOH / Outdoor'),
        ('print', 'Print'),
        ('digital', 'Digital / Web'),
        ('other', 'Other'),
    ], default='key_visual', required=True)
    version = fields.Integer(default=1, tracking=True)
    file = fields.Binary(string='File', attachment=True)
    file_name = fields.Char()
    preview = fields.Image(string='Preview', max_width=1280, max_height=1280)
    state = fields.Selection([
        ('wip', 'In Progress'),
        ('review', 'In Review'),
        ('changes', 'Changes Requested'),
        ('approved', 'Approved'),
    ], default='wip', required=True, tracking=True, group_expand='_group_expand_state')
    review_ids = fields.One2many('c2p.creative.review', 'asset_id', string='Review Rounds')
    review_count = fields.Integer(compute='_compute_review_count', store=True)
    first_review_date = fields.Datetime(compute='_compute_turnaround', store=True)
    approval_date = fields.Datetime(compute='_compute_turnaround', store=True)
    turnaround_days = fields.Float(
        compute='_compute_turnaround', store=True, digits=(6, 2),
        string='Approval Turnaround (days)',
        help='Calendar days between the first review round and the approving one.')
    round_counter = fields.Integer(
        string='Rounds Issued', default=0, readonly=True, copy=False,
        help='Highest review round number ever issued for this asset. Kept so a '
             'withdrawn round never has its number reissued.')
    partner_id = fields.Many2one(related='brief_id.partner_id', store=True)
    company_id = fields.Many2one(related='brief_id.company_id', store=True, index=True)

    @api.model
    def _group_expand_state(self, *args, **kwargs):
        return [key for key, _label in self._fields['state'].selection]

    @api.depends('review_ids')
    def _compute_review_count(self):
        for rec in self:
            rec.review_count = len(rec.review_ids)

    @api.depends('review_ids.date', 'review_ids.decision')
    def _compute_turnaround(self):
        for rec in self:
            dates = rec.review_ids.filtered('date').mapped('date')
            approved = rec.review_ids.filtered(
                lambda r: r.decision == 'approved' and r.date).sorted('date')
            rec.first_review_date = min(dates) if dates else False
            rec.approval_date = approved[0].date if approved else False
            if rec.first_review_date and rec.approval_date:
                delta = rec.approval_date - rec.first_review_date
                rec.turnaround_days = delta.total_seconds() / 86400.0
            else:
                rec.turnaround_days = 0.0

    def action_send_review(self):
        self.write({'state': 'review'})

    def action_new_version(self):
        for rec in self:
            rec.write({'version': rec.version + 1, 'state': 'review'})
            rec.message_post(body=_('Version %s uploaded and sent for review.', rec.version))

    @api.model
    def _demo_assign_designers(self):
        """Give the demo assets real designers from whatever employees this database has.

        The seeded employees are not XML-id addressable, so look them up instead of
        inventing names. Does nothing if the database has no employees.
        """
        assets = self.env.ref('c2p_creative_studio.demo_brief_digital_savings',
                              raise_if_not_found=False)
        if not assets:
            return
        assets = assets.asset_ids.sorted('id')
        employees = self.env['hr.employee'].sudo().search(
            [('company_id', 'in', self.env.companies.ids)], order='id', limit=len(assets))
        if not employees:
            return
        for index, asset in enumerate(assets):
            asset.designer_id = employees[index % len(employees)]

    def action_view_reviews(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Review Rounds'),
            'res_model': 'c2p.creative.review',
            'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id},
        }


class CreativeReview(models.Model):
    _name = 'c2p.creative.review'
    _description = 'Art Direction Review Round'
    _order = 'asset_id, round desc'

    asset_id = fields.Many2one('c2p.creative.asset', required=True, ondelete='cascade', index=True)
    brief_id = fields.Many2one(related='asset_id.brief_id', store=True)
    company_id = fields.Many2one(related='asset_id.company_id', store=True, index=True)
    round = fields.Integer(default=1, readonly=True, copy=False)
    reviewer_id = fields.Many2one('res.users', string='Reviewer', default=lambda self: self.env.user)
    date = fields.Datetime(default=fields.Datetime.now)
    decision = fields.Selection([
        ('approved', 'Approved'),
        ('changes', 'Changes Requested'),
        ('rejected', 'Rejected'),
    ], required=True, default='changes')
    feedback = fields.Html(string='Feedback')

    @api.model
    def _high_water_mark(self, asset):
        """Highest round number ever issued for this asset.

        Read from the asset's counter rather than from ``max(round)`` over the
        live rows, so withdrawing the latest round does not free its number for
        the next one. Falls back to the live rows for assets that predate the
        counter.
        """
        existing = asset.review_ids.mapped('round') or [0]
        return max(asset.round_counter, max(existing))

    @api.model_create_multi
    def create(self, vals_list):
        # Number each round from the asset's counter, advancing it within this
        # batch so two rounds created at once cannot land on the same number.
        assets = self.env['c2p.creative.asset'].browse(
            {vals['asset_id'] for vals in vals_list if vals.get('asset_id')})
        issued = {asset.id: self._high_water_mark(asset) for asset in assets}
        for vals in vals_list:
            asset_id = vals.get('asset_id')
            if asset_id and not vals.get('round'):
                issued[asset_id] += 1
                vals['round'] = issued[asset_id]
        reviews = super().create(vals_list)
        for asset in assets:
            if asset.round_counter < issued[asset.id]:
                asset.round_counter = issued[asset.id]
        for rev in reviews:
            if rev.decision == 'approved':
                rev.asset_id.state = 'approved'
            elif rev.decision == 'changes':
                rev.asset_id.state = 'changes'
            rev.asset_id.message_post(body=_(
                'Review round %(round)s: %(decision)s',
                round=rev.round,
                decision=dict(self._fields['decision'].selection)[rev.decision]))
        return reviews

    def unlink(self):
        if any(r.decision == 'approved' for r in self) and not self.env.user.has_group(
                'c2p_creative_studio.group_creative_director'):
            raise UserError(_('Only a Creative Director can remove an approving review round.'))
        return super().unlink()
