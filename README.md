# Media-creative

Odoo 20 custom modules for a creative agency demo. Two modules, both LGPL-3,
authored by C2P Consultants.

| Module | What it does |
| --- | --- |
| `c2p_creative_studio` | Creative briefs, concept routes, art-direction review rounds and approvals. |
| `c2p_management_dashboard` | One screen for the agency director: margin leaks, profitability, retainer burn, utilisation, pipeline, pitch economics, receivables and studio throughput. |

## c2p_creative_studio

Models: `c2p.creative.brief` → `c2p.creative.concept` (routes, versioned and
combinable) → `c2p.creative.asset` → `c2p.creative.review` (numbered rounds).

Roles, replacing blanket `base.group_user` access:

| Group | May |
| --- | --- |
| Creative Studio User | Read and work on briefs, routes and assets. Reads review rounds. |
| Art Director | Shortlist, select and combine routes; record review decisions. |
| Creative Director | Approve a brief; delete records. |

A brief cannot be approved until one route is selected, and only a Creative
Director can approve it. Review rounds number themselves from `max(round) + 1`
per asset, so deleting a round never hands its number to the next one.

## c2p_management_dashboard

An OWL client action (`c2p_management_dashboard` tag) over an ORM-only
aggregation service. No raw SQL, no `sudo()`: every query runs under the calling
user's own access rights and is restricted to `self.env.companies`, so two users
on the same screen can legitimately see different totals.

### How each figure is defined

Nothing here is estimated. Where a database has no data for a panel, the panel
reports zero and says what it looked for.

| Figure | Read from |
| --- | --- |
| Revenue | Posted customer invoice lines on income accounts, `-balance` so credit notes net off. Attributed to a job through the invoice line's sale order line. |
| Timesheet cost | `account.analytic.line.unit_amount` grouped by employee, times that employee's hourly cost. Computed from hours × rate rather than read off the analytic line's own amount, so it matches the stated definition. |
| Media pass-through margin | Vendor purchase order lines (state purchase/done) against sale order lines flagged `is_expense`. Only shown when Purchase is installed. |
| Retainer burn | Timesheet cost in the range against `project.c2p_monthly_fee` × months in range. A retainer with no fee recorded is listed as unconfigured, never guessed. |
| Utilisation | Logged timesheet hours, planned `planning.slot` allocated hours, and capacity from the employee's `resource.calendar`. |
| Pipeline | Open `crm.lead` opportunities grouped by stage; weighted forecast is `expected_revenue × probability / 100`. Win rate is won against won + lost over the range. |
| Pitch cost | Time booked to projects flagged `c2p_is_pitch`, set against the `expected_revenue` of the opportunity each pitch project names. |
| Receivables | Open receivable move lines, `amount_residual`, bucketed on `date_maturity` as at the end of the range. |
| Margin leaks headline | The sum of four separately drillable parts: retainer cost past the fee, fee left on retainers past 80% burn, overdue receivables, and delivered-but-uninvoiced order value (`untaxed_amount_to_invoice`). |
| Creative throughput | Briefs by state, review rounds per asset, and mean `turnaround_days` (first review round to the approving one). |

Every tile and table row drills through to the records behind it.

### Also included

- **Client 360** — one page per client: revenue, margin, open invoices, active
  jobs, retainer burn and recent review rounds. Opened from any client row.
- **Retainer burn alert** — a daily `ir.cron` that posts on the project and
  schedules an activity for the account manager once a retainer passes 80% of
  the month's fee, at most once per retainer per month.
- **Overbooking flag** — employees planned above their weekly calendar capacity,
  each shown alongside peers in the same job role who have spare hours.

### Configuration

Two fields on the project form drive three of the panels:

- **Retainer** + **Monthly Retainer Fee** — enables retainer burn, the burn
  alert, and the over-scope part of the margin-leak headline.
- **Pitch / New Business** + **Opportunity** — enables pitch cost vs win rate.

Until those are set on the relevant projects, the panels say so rather than
showing a number.

### Seeded data

On a database carrying Odoo's demo flag the dashboard shows a banner saying so,
because seeded records otherwise read as real trading activity.
