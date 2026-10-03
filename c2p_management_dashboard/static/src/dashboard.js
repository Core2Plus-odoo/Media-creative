/** @odoo-module **/

import { Component, onWillStart, proxy } from "@odoo/owl";
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
    // No static props declaration: Owl 3 (Odoo 20) rejects static props and
    // defaultProps outright. This component reads nothing off this.props -- the
    // client action passes the usual action bag and we ignore it -- so there is
    // no schema to express through useProps.

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        const today = new Date();
        const start = new Date(today.getFullYear(), today.getMonth() - 2, 1);
        // Owl 3 (Odoo 20) replaced useState with proxy(), and only a reactive
        // object is visible to the template -- a plain one renders as
        // undefined. This is the pattern core uses throughout, e.g.
        // web/static/src/core/autocomplete/autocomplete.js.
        this.state = proxy({
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
    // presentation helpers: anything the layout needs that is arithmetic or
    // string work, kept out of the template
    // ------------------------------------------------------------------

    /** Up to two initials, for the client league badges. */
    initials(name) {
        return String(name || "")
            .split(/\s+/)
            .filter((word) => word.length)
            .slice(0, 2)
            .map((word) => word[0].toUpperCase())
            .join("");
    }

    /** One value's share of a total, as a percentage, clamped. */
    shareOf(value, total) {
        const divisor = Number(total || 0);
        if (!divisor) {
            return 0;
        }
        return this.clampPct((Math.abs(Number(value || 0)) / Math.abs(divisor)) * 100);
    }

    /** Heat band for a utilisation cell: under-used, healthy, or over. */
    heatTone(percentage) {
        const value = Number(percentage || 0);
        if (value > 100) {
            return "c2p_heat_over";
        }
        if (value >= 75) {
            return "c2p_heat_good";
        }
        if (value >= 50) {
            return "c2p_heat_mid";
        }
        return "c2p_heat_low";
    }

    /** Funnel width: each stage against the widest one. */
    funnelWidth(value, rows, key) {
        const max = Math.max(...rows.map((row) => Math.abs(Number(row[key] || 0))), 1);
        const share = (Math.abs(Number(value || 0)) / max) * 100;
        // never collapse to nothing, or a small stage disappears entirely
        return Math.max(share, 8);
    }

    /** Scroll a section into view from the section nav. */
    jumpTo(sectionId) {
        const target = document.getElementById(sectionId);
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    get sections() {
        return [
            { id: "c2p_s_leaks", label: "Margin leaks" },
            { id: "c2p_s_profit", label: "Profitability" },
            { id: "c2p_s_retainers", label: "Retainers" },
            { id: "c2p_s_util", label: "Utilisation" },
            { id: "c2p_s_pipeline", label: "Pipeline" },
            { id: "c2p_s_pitch", label: "Pitch" },
            { id: "c2p_s_receivables", label: "Receivables" },
            { id: "c2p_s_studio", label: "Studio" },
        ];
    }

    /**
     * Dash array for a progress ring, as a share of its circumference.
     * Kept here rather than in the template so the template holds no maths.
     */
    ringDash(percentage, radius = 42) {
        const circumference = 2 * Math.PI * radius;
        return `${(this.clampPct(percentage) / 100) * circumference} ${circumference}`;
    }

    /** Ring colour band: healthy, watch, or trouble. */
    ringTone(percentage, invert = false) {
        const value = Number(percentage || 0);
        const bad = invert ? value > 66 : value < 34;
        const watch = invert ? value > 33 : value < 67;
        return bad ? "c2p_ring_bad" : watch ? "c2p_ring_watch" : "c2p_ring_good";
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
