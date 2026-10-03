/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MODEL = "c2p.management.dashboard";

function isoDate(date) {
    return date.toISOString().slice(0, 10);
}

/**
 * Management dashboard for an agency director.
 *
 * Every number rendered here arrives from get_dashboard_data, which reads live
 * records under the user's own rights. Nothing is computed client-side beyond
 * layout geometry, so what is on the projector is what is in the database.
 */
export class C2pManagementDashboard extends Component {
    static template = "c2p_management_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        const today = new Date();
        const start = new Date(today.getFullYear(), today.getMonth() - 2, 1);
        this.state = useState({
            loading: true,
            error: null,
            dateFrom: isoDate(start),
            dateTo: isoDate(today),
            data: null,
            client360: null,
        });

        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(MODEL, "get_dashboard_data", [], {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
            });
        } catch (error) {
            this.state.error = error.message || "Could not load the dashboard.";
            throw error;
        } finally {
            this.state.loading = false;
        }
    }

    onDateChange(field, ev) {
        this.state[field] = ev.target.value;
    }

    async applyRange() {
        this.state.client360 = null;
        await this.load();
    }

    async setPreset(preset) {
        const today = new Date();
        let from;
        if (preset === "month") {
            from = new Date(today.getFullYear(), today.getMonth(), 1);
        } else if (preset === "quarter") {
            from = new Date(today.getFullYear(), today.getMonth() - 2, 1);
        } else if (preset === "year") {
            from = new Date(today.getFullYear(), 0, 1);
        } else {
            from = new Date(today.getFullYear() - 1, today.getMonth(), 1);
        }
        this.state.dateFrom = isoDate(from);
        this.state.dateTo = isoDate(today);
        await this.applyRange();
    }

    // ------------------------------------------------------------------
    // formatting
    // ------------------------------------------------------------------
    get currency() {
        return (this.state.data && this.state.data.currency) || { symbol: "", decimals: 0 };
    }

    money(amount) {
        const value = Number(amount || 0);
        const formatted = new Intl.NumberFormat(undefined, {
            maximumFractionDigits: 0,
        }).format(Math.round(value));
        return `${this.currency.symbol || ""} ${formatted}`.trim();
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

    // Templates call these rather than touching Math/Intl directly: OWL compiles
    // bare identifiers as context lookups, so globals are not safe to assume.
    number(value, digits = 1) {
        return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(
            Number(value || 0)
        );
    }

    clampPct(value) {
        const number = Number(value || 0);
        return number < 0 ? 0 : Math.min(number, 100);
    }

    days(value) {
        return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(
            Number(value || 0)
        )} d`;
    }

    // ------------------------------------------------------------------
    // chart geometry: plain SVG, so there is no charting library to keep
    // in step with the web client across versions
    // ------------------------------------------------------------------
    barWidth(value, rows, key) {
        const max = Math.max(...rows.map((row) => Math.abs(Number(row[key] || 0))), 1);
        return Math.min(Math.abs(Number(value || 0)) / max * 100, 100);
    }

    donutSegments(buckets) {
        const total = buckets.reduce((sum, bucket) => sum + Math.abs(bucket.amount || 0), 0);
        if (!total) {
            return [];
        }
        const radius = 54;
        const circumference = 2 * Math.PI * radius;
        let offset = 0;
        return buckets.map((bucket, index) => {
            const share = Math.abs(bucket.amount || 0) / total;
            const segment = {
                label: bucket.label,
                amount: bucket.amount,
                key: bucket.key,
                share: share * 100,
                dash: `${share * circumference} ${circumference}`,
                offset: -offset * circumference,
                shade: index,
            };
            offset += share;
            return segment;
        });
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

    async openClient360(partnerId) {
        this.state.client360 = await this.orm.call(MODEL, "get_client_360", [partnerId], {
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
        });
    }

    closeClient360() {
        this.state.client360 = null;
    }
}

registry.category("actions").add("c2p_management_dashboard", C2pManagementDashboard);
