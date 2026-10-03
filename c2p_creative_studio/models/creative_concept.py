from odoo import api, fields, models, _
from odoo.exceptions import UserError

SCORE = [('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5')]


class CreativeConcept(models.Model):
    _name = 'c2p.creative.concept'
    _description = 'Concept Route'
    _inherit = ['mail.thread']
    _order = 'brief_id, score desc, id'

    name = fields.Char(string='Route Name', required=True, tracking=True)
    brief_id = fields.Many2one('c2p.creative.brief', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one(related='brief_id.partner_id', store=True)
    company_id = fields.Many2one(related='brief_id.company_id', store=True, index=True)
    tagline = fields.Char()
    rationale = fields.Html(string='Idea & Rationale')
    visual_direction = fields.Html(string='Visual Direction')
    moodboard = fields.Image(string='Moodboard / Key Frame', max_width=1920, max_height=1920)
    author_id = fields.Many2one('res.users', string='Author', default=lambda self: self.env.user)
    state = fields.Selection([
        ('idea', 'Idea'),
        ('shortlisted', 'Shortlisted'),
        ('selected', 'Selected'),
        ('parked', 'Parked'),
        ('rejected', 'Rejected'),
    ], default='idea', required=True, tracking=True, group_expand='_group_expand_state')
    originality = fields.Selection(SCORE, string='Originality')
    brand_fit = fields.Selection(SCORE, string='Brand Fit')
    feasibility = fields.Selection(SCORE, string='Feasibility')
    score = fields.Float(compute='_compute_score', store=True, digits=(3, 1),
                         help='Average of originality, brand fit and feasibility (out of 5).')
    version = fields.Integer(default=1, readonly=True)
    parent_id = fields.Many2one('c2p.creative.concept', string='Refined From', readonly=True, copy=False)
    child_ids = fields.One2many('c2p.creative.concept', 'parent_id', string='Refinements')
    child_count = fields.Integer(compute='_compute_child_count')
    source_ids = fields.Many2many(
        'c2p.creative.concept', 'c2p_creative_concept_combine_rel', 'combined_id', 'source_id',
        string='Combined From', readonly=True, copy=False)

    @api.model
    def _group_expand_state(self, *args, **kwargs):
        return [key for key, _label in self._fields['state'].selection]

    @api.depends('originality', 'brand_fit', 'feasibility')
    def _compute_score(self):
        for rec in self:
            values = [int(v) for v in (rec.originality, rec.brand_fit, rec.feasibility) if v]
            rec.score = sum(values) / len(values) if values else 0.0

    @api.depends('child_ids')
    def _compute_child_count(self):
        for rec in self:
            rec.child_count = len(rec.child_ids)

    def action_shortlist(self):
        self.write({'state': 'shortlisted'})

    def action_select(self):
        if not self.env.user.has_group('c2p_creative_studio.group_art_director'):
            raise UserError(_('Only an Art Director can select the route.'))
        for rec in self:
            others = rec.brief_id.concept_ids.filtered(
                lambda c, rec=rec: c.id != rec.id and c.state == 'selected')
            others.write({'state': 'shortlisted'})
            rec.state = 'selected'

    def action_park(self):
        self.write({'state': 'parked'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_reset(self):
        self.write({'state': 'idea'})

    def action_refine(self):
        """Create the next version of this route, keeping the lineage."""
        self.ensure_one()
        new = self.copy({
            'name': self.name,
            'version': self.version + 1,
            'parent_id': self.id,
            'state': 'idea',
        })
        self.message_post(body=_('Refined into version %s.', new.version))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'c2p.creative.concept',
            'res_id': new.id,
            'view_mode': 'form',
        }

    def action_combine(self):
        """Merge two or more routes of the same brief into a single new route."""
        if len(self) < 2:
            raise UserError(_('Pick at least two routes to combine.'))
        if len(self.brief_id) != 1:
            raise UserError(_('Only routes of the same brief can be combined.'))
        combined = self.create({
            'brief_id': self.brief_id.id,
            'name': _('%s (combined)', ' + '.join(self.mapped('name'))),
            'tagline': self[0].tagline,
            'state': 'shortlisted',
            'source_ids': [(6, 0, self.ids)],
        })
        for rec in self:
            rec.message_post(body=_('Combined into route "%s".', combined.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'c2p.creative.concept',
            'res_id': combined.id,
            'view_mode': 'form',
        }

    def action_view_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refinements'),
            'res_model': 'c2p.creative.concept',
            'view_mode': 'list,form',
            'domain': [('parent_id', '=', self.id)],
        }
