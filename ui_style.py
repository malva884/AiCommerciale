"""Stile UI 'Metriks-like': tema chiaro, accento indigo/viola, hero e agent cards."""
import streamlit as st

CSS = """
<style>
/* ---------- palette & base ---------- */
:root { --mk-indigo: #4f46e5; --mk-violet: #7c3aed; }
.block-container { padding-top: 2rem; max-width: 1400px; }

/* ---------- hero ---------- */
.mk-hero { background: linear-gradient(120deg, #312e81 0%, #4f46e5 55%, #7c3aed 100%);
           color: #fff; border-radius: 18px; padding: 2.6rem 2.2rem 2.2rem;
           margin-bottom: 1.4rem; box-shadow: 0 12px 32px rgba(79,70,229,.25); }
.mk-hero .mk-badge { display: inline-block; background: rgba(255,255,255,.16);
           border: 1px solid rgba(255,255,255,.35); border-radius: 999px;
           padding: .15rem .8rem; font-size: .75rem; letter-spacing: .06em;
           text-transform: uppercase; margin-bottom: .9rem; }
.mk-hero h1 { color: #fff !important; font-size: 2.3rem; font-weight: 800;
              line-height: 1.15; margin: 0 0 .5rem 0; padding: 0; }
.mk-hero p { color: #e0e7ff; font-size: 1.02rem; max-width: 56rem; margin: 0; }

/* ---------- agent cards ---------- */
.mk-agents { display: grid; grid-template-columns: repeat(3, 1fr);
             gap: 1rem; margin-bottom: .4rem; }
.mk-card { background: #fff; border: 1px solid #e6e8f0; border-radius: 16px;
           padding: 1.1rem 1.2rem; box-shadow: 0 4px 14px rgba(15,23,42,.05);
           transition: transform .15s ease, box-shadow .15s ease; }
.mk-card:hover { transform: translateY(-3px);
                 box-shadow: 0 10px 26px rgba(79,70,229,.14); }
.mk-card .mk-ico { font-size: 1.6rem; margin-bottom: .4rem; }
.mk-card h4 { margin: 0 0 .25rem 0; font-size: 1rem; color: #1e293b; }
.mk-card p { margin: 0; font-size: .82rem; color: #64748b; line-height: 1.45; }
@media (max-width: 900px) { .mk-agents { grid-template-columns: 1fr 1fr; } }
@media (max-width: 560px) { .mk-agents { grid-template-columns: 1fr; } }

/* ---------- componenti streamlit ---------- */
div[data-testid="stMetric"] { background: #fff; border: 1px solid #e6e8f0;
    border-radius: 14px; padding: .6rem 1rem;
    box-shadow: 0 2px 8px rgba(15,23,42,.04); }
.stTabs [data-baseweb="tab-list"] { gap: .4rem; }
.stTabs [data-baseweb="tab"] { background: #eef1f7; border-radius: 10px;
    padding: .35rem .9rem; font-weight: 600; }
.stTabs [aria-selected="true"] { background: #4f46e5; }
.stTabs [aria-selected="true"] p { color: #fff !important; }
.stButton > button { border-radius: 10px; font-weight: 600; }
.stButton > button[kind="primary"] {
    background: linear-gradient(90deg, #4f46e5, #7c3aed); border: none; }
section[data-testid="stSidebar"] { background: #f8fafc; }
section[data-testid="stSidebar"] div[role="radiogroup"] label {
    padding: .45rem .8rem; border-radius: 10px; width: 100%;
    transition: background .12s ease; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background: #e8eaf3; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
    background: #4f46e5; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p {
    color: #fff !important; }
</style>
"""


def inject_styles():
    """Inietta il CSS del tema 'Metriks-like' (accento indigo/viola)."""
    st.markdown(CSS, unsafe_allow_html=True)


def hero():
    """Hero a gradiente stile landing SaaS: badge, claim e sottotitolo."""
    st.markdown("""
    <div class="mk-hero">
      <span class="mk-badge">AI Agentica per l'execution commerciale</span>
      <h1>⚡ Co-Pilota Commerciale — Cavi Speciali B2B</h1>
      <p>Intelligence europea su bandi e news, analisi RFP, dossier account,
         retention CRM e prospecting lookalike: un unico ecosistema che legge
         i segnali del mercato e li trasforma in azioni commerciali concrete.</p>
    </div>""", unsafe_allow_html=True)


_AGENTS = [
    ("🎯", "Tender Intelligence",
     "News RSS e bandi TED scorati dall'AI: priorita' commerciale, settore e prossima azione."),
    ("📄", "RFP Analyzer",
     "Capitolati e gare letti dall'LLM: requisiti, scadenze, criteri e strategia d'offerta."),
    ("🏢", "Account Dossier",
     "Scheda cliente da fonti pubbliche: fatturato, struttura, progetti e leve di vendita."),
    ("📊", "CRM Retention",
     "Ordini ERP SQL Server: periodicita', salute pipeline e suggerimenti prodotto."),
    ("✉️", "Outreach AI",
     "Email, LinkedIn e cold-call script multilingua generati sul contesto del prospect."),
    ("🔧", "Admin & Monitor",
     "Motore AI, quota Gemini per-chiave, log pipeline live e storico errori."),
]


def agent_cards():
    """Griglia di card stile Metriks che presenta gli 'agenti' della suite."""
    cards = "".join(
        f'<div class="mk-card"><div class="mk-ico">{i}</div>'
        f"<h4>{t}</h4><p>{d}</p></div>"
        for i, t, d in _AGENTS)
    st.markdown(f'<div class="mk-agents">{cards}</div>', unsafe_allow_html=True)
