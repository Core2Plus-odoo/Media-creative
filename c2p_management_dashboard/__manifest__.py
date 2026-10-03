{
    'name': 'C2P Management Dashboard',
    'version': '20.0.1.4.0',
    'category': 'Services/Project',
    'summary': 'Agency management dashboard: profitability, utilisation, pipeline, '
               'receivables and creative throughput',
    'description': """
A single screen for the agency owner, built on live records only.

Panels: profitability by client and by job (revenue against timesheet cost and
media pass-through margin), retainer burn, utilisation by employee and
department, pipeline by stage with win rate and weighted forecast, receivables
ageing, and creative studio throughput. Every figure drills through to the
records behind it.
""",
    'author': 'C2P Consultants',
    'website': 'https://core2plus.com',
    'license': 'LGPL-3',
    'depends': [
        'project',
        'hr_timesheet',
        'sale_timesheet',
        'crm',
        'account',
        'planning',
        'c2p_creative_studio',
    ],
    'data': [
        'security/dashboard_groups.xml',
        'data/ir_cron.xml',
        'views/project_views.xml',
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'c2p_management_dashboard/static/src/dashboard.scss',
            'c2p_management_dashboard/static/src/dashboard.js',
            'c2p_management_dashboard/static/src/dashboard.xml',
        ],
    },
    'application': True,
    'installable': True,
}
