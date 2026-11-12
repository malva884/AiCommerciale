"""Stile UI 'Metriks Suite' pixel-perfect: dark navy, sidebar, KPI cards con sparkline, zero bug markdown."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {
    --mk-bg: #080c18;
    --mk-sidebar: #050811;
    --mk-card: #0f1526;
    --mk-card-hover: #141c32;
    --mk-border: #1a2238;
    --mk-border-focus: #7c5cff;
    --mk-purple: #7c5cff;
    --mk-purple-glow: rgba(124, 92, 255, 0.28);
    --mk-purple-active: #1c1538;
    --mk-text: #f1f5f9;
    --mk-text-dim: #818ba4;
    --mk-text-muted: #525c76;
    --mk-green: #10b981;
    --mk-green-bg: rgba(16, 185, 129, 0.12);
    --mk-amber: #f59e0b;
    --mk-amber-bg: rgba(245, 158, 11, 0.12);
    --mk-blue: #3b82f6;
    --mk-blue-bg: rgba(59, 130, 246, 0.12);
}

html, body, [class*="css"], .stApp {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    background-color: var(--mk-bg) !important;
    color: var(--mk-text) !important;
}

header[data-testid="stHeader"] {
    background: transparent !important;
    z-index: 1 !important;
}

.block-container {
    padding-top: 4.2rem !important;
    padding-bottom: 3rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1440px !important;
}

/* ==========================================================================
   SIDEBAR METRIKS SUITE IDENTICA ALLA FOTO
   ========================================================================== */
section[data-testid="stSidebar"] {
    background-color: var(--mk-sidebar) !important;
    border-right: 1px solid var(--mk-border) !important;
    width: 270px !important;
}

section[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.2rem !important;
    padding-left: 0.9rem !important;
    padding-right: 0.9rem !important;
}

/* Brand Metriks Suite con Cubo Wireframe 3D */
.mk-brand-container {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 6px 10px 18px 8px;
    margin-bottom: 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.mk-cube-svg {
    width: 32px;
    height: 32px;
    flex-shrink: 0;
}

.mk-brand-title {
    font-size: 1.22rem;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 6px;
}

.mk-brand-badge {
    font-size: 0.62rem;
    font-weight: 600;
    background: rgba(124, 92, 255, 0.2);
    border: 1px solid rgba(124, 92, 255, 0.4);
    color: #c4b5fd;
    padding: 1px 6px;
    border-radius: 999px;
    text-transform: uppercase;
}

/* NASCONDI COMPLETAMENTE IL PALLINO NATIVO DEL RADIO BUTTON */
[data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child,
[data-testid="stSidebar"] div[role="radiogroup"] label div[data-baseweb="radio"] > div:first-child,
[data-testid="stSidebar"] div[role="radiogroup"] input[type="radio"],
[data-testid="stSidebar"] div[role="radiogroup"] svg,
[data-testid="stSidebar"] div[role="radiogroup"] label > div:not(:last-child) {
    display: none !important;
    width: 0 !important;
    height: 0 !important;
    opacity: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}

/* Menu items sidebar identici a Metriks */
section[data-testid="stSidebar"] div[role="radiogroup"] {
    gap: 4px !important;
}

section[data-testid="stSidebar"] div[role="radiogroup"] label {
    display: flex !important;
    align-items: center !important;
    padding: 10px 14px !important;
    border-radius: 12px !important;
    color: #8b95af !important;
    font-size: 0.92rem !important;
    font-weight: 500 !important;
    cursor: pointer !important;
    background: transparent !important;
    border: 1px solid transparent !important;
    margin: 0 0 3px 0 !important;
    width: 100% !important;
    transition: all 0.16s ease !important;
}

section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
    background: #111728 !important;
    color: #e2e8f0 !important;
}

/* Voce attiva con pill viola scuro e bordo viola acceso con glow (esattamente come 'Documenti' nello screenshot) */
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
    background: var(--mk-purple-active) !important;
    border: 1px solid var(--mk-purple) !important;
    box-shadow: 0 0 18px var(--mk-purple-glow), inset 0 0 12px rgba(124, 92, 255, 0.12) !important;
}

section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p {
    color: #ffffff !important;
    font-weight: 600 !important;
}

section[data-testid="stSidebar"] div[role="radiogroup"] label p {
    font-size: 0.92rem !important;
    margin: 0 !important;
}

/* Footer notifiche in fondo alla sidebar */
.mk-notif-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 11px 14px;
    border-radius: 12px;
    background: #101627;
    border: 1px solid var(--mk-border);
    margin-top: 18px;
    color: var(--mk-text-dim);
    font-size: 0.88rem;
    font-weight: 500;
}

.mk-notif-pill {
    background: #251b47;
    color: #c4b5fd;
    border: 1px solid rgba(124, 92, 255, 0.4);
    font-size: 0.75rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
}

/* ==========================================================================
   HEADER PRINCIPALE
   ========================================================================== */
.mk-top-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 24px;
}

.mk-top-title {
    font-size: 2.15rem;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.03em;
    margin: 0 0 5px 0;
    line-height: 1.15;
}

.mk-top-sub {
    font-size: 0.98rem;
    color: var(--mk-text-dim);
    margin: 0;
    font-weight: 400;
}

.mk-date-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: var(--mk-card);
    border: 1px solid var(--mk-border);
    border-radius: 12px;
    font-size: 0.85rem;
    color: #cbd5e1;
    font-weight: 500;
}

/* ==========================================================================
   KPI TILES: 3 COLONNE ORIZZONTALI CON SPARKLINE
   ========================================================================== */
.mk-kpi-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 24px;
    width: 100%;
}

.mk-kpi-card {
    background: var(--mk-card);
    border: 1px solid var(--mk-border);
    border-radius: 16px;
    padding: 18px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    transition: transform 0.15s ease, border-color 0.15s ease;
}

.mk-kpi-card:hover {
    border-color: rgba(124, 92, 255, 0.4);
    transform: translateY(-2px);
}

.mk-kpi-left {
    display: flex;
    align-items: center;
    gap: 16px;
}

.mk-kpi-icon-box {
    width: 48px;
    height: 48px;
    border-radius: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.mk-kpi-icon-purple {
    background: #241c49;
    border: 1px solid rgba(124, 92, 255, 0.35);
    color: #a78bfa;
}

.mk-kpi-icon-blue {
    background: #172242;
    border: 1px solid rgba(59, 130, 246, 0.35);
    color: #60a5fa;
}

.mk-kpi-icon-amber {
    background: #332111;
    border: 1px solid rgba(245, 158, 11, 0.35);
    color: #fbbf24;
}

.mk-kpi-label {
    font-size: 0.82rem;
    color: var(--mk-text-dim);
    font-weight: 500;
    margin-bottom: 4px;
}

.mk-kpi-val-row {
    display: flex;
    align-items: baseline;
    gap: 10px;
}

.mk-kpi-val {
    font-size: 1.85rem;
    font-weight: 800;
    color: #ffffff;
    line-height: 1;
}

.mk-kpi-delta {
    font-size: 0.78rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 3px;
}

.mk-delta-green {
    color: var(--mk-green);
    background: var(--mk-green-bg);
}

.mk-delta-amber {
    color: var(--mk-amber);
    background: var(--mk-amber-bg);
}

.mk-kpi-sub {
    font-size: 0.72rem;
    color: var(--mk-text-muted);
    margin-top: 4px;
}

.mk-sparkline-svg {
    width: 88px;
    height: 38px;
    flex-shrink: 0;
}

/* ==========================================================================
   PANNELLO / CARD
   ========================================================================== */
.mk-panel {
    background: var(--mk-card);
    border: 1px solid var(--mk-border);
    border-radius: 16px;
    padding: 22px 24px;
    margin-bottom: 20px;
}

.mk-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
}

.mk-panel-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #ffffff;
    margin: 0;
}

/* ==========================================================================
   AGENT PANEL LATERALE (STILE 'HR AGENT' A DESTRA NELLA FOTO)
   ========================================================================== */
.mk-agent-sidecard {
    background: var(--mk-card);
    border: 1px solid var(--mk-border);
    border-radius: 16px;
    padding: 18px 20px;
    margin-bottom: 20px;
}

.mk-agent-sidecard-title {
    font-size: 1.02rem;
    font-weight: 700;
    color: #ffffff;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.mk-agent-alert-box {
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.28);
    border-radius: 12px;
    padding: 12px 14px;
    color: #fbbf24;
    font-size: 0.84rem;
    margin-bottom: 14px;
    line-height: 1.4;
}

/* ==========================================================================
   STREAMLIT NATIVE ELEMENTS TWEAKS
   ========================================================================== */
div[data-testid="stDataFrame"], div[data-testid="stTable"] {
    background: var(--mk-card) !important;
    border: 1px solid var(--mk-border) !important;
    border-radius: 14px !important;
    overflow: hidden !important;
}

div[data-testid="stExpander"] {
    background: var(--mk-card) !important;
    border: 1px solid var(--mk-border) !important;
    border-radius: 14px !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 8px !important;
    background: transparent !important;
}

.stTabs [data-baseweb="tab"] {
    background: #111728 !important;
    border: 1px solid var(--mk-border) !important;
    border-radius: 10px !important;
    color: #94a3b8 !important;
    padding: 8px 16px !important;
    font-weight: 600 !important;
}

.stTabs [aria-selected="true"] {
    background: var(--mk-purple) !important;
    border-color: var(--mk-purple) !important;
    color: #ffffff !important;
}

.stTabs [aria-selected="true"] p {
    color: #ffffff !important;
}

.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    border: 1px solid var(--mk-border) !important;
    background: #151c30 !important;
    color: #f1f5f9 !important;
}

.stButton > button:hover {
    border-color: var(--mk-purple) !important;
    color: #ffffff !important;
}

.stButton > button[kind="primary"] {
    background: linear-gradient(90deg, #5b3fd6, #7c5cff) !important;
    border: none !important;
    box-shadow: 0 4px 14px rgba(124, 92, 255, 0.35) !important;
}

.stTextInput input, .stTextArea textarea, .stSelectbox [data-baseweb="select"] {
    background: #111728 !important;
    border: 1px solid var(--mk-border) !important;
    border-radius: 10px !important;
    color: #f1f5f9 !important;
}

@media (max-width: 1050px) {
    .mk-kpi-grid { grid-template-columns: 1fr; }
}
</style>
"""


def inject_styles():
    """Inietta il CSS completo del tema Metriks Suite."""
    st.markdown(CSS, unsafe_allow_html=True)


def brand():
    """Logo e brand Metriks Suite identici alla foto con cubo wireframe 3D isometrico."""
    st.sidebar.markdown(
        '<div class="mk-brand-container">'
        '<svg class="mk-cube-svg" viewBox="0 0 32 32" fill="none">'
        '<path d="M16 2L28 8.5V22.5L16 29L4 22.5V8.5L16 2Z" stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round"/>'
        '<path d="M16 2V15.5" stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round"/>'
        '<path d="M16 15.5L28 8.5" stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round"/>'
        '<path d="M16 15.5L4 8.5" stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round"/>'
        '<path d="M16 29V15.5" stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round"/>'
        '<circle cx="21" cy="6" r="1.5" fill="#a78bfa"/>'
        '<path d="M21 4V8M19 6H23" stroke="#a78bfa" stroke-width="1.3"/>'
        '</svg>'
        '<div>'
        '<div class="mk-brand-title">MB Sales<span style="font-weight:300; opacity:0.9;">Metriks</span></div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True
    )


def sidebar_footer(unresolved_count: int = 0):
    """Pill notifiche/errori fissato sul fondo della sidebar (identico alla foto)."""
    badge_label = str(unresolved_count) if unresolved_count > 0 else "0"
    st.sidebar.markdown(
        '<div class="mk-notif-bar">'
        '<span>🔔 Notifiche & Stato</span>'
        f'<span class="mk-notif-pill">{badge_label}</span>'
        '</div>',
        unsafe_allow_html=True
    )


def page_header(title: str, subtitle: str, date_tag: str = "Novembre 2026"):
    """Header compatto della pagina con titolo bold, sottotitolo e pill della data in alto a destra."""
    st.markdown(
        '<div class="mk-top-header">'
        '<div>'
        f'<div class="mk-top-title">{title}</div>'
        f'<div class="mk-top-sub">{subtitle}</div>'
        '</div>'
        f'<div class="mk-date-pill">📅 {date_tag}</div>'
        '</div>',
        unsafe_allow_html=True
    )


def kpi_cards_row(kpis: list[dict]):
    """Griglia di 3 KPI cards identiche alla foto con icona colorata, delta verde/arancio e sparkline SVG.
    TUTTO IL MARKDOWN È RIGOROSAMENTE FORMATTATO SENZA INDENTAZIONE PER EVITARE BUG PRE/CODE."""
    spk_purple = (
        '<svg class="mk-sparkline-svg" viewBox="0 0 100 40" fill="none">'
        '<path d="M4 32 C 22 28, 30 18, 48 24 C 66 30, 76 8, 96 12" stroke="#8b5cf6" stroke-width="2.6" stroke-linecap="round"/>'
        '<circle cx="96" cy="12" r="2.8" fill="#8b5cf6"/>'
        '</svg>'
    )
    spk_blue = (
        '<svg class="mk-sparkline-svg" viewBox="0 0 100 40" fill="none">'
        '<path d="M4 28 C 24 34, 38 12, 58 20 C 74 26, 82 6, 96 10" stroke="#3b82f6" stroke-width="2.6" stroke-linecap="round"/>'
        '<circle cx="96" cy="10" r="2.8" fill="#3b82f6"/>'
        '</svg>'
    )
    spk_amber = (
        '<svg class="mk-sparkline-svg" viewBox="0 0 100 40" fill="none">'
        '<path d="M4 24 C 20 20, 40 32, 60 16 C 78 4, 86 14, 96 8" stroke="#f59e0b" stroke-width="2.6" stroke-linecap="round"/>'
        '<circle cx="96" cy="8" r="2.8" fill="#f59e0b"/>'
        '</svg>'
    )

    cards = []
    for k in kpis:
        variant = k.get("variant", "purple")
        icon_cls = f"mk-kpi-icon-{variant}"
        delta_cls = "mk-delta-amber" if variant == "amber" else "mk-delta-green"
        spk = spk_amber if variant == "amber" else (spk_blue if variant == "blue" else spk_purple)
        cards.append(
            '<div class="mk-kpi-card">'
            '<div class="mk-kpi-left">'
            f'<div class="mk-kpi-icon-box {icon_cls}"><span style="font-size:1.35rem;">{k["icon"]}</span></div>'
            '<div>'
            f'<div class="mk-kpi-label">{k["label"]}</div>'
            '<div class="mk-kpi-val-row">'
            f'<div class="mk-kpi-val">{k["value"]}</div>'
            f'<div class="mk-kpi-delta {delta_cls}">{k["delta"]}</div>'
            '</div>'
            f'<div class="mk-kpi-sub">{k["sub"]}</div>'
            '</div>'
            '</div>'
            f'<div>{spk}</div>'
            '</div>'
        )

    grid_html = f'<div class="mk-kpi-grid">{"".join(cards)}</div>'
    st.markdown(grid_html, unsafe_allow_html=True)
