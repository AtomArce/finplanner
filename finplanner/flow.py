"""Money-flow map (MindNode-style), prototype v6 feature ported to the Python build.

Returns a structured graph (core-side, testable) of annualized money flow: income sources ->
a central cash pool -> outflows (expenses / taxes / savings). The UI renders it with graphviz.

Under-the-table income is shown but flagged (PROCESS_LOG decision 1) — spendable cash, excluded
from tax, carrying legal/IRS risk. Modeled exactly as entered; not endorsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import PlannerConfig

CASH_POOL = "Cash pool"


@dataclass
class FlowEdge:
    src: str
    dst: str
    amount: float  # annualized USD
    flagged: bool = False  # True for under-the-table (drawn distinct + noted)
    note: str = ""


@dataclass
class FlowGraph:
    sources: list[str]
    sinks: list[str]
    edges: list[FlowEdge] = field(default_factory=list)

    def edge(self, src: str, dst: str) -> FlowEdge | None:
        for e in self.edges:
            if e.src == src and e.dst == dst:
                return e
        return None


def build_flow(cfg: PlannerConfig, summary) -> FlowGraph:
    """Annualized flow graph from config + a built Summary (single source of truth)."""
    sources: list[str] = []
    sinks: list[str] = []
    edges: list[FlowEdge] = []

    def add_source(name: str, amount: float, flagged: bool = False, note: str = "") -> None:
        if amount > 0:
            sources.append(name)
            edges.append(FlowEdge(name, CASH_POOL, amount, flagged=flagged, note=note))

    def add_sink(name: str, amount: float) -> None:
        if amount > 0:
            sinks.append(name)
            edges.append(FlowEdge(CASH_POOL, name, amount))

    # Income sources -> cash pool
    add_source("W-2 wages", cfg.income.w2_earned_ytd_2026)
    add_source("Severance", cfg.severance.total_pretax)
    add_source("Freelance (taxable)", cfg.freelance_taxable_annual)
    add_source(
        "Under-the-table", cfg.freelance_under_table_annual,
        flagged=True, note="excluded from tax; legal/IRS risk; not endorsed",
    )
    add_source("HYSA interest", summary.ledger.taxable_interest_annual)

    # Cash pool -> outflows (annualized)
    add_sink("Rent", cfg.expenses.rent_monthly * 12)
    add_sink("Other living", cfg.expenses.other_monthly * 12)
    add_sink("Student loan", cfg.debt.student_loan.monthly_payment * 12)
    add_sink("Business expense", cfg.bizexp_annual)
    add_sink("SEP IRA", summary.sep_contribution)
    add_sink("Roth IRA", summary.roth_contribution)
    add_sink("Taxable ETF", summary.etf_contribution)
    add_sink("Taxes (2026)", summary.total_tax_due)

    return FlowGraph(sources=sources, sinks=sinks, edges=edges)


def to_dot(graph: FlowGraph) -> str:
    """Render the FlowGraph as graphviz DOT for st.graphviz_chart."""
    lines = ["digraph money {", "  rankdir=LR;", '  node [shape=box, style=rounded];']
    lines.append(f'  "{CASH_POOL}" [shape=ellipse, style=filled, fillcolor="#dceeff"];')
    for src in graph.sources:
        lines.append(f'  "{src}" [style=filled, fillcolor="#d8f5d8"];')
    for sink in graph.sinks:
        lines.append(f'  "{sink}" [style=filled, fillcolor="#ffe6e0"];')
    for e in graph.edges:
        attrs = [f'label="${e.amount:,.0f}"']
        if e.flagged:
            attrs.append('color="red"')
            attrs.append('style="dashed"')
            attrs.append('fontcolor="red"')
        lines.append(f'  "{e.src}" -> "{e.dst}" [{", ".join(attrs)}];')
    lines.append("}")
    return "\n".join(lines)
