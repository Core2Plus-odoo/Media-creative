/** @odoo-module **/

import { Component, onWillStart, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MODEL = "c2p.management.dashboard";

function isoDate(date) {
    return date.toISOString().slice(0, 10);
}

/**
 * One page per client: what they are worth, what they owe, what is in the
 * studio for them, and how the creative is moving.
 *
 * Shares the aggregation service with the dashboard, so the figures on this
 * page and the dashboard's profitability panel are the same figures, read from
 * the same records under the same rights.
 */
export class C2pClient360 extends Component {
    static template = "c2p_management_dashboard.Client360";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        const today = new Date();
        const start = new Date(today.getFullYear(), today.getMonth() - 2, 1);
        this.state = proxy({
            loading: true,
            error: null,
            dateFrom: isoDate(start),
            dateTo: isoDate(today),
            clients: [],
            partnerId: null,
            data: null,
        });

        onWillStart(() => this.loadClients());
    }

    async loadClients() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.clients = await this.orm.call(MODEL, "get_client_list", [], {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
            });
            if (this.state.clients.length) {
                const stillThere = this.state.clients.some(
                    (client) => client.id === this.state.partnerId
                );
                if (!stillThere) {
                    this.state.partnerId = this.state.clients[0].id;
                }
                await this.loadClient();
            } else {
                this.state.data = null;
            }
        } catch (error) {
            this.state.error = error.message || "Could not load the client list.";
            throw error;
        } finally {
            this.state.loading = false;
        }
    }

    async loadClient() {
        if (!this.state.partnerId) {
            this.state.data = null;
            return;
        }
        this.state.data = await this.orm.call(MODEL, "get_client_360", [this.state.partnerId], {
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
        });
    }

    async selectClient(ev) {
        this.state.partnerId = Number(ev.target.value);
        this.state.loading = true;
        try {
            await this.loadClient();
        } finally {
            this.state.loading = false;
        }
    }

    onDateChange(field, ev) {
        this.state[field] = ev.target.value;
    }

    async applyRange() {
        await this.loadClients();
    }

    // ------------------------------------------------------------------
    // formatting, kept identical to the dashboard's
    // ------------------------------------------------------------------
    money(amount) {
        const formatted = new Intl.NumberFormat(undefined, {
            maximumFractionDigits: 0,
        }).format(Math.round(Number(amount || 0)));
        const symbol = (this.state.data && this.state.data.currency_symbol) || "";
        return `${symbol} ${formatted}`.trim();
    }

    hours(value) {
        return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(
            Number(value || 0)
        )} h`;
    }

    pct(value) {
        return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(
            Number(value || 0)
        )}%`;
    }

    clampPct(value) {
        const number = Number(value || 0);
        return number < 0 ? 0 : Math.min(number, 100);
    }

    marginPct() {
        const money = this.state.data && this.state.data.money;
        if (!money || !money.revenue) {
            return 0;
        }
        return (money.gross_margin / money.revenue) * 100;
    }

    // ------------------------------------------------------------------
    // drill-through
    // ------------------------------------------------------------------
    async drill(kind, recordId) {
        const action = await this.orm.call(MODEL, "action_drill", [kind], {
            record_id: recordId || null,
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
        });
        await this.action.doAction(action);
    }
}

registry.category("actions").add("c2p_client_360", C2pClient360);
