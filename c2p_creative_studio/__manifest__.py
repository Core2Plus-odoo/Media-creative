{
    'name': 'C2P Creative Studio',
    'version': '20.0.1.0.0',
    'category': 'Services/Project',
    'summary': 'Creative briefs, concept routes, art-direction reviews and approvals for agencies',
    'description': """
Creative Studio for agencies, built around the Art Director's role:
receive the brief, develop and score concept routes, refine them in versions,
art-direct deliverables through review rounds and secure approval.
""",
    'author': 'C2P Consultants',
    'website': 'https://core2plus.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'hr', 'project'],
    'data': [
        'security/creative_studio_groups.xml',
        'security/ir.access.csv',
        'data/sequence.xml',
        'views/creative_brief_views.xml',
        'views/creative_concept_views.xml',
        'views/creative_asset_views.xml',
        'views/menus.xml',
    ],
    'demo': [
        'demo/creative_studio_demo.xml',
    ],
    'application': True,
    'installable': True,
}
