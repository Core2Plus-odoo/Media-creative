from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CreativeBrief(models.Model):
    _name = 'c2p.creative.brief'
    _description = 'Creative Brief'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'deadline, id desc'

    name = fields.Char(string='Campaign / Job', required=True, tracking=True)
    reference = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='Client', tracking=True,
                                 check_company=True)
    project_id = fields.Many2one('project.project', string='Project', check_company=True)
    art_director_id = fields.Many2one(
        'res.users', string='Art Director', default=lambda self: self.env.user, tracking=True)
    deadline = fields.Date(tracking=True)
    objective = fields.Html(string='Objective')
    audience = fields.Html(string='Target Audience')
    proposition = fields.Char(string='Single-minded Proposition', tracking=True)
    tone = fields.Char(string='Tone of Voice')
    mandatories = fields.Html(string='Mandatories & Guidelines')
    deliverables = fields.Html(string='Deliverables')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('briefed', 'Briefed'),
        ('concepting', 'Concepting'),
        ('review', 'In Review'),
        ('approved', 'Approved'),
        ('closed', 'Closed'),
    ], default='draft', required=True, tracking=True, group_expand='_group_expand_state')
    concept_ids = fields.One2many('c2p.creative.concept', 'brief_id', string='Concept Routes')
    asset_ids = fields.One2many('c2p.creative.asset', 'brief_id', string='Assets')
    concept_count = fields.Integer(compute='_compute_counts')
    asset_count = fields.Integer(compute='_compute_counts')
    selected_concept_id = fields.Many2one(
        'c2p.creative.concept', compute='_compute_selected_concept', string='Selected Route')
    approval_date = fields.Datetime(readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, default=lambda self: self.env.company)

    @api.model
    def _group_expand_state(self, *args, **kwargs):
        """Show every stage as a kanban column, even when empty.

        Odoo has changed this hook's signature more than once (``stages, domain,
        order`` then ``values, domain``), so accept whatever it is handed.
        """
        return [key for key, _label in self._fields['state'].selection]

    @api.depends('concept_ids', 'asset_ids')
    def _compute_counts(self):
        for rec in self:
            rec.concept_count = len(rec.concept_ids)
            rec.asset_count = len(rec.asset_ids)

    @api.depends('concept_ids.state')
    def _compute_selected_concept(self):
        for rec in self:
            rec.selected_concept_id = rec.concept_ids.filtered(lambda c: c.state == 'selected')[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference') or vals.get('reference') == _('New'):
                company_id = vals.get('company_id') or self.env.company.id
                vals['reference'] = self.env['ir.sequence'].with_company(
                    company_id).next_by_code('c2p.creative.brief') or _('New')
        return super().create(vals_list)

    def action_brief(self):
        self.write({'state': 'briefed'})

    def action_start_concepting(self):
        self.write({'state': 'concepting'})

    def action_send_review(self):
        for rec in self:
            if not rec.concept_ids:
                raise UserError(_('Add at least one concept route before sending for review.'))
        self.write({'state': 'review'})

    def action_approve(self):
        if not self.env.user.has_group('c2p_creative_studio.group_creative_director'):
            raise UserError(_('Only a Creative Director can approve a brief.'))
        for rec in self:
            if not rec.selected_concept_id:
                raise UserError(_('Select one concept route before approving the brief.'))
        self.write({'state': 'approved', 'approval_date': fields.Datetime.now()})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset(self):
        self.write({'state': 'draft'})

    def action_view_concepts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Concept Routes'),
            'res_model': 'c2p.creative.concept',
            'view_mode': 'kanban,list,form',
            'domain': [('brief_id', '=', self.id)],
            'context': {'default_brief_id': self.id},
        }

    def action_view_assets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assets'),
            'res_model': 'c2p.creative.asset',
            'view_mode': 'kanban,list,form',
            'domain': [('brief_id', '=', self.id)],
            'context': {'default_brief_id': self.id},
        }
