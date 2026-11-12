"""Stile UI 'Metriks-like': tema scuro navy, accento viola, nav laterale, KPI tile."""
import streamlit as st

CSS = """
<style>
:root { --mk-bg:#0c1120; --mk-panel:#141b31; --mk-border:#222b48;
        --mk-text:#e7eaf5; --mk-dim:#8d96b8; --mk-purple:#7c5cff; }
.stApp, .block-container { background: var(--mk-bg); }
.block-container { padding-top: 1.6rem; max-width: 1400px; }
section[data-testid="stSidebar"] { background: #0a0f1e;
    border-right: 1px solid var(--mk-border); }

/* ---------- brand sidebar ---------- */
.mk-brand { display: flex; align-items: center; gap: .65rem;
            padding: .1rem 0 1rem 0; }
.mk-brand .logo { width: 38px; height: 38px; border-radius: 11px; display: flex;
    align-items: center; justify-content: center; font-size: 1.2rem; color: #fff;
    background: linear-gradient(135deg, #5a3fd6, #8b5cf6);
    box-shadow: 0 4px 14px rgba(124,92,255,.4); }
.mk-brand .name { font-weight: 800; font-size: 1.05rem; color: #fff; line-height: 1.1; }
.mk-brand .sub { font-size: .68rem; color: var(--mk-dim);
                 letter-spacing: .09em; text-transform: uppercase; }

/* ---------- nav laterale ---------- */
section[data-testid="stSidebar"] div[role="radiogroup"] label {
    padding: .5rem .85rem; border-radius: 10px; margin-bottom: 2px;
    transition: background .12s ease; border-left: 3px solid transparent; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background: #141b31; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
    background: linear-gradient(90deg, #5a3fd6, #7c5cff);
    border-left: 3px solid #b79bff; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p {
    color: #fff !important; font-weight: 600; }

/* ---------- page header ---------- */
.mk-ph { margin-bottom: 1.15rem; }
.mk-ph h1 { color: #fff !important; font-size: 1.9rem; font-weight: 800;
            margin: 0; padding: 0; }
.mk-ph p { color: var(--mk-dim); margin: .15rem 0 0 0; font-size: .95rem; }

/* ---------- kpi tiles ---------- */
.mk-kpis { display: grid; grid-template-columns: repeat(4, 1fr);
           gap: 1rem; margin-bottom: 1.2rem; }
.mk-kpi { background: var(--mk-panel); border: 1px solid var(--mk-border);
          border-radius: 14px; padding: 1rem 1.1rem; display: flex;
          gap: .85rem; align-items: flex-start; }
.mk-kpi .ico { min-width: 42px; height: 42px; border-radius: 11px; display: flex;
    align-items: center; justify-content: center; font-size: 1.25rem;
    background: rgba(124,92,255,.16); border: 1px solid rgba(124,92,255,.35); }
.mk-kpi .v { font-size: 1.6rem; font-weight: 800; color: #fff; line-height: 1.1; }
.mk-kpi .l { font-size: .8rem; color: var(--mk-text); font-weight: 600; }
.mk-kpi .cap { font-size: .72rem; color: var(--mk-dim); margin-top: .15rem; }
@media (max-width: 1100px) { .mk-kpis { grid-template-columns: 1fr 1fr; } }
@media (max-width: 560px) { .mk-kpis { grid-template-columns: 1fr; } }

/* ---------- agent cards ---------- */
.mk-agents { display: grid; grid-template-columns: repeat(3, 1fr);
             gap: 1rem; margin: .4rem 0 1.2rem; }
.mk-card { background: var(--mk-panel); border: 1px solid var(--mk-border);
           border-radius: 14px; padding: 1.05rem 1.15rem;
           transition: transform .15s ease, border-color .15s ease; }
.mk-card:hover { transform: translateY(-3px); border-color: var(--mk-purple); }
.mk-card .mk-ico { width: 38px; height: 38px; border-radius: 10px; display: flex;
    align-items: center; justify-content: center; font-size: 1.15rem;
    background: rgba(124,92,255,.16); border: 1px solid rgba(124,92,255,.35);
    margin-bottom: .55rem; }
.mk-card h4 { margin: 0 0 .25rem 0; font-size: .98rem; color: #fff; }
.mk-card p { margin: 0; font-size: .8rem; color: var(--mk-dim); line-height: 1.45; }
@media (max-width: 900px) { .mk-agents { grid-template-columns: 1fr 1fr; } }
@media (max-width: 560px) { .mk-agents { grid-template-columns: 1fr; } }

/* ---------- componenti streamlit ---------- */
div[data-testid="stMetric"] { background: var(--mk-panel);
    border: 1px solid var(--mk-border); border-radius: 14px; padding: .6rem 1rem; }
.stTabs [data-baseweb="tab-list"] { gap: .4rem; }
.stTabs [data-baseweb="tab"] { background: #141b31; border: 1px solid var(--mk-border);
    border-radius: 10px; padding: .35rem .9rem; font-weight: 600; }
.stTabs [aria-selected="true"] { background: var(--mk-purple);
    border-color: var(--mk-purple); }
.stTabs [aria-selected="true"] p { color: #fff !important; }
.stButton > button { border-radius: 10px; font-weight: 600; }
.stButton > button[kind="primary"] {
    background: linear-gradient(90deg, #5a3fd6, #8b5cf6); border: none; }
div[data-testid="stDataFrame"], div[data-testid="stExpander"] {
    border: 1px solid var(--mk-border); border-radius: 14px; overflow: hidden; }
hr { border-color: var(--mk-border); }
.stTextInput input, .stTextArea textarea {
    background: #141b31 !important; border: 1px solid var(--mk-border) !important;
    border-radius: 10px !important; color: var(--mk-text) !important; }
</style>
"""


def inject_styles():
    """Inietta il CSS del tema scuro 'Metriks-like' (navy + viola)."""
    st.markdown(CSS, unsafe_allow_html=True)


def brand():
    """Logo + nome suite in cima alla sidebar (stile Metriks)."""
    st.sidebar.markdown(
        '<div class="mk-brand"><div class="logo">\u26a1</div>'
        '<div><div class="name">AiCommerciale</div>'
        '<div class="sub">AI Sales Suite</div></div></div>',
        unsafe_allow_html=True)


_SUBTITLES = {
    "\U0001f3e0 Panoramica": "La tua suite di agenti AI per lo sviluppo commerciale",
    "\U0001f3af Tender Intelligence & News": "Segnali da news e bandi TED scorati dall'AI",
    "\U0001f4c4 RFP & Capitolati Analyzer": "Analisi capitolati, requisiti e strategia d'offerta",
    "\U0001f3e2 Account Research & Dossier": "Schede account e preparazione meeting da fonti pubbliche",
    "\U0001f4ca CRM & Retention Ordini": "Periodicita', retention e cross-selling da ERP",
    "\U0001f680 New Business & Lookalike UE": "Prospect gemelli in Europa e outreach multilingua",
    "\U0001f527 Admin & Logs": "Motore AI, quota Gemini, monitor pipeline e log errori",
}


def page_header(section: str):
    """Header compatto di sezione: titolo bold + sottotitolo dim (stile Metriks)."""
    sub = _SUBTITLES.get(section, "")
    st.markdown(f'<div class="mk-ph"><h1>{section}</h1><p>{sub}</p></div>',
                unsafe_allow_html=True)


def kpi_tiles(items):
    """Tile KPI scure: icona in quadrato viola, valore, label e caption.
    items: lista di tuple (icona, label, valore, caption)."""
    tiles = "".join(
        f'<div class="mk-kpi"><div class="ico">{i}</div>'
        f'<div><div class="l">{l}</div><div class="v">{v}</div>'
        f'<div class="cap">{c}</div></div></div>'
        for i, l, v, c in items)
    st.markdown(f'<div class="mk-kpis">{tiles}</div>', unsafe_allow_html=True)


_AGENTS = [
    ("\U0001f3af", "Tender Intelligence",
     "News RSS e bandi TED scorati dall'AI: priorita' commerciale, settore e prossima azione."),
    ("\U0001f4c4", "RFP Analyzer",
     "Capitolati e gare letti dall'LLM: requisiti, scadenze, criteri e strategia d'offerta."),
    ("\U0001f3e2", "Account Dossier",
     "Scheda cliente da fonti pubbliche: fatturato, struttura, progetti e leve di vendita."),
    ("\U0001f4ca", "CRM Retention",
     "Ordini ERP SQL Server: periodicita', salute pipeline e suggerimenti prodotto."),
    ("\u2709\ufe0f", "Outreach AI",
     "Email, LinkedIn e cold-call script multilingua generati sul contesto del prospect."),
    ("\U0001f527", "Admin & Monitor",
     "Motore AI, quota Gemini per-chiave, log pipeline live e storico errori."),
]


def agent_cards():
    """Griglia di card scure stile Metriks che presenta gli 'agenti' della suite."""
    cards = "".join(
        f'<div class="mk-card"><div class="mk-ico">{i}</div>'
        f"<h4>{t}</h4><p>{d}</p></div>"
        for i, t, d in _AGENTS)
    st.markdown(f'<div class="mk-agents">{cards}</div>', unsafe_allow_html=True)
