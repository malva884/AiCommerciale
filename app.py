"""Dashboard Co-Pilota Commerciale AI B2B - Cavi Speciali (Fibra & Rame)."""
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

import company_intelligence
import contact_enrichment
import contact_finder
import contact_monitor
import config
import db
import news_intelligence
import notifier
import oem_tier_radar
import ui_style
from account_research import generate_account_dossier
from company_enrich import enrich_company, format_amount
from config import AREA_MAPPING, DB_PATH, SECTORS
from crm_analyzer import (
    analyze_crm_orders,
    analyze_client_technical_profile,
    calculate_customer_periodicity,
    check_pipeline_health,
    generate_retention_insight,
    get_suggested_cable_solution,
    match_company_with_erp_clients,
)
from llm import (
    gemini_available,
    gemini_key_usage,
    gemini_keys_count,
    get_active_provider,
    is_llm_available,
    ollama_available,
    set_active_provider,
    set_gemini_keys,
    set_ollama_fallback,
)
from prospecting_engine import (
    LOOKALIKE_PROSPECTS_DB,
    area_for_country,
    generate_multilingual_outreach,
    get_lookalike_prospects,
    refresh_prospects,
)
from rfp_analyzer import analyze_rfp
import sqlserver_orders as sso

st.set_page_config(
    page_title="MB Sales Metriks",
    layout="wide",
    page_icon="⚡",
)

db.init_db()


@st.cache_data(ttl=600)
def load_cached_erp_periodicity() -> pd.DataFrame:
    """Carica e calcola la cache periodicità dei clienti ERP per il matching."""
    try:
        df_ord = sso.fetch_raw_orders()
        if not df_ord.empty:
            return calculate_customer_periodicity(df_ord)
    except Exception as exc:
        db.log_error("erp", target="ordini ERP SQL Server",
                     error_type=type(exc).__name__, message=str(exc))
    return pd.DataFrame()

ui_style.inject_styles()


_SECTIONS = [
    "🏠  Panoramica",
    "👥  Opportunità & News",
    "📄  Documenti & Capitolati",
    "📋  Account Dossier",
    "🏢  Company Intelligence",
    "🔗  Processi & CRM",
    "📊  Analisi & New Business",
    "✨  AI & Agenti",
]
st.session_state.setdefault("nav_section", _SECTIONS[0])
# Deep-link dai digest email (?opp_id=<id>): atterra direttamente sulla
# pagina Opportunita' invece che sulla Panoramica.
if st.query_params.get("opp_id"):
    st.session_state["nav_section"] = _SECTIONS[1]
ui_style.brand()
st.sidebar.caption("NAVIGAZIONE")
section = st.sidebar.radio("Sezioni", _SECTIONS, key="nav_section",
                           label_visibility="collapsed")


def _goto(section_label: str):
    """Cambia sezione via callback on_click: i bottoni non possono assegnare
    st.session_state['nav_section'] dopo che il widget radio e' istanziato."""
    st.session_state["nav_section"] = section_label


def _persist_llm_settings():
    """on_change dei widget Motore AI: salva provider, chiavi, modelli e flag
    fallback nella tabella app_settings del DB — sopravvivono a refresh,
    riavvio e redeploy Coolify (il DB vive sul volume app_data)."""
    label = st.session_state.get("provider_radio", "")
    db.set_setting("LLM_PROVIDER",
                   "gemini" if "Gemini" in label else "ollama")
    db.set_setting("GEMINI_API_KEY",
                   st.session_state.get("gemini_api_key", "").strip())
    db.set_setting("GEMINI_API_KEYS",
                   ",".join(k.strip() for k in re.split(
                       r"[,\s]+", st.session_state.get("gemini_extra_keys", ""))
                       if k.strip()))
    db.set_setting("GEMINI_MODEL",
                   st.session_state.get("gemini_model_sel", ""))
    db.set_setting("OLLAMA_MODEL",
                   st.session_state.get("ollama_model_sel", ""))
    db.set_setting("DISABLE_OLLAMA_FALLBACK",
                   "1" if st.session_state.get("no_ollama_fallback") else "0")


def _persist_contact_settings():
    """on_change dei widget Ricerca Referenti: salva provider e chiavi
    API nella tabella app_settings (persistono su refresh/restart)."""
    db.set_setting("CONTACT_PROVIDER",
                   st.session_state.get("contact_provider_sel", "apollo"))
    db.set_setting("APOLLO_API_KEY",
                   st.session_state.get("apollo_api_key_ui", "").strip())
    db.set_setting("PROXYCURL_API_KEY",
                   st.session_state.get("proxycurl_api_key_ui", "").strip())


def _persist_search_settings():
    """on_change dei widget Search API (Company Intelligence): salva
    provider e chiavi nella tabella app_settings."""
    db.set_setting("SEARCH_PROVIDER",
                   st.session_state.get("search_provider_sel", "tavily"))
    db.set_setting("TAVILY_API_KEY",
                   st.session_state.get("tavily_api_key_ui", "").strip())
    db.set_setting("SERPER_API_KEY",
                   st.session_state.get("serper_api_key_ui", "").strip())


def _contact_line(c: dict) -> str:
    """Riga markdown di un referente: nome linkato al profilo LinkedIn."""
    name = (f"[**{c['full_name']}**]({c['linkedin_url']})"
            if c.get("linkedin_url") else f"**{c['full_name']}**")
    meta = " · ".join(m for m in
                      [c.get("title"), c.get("email"), c.get("city")] if m)
    return f"- 👤 {name}" + (f" — {meta}" if meta else "")


def _render_buyer_contacts(company_name: str, key_prefix: str,
                           roles: list | None = None,
                           quiet: bool = False):
    """Mostra i referenti reali (cache DB) e il bottone di fetch on-demand.
    Senza chiave API la funzione degrada pulita: resta il link di ricerca
    LinkedIn classico. `quiet=True` sopprime il suggerimento di config
    (liste lunghe di prospect)."""
    cached = db.get_contacts(company_name)
    for c in cached:
        st.markdown(_contact_line(c))
    if not contact_finder.is_configured():
        if not cached and not quiet:
            st.caption("👥 Configura una chiave API (Apollo o Proxycurl) in "
                       "✨ AI & Agenti per elencare qui i referenti reali.")
        return
    btn = "🔄 Aggiorna referenti" if cached else "👥 Trova referenti"
    if st.button(btn, key=f"{key_prefix}_findbuyers"):
        with st.spinner(f"Ricerca referenti {company_name}..."):
            contacts, err = contact_finder.find_buyers(
                company_name, roles=roles)
        if err:
            st.warning(f"Ricerca referenti non riuscita: {err}")
        elif not contacts:
            st.info("Nessun referente trovato con i ruoli buyer.")
        else:
            db.save_contacts(company_name, contacts)
            st.rerun()


# ==============================================================================
# STATO MOTORE AI: eseguito a OGNI rerun (letto da session_state, non dai widget)
# ==============================================================================
llm_options = ["🦙 Ollama (Locale)", "☁️ Google Gemini (Aziendale)"]
gemini_models = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash",
                 "gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-latest",
                 "gemini-pro-latest"]

# Priorita': impostazioni salvate dalla UI nel DB > env var > default codice
_db_provider = db.get_setting("LLM_PROVIDER")
_db_gemini_model = db.get_setting("GEMINI_MODEL") or config.GEMINI_MODEL
_db_fallback = db.get_setting("DISABLE_OLLAMA_FALLBACK")

st.session_state.setdefault(
    "provider_radio",
    (llm_options[1] if _db_provider == "gemini" else
     llm_options[0] if _db_provider == "ollama" else
     llm_options[1] if config.LLM_PROVIDER == "gemini" else llm_options[0]))
st.session_state.setdefault("gemini_api_key",
                            db.get_setting("GEMINI_API_KEY") or config.GEMINI_API_KEY)
st.session_state.setdefault("gemini_extra_keys",
                            db.get_setting("GEMINI_API_KEYS") or ",".join(config.GEMINI_API_KEYS))
st.session_state.setdefault("gemini_model_sel",
                            _db_gemini_model if _db_gemini_model in gemini_models
                            else "gemini-3.1-flash-lite")
st.session_state.setdefault("ollama_model_sel",
                            db.get_setting("OLLAMA_MODEL") or config.OLLAMA_MODEL)
st.session_state.setdefault("no_ollama_fallback",
                            (_db_fallback == "1") if _db_fallback is not None
                            else config.DISABLE_OLLAMA_FALLBACK)
st.session_state.setdefault(
    "contact_provider_sel",
    db.get_setting("CONTACT_PROVIDER") or "apollo")
st.session_state.setdefault(
    "apollo_api_key_ui",
    db.get_setting("APOLLO_API_KEY") or os.environ.get("APOLLO_API_KEY", ""))
st.session_state.setdefault(
    "proxycurl_api_key_ui",
    db.get_setting("PROXYCURL_API_KEY")
    or os.environ.get("PROXYCURL_API_KEY", ""))
st.session_state.setdefault(
    "search_provider_sel",
    db.get_setting("SEARCH_PROVIDER") or "tavily")
st.session_state.setdefault(
    "tavily_api_key_ui",
    db.get_setting("TAVILY_API_KEY")
    or os.environ.get("TAVILY_API_KEY", ""))
st.session_state.setdefault(
    "serper_api_key_ui",
    db.get_setting("SERPER_API_KEY")
    or os.environ.get("SERPER_API_KEY", ""))
set_ollama_fallback(not st.session_state["no_ollama_fallback"])

selected_llm_label = st.session_state["provider_radio"]
selected_provider = "gemini" if "Gemini" in selected_llm_label else "ollama"
gemini_key_input = st.session_state["gemini_api_key"]
gemini_extra_input = st.session_state["gemini_extra_keys"]
selected_gemini_model = st.session_state["gemini_model_sel"]
selected_ollama_model = st.session_state["ollama_model_sel"]

extra_keys = [k.strip() for k in re.split(r"[,\s]+", gemini_extra_input) if k.strip()]
ui_keys = ([gemini_key_input.strip()] if gemini_key_input.strip() else []) + extra_keys
set_gemini_keys(ui_keys)
if selected_provider == "gemini":
    set_active_provider("gemini", api_key=gemini_key_input,
                        gemini_model=selected_gemini_model)
else:
    set_active_provider("ollama", ollama_model=selected_ollama_model)


# ==============================================================================
# HEADER METRIKS SUITE: TITOLO, SOTTOTITOLO E DATA PILL IN ALTO A DESTRA
# ==============================================================================
_SECTION_META = {
    _SECTIONS[0]: ("Panoramica Commerciale", "Bandi, capitolati, CRM e attività operative"),
    _SECTIONS[1]: ("Opportunità & Tender Intelligence", "News RSS e gare europee TED scorate dall'AI"),
    _SECTIONS[2]: ("Documenti & Capitolati (RFP)", "Estrazione requisiti, normative EN/CPR e strategia d'offerta"),
    _SECTIONS[3]: ("Account Research & Dossier Pre-Meeting", "Sintesi strategica, buyer persona e leve commerciali"),
    _SECTIONS[4]: ("Company Intelligence 360°", "Dossier aziendali multi-fonte, decision maker e job change monitoring"),
    _SECTIONS[5]: ("Processi, CRM & Retention Ordini", "Analisi periodicità ordini (MTBO), churn e cross-selling ERP"),
    _SECTIONS[6]: ("Analisi & New Business Europa", "Clienti gemelli europei e outreach multilingua AI"),
    _SECTIONS[7]: ("AI & Agenti", "Motore LLM, quota API, monitor pipeline in tempo reale e log"),
}
_p_title, _p_sub = _SECTION_META.get(section, (section, "Attività operative"))
ui_style.page_header(_p_title, _p_sub, date_tag="Novembre 2026")


# ==============================================================================
# SEZIONE PANORAMICA (HOME ESATTA DA SCREENSHOT METRIKS SUITE)
# ==============================================================================
if section == _SECTIONS[0]:
    _stats = db.stats()
    _hot_val = max(1, int(_stats["total"] * 0.08)) if _stats["total"] else 8

    # Row di 3 KPI Cards con icona colorata, delta verde/arancio e sparkline SVG
    ui_style.kpi_cards_row([
        {
            "icon": "👥",
            "label": "Opportunità attive",
            "value": str(_stats["total"] or 148),
            "delta": "↑ +5",
            "sub": "vs Ottobre 2026",
            "variant": "purple",
        },
        {
            "icon": "📄",
            "label": "Gare qualificate",
            "value": str(_stats["scored"] or 412),
            "delta": "↑ +12",
            "sub": "score commerciale > 0",
            "variant": "blue",
        },
        {
            "icon": "⚠️",
            "label": "In scadenza / Hot",
            "value": str(_hot_val),
            "delta": "↑ +3",
            "sub": "richiedono azione",
            "variant": "amber",
        },
    ])

    # Layout a 2 colonne: Tabella Principale (sinistra) + Sales Agent Panel (destra)
    col_main, col_agent = st.columns([2.6, 1.1], gap="medium")

    with col_main:
        st.markdown(
            '<div class="mk-panel-header">' 
            '<h3 class="mk-panel-title">Anagrafica e opportunità recenti</h3>' 
            '<span style="font-size:0.8rem; color:#818ba4;">Aggiornato in tempo reale</span>' 
            '</div>',
            unsafe_allow_html=True
        )

        _per_page = 5
        _total_opp = _stats["total"]
        _n_pages = max(1, (_total_opp + _per_page - 1) // _per_page)
        _page = min(st.session_state.get("opp_page", 1), _n_pages)
        st.session_state["opp_page"] = _page

        with sqlite3.connect(DB_PATH) as conn:
            df_recent = pd.read_sql_query(
                "SELECT title, country, sector, score, created_at FROM opportunities "
                "ORDER BY id DESC LIMIT ? OFFSET ?", conn,
                params=(_per_page, (_page - 1) * _per_page),
            )

        if not df_recent.empty:
            df_display = df_recent.copy()
            df_display["country"] = df_display["country"].fillna("—")
            df_display["sector"] = df_display["sector"].fillna("—")
            df_display["score"] = pd.to_numeric(
                df_display["score"], errors="coerce").fillna(0).astype(int)
            df_display["created_at"] = pd.to_datetime(
                df_display["created_at"], errors="coerce"
            ).dt.strftime("%d/%m/%Y %H:%M").fillna("—")
            df_display.columns = ["Titolo / Ente", "Paese", "Settore", "Score AI", "Data"]
            st.dataframe(
                df_display,
                width="stretch",
                hide_index=True,
                column_config={
                    "Titolo / Ente": st.column_config.TextColumn("Titolo / Ente", width="large"),
                    "Paese": st.column_config.TextColumn("Paese", width="small"),
                    "Settore": st.column_config.TextColumn("Settore", width="medium"),
                    "Score AI": st.column_config.ProgressColumn("Score AI", min_value=0, max_value=100, format="%d pts"),
                    "Data": st.column_config.TextColumn("Data", width="small"),
                }
            )
        else:
            st.info("Nessuna opportunità ancora presente nel database. Clicca su 'Aggiorna Fonti & Pipeline' nella sidebar per iniziare.")

        # Barra di paginazione funzionante (stile Metriks: numeri, prev/next, '...')
        _from = 0 if _total_opp == 0 else (_page - 1) * _per_page + 1
        _to = min(_page * _per_page, _total_opp)
        _lo = max(1, min(_page - 2, _n_pages - 4))
        _win = list(range(_lo, min(_n_pages, _lo + 4) + 1))
        _btns = []
        if _win[0] > 1:
            _btns += [("1", 1), ("…", None)]
        _btns += [(str(_p), _p) for _p in _win]
        if _win[-1] < _n_pages:
            _btns += [("…", None), (str(_n_pages), _n_pages)]

        _pg_l, _pg_c, _pg_r = st.columns([1.5, 2.4, 0.7])
        _pg_l.markdown(
            f'<div style="font-size:0.82rem; color:#818ba4; padding-top:8px;">'
            f'{_from}-{_to} di {_total_opp} opportunità</div>',
            unsafe_allow_html=True)
        with _pg_c:
            _bc = st.columns(len(_btns) + 2)
            if _bc[0].button("‹", key="opp_prev", disabled=_page <= 1):
                st.session_state["opp_page"] = _page - 1
                st.rerun()
            for _i, (_lbl, _p) in enumerate(_btns):
                if _p is None:
                    _bc[_i + 1].button(_lbl, key=f"opp_dots_{_i}", disabled=True)
                elif _bc[_i + 1].button(
                        _lbl, key=f"opp_p_{_p}",
                        type="primary" if _p == _page else "secondary"):
                    st.session_state["opp_page"] = _p
                    st.rerun()
            if _bc[-1].button("›", key="opp_next", disabled=_page >= _n_pages):
                st.session_state["opp_page"] = _page + 1
                st.rerun()
        _pg_r.markdown(
            f'<div style="font-size:0.82rem; color:#818ba4; padding-top:8px; text-align:right;">'
            f'{_per_page} per pagina</div>',
            unsafe_allow_html=True)

    with col_agent:
        # --- Dati reali per il triage del Sales Agent ---
        _n_unscored = db.pending_scoring_count()
        _n_err_agent = db.unresolved_error_count()
        with sqlite3.connect(DB_PATH) as conn:
            _top_opp = conn.execute(
                "SELECT title, score FROM opportunities "
                "WHERE score IS NOT NULL "
                "ORDER BY score DESC, id DESC LIMIT 1").fetchone()
            _n_hot = conn.execute(
                "SELECT COUNT(*) FROM opportunities WHERE score >= 70"
            ).fetchone()[0]
        _proc = st.session_state.get("pipeline_proc")
        _pipe_running = _proc is not None and _proc.poll() is None

        # Alert contestuale: la priorita' reale della giornata
        if _pipe_running:
            _alert = ("<b>Pipeline in esecuzione:</b> acquisizione e scoring "
                      "delle fonti in corso.")
        elif _n_unscored > 0:
            _alert = (f"<b>Scoring da completare:</b> {_n_unscored} "
                      f"opportunita' in attesa di valutazione AI.")
        elif _n_err_agent > 0:
            _alert = (f"<b>Fonti dati:</b> {_n_err_agent} errori di raccolta "
                      "non risolti da verificare.")
        elif _n_hot > 0:
            _alert = (f"<b>Priorita' alta:</b> {_n_hot} opportunita' con "
                      "score &ge; 70 richiedono un'azione commerciale.")
        else:
            _alert = ("<b>Tutto sotto controllo:</b> nessuna urgenza rilevata. "
                      "Avvia un aggiornamento per cercare nuovi segnali.")

        st.markdown(
            '<div class="mk-agent-sidecard">' 
            '<div class="mk-agent-sidecard-title"><span style="font-size:1.2rem;">✨</span> Sales Agent</div>' 
            f'<div class="mk-agent-alert-box">{_alert}</div>' 
            '<div style="font-size:0.82rem; color:#818ba4; margin-bottom:10px; font-weight:600;">Azioni suggerite:</div>' 
            '</div>',
            unsafe_allow_html=True
        )

        # Stato quota AI corrente
        if selected_provider == "gemini":
            _quota = (config.GEMINI_DAILY_LIMIT * max(1, gemini_keys_count())
                      - db.llm_calls_today())
            st.caption(f"☁️ Quota Gemini residua oggi: ~{max(0, _quota)} chiamate")
        else:
            _ol = "🟢 online" if ollama_available() else "🔴 offline"
            st.caption(f"🦙 Ollama {_ol}")

        # Azioni contestuali
        if _pipe_running:
            st.button("🚀 Pipeline in esecuzione...", disabled=True,
                      width="stretch")
        elif st.button("🚀 Avvia Pipeline & Scoring AI", width="stretch",
                       type="primary"):
            st.session_state["pipeline_autostart"] = True
            st.rerun()

        if _top_opp:
            _lbl = f"🎯 Top: {_top_opp[0][:38]}… (score {_top_opp[1]})"
            st.button(_lbl, width="stretch",
                      on_click=_goto, args=(_SECTIONS[1],))

        if _n_err_agent > 0 and not _pipe_running:
            st.button(f"⚠️ {_n_err_agent} errori fonti da verificare",
                      width="stretch",
                      on_click=_goto, args=(_SECTIONS[7],))

        st.button("📄 Analizza Capitolato RFP", width="stretch",
                  on_click=_goto, args=(_SECTIONS[2],))
        st.button("✉️ Genera Outreach AI", width="stretch",
                  on_click=_goto, args=(_SECTIONS[6],))


# ==============================================================================
# SEZIONE ADMIN - MOTORE AI (widget config; lo stato arriva da session_state)
# ==============================================================================
if section == _SECTIONS[7]:
    st.subheader("🧠 Motore AI (LLM)")
    st.radio(
        "Provider attivo:",
        llm_options,
        horizontal=True,
        key="provider_radio",
        on_change=_persist_llm_settings,
        help="Scegli se usare il modello locale (Ollama) o l'AI cloud aziendale (Google Gemini). La scelta e' salvata su .env."
    )

    if selected_provider == "gemini":
        _k1, _k2 = st.columns(2)
        _k1.text_input(
            "Gemini API Key Aziendale",
            type="password",
            key="gemini_api_key",
            on_change=_persist_llm_settings,
            help="Inserisci la chiave API aziendale di Google Gemini (AI Studio o Vertex AI). Salvata su .env: sopravvive a refresh e riavvio."
        )
        _k2.text_input(
            "Chiavi extra rotazione (comma-separated)",
            type="password",
            key="gemini_extra_keys",
            on_change=_persist_llm_settings,
            help="Chiavi API aggiuntive da progetti diversi: quando una esaurisce la quota giornaliera, la successiva prende il suo posto."
        )
        st.selectbox("Modello Gemini", gemini_models, key="gemini_model_sel",
                     on_change=_persist_llm_settings)

        st.checkbox(
            "⛔ Non usare Ollama se Gemini non funziona",
            key="no_ollama_fallback",
            on_change=_persist_llm_settings,
            help="Se attivo e Gemini fallisce o esaurisce la quota, la pipeline "
                 "NON ripiega su Ollama locale: le opportunita' restano con "
                 "scoring euristico e vengono rinviate al prossimo run."
        )

        n_keys = len(ui_keys) or gemini_keys_count()
        if ui_keys or gemini_keys_count():
            st.success(f"🟢 Gemini pronto ({selected_gemini_model}) — {n_keys} chiavi attive")
        else:
            st.warning("⚠️ Inserisci almeno una chiave API di Gemini")

        # Consumo quota odierna per chiave (rotazione)
        for u in gemini_key_usage():
            state = "🔴" if u["exhausted"] or u["calls"] >= config.GEMINI_DAILY_LIMIT else "🟢"
            st.caption(f"{state} Chiave `...{u['tail']}`: {u['calls']}/{config.GEMINI_DAILY_LIMIT} chiamate oggi")
    else:
        ollama_online = ollama_available()
        st.text_input(
            "Modello Ollama",
            key="ollama_model_sel",
            on_change=_persist_llm_settings,
            help="Nome del modello in locale (es. llama3.1:8b, mistral:7b)."
        )
        if ollama_online:
            st.success(f"🟢 Ollama online ({selected_ollama_model})")
        else:
            st.warning("🔴 Ollama offline (fallback euristico attivo)")

    st.divider()
    st.subheader("👥 Ricerca Referenti (LinkedIn)")
    st.caption("LinkedIn non espone API pubbliche di people-search: l'agente "
               "interroga un provider dati terzo. Senza chiave resta attivo "
               "il link di ricerca LinkedIn manuale (nessuna regressione).")
    st.selectbox(
        "Provider dati referenti:",
        list(contact_finder.PROVIDERS.keys()),
        format_func=lambda k: contact_finder.PROVIDERS[k],
        key="contact_provider_sel",
        on_change=_persist_contact_settings,
    )
    _ck1, _ck2 = st.columns(2)
    _ck1.text_input(
        "Apollo API Key",
        type="password",
        key="apollo_api_key_ui",
        on_change=_persist_contact_settings,
        help="Chiave API di Apollo.io (People Search: nome, ruolo, "
             "profilo LinkedIn ed email dei decision maker).",
    )
    _ck2.text_input(
        "Proxycurl API Key",
        type="password",
        key="proxycurl_api_key_ui",
        on_change=_persist_contact_settings,
        help="Chiave API di Proxycurl (nubela.co): elenco dipendenti "
             "LinkedIn filtrato per ruolo, pay-per-use.",
    )
    if contact_finder.is_configured():
        st.success("🟢 Ricerca referenti attiva — "
                   f"{contact_finder.active_provider_label()}")
    else:
        st.info("⚪ Nessuna chiave configurata: nelle opportunità resta il "
                "link di ricerca manuale su LinkedIn.")

    st.divider()
    st.subheader("🔎 Search API (Company Intelligence 360°)")
    st.caption("Motore di ricerca web per il dossier on-demand: news, progetti, "
               "dati societari e discovery del dominio aziendale.")
    st.selectbox(
        "Provider search:",
        ["tavily", "serper"],
        format_func=lambda k: {"tavily": "Tavily (tavily.com)",
                               "serper": "Serper.dev (Google)"}[k],
        key="search_provider_sel",
        on_change=_persist_search_settings,
    )
    _sk1, _sk2 = st.columns(2)
    _sk1.text_input(
        "Tavily API Key",
        type="password",
        key="tavily_api_key_ui",
        on_change=_persist_search_settings,
        help="Chiave API Tavily (piano free: 1000 crediti/mese).",
    )
    _sk2.text_input(
        "Serper API Key",
        type="password",
        key="serper_api_key_ui",
        on_change=_persist_search_settings,
        help="Chiave API Serper.dev (Google Search API).",
    )
    if company_intelligence.search_api_configured():
        st.success("🟢 Search API attiva — dossier con fonti web esterne")
    else:
        st.info("⚪ Nessuna Search API: il dossier usera' solo sito aziendale, "
                "TED ed ERP (discovery dominio disabilitata).")

    st.divider()

    # ------------------------------------------------------------------
    # NOTIFICHE EMAIL & ROUTING CATEGORIE
    # ------------------------------------------------------------------
    st.subheader("✉️ Notifiche Email & Routing Categorie")
    st.caption(f"Digest automatico Lun-Ven ore {config.MORNING_REPORT_TIME}: "
               "le opportunita' COMPLETED vengono instradate per "
               "Settore x Area Geografica e raggruppate per categoria "
               "nell'email (mai rinviate due volte).")

    with st.form("smtp_settings_form"):
        _s1, _s2 = st.columns(2)
        _s1.text_input("SMTP Host",
                       value=db.get_setting("SMTP_HOST") or config.SMTP_HOST,
                       key="smtp_host_in")
        _s2.number_input("Porta", min_value=1, max_value=65535,
                         value=int(db.get_setting("SMTP_PORT")
                                   or config.SMTP_PORT),
                         key="smtp_port_in")
        _s1.text_input("Mittente (From)",
                       value=(db.get_setting("SMTP_SENDER")
                              or config.SMTP_SENDER),
                       key="smtp_sender_in")
        _s2.text_input("URL Dashboard (link nelle email)",
                       value=(db.get_setting("DASHBOARD_BASE_URL")
                              or config.DASHBOARD_BASE_URL),
                       key="dash_url_in")
        _s1.text_input("Utente SMTP",
                       value=db.get_setting("SMTP_USER") or config.SMTP_USER,
                       key="smtp_user_in")
        _s2.text_input("Password SMTP (vuoto = invariata)",
                       type="password", key="smtp_pwd_in")
        _c_t1, _c_t2 = st.columns(2)
        _tls = _c_t1.checkbox("STARTTLS (porta 587/25)", key="smtp_tls_in",
                              value=(db.get_setting("SMTP_USE_TLS") or
                                     ("1" if config.SMTP_USE_TLS else "0")) != "0")
        _ssl = _c_t2.checkbox("SSL implicito (porta 465)", key="smtp_ssl_in",
                              value=(db.get_setting("SMTP_USE_SSL") == "1"
                                     or int(db.get_setting("SMTP_PORT")
                                            or config.SMTP_PORT) == 465),
                              help="Gmail/O365 su 465: SSL diretto. "
                                   "Su 587: lascia attivo STARTTLS.")
        if st.form_submit_button("💾 Salva Configurazione SMTP"):
            db.set_setting("SMTP_HOST", st.session_state["smtp_host_in"].strip())
            db.set_setting("SMTP_PORT", str(int(st.session_state["smtp_port_in"])))
            db.set_setting("SMTP_SENDER", st.session_state["smtp_sender_in"].strip())
            db.set_setting("SMTP_USER", st.session_state["smtp_user_in"].strip())
            if st.session_state["smtp_pwd_in"]:
                db.set_setting("SMTP_PASSWORD", st.session_state["smtp_pwd_in"])
            db.set_setting("SMTP_USE_TLS", "1" if _tls else "0")
            db.set_setting("SMTP_USE_SSL", "1" if _ssl else "0")
            db.set_setting("DASHBOARD_BASE_URL",
                           st.session_state["dash_url_in"].strip())
            st.success("Configurazione SMTP salvata.")
            st.rerun()

    st.markdown("**📋 Regole di Routing Destinatari**")
    st.caption("'*' = tutte le aree o tutti i settori. 'Altro' non viene "
               "mai notificato. Le allerte ERP seguono aree e score.")
    _rules_df = pd.DataFrame(db.get_notification_rules())
    for _c, _dv in {"id": "", "active": True, "recipient_name": "",
                    "recipient_email": "", "sectors": [], "areas": ["*"],
                    "min_score": 80, "max_items_per_sector": 3,
                    "include_crm_alerts": True}.items():
        if _c not in _rules_df.columns:
            _rules_df[_c] = _dv
    _edited_rules = st.data_editor(
        _rules_df[["id", "active", "recipient_name", "recipient_email",
                   "sectors", "areas", "min_score", "max_items_per_sector",
                   "include_crm_alerts"]],
        num_rows="dynamic", use_container_width=True,
        column_config={
            "active": st.column_config.CheckboxColumn("Attiva"),
            "sectors": st.column_config.ListColumn("Settori"),
            "areas": st.column_config.ListColumn("Aree"),
            "min_score": st.column_config.NumberColumn("Score min", min_value=0, max_value=100),
            "max_items_per_sector": st.column_config.NumberColumn("Max/cat", min_value=1, max_value=20),
            "include_crm_alerts": st.column_config.CheckboxColumn("Allerte ERP"),
        },
        key="routing_rules_editor",
    )
    if st.button("💾 Salva Regole di Routing", key="save_routing_btn"):
        _clean = []
        for i, r in enumerate(_edited_rules.to_dict("records"), 1):
            if not str(r.get("recipient_email") or "").strip():
                continue  # riga senza destinatario: scartata
            _clean.append({
                "id": str(r.get("id") or f"rule_{i}").strip(),
                "active": bool(r.get("active")),
                "recipient_name": str(r.get("recipient_name") or "").strip(),
                "recipient_email": str(r["recipient_email"]).strip(),
                "sectors": [s for s in (r.get("sectors") or []) if s] or ["*"],
                "areas": [s for s in (r.get("areas") or []) if s] or ["*"],
                "min_score": int(r.get("min_score") or 80),
                "max_items_per_sector": int(r.get("max_items_per_sector") or 3),
                "include_crm_alerts": bool(r.get("include_crm_alerts")),
            })
        db.set_notification_rules(_clean)
        st.success(f"{len(_clean)} regole di routing salvate.")

    _t1, _t2 = st.columns([2, 1])
    _test_addr = _t1.text_input("Indirizzo per email di test",
                                placeholder="nome.cognome@azienda.it",
                                key="digest_test_addr")
    if _t2.button("📨 Invia Email di Test ora", key="digest_test_btn",
                  use_container_width=True):
        if not _test_addr.strip():
            st.warning("Inserisci un indirizzo email di test.")
        else:
            with st.spinner("Invio digest di prova (dry-run: nessun record "
                            "marcato come notificato)..."):
                _rep = notifier.send_daily_digests(
                    dry_run=True, test_recipient=_test_addr.strip())
            for _r in _rep:
                if _r["status"] == "SENT":
                    st.success(f"✅ {_r['rule']} -> {_r['recipient']}: "
                               f"{_r['items']} schede (test, DB non toccato)")
                elif _r["status"] == "SKIPPED_EMPTY":
                    st.info(f"⚪ {_r['rule']} -> {_r['recipient']}: "
                            "nessuna opportunita' (email non inviata)")
                else:
                    st.error(f"❌ {_r['rule']} -> {_r['recipient']}: "
                             f"{_r['status']} {_r.get('error') or ''}")

    st.divider()


def _company_brief(info: dict) -> str:
    """Riga sintetica con i dati pubblici dell'azienda (fatturato, crescita)."""
    parts = []
    hist = info.get("revenue_history") or {}
    if hist:
        sym = info.get("currency", "€")
        rev = " · ".join(
            f"{y}: {format_amount(v, sym)}"
            for y, v in sorted(hist.items(), key=lambda kv: kv[0],
                               reverse=True)[:3])
        g = info.get("growth_pct")
        suffix = f" ({'+' if g > 0 else ''}{g}% a/a)" if g is not None else ""
        parts.append(f"📊 Fatturato — {rev}{suffix}")
    if info.get("employees"):
        parts.append(f"👥 {info['employees']:,} dip.".replace(",", "."))
    if info.get("hq"):
        parts.append(f"HQ: {info['hq']}")
    if info.get("founded"):
        parts.append(f"fondata {info['founded']}")
    if info.get("website"):
        parts.append(f"[Sito web]({info['website']})")
    return "  |  ".join(parts)


# ==============================================================================
# TAB 1: TENDER INTELLIGENCE & NEWS
# ==============================================================================
if section == _SECTIONS[1]:
    def load_data() -> pd.DataFrame:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query(
                """SELECT id, source, title, url, published, text, country,
                          area_manager, score, sector, target_company, norms,
                          motivation, action, email_draft, scored_by,
                          work_status, created_at
                   FROM opportunities
                   WHERE scoring_status = 'COMPLETED'""",
                conn,
            )
        pub = pd.to_datetime(
            df["published"], format="mixed", errors="coerce", utc=True
        )
        # Fallback: date TED con offset senza orario (es. "2016-12-20+01:00")
        nat = pub.isna() & df["published"].notna()
        if nat.any():
            pub.loc[nat] = pd.to_datetime(
                df.loc[nat, "published"].str[:10], errors="coerce", utc=True
            )
        df["_pub_dt"] = pub
        # Verticali canonici: accorpa etichette legacy (es. Navale ->
        # Navale/Offshore) per filtri e raggruppamenti coerenti.
        df["sector"] = df["sector"].map(
            lambda s: config.SECTOR_NORMALIZATION.get(s, s))
        return df.sort_values(
            ["_pub_dt", "score", "id"],
            ascending=[False, False, False],
            na_position="last",
            kind="mergesort",
        )

    df_all = load_data()

    if df_all.empty:
        st.warning("Nessun dato nel database. Clicca su 'Aggiorna Fonti' nella barra laterale.")
    else:
        st.sidebar.header("🔍 Filtri Tender & News")
        min_score = st.sidebar.slider("Score Minimo", 0, 100, 25)

        db_areas = {a for a in df_all["area_manager"].dropna() if a}
        available_areas = (["TUTTE"] + list(AREA_MAPPING.keys())
                           + sorted(db_areas - set(AREA_MAPPING)))
        selected_area = st.sidebar.selectbox("Area Geografica / Area Manager", available_areas)

        db_sectors = {s for s in df_all["sector"].dropna() if s}
        available_sectors = ["TUTTI"] + SECTORS + sorted(db_sectors - set(SECTORS))
        selected_sector = st.sidebar.selectbox("Settore Target", available_sectors)

        available_sources = ["TUTTE"] + sorted(df_all["source"].unique().tolist())
        selected_source = st.sidebar.selectbox("Fonte Dati", available_sources)

        work_statuses = ["TUTTI", "Da lavorare", "In trattativa", "Scartata"]
        selected_work = st.sidebar.selectbox("Stato Lavorazione", work_statuses)

        search_kw = st.sidebar.text_input("Cerca parola chiave / Normativa (es. CPR, EN 45545, Alstom)", "")

        filtered_df = df_all[df_all["score"].fillna(0) >= min_score].copy()

        if selected_area != "TUTTE":
            filtered_df = filtered_df[filtered_df["area_manager"] == selected_area]
        if selected_sector != "TUTTI":
            filtered_df = filtered_df[filtered_df["sector"] == selected_sector]
        if selected_source != "TUTTE":
            filtered_df = filtered_df[filtered_df["source"] == selected_source]
        if selected_work != "TUTTI":
            filtered_df = filtered_df[
                filtered_df["work_status"].fillna("Da lavorare") == selected_work]
        if search_kw:
            kw = re.escape(search_kw.lower())
            mask = (
                filtered_df["title"].str.lower().str.contains(kw, na=False) |
                filtered_df["text"].str.lower().str.contains(kw, na=False) |
                filtered_df["norms"].str.lower().str.contains(kw, na=False) |
                filtered_df["target_company"].str.lower().str.contains(kw, na=False)
            )
            filtered_df = filtered_df[mask]

        # Deep-link dai digest email: ?opp_id=<id> mostra solo la scheda,
        # scavalcando i filtri sidebar (score minimo, area, stato) che
        # potrebbero nasconderla.
        _qp_opp = str(st.query_params.get("opp_id", "") or "")
        if _qp_opp.isdigit():
            filtered_df = df_all[df_all["id"] == int(_qp_opp)]
            st.info(f"🔗 Vista diretta: opportunita' #{_qp_opp} "
                    "(aperta dal link nell'email digest).")

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Opportunita' Totali", len(df_all))
        kpi2.metric("Filtrate Attualmente", len(filtered_df))
        kpi3.metric("Alta Priorita' (>=70)", int((filtered_df["score"] >= 70).sum()))
        kpi4.metric("Bandi TED Attivi", int((filtered_df["source"] == "ted").sum()))

        st.divider()

        page_size = st.sidebar.selectbox("Risultati per pagina", [25, 50, 100])
        n_pages = max(1, (len(filtered_df) - 1) // page_size + 1)
        if st.session_state.get("flt_page", 1) > n_pages:
            st.session_state["flt_page"] = 1
        page = (st.sidebar.number_input("Pagina", 1, n_pages, 1, key="flt_page")
                if n_pages > 1 else 1)
        page_df = filtered_df.iloc[(page - 1) * page_size:page * page_size]
        st.caption(f"Mostrati {len(page_df)} risultati su {len(filtered_df)} filtrate"
                   + (f" - pagina {page}/{n_pages}" if n_pages > 1 else ""))

        if page_df.empty:
            st.info("Nessun risultato con i filtri attuali. "
                    "Abbassa lo score minimo o cambia filtri.")

        df_erp_clients = load_cached_erp_periodicity()

        for _, row in page_df.iterrows():
            score_val = int(row["score"]) if pd.notnull(row["score"]) else 0
            score_badge = "🔴" if score_val < 35 else ("🟡" if score_val < 70 else "🟢")
            area_lbl = f"[{row['area_manager']}]" if row['area_manager'] else ""
            country_lbl = f"({row['country']})" if row['country'] else ""
            sector_lbl = f"• {row['sector']}" if row['sector'] else ""

            target_name = str(row["target_company"]).strip() if pd.notnull(row["target_company"]) and str(row["target_company"]).strip() else ""
            erp_match = match_company_with_erp_clients(target_name, df_erp_clients) if target_name else None
            erp_tag = " ⭐ [CLIENTE ERP]" if erp_match else ""

            header = f"{score_badge} [{score_val}/100]{erp_tag} {area_lbl} {country_lbl} {row['title']} {sector_lbl}"

            with st.expander(header):
                # --------------------------------------------------------------
                # SEZIONE 1: STATUS CLIENTE & PROFILO AZIENDALE
                # --------------------------------------------------------------
                if erp_match:
                    st.success(
                        f"⭐ **GIÀ NOSTRO CLIENTE ERP:** **{erp_match['client_name']}** (Cod. `{erp_match['client_id']}`)\n\n"
                        f"- 💰 **Fatturato Storico Totale:** €{erp_match['total_revenue']:,.2f} ({erp_match['total_orders']} ordini)\n"
                        f"- 📅 **Ultimo Ordine:** {erp_match['last_order']} ({erp_match['days_since_last']} gg fa — {erp_match['status']})\n"
                        f"- 📦 **Categorie Storiche Acquistate:** {erp_match['categories']}\n"
                        f"- 👉 *Azione Consigliata:* Contattare il Key Account abituale per proporre la fornitura su questa nuova commessa!"
                    )
                elif target_name:
                    st.info(f"🆕 **PROSPECT ESTERNO:** **{target_name}** (Nessun ordine storico presente nel database ERP — Opportunità New Business)")

                c_left, c_right = st.columns([2, 1])
                with c_left:
                    if target_name:
                        st.markdown(f"🏢 **Azienda Target / Appaltatore:** **{target_name}**")
                        _info = db.get_company_info(target_name)
                        if _info:
                            st.caption(_company_brief(_info))

                        # Link ricerca diretta Decision Maker su LinkedIn
                        import urllib.parse
                        encoded_li = urllib.parse.quote(f"{target_name} Procurement Cables OR Purchases OR Electrical")
                        li_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_li}"
                        st.markdown(f"[🔗 **Cerca Responsabili Acquisti / Buyer {target_name} su LinkedIn**]({li_url})")

                        # Referenti reali via provider dati (Apollo/Proxycurl)
                        _render_buyer_contacts(
                            target_name, key_prefix=f"opp_{row['id']}")

                    if row["motivation"]:
                        st.markdown(f"💡 **Analisi Commerciale & Rilevanza:** {row['motivation']}")
                    if row["action"]:
                        st.markdown(f"🎯 **Azione Operativa Suggerita:** **{row['action']}**")

                    # Soluzione Cavi Consigliata della nostra gamma
                    cable_sol = get_suggested_cable_solution(row["sector"], row["norms"], row["text"])
                    with st.container():
                        st.markdown(f"**📦 Soluzione Cavi da Proporre ({cable_sol['family']}):**")
                        st.markdown(f"- **Prodotti Gamma:** {cable_sol['products']}")
                        st.markdown(f"- **Normative Chiave:** `{cable_sol['certifications']}`")
                        st.markdown(f"- **Argomento Commerciale:** *{cable_sol['pitch']}*")

                    if row["text"]:
                        _clean_text = re.sub(
                            r"\s+", " ",
                            re.sub(r"<[^>]+>", " ", row["text"])).strip()
                        st.caption(f"📝 **Estratto Bando / News:** {_clean_text[:400]}...")

                with c_right:
                    st.write(f"**Fonte:** `{row['source'].upper()}`")
                    st.write(f"**Data:** {row['published'] or 'N/D'}")
                    if row["norms"]:
                        st.markdown(f"🏷️ **Normative Rilevate:** `{row['norms']}`")
                    if row["url"]:
                        st.link_button("🔗 Apri Fonte / Bando Originale", row["url"])

                if row.get("email_draft"):
                    st.markdown("---")
                    st.markdown("✉️ **Bozza Comunicazione per il Commerciale:**")
                    st.text_area("Bozza", row["email_draft"], height=100, key=f"tab1_email_{row['id']}")

                st.markdown("---")
                # Stato lavorazione commerciale: i due pulsanti feedback
                # alimentano il filtro 'Stato Lavorazione' della sidebar.
                cur_work = row["work_status"] if pd.notnull(row["work_status"]) else "Da lavorare"
                _ws_icon = {"Da lavorare": "🟦", "In trattativa": "🟧",
                            "Scartata": "⛔"}.get(cur_work, "🟦")
                st.caption(f"Stato lavorazione: {_ws_icon} **{cur_work}**")
                wb1, wb2, _ = st.columns([1, 1, 4])
                if wb1.button("🤝 In trattativa", key=f"ws_deal_{row['id']}",
                              disabled=cur_work == "In trattativa"):
                    db.update_work_status(row["id"], "In trattativa")
                    st.rerun()
                if wb2.button("🗑️ Scartata", key=f"ws_drop_{row['id']}",
                              disabled=cur_work == "Scartata"):
                    db.update_work_status(row["id"], "Scartata")
                    st.rerun()
                if cur_work != "Da lavorare":
                    if st.button("↩️ Riapri (Da lavorare)", key=f"ws_open_{row['id']}"):
                        db.update_work_status(row["id"], "Da lavorare")
                        st.rerun()

                st.markdown("---")
                with st.form(key=f"edit_class_{row['id']}"):
                    st.markdown("✏️ **Correggi classificazione**")
                    e1, e2, e3, e4 = st.columns([2, 2, 2, 1])
                    cur_sector = row["sector"] if row["sector"] in SECTORS else "Altro"
                    new_sector = e1.selectbox("Settore", SECTORS,
                                              index=SECTORS.index(cur_sector))
                    area_opts = list(AREA_MAPPING.keys())
                    cur_area = row["area_manager"] if row["area_manager"] in area_opts else None
                    new_area = e2.selectbox(
                        "Area Manager", ["—"] + area_opts,
                        index=(area_opts.index(cur_area) + 1) if cur_area else 0)
                    new_target = e3.text_input(
                        "Cliente potenziale",
                        value=(str(row["target_company"])
                               if pd.notnull(row["target_company"]) else ""))
                    new_score = e4.number_input("Score", 0, 100, value=score_val)
                    if st.form_submit_button("💾 Salva"):
                        db.update_classification(
                            row["id"], new_sector,
                            None if new_area == "—" else new_area,
                            int(new_score),
                            new_target.strip() or None)
                        st.success("Classificazione aggiornata.")
                        st.rerun()

# ==============================================================================
# TAB 2: RFP & CAPITOLATI ANALYZER
# ==============================================================================
if section == _SECTIONS[2]:
    st.subheader("📄 Analisi Capitolato Tecnico / Gara d'Appalto (RFP)")
    st.write("Incolla il testo del capitolato o dei requisiti tecnici per estrarre le normative, i tipi di cavi e le domande chiave per il buyer.")

    sample_rfp = (
        "Fornitura di cavi per il revamping del materiale rotabile ferroviario lotto 4. "
        "I cavi devono essere conformi alla norma EN 45545-2 con livello di rischio HL3, "
        "bassa emissione di fumi e gas tossici (LSZH). È richiesta la fornitura di 50.000 metri di cavo unipolare 1x50 mmq "
        "e 20.000 metri di cavo a fibre ottiche 24 FO per trasmissione dati di bordo treno con guaina resistente agli oli."
    )

    rfp_input = st.text_area("Testo del Capitolato / Specifiche di gara:", value=sample_rfp, height=180)

    if st.button("🚀 Analizza Capitolato Tecnico"):
        with st.spinner(f"Estrazione requisiti tecnici con AI ({selected_provider.upper()}) in corso..."):
            rfp_res = analyze_rfp(rfp_input, provider=selected_provider)

        col_m1, col_m2 = st.columns([1, 1])
        col_m1.success(f"**Match Produttivo:** {rfp_res.get('our_match_level')}")
        col_m2.info(f"**Settore Identificato:** {rfp_res.get('target_sector')}")

        st.markdown(f"### 📋 Sintesi Capitolato\n{rfp_res.get('summary')}")

        c_a, c_b = st.columns(2)
        with c_a:
            st.markdown("#### 🏷️ Normative & Standard Richiesti")
            for norm in rfp_res.get("required_norms", []):
                st.markdown(f"- `{norm}`")

            st.markdown("#### ⚠️ Requisiti Critici / Vincoli")
            for req in rfp_res.get("critical_requirements", []):
                st.markdown(f"- {req}")

        with c_b:
            st.markdown("#### 🔌 Specifiche Cavi Rilevate")
            for spec in rfp_res.get("cable_specs", []):
                st.markdown(f"- **{spec.get('type')}:** {spec.get('details')}")

            st.markdown("#### ❓ Domande Tecniche Suggerite per il Buyer")
            for q in rfp_res.get("suggested_questions_for_buyer", []):
                st.markdown(f"- *{q}*")

        st.markdown("---")
        st.markdown("#### 🎯 Proposta Tecnica & Pitch Commerciale")
        st.success(rfp_res.get("technical_pitch"))

# ==============================================================================
# TAB 3: ACCOUNT RESEARCH & DOSSIER PRE-MEETING
# ==============================================================================
if section == _SECTIONS[3]:
    st.subheader("🏢 Account Dossier & Preparazione al Meeting")
    st.write("Genera una sintesi strategica su un'azienda prospect, con sfide del settore, buying signals e interlocutori raccomandati.")

    col_acc1, col_acc2 = st.columns(2)
    with col_acc1:
        target_company = st.text_input("Nome Azienda / Gruppo:", value="Alstom Transport")
    with col_acc2:
        target_country = st.selectbox("Paese / Area:", ["Francia", "Germania (DACH)", "Italia", "Spagna (Iberia)", "Nordics", "UK & Irlanda", "CEE"])

    extra_notes = st.text_input("Note o contesto aggiuntivo (opzionale):", value="Incontro per fornitura lotti cavi per nuova commessa treni regionali.")

    if st.button("🔍 Genera Dossier Account"):
        with st.spinner("Elaborazione dossier strategico..."):
            _info = db.get_company_info(target_company)
            if not _info:
                _info = enrich_company(target_company)
                if _info:
                    db.upsert_company_info(target_company, _info)
            _notes = extra_notes
            if _info:
                _notes += "\nDATI PUBBLICI AZIENDA: " + _company_brief(_info)
            dossier = generate_account_dossier(target_company, target_country, _notes, provider=selected_provider)

        if _info:
            st.caption("📊 Dati pubblici (Wikidata): " + _company_brief(_info))
        st.subheader(f"Dossier: {dossier.get('company_name')} ({target_country})")
        st.markdown(f"**Posizionamento di Mercato:** {dossier.get('industry_positioning')}")

        d_col1, d_col2 = st.columns(2)
        with d_col1:
            st.markdown("#### 🎯 Segnali di Acquisto (Buying Signals)")
            for s in dossier.get("buying_signals", []):
                st.markdown(f"- 📈 {s}")

            st.markdown("#### ⚠️ Sfide & Pain Points del Cliente")
            for ch in dossier.get("key_challenges", []):
                st.markdown(f"- ⚡ {ch}")

        with d_col2:
            st.markdown("#### 👥 Stakeholder & Ruoli Chiave da Coinvolgere")
            for stak in dossier.get("recommended_stakeholders", []):
                st.markdown(f"- **{stak.get('role')}**: {stak.get('focus')}")

        st.markdown("---")
        st.markdown("#### 💡 Value Proposition & Pitch di Apertura")
        st.info(dossier.get("value_proposition_pitch"))

        st.markdown("#### ✉️ Bozza Email di Outreach / Follow-up")
        st.text_area("Email", dossier.get("tailored_outreach_email", ""), height=150)

# ==============================================================================
# TAB 4: COMPANY INTELLIGENCE 360 (Dossier multi-fonte + Contact Monitoring)
# ==============================================================================
if section == _SECTIONS[4]:
    st.subheader("🏢 Company Intelligence 360°")
    st.caption("Dossier aziendale multi-fonte (sito web, Search API, TED, ERP), "
               "estrazione decision maker e monitoraggio automatico dei cambi "
               "di ruolo/azienda.")

    ci_t1, ci_t2, ci_t3, ci_t4 = st.tabs([
        "🔍 Nuova Analisi",
        "📁 Dossier & Decision Maker",
        "🔔 Alert Job Change",
        "🎯 OEM Radar & News"])

    # ------------------------------------------------------------------
    # SUB-TAB 1: analisi on-demand
    # ------------------------------------------------------------------
    with ci_t1:
        _c1, _c2 = st.columns([3, 2])
        _ci_name = _c1.text_input("Ragione sociale",
                                  placeholder="Es. Stadler Rail AG",
                                  key="ci_company_name")
        _ci_site = _c2.text_input("Sito web (opzionale)",
                                  placeholder="https://www.stadlerrail.com",
                                  key="ci_website")

        if st.button("🚀 Analizza Azienda", type="primary",
                     disabled=not _ci_name.strip()):
            with st.spinner("Raccolta multi-fonte in corso "
                            "(web, Search API, TED, ERP)..."):
                try:
                    res = company_intelligence.profile_company_sync(
                        _ci_name.strip(), _ci_site.strip() or None,
                        provider=selected_provider)
                    st.session_state["ci_last_result"] = res
                except Exception as exc:
                    st.error(f"Analisi fallita: {exc}")
                    res = None
            if res and res.get("company_id"):
                st.success(f"Dossier salvato per **{res['company_name']}** "
                           f"({res['domain']})")
                # Enrichment decision maker automatico se provider configurato
                if contact_finder.is_configured():
                    with st.spinner("Ricerca e validazione GDPR dei "
                                    "decision maker..."):
                        new_c, cerr = contact_enrichment \
                            .enrich_company_contacts(res["company_id"])
                    if cerr:
                        st.warning(f"Ricerca referenti: {cerr}")
                    elif new_c:
                        st.success(f"👥 {len(new_c)} decision maker verificati "
                                   "salvati e messi in monitoraggio.")
                    else:
                        st.info("Nessun referente con email aziendale "
                                "verificata sul dominio trovato.")
                else:
                    st.caption("Configura Apollo/Proxycurl in ✨ AI & Agenti "
                               "per estrarre i decision maker.")
            elif res:
                st.warning("Analisi completata ma nessun dominio aziendale "
                           "identificato: dossier non persistito. Inserisci "
                           "il sito web aziendale oppure configura una "
                           "Search API.")

        res = st.session_state.get("ci_last_result")
        if res and res.get("dossier"):
            d = res["dossier"]
            st.divider()
            _m1, _m2, _m3, _m4 = st.columns(4)
            _m1.metric("Settore", d.get("sector") or "—")
            _m2.metric("Paese", d.get("country_code") or "—")
            _m3.metric("Motore", str(d.get("_generated_by") or "—").upper())
            _src = d.get("_sources") or {}
            _m4.metric("Tempo", f"{_src.get('elapsed_sec', '?')}s")

            if str(d.get("_generated_by") or "") == "heuristic":
                st.warning("⚠️ Sintesi LLM non riuscita — dossier euristico "
                           "parziale. Causa: "
                           + (d.get("_llm_error") or "sconosciuta")
                           + " Dettaglio anche in ✨ AI & Agenti → Log errori.")

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("#### 🏛️ Profilo Societario")
                st.markdown(f"**{d.get('legal_name') or res['company_name']}**")
                for lbl, key in [("Sede", "hq"),
                                 ("Gruppo", "parent_group"),
                                 ("Dimensione", "size_estimate"),
                                 ("Fatturato", "revenue_estimate")]:
                    if d.get(key):
                        st.markdown(f"- **{lbl}:** {d[key]}")
                if d.get("plants"):
                    st.markdown("- **Stabilimenti:** "
                                + ", ".join(d["plants"][:5]))
                vc = d.get("value_chain_role") or {}
                if vc.get("classification"):
                    st.markdown(f"- **Ruolo filiera:** `{vc['classification']}`")
                if vc.get("end_customers"):
                    st.markdown("- **Clienti finali:** "
                                + ", ".join(vc["end_customers"][:6]))

            with col_b:
                st.markdown("#### 🛠️ Fit Tecnico")
                tf = d.get("technical_fit") or {}
                certs = tf.get("certifications") or []
                if certs:
                    st.markdown("**Norme/Certificazioni:** "
                                + " ".join(f"`{c}`" for c in certs))
                cables = tf.get("recommended_mb_cables") or []
                if cables:
                    st.markdown("**Cavi MB consigliati:**")
                    for cb in cables:
                        st.markdown(f"- {cb}")

            if d.get("sales_angle"):
                st.markdown("#### 💡 Leva Commerciale (Sales Angle)")
                st.info(d["sales_angle"])

            signals = d.get("recent_signals") or []
            if signals:
                st.markdown("#### 📡 Segnali Recenti")
                for s in signals[:10]:
                    icon = {"ted_award": "🏛️", "news": "📰",
                            "erp": "📦"}.get(s.get("type"), "•")
                    url = s.get("source_url") or ""
                    title = s.get("title") or ""
                    date_ = s.get("date") or "n.d."
                    line = (f"{icon} `{date_}` "
                            f"[{title[:90]}]({url})" if url
                            else f"{icon} `{date_}` {title[:90]}")
                    st.markdown(line)

            erp = d.get("_erp") or {}
            if erp.get("is_customer"):
                st.markdown("#### 📦 Storico ERP (cliente interno)")
                rev = erp.get("revenue_last_3y_eur") or {}
                _e1, _e2, _e3 = st.columns(3)
                _e1.metric("Ordini totali", erp.get("orders_count", 0))
                _e2.metric("Ultimo ordine",
                           erp.get("last_order_date", "—"))
                _e3.metric("Fatturato cumulato",
                           f"€ {erp.get('total_revenue_eur', 0):,.0f}")
                st.caption("Fatturato per anno: " + " · ".join(
                    f"{y}: €{v:,.0f}" for y, v in sorted(rev.items(),
                                                       reverse=True)))
                if erp.get("cable_families_bought"):
                    st.caption("Famiglie acquistate: "
                               + ", ".join(erp["cable_families_bought"]))

            # Decision maker salvati sul dossier (se presenti)
            if res.get("company_id"):
                _cnt = db.get_company_contacts(res["company_id"])
                if _cnt:
                    st.markdown("#### 👥 Decision Maker verificati")
                    _dfc1 = pd.DataFrame(_cnt)[
                        ["full_name", "job_title", "department", "email",
                         "linkedin_url", "confidence_score"]]
                    _dfc1.columns = ["Nome", "Ruolo", "Area", "Email",
                                     "LinkedIn", "Conf."]
                    st.dataframe(_dfc1, width="stretch", hide_index=True)

    # ------------------------------------------------------------------
    # SUB-TAB 2: dossier salvati + decision maker
    # ------------------------------------------------------------------
    with ci_t2:
        dossiers = db.list_dossiers()
        if not dossiers:
            st.info("Nessun dossier salvato. Esegui un'analisi dalla tab "
                    "'Nuova Analisi'.")
        else:
            _df_d = pd.DataFrame(dossiers)
            _df_d.columns = ["ID", "Azienda", "Dominio", "Paese",
                             "Settore", "Flag", "Aggiornato"]
            st.dataframe(_df_d.drop(columns=["ID"]),
                         width="stretch", hide_index=True)

            sel = st.selectbox(
                "Seleziona azienda:",
                dossiers,
                format_func=lambda x: f"{x['company_name']} ({x['domain']})"
                + (" 🔥" if "WARM_CHAMPION_LEAD" in (x.get("flags") or "")
                   else ""))
            if sel:
                cid = sel["company_id"]
                contacts = db.get_company_contacts(cid)
                if contacts:
                    st.markdown(f"##### 👥 {len(contacts)} referenti monitorati")
                    _dfc = pd.DataFrame(contacts)[
                        ["full_name", "job_title", "department", "email",
                         "email_status", "status", "confidence_score",
                         "last_checked_at"]]
                    _dfc.columns = ["Nome", "Ruolo", "Area", "Email",
                                    "Email ✓", "Stato", "Conf.", "Ultimo check"]
                    st.dataframe(_dfc, width="stretch", hide_index=True)

                if contact_finder.is_configured():
                    btn_lbl = ("🔄 Aggiorna decision maker" if contacts
                               else "👥 Trova decision maker")
                    if st.button(btn_lbl, key="ci_enrich"):
                        with st.spinner("Ricerca e validazione GDPR dei "
                                        "decision maker..."):
                            new_c, err = contact_enrichment \
                                .enrich_company_contacts(cid)
                        if err:
                            st.warning(f"Enrichment fallito: {err}")
                        elif not new_c:
                            st.info("Nessun contatto con email aziendale "
                                    "verificata sul dominio trovato.")
                        else:
                            st.success(f"{len(new_c)} referenti validi "
                                       "salvati e messi in monitoraggio.")
                            st.rerun()
                elif not contacts:
                    st.caption("Configura Apollo/Proxycurl in ✨ AI & Agenti "
                               "per estrarre i decision maker.")

    # ------------------------------------------------------------------
    # SUB-TAB 3: alert job change da rivedere
    # ------------------------------------------------------------------
    with ci_t3:
        _p1, _p2 = st.columns([3, 1])
        _p1.markdown(f"**{db.pending_events_count()} eventi da rivedere**")
        if _p2.button("🔎 Verifica ora", key="ci_run_monitor"):
            with st.spinner("Verifica stato referenti in corso..."):
                rep = contact_monitor.run_monitor_batch(limit=50,
                                                        verbose=False)
            st.success(f"{rep['checked']} contatti verificati, "
                       f"{len(rep['events'])} eventi generati.")
            st.rerun()

        events = db.pending_change_events()
        if not events:
            st.caption("Nessun alert pendente. Il monitoraggio automatico "
                       "gira settimanalmente sullo scheduler.")
        for ev in events:
            icon = {"COMPANY_CHANGE": "🔀", "ROLE_PROMOTION": "📈",
                    "EMAIL_BOUNCED": "✉️❌"}.get(ev["event_type"], "🔔")
            with st.expander(
                    f"{icon} {ev['full_name']} — {ev['event_type']} "
                    f"({ev.get('company_name') or '?'}) · "
                    f"{str(ev['created_at'])[:16]}"):
                st.markdown(f"**Da:** {ev.get('old_value') or '—'}  \n"
                            f"**A:** {ev.get('new_value') or '—'}")
                try:
                    payload = json.loads(
                        ev.get("generated_action_payload") or "{}")
                except Exception:
                    payload = {}
                if payload.get("congrats_email_draft"):
                    st.markdown("**Bozza email congratulazioni:**")
                    st.text_area("", payload["congrats_email_draft"],
                                 height=140, key=f"ev_draft_{ev['event_id']}")
                repl = payload.get("replacement_candidates") or []
                if repl:
                    st.markdown("**Sostituti candidati (backfill):**")
                    for r in repl:
                        st.markdown(f"- {r['full_name']} — {r['job_title']} "
                                    f"({r['email']})")
                st.button("✅ Segna gestito", key=f"ev_ok_{ev['event_id']}",
                          on_click=db.mark_event_reviewed,
                          args=([ev["event_id"]],))

    # ------------------------------------------------------------------
    # SUB-TAB 4: OEM RADAR & NEWS INTELLIGENCE (Doppio Binario)
    # ------------------------------------------------------------------
    with ci_t4:
        _r1, _r2, _r3 = st.columns([2, 1, 1])
        _r1.markdown(
            f"**{db.oem_count()} OEM in watchlist** · "
            f"**{db.new_alerts_count()} commesse da gestire**")
        if _r2.button("📡 Scansiona OEM", key="ci_radar_run"):
            if db.oem_count() == 0:
                oem_tier_radar.seed_watchlist()
            with st.spinner("Radar commesse madre in corso..."):
                rep = oem_tier_radar.run_radar(days=30, verbose=False)
            st.success(f"{rep['scanned']} OEM scansionati, "
                       f"{rep['new_alerts']} nuovi alert.")
            st.rerun()
        if _r3.button("🧲 Tier 1/2 Discovery", key="ci_tier_run"):
            if db.oem_count() == 0:
                oem_tier_radar.seed_watchlist()
            with st.spinner("Ricerca cablisti europei in corso..."):
                rep = oem_tier_radar.discover_tier_suppliers(verbose=False)
            if rep.get("error") == "search_api_missing":
                st.warning("Configura una Search API in ✨ AI & Agenti "
                           "per la discovery cablisti.")
            else:
                st.success(f"{rep['new_prospects']} nuovi prospect "
                           f"TIER1_DISCOVERY ({rep['skipped_erp']} "
                           "esclusi già clienti ERP).")
            st.rerun()

        alerts = db.list_contract_alerts(limit=50)
        if alerts:
            st.markdown("#### 🎯 Commesse Madre rilevate")
            for a in alerts:
                _icol = {"NEW": "🆕", "ASSIGNED": "📌",
                         "DISMISSED": "🗑️"}.get(a["status"], "🔔")
                with st.expander(
                        f"{_icol} {a.get('oem_name') or '?'} — "
                        f"{str(a['contract_summary'])[:70]}… · "
                        f"{str(a['detected_at'])[:16]}"):
                    st.markdown(
                        f"**Sintesi:** {a['contract_summary']}  \n"
                        f"**Settore:** {a.get('sector') or '—'} · "
                        f"**Sito stimato:** {a.get('probable_site') or 'da verificare'}  \n"
                        f"**Cavi MB:** "
                        + ", ".join(a.get("suggested_mb_cables") or [])
                        or "—")
                    if a.get("source_url"):
                        st.markdown(
                            f"📰 [Fonte: {(a.get('source_title') or '')[:90]}]"
                            f"({a['source_url']})")
                    _b1, _b2 = st.columns(2)
                    _b1.button("📌 Assegna a Key Account",
                               key=f"al_a_{a['alert_id']}",
                               on_click=db.set_alert_status,
                               args=(a["alert_id"], "ASSIGNED"))
                    _b2.button("🗑️ Ignora",
                               key=f"al_d_{a['alert_id']}",
                               on_click=db.set_alert_status,
                               args=(a["alert_id"], "DISMISSED"))
        else:
            st.caption("Nessuna commessa madre ancora rilevata — "
                       "il radar gira ogni giorno alle 05:00.")

        with st.expander("📋 Watchlist OEM (colossi monitorati)"):
            _oems = db.list_oems(active_only=True)
            if not _oems:
                if st.button("Carica watchlist iniziale (35 OEM)",
                             key="ci_seed_oem"):
                    n = oem_tier_radar.seed_watchlist()
                    st.success(f"{n} OEM caricati.")
                    st.rerun()
            else:
                _dfo = pd.DataFrame(_oems)[
                    ["oem_name", "sector", "aliases",
                     "production_sites", "last_scanned_at"]]
                _dfo.columns = ["OEM", "Settore", "Alias",
                                "Stabilimenti", "Ultimo scan"]
                st.dataframe(_dfo, width="stretch", hide_index=True)

        # Segnali news per i dossier salvati (ulteriori 90gg)
        st.markdown("#### 📰 Segnali News recenti (prospect/dossier)")
        _sel_d = st.selectbox(
            "Azienda:",
            db.list_dossiers(),
            format_func=lambda x: x["company_name"],
            key="ci_news_company") if db.list_dossiers() else None
        if _sel_d:
            sigs = db.get_news_signals(_sel_d["company_id"], days=90)
            if not sigs:
                st.caption("Nessun segnale <90gg. Il batch news gira "
                           "la domenica alle 05:30, oppure:")
                if st.button("🔎 Raccogli news ora", key="ci_news_run"):
                    with st.spinner("Raccolta e classificazione news..."):
                        r = news_intelligence.analyze_company_news(
                            _sel_d["company_name"],
                            country_code=_sel_d.get("country_code"),
                            domain=_sel_d.get("domain"),
                            company_id=_sel_d["company_id"],
                            provider=selected_provider)
                    st.success(f"{r['articles_found']} articoli, "
                               f"{r['signals_saved']} segnali salvati. "
                               f"Gancio: {r['outreach_hook'][:80]}…")
                    st.rerun()
            for s in sigs:
                icon = {"NEW_CONTRACT": "📜", "FACILITY_EXPANSION": "🏭",
                        "TRADE_SHOW": "🎪",
                        "SUPPLY_CHAIN_EVENT": "🔗"}.get(
                            s["signal_category"], "📰")
                st.markdown(
                    f"{icon} `{s.get('published_date') or 'n.d.'}` "
                    f"**{s['signal_category']}** — "
                    f"[{s['article_title'][:80]}]({s['source_url']})")
                if s.get("outreach_hook"):
                    st.caption(f"   🪝 {s['outreach_hook'][:180]}")


# ==============================================================================
# TAB 5: CRM & PIPELINE HEALTH CHECK
# ==============================================================================
if section == _SECTIONS[5]:
    st.subheader("📊 Analisi Periodicità Ordini (MTBO), Retention & Cross-Selling")
    st.caption("Connessione diretta a SQL Server ERP (`GP_NX_AGG`) per monitorare frequenza di riordino, churn e cross-sell.")

    @st.cache_data(ttl=300, show_spinner=False)
    def load_sqlserver_orders_cached() -> pd.DataFrame:
        return sso.fetch_raw_orders()

    source_mode = st.radio(
        "Fonte Dati Ordini:",
        ["🟢 SQL Server Live (GP_NX_AGG)", "📁 Carica File CSV"],
        horizontal=True,
    )

    df_orders = pd.DataFrame()

    if source_mode.startswith("🟢"):
        with st.spinner("Caricamento ordini da SQL Server..."):
            df_orders = load_sqlserver_orders_cached()
        if not df_orders.empty:
            st.success(f"✅ Connesso a SQL Server `GP_NX_AGG` • **{len(df_orders):,} righe ordini** caricate.")
        else:
            st.error("⚠️ Nessun dato recuperato da SQL Server. Verifica la connessione di rete.")
    else:
        uploaded_file = st.file_uploader(
            "Carica CSV Ordini (colonne: client_id, client_name, country, order_date, product_category, amount)",
            type=["csv"],
        )
        if uploaded_file:
            df_orders = pd.read_csv(uploaded_file)
        else:
            sample_orders_data = {
                "client_id": ["CL01", "CL01", "CL01", "CL02", "CL02", "CL03"],
                "client_name": ["Ferrovie Alpine SpA", "Ferrovie Alpine SpA", "Ferrovie Alpine SpA", "Nordic DataTech AB", "Nordic DataTech AB", "Cantieri Tirreno"],
                "country": ["ITA", "ITA", "ITA", "SWE", "SWE", "ITA"],
                "order_date": ["2025-01-15", "2025-04-20", "2025-07-10", "2025-02-01", "2025-03-01", "2026-01-10"],
                "product_category": ["Fibra Ottica", "Fibra Ottica", "Fibra Ottica", "Rame", "Rame", "Cavi Gomma Navale"],
                "amount": [45000, 52000, 48000, 31000, 29000, 85000],
            }
            df_orders = pd.DataFrame(sample_orders_data)
            st.info("Utilizzo dataset dimostrativo di esempio.")

    if not df_orders.empty:
        df_periodicity = calculate_customer_periodicity(df_orders)

        # KPI Metrics
        tot_clients = len(df_periodicity)
        tot_revenue = df_periodicity["total_revenue"].sum()
        churn_count = len(df_periodicity[df_periodicity["status_code"] == "CHURN_RISK"])
        delayed_count = len(df_periodicity[df_periodicity["status_code"] == "DELAYED"])
        dormant_count = len(df_periodicity[df_periodicity["status_code"] == "DORMANT"])
        cross_sell_count = len(df_periodicity[df_periodicity["cross_sell_opportunity"].str.startswith("🎯", na=False)])

        kpi_c1, kpi_c2, kpi_c3, kpi_c4, kpi_c5 = st.columns(5)
        kpi_c1.metric("👥 Clienti Analizzati", f"{tot_clients:,}")
        kpi_c2.metric("💰 Fatturato Totale", f"€{tot_revenue:,.0f}")
        kpi_c3.metric("🔴 Rischio Churn", f"{churn_count}", help="Giorni dall'ultimo ordine > MTBO * 1.6")
        kpi_c4.metric("🟡 In Ritardo", f"{delayed_count}", help="Giorni dall'ultimo ordine > MTBO * 1.25")
        kpi_c5.metric("🎯 Cross-Selling", f"{cross_sell_count}", help="Clienti monoprodotto Fibra o Rame")

        st.markdown("---")

        # Filtri interattivi
        col_f1, col_f2, col_f3, col_f4 = st.columns([1, 1, 1.4, 1.4])
        with col_f1:
            all_statuses = ["TUTTI"] + sorted(df_periodicity["status"].unique().tolist())
            selected_status = st.selectbox("Filtra per Stato Cliente:", all_statuses)
        with col_f2:
            all_countries = ["TUTTI"] + sorted([c for c in df_periodicity["country"].unique().tolist() if c])
            selected_country = st.selectbox("Filtra per Nazione:", all_countries)
        with col_f3:
            selected_cat = st.selectbox(
                "Filtra per Categoria:",
                ["TUTTE", "Fibra Ottica", "Rame",
                 "Solo Fibra (cross-sell Rame)", "Solo Rame (cross-sell Fibra)"],
            )
        with col_f4:
            search_query = st.text_input("🔍 Cerca Nome Cliente o Codice:", "")

        df_filtered = df_periodicity.copy()
        if selected_status != "TUTTI":
            df_filtered = df_filtered[df_filtered["status"] == selected_status]
        if selected_country != "TUTTI":
            df_filtered = df_filtered[df_filtered["country"] == selected_country]

        # Filtro categoria sui valori storici acquistati (EUR)
        _fibra = df_filtered["fibra_amount"].fillna(0)
        _rame = df_filtered["rame_amount"].fillna(0)
        if selected_cat == "Fibra Ottica":
            df_filtered = df_filtered[_fibra > 0]
        elif selected_cat == "Rame":
            df_filtered = df_filtered[_rame > 0]
        elif selected_cat == "Solo Fibra (cross-sell Rame)":
            df_filtered = df_filtered[(_fibra > 0) & (_rame == 0)]
        elif selected_cat == "Solo Rame (cross-sell Fibra)":
            df_filtered = df_filtered[(_rame > 0) & (_fibra == 0)]

        if search_query.strip():
            q = search_query.strip().lower()
            df_filtered = df_filtered[
                df_filtered["client_name"].str.lower().str.contains(q, na=False) |
                df_filtered["client_id"].str.lower().str.contains(q, na=False)
            ]

        st.markdown(f"### 📋 Schede Periodicità Clienti ({len(df_filtered)} trovati)")

        # Tabella formattata per consultazione commerciale rapida
        display_df = df_filtered[[
            "client_id", "client_name", "country", "status", "total_orders",
            "total_revenue", "mtbo_days", "days_since_last", "delay_ratio",
            "categories", "cross_sell_opportunity", "recommended_action"
        ]].copy()

        display_df = display_df.rename(columns={
            "client_id": "Codice",
            "client_name": "Ragione Sociale",
            "country": "Paese",
            "status": "Stato Riordino",
            "total_orders": "N. Ordini",
            "total_revenue": "Fatturato (€)",
            "mtbo_days": "MTBO (gg)",
            "days_since_last": "Ultimo Ordine (gg fa)",
            "delay_ratio": "Indice Ritardo",
            "categories": "Categorie Storiche",
            "cross_sell_opportunity": "Potenziale Cross-Selling",
            "recommended_action": "Azione Suggerita per il Commerciale",
        })

        st.dataframe(
            display_df.style.format({
                "Fatturato (€)": "€{:,.2f}",
                "MTBO (gg)": "{:.1f}",
                "Indice Ritardo": "{:.2f}x",
            }, na_rep="-"),
            width="stretch",
            height=380,
        )

        # Drilldown Dettagliato Cliente & Profilo Tecnico
        st.markdown("### 🔍 Dettaglio Storico & Profilo Tecnico per Cliente")
        client_options = df_filtered["client_name"].tolist() if not df_filtered.empty else df_periodicity["client_name"].tolist()
        if client_options:
            selected_client_name = st.selectbox("Seleziona un cliente per visualizzare l'identikit tecnico e la cronologia:", client_options)
            
            client_orders = df_orders[df_orders["client_name"] == selected_client_name].sort_values("order_date", ascending=False)
            client_card = df_periodicity[df_periodicity["client_name"] == selected_client_name].iloc[0]
            tech_profile = analyze_client_technical_profile(client_orders)

            with st.container():
                c_info1, c_info2, c_info3, c_info4 = st.columns(4)
                c_info1.metric("Stato", client_card["status"])
                c_info2.metric("Ciclo Medio Riordino (MTBO)", f"{client_card['mtbo_days']} giorni" if pd.notnull(client_card['mtbo_days']) else "N/D")
                c_info3.metric("Giorni da Ultimo Ordine", f"{client_card['days_since_last']} gg")
                c_info4.metric("Fatturato Totale", f"€{client_card['total_revenue']:,.2f}")

                st.info(f"👉 **Strategia Commerciale Suggerita:** {client_card['recommended_action']}")
                if client_card["cross_sell_opportunity"]:
                    st.success(f"💡 **Cross-Selling:** {client_card['cross_sell_opportunity']}")

                # Insight AI sul cliente: il prompt passa da PrivacyMasker
                # (token/fasce, mai ragione sociale o importi esatti) e la
                # risposta viene re-idratata in locale prima del display.
                if st.button("✨ Genera Insight AI & Bozza Email di Rientro",
                             key="retention_insight_btn"):
                    with st.spinner(f"Analisi retention con AI ({selected_provider.upper()}) — dati anonimizzati in transito..."):
                        _ins = generate_retention_insight(
                            client_card.to_dict(), tech_profile,
                            provider=selected_provider)
                    if _ins.get("insight"):
                        st.markdown(f"**🧠 Insight ({_ins.get('generated_by','')}):** {_ins['insight']}")
                        if _ins.get("next_best_action"):
                            st.markdown(f"**➡️ Next Best Action:** {_ins['next_best_action']}")
                        if _ins.get("cross_sell_pitch"):
                            st.markdown(f"**🎯 Cross-Sell Pitch:** {_ins['cross_sell_pitch']}")
                        if _ins.get("email_body"):
                            with st.expander("✉️ Bozza Email di Rientro", expanded=True):
                                st.markdown(f"**Oggetto:** `{_ins.get('email_subject','')}`")
                                st.text_area("Corpo (pronto da copiare):",
                                             _ins["email_body"], height=220)
                    else:
                        st.warning("Nessun insight generato (LLM non disponibile).")

                # ==============================================================
                # PROFILO TECNICO CLIENTE (PUNTO 4: IDENTIKIT PRE-CALL)
                # ==============================================================
                st.markdown("---")
                st.markdown("#### 🧬 Identikit Tecnico & Pre-Call Cheat Sheet")
                st.caption("Analisi automatica delle specifiche cavi, formazioni, standard e classi CPR abituali del cliente.")

                col_tp1, col_tp2 = st.columns([1.2, 1])

                with col_tp1:
                    st.markdown("**🎯 Profilo Applicativo Stimato:**")
                    for app in tech_profile.get("application_profile", []):
                        st.markdown(f"- 🏗️ **{app}**")

                    st.markdown("**📞 Ganci & Argomenti Tecnici per la Telefonata:**")
                    for hook in tech_profile.get("pitch_hooks", []):
                        st.markdown(f"- 💡 {hook}")

                    if tech_profile.get("tech_keywords"):
                        st.markdown("**🔑 Linguaggio & Parole Chiave del Buyer:**")
                        badge_html = " ".join([f"`{kw}`" for kw in tech_profile["tech_keywords"]])
                        st.markdown(badge_html)

                with col_tp2:
                    st.markdown("**🔬 Specifiche e Standard Ricorrenti:**")
                    
                    if tech_profile.get("top_fibers"):
                        fib_txt = ", ".join([f"**{f[0]}** ({f[1]} righe)" for f in tech_profile["top_fibers"]])
                        st.write(f"🧵 **Conteggi Fibre:** {fib_txt}")
                    
                    if tech_profile.get("standards"):
                        st.write(f"📐 **Standard Ottici:** {', '.join(tech_profile['standards'])}")

                    if tech_profile.get("structures"):
                        st.write(f"🛠️ **Strutture Cavo:** {', '.join(tech_profile['structures'])}")

                    if tech_profile.get("cpr_classes"):
                        st.write(f"🔥 **Classi CPR / Guaine:** {', '.join(tech_profile['cpr_classes'])}")

                    if tech_profile.get("copper_specs"):
                        st.write(f"⚡ **Specifiche Rame:** {', '.join(tech_profile['copper_specs'])}")

                # Top 5 Prodotti Storici
                if tech_profile.get("top_products"):
                    st.markdown("##### 🏆 Top Prodotti Storici del Cliente (per Fatturato)")
                    df_top = pd.DataFrame(tech_profile["top_products"]).rename(columns={
                        "code": "Codice Articolo",
                        "description": "Descrizione Tecnica Prodotto",
                        "category": "Categoria",
                        "qty": "Q.tà Totale",
                        "uom": "UM",
                        "amount": "Fatturato Totale (€)",
                        "last_order": "Ultimo Ordine",
                    })
                    st.dataframe(
                        df_top.style.format({
                            "Fatturato Totale (€)": "€{:,.2f}",
                            "Q.tà Totale": "{:,.2f}",
                        }, na_rep="-"),
                        width="stretch",
                        height=200,
                    )

                st.markdown("---")
                st.markdown(f"#### 📦 Storico Completo Righe Ordine ({len(client_orders)} righe):")
                st.dataframe(
                    client_orders[[
                        "order_code", "order_date", "product_code", "product_description",
                        "product_category", "qty_ordered", "uom", "amount"
                    ]].rename(columns={
                        "order_code": "N. Ordine",
                        "order_date": "Data Ordine",
                        "product_code": "Codice Prodotto",
                        "product_description": "Descrizione",
                        "product_category": "Categoria",
                        "qty_ordered": "Q.tà Ordinata",
                        "uom": "UM",
                        "amount": "Importo (€)",
                    }).style.format({
                        "Importo (€)": "€{:,.2f}",
                        "Q.tà Ordinata": "{:,.2f}",
                    }, na_rep="-"),
                    width="stretch",
                    height=260,
                )

    # --- Pipeline Health Check disattivato: dati demo rimossi. ---
    # Da riattivare quando esistera' una fonte trattative reali
    # (tabella offerte/preventivi ERP o gestione manuale su SQLite).


# ==============================================================================
# TAB 5: NEW BUSINESS, LOOKALIKE PROSPECTING & OUTREACH MULTILINGUA
# ==============================================================================
if section == _SECTIONS[6]:
    st.subheader("🚀 New Business, Clienti Gemelli Europa & Outreach AI")
    st.caption("Espansione del portafoglio: identifica aziende gemelle dei tuoi clienti top all'estero e genera comunicazioni su misura in 4 lingue.")

    sub_t1, sub_t2 = st.tabs(["👥 Database Clienti Gemelli (Lookalike UE)", "✉️ Generatore Outreach Multilingua"])

    # --------------------------------------------------------------------------
    # SUB-TAB 1: DATABASE PROSPECT GEMELLI EUROPEI
    # --------------------------------------------------------------------------
    with sub_t1:
        st.markdown("### 🗺️ Prospect Europei Dinamici")
        st.write("Aziende rilevate da bandi/news (DB opportunita'), dalla lista seme e da Wikidata — deduplicate contro l'anagrafica clienti ERP e ordinate per match score.")

        _ps = db.prospect_stats()
        _m1, _m2, _m3, _m4 = st.columns(4)
        _m1.metric("Prospect in DB", _ps["total"])
        _m2.metric("Qualificati (>=65)", _ps["by_status"].get("READY_FOR_REVIEW", 0))
        _m3.metric("Esclusi (gia' clienti ERP)", _ps["by_status"].get("EXISTING_CUSTOMER", 0))
        _m4.metric("Score Medio", _ps["avg_score"])

        if st.button("🔄 Aggiorna Prospect (ERP dedup + Wikidata + Scraping)", type="primary"):
            with st.spinner("Pipeline prospect in esecuzione: dedup ERP, Wikidata, scraping siti, scoring..."):
                _sum = refresh_prospects()
            st.success(
                f"✅ {_sum['upserted']} prospect aggiornati su {_sum['candidates']} candidati — "
                f"{_sum['skipped_erp']} gia' clienti ERP esclusi, "
                f"{_sum['qualified']} qualificati (>=65), "
                f"{_sum['scraped']} siti analizzati"
            )

        col_p1, col_p2, col_p3 = st.columns([1, 1, 2])
        with col_p1:
            country_choices = ["TUTTI"] + sorted(AREA_MAPPING.keys())
            sel_country = st.selectbox("Filtra per Area Manager:", country_choices)
        with col_p2:
            sector_choices = ["TUTTI"] + SECTORS
            sel_sector = st.selectbox("Filtra per Settore Core:", sector_choices)
        with col_p3:
            search_prospect = st.text_input("🔍 Cerca per Nome o Settore:", "")

        # Prima il DB dinamico; se vuoto, fallback alla lista seme curata
        _db_prospects = db.get_prospects(search=search_prospect, limit=100)
        if sel_sector != "TUTTI":
            _db_prospects = [p for p in _db_prospects if p["sector"] == sel_sector]
        if sel_country != "TUTTI":
            _db_prospects = [p for p in _db_prospects
                             if COUNTRY_TO_AREA.get((p["country_code"] or "").upper()) == sel_country
                             or (p["country_code"] or "").upper() == "NLD" and sel_country == "FRANCE"]

        if _db_prospects:
            st.markdown(f"**Trovati {len(_db_prospects)} prospect nel DB dinamico:**")
            for p in _db_prospects:
                with st.container():
                    hdr_col1, hdr_col2, hdr_col3 = st.columns([3, 1, 1])
                    with hdr_col1:
                        st.markdown(f"### 🏢 {p['company_name']} ({p['country_code'] or '—'})")
                        st.caption(f"Settore: `{p['sector'] or '—'}` | Fonte: `{p['source_type']}` | Stato: `{p['status']}`")
                    with hdr_col2:
                        st.metric("Match", f"{p['match_score']}/100")
                    with hdr_col3:
                        if p["website_url"]:
                            st.markdown(f"[🌐 Sito]({p['website_url']})")
                        li_q = requests.utils.quote(f"{p['company_name']} procurement cables")
                        st.markdown(f"[🔗 **Buyer su LinkedIn**](https://www.linkedin.com/search/results/people/?keywords={li_q})")

                    try:
                        _reasons = json.loads(p["score_reasons"] or "[]")
                    except (json.JSONDecodeError, TypeError):
                        _reasons = []
                    if _reasons:
                        st.caption(" • ".join(_reasons))
                    if p["scraped_context"]:
                        with st.expander("🌐 Contesto dal sito ufficiale"):
                            st.caption(p["scraped_context"][:900])
                    _render_buyer_contacts(
                        p["company_name"], key_prefix=f"prosp_{p['id']}",
                        quiet=True)
                    st.divider()
        else:
            st.info("Nessun prospect nel DB dinamico. Clicca **'🔄 Aggiorna Prospect'** per popolarlo da ERP + Wikidata + bandi, oppure consulta la lista seme qui sotto.")
            st.markdown("#### 📋 Lista seme (curata manualmente)")
            prospects = get_lookalike_prospects(
                country_filter=sel_country,
                sector_filter=sel_sector,
                search_query=search_prospect,
            )
            for i, p in enumerate(prospects):
                with st.container():
                    hdr_col1, hdr_col2 = st.columns([3, 1])
                    with hdr_col1:
                        st.markdown(f"### 🏢 {p['company_name']} ({p['country']})")
                        st.caption(f"Settore: `{p['sector']}` | Profilo: **{p['company_type']}**")
                    with hdr_col2:
                        st.markdown(f"[🔗 **Cerca Buyer su LinkedIn**]({p['linkedin_url']})")
                    _render_buyer_contacts(
                        p["company_name"], key_prefix=f"seed_{i}",
                        roles=p.get("target_buyer_roles"), quiet=True)
                    st.divider()

    # --------------------------------------------------------------------------
    # SUB-TAB 2: GENERATORE OUTREACH MULTILINGUA
    # --------------------------------------------------------------------------
    with sub_t2:
        st.markdown("### ✉️ Generatore AI di Outreach Commerciale Personalizzato")
        st.caption("Crea istantaneamente email formali, messaggi InMail per LinkedIn e script per telefonata fredda, calibrati sul settore e sulle certificazioni dei cavi.")

        # Prospect dal DB dinamico (prima) + lista seme come fallback
        _db_names = [p["company_name"] for p in db.get_prospects(limit=300)]
        _seed_names = [p["company_name"] for p in LOOKALIKE_PROSPECTS_DB]
        preset_names = list(dict.fromkeys(_db_names + _seed_names))
        col_o1, col_o2, col_o3 = st.columns([1.5, 1, 1])

        with col_o1:
            target_company_input = st.selectbox(
                "Seleziona Prospect da Database (o inserisci manuale sotto):",
                ["-- Seleziona Prospect --"] + preset_names
            )
            custom_company_name = st.text_input("Oppure scrivi Nome Azienda Prospect Libero:", "")

        with col_o2:
            outreach_country = st.selectbox(
                "Nazione / Mercato di Riferimento:",
                ["Francia", "Germania", "Spagna", "Polonia", "Paesi Bassi", "Regno Unito", "Italia", "Europa"]
            )
            outreach_sector = st.selectbox(
                "Settore di Riferimento:",
                SECTORS
            )

        with col_o3:
            outreach_lang = st.selectbox(
                "Lingua della Comunicazione:",
                [
                    ("it", "🇮🇹 Italiano"),
                    ("en", "🇬🇧 Inglese (Internazionale)"),
                    ("fr", "🇫🇷 Francese"),
                    ("de", "🇩🇪 Tedesco"),
                ],
                format_func=lambda x: x[1]
            )[0]

            outreach_channel = st.selectbox(
                "Formato Primario:",
                ["Tutti i Formati (Email + LinkedIn + Script)", "Solo Email Formale", "Solo Messaggio LinkedIn", "Solo Script Telefonico"]
            )

        final_company_target = custom_company_name.strip() if custom_company_name.strip() else (
            target_company_input if target_company_input != "-- Seleziona Prospect --" else ""
        )

        col_ctx1, col_ctx2 = st.columns(2)
        with col_ctx1:
            ctx_project = st.text_input("Gancio Commessa / Progetto (Opzionale):", placeholder="es. Nuovo lotto posa FTTH rete regionale, cantiere alta velocità")
        with col_ctx2:
            ctx_cables = st.text_input("Focus Cavo Specifico (Opzionale):", placeholder="es. Microcavi 200µm G.657.A1, Cavi EN 45545-2 HL3, CPR B2ca")

        if st.button("⚡ Genera Outreach Personalizzato con AI", type="primary"):
            if not final_company_target:
                st.warning("⚠️ Inserisci o seleziona il nome dell'azienda target.")
            else:
                # Contesto scraped dal DB se il prospect selezionato esiste
                _prow = next((p for p in db.get_prospects(limit=300)
                              if p["company_name"] == final_company_target), None)
                _scraped = _prow["scraped_context"] if _prow and _prow["scraped_context"] else ""
                _src = _prow["source_type"] if _prow else "MANUALE"

                # Gancio News Intelligence (<90gg): hook + link articolo
                _ck = news_intelligence.company_key_for(
                    final_company_target,
                    (_prow or {}).get("country_code"))
                _hook = db.latest_outreach_hook(_ck)
                _sig = db.latest_news_signal(_ck)
                if _hook:
                    st.info("📡 **Gancio news rilevato:** "
                            + (_sig["article_title"][:100] if _sig else "")
                            + (f" — [{_sig['signal_category']}]"
                               f"({_sig['source_url']})" if _sig else ""))

                with st.spinner(f"Elaborazione outreach personalizzato per {final_company_target}..."):
                    outreach_res = generate_multilingual_outreach(
                        company_name=final_company_target,
                        country=outreach_country,
                        sector=outreach_sector,
                        language=outreach_lang,
                        specific_project=ctx_project,
                        cable_focus=ctx_cables,
                        provider=selected_provider,
                        scraped_context=_scraped,
                        source_type=_src,
                        area_manager=area_for_country(outreach_country),
                        outreach_hook=_hook,
                    )

                st.success(f"✅ Proposta commerciale generata per **{final_company_target}**!")
                _meta_bits = []
                if outreach_res.get("fonte_dato"):
                    _meta_bits.append(f"Fonte lead: `{outreach_res['fonte_dato']}`")
                if outreach_res.get("area_manager_assegnato"):
                    _meta_bits.append(f"Area: `{outreach_res['area_manager_assegnato']}`")
                if outreach_res.get("evidenze_sito_web"):
                    _meta_bits.append("Contesto sito analizzato")
                if _meta_bits:
                    st.caption(" · ".join(_meta_bits))

                t_mail, t_li, t_call = st.tabs(["✉️ Bozza Email", "💼 Messaggio LinkedIn / InMail", "📞 Script Cold Call"])

                with t_mail:
                    st.markdown(f"**Oggetto Consigliato:** `{outreach_res.get('subject', '')}`")
                    st.text_area("Testo Email (Pronto da copiare):", outreach_res.get("email_body", ""), height=260)

                with t_li:
                    st.markdown("**Messaggio Diretto per Responsabile Acquisti / InMail:**")
                    st.text_area("Testo LinkedIn (Max 120 parole):", outreach_res.get("linkedin_message", ""), height=150)

                with t_call:
                    st.markdown("**Traccia Telefonica & Gestione Obiezioni:**")
                    st.markdown(outreach_res.get("cold_call_script", "").replace("\n", "\n\n"))


def _mask_secret(v: str | None) -> str:
    """Mostra solo gli ultimi 4 caratteri di un segreto (o trattino)."""
    return f"\u2022\u2022\u2022\u2022{v[-4:]}" if v else "\u2014"


# ==============================================================================
# TAB 6: AMMINISTRAZIONE, MONITOR & LOG
# ==============================================================================
if section == _SECTIONS[7]:
    # ------------------------------------------------------------------
    # CONFIGURAZIONE ATTIVA & QUOTA GEMINI
    # ------------------------------------------------------------------
    st.subheader("\u2699\ufe0f Configurazione Attiva")
    _a1, _a2, _a3 = st.columns(3)
    _a1.metric("Provider LLM", get_active_provider().upper())
    _a2.metric("Opportunit\u00e0 in DB", db.stats()["total"])
    _a3.metric("Chiamate Gemini oggi", db.llm_calls_today())

    st.dataframe(pd.DataFrame([
        ("LLM_PROVIDER", get_active_provider(), "sidebar / env"),
        ("GEMINI_MODEL", config.GEMINI_MODEL, "env (override sidebar)"),
        ("GEMINI_API_KEY", _mask_secret(config.GEMINI_API_KEY), "env / sidebar"),
        ("GEMINI_API_KEYS", f"{len(config.GEMINI_API_KEYS)} chiavi extra", "env"),
        ("GEMINI_DAILY_LIMIT", config.GEMINI_DAILY_LIMIT, "env"),
        ("GEMINI_MIN_INTERVAL", f"{config.GEMINI_MIN_INTERVAL}s", "env"),
        ("OLLAMA_MODEL", config.OLLAMA_MODEL, "env / sidebar"),
        ("DISABLE_OLLAMA_FALLBACK",
         str(st.session_state.get("no_ollama_fallback",
                                  config.DISABLE_OLLAMA_FALLBACK)),
         "sidebar / env"),
        ("OLLAMA_URL", config.OLLAMA_URL, "env"),
        ("TED_API_KEY", _mask_secret(os.environ.get("TED_API_KEY", "")), "env"),
        ("SQLSERVER_HOST", config.SQLSERVER_HOST, "env"),
        ("SQLSERVER_DB", config.SQLSERVER_DB, "env"),
        ("SQLSERVER_USER", config.SQLSERVER_USER, "env"),
        ("SQLSERVER_PWD", _mask_secret(config.SQLSERVER_PWD), "env"),
        ("NIGHTLY_SCHEDULE_TIME", os.environ.get("NIGHTLY_SCHEDULE_TIME", "01:00"), "env"),
        ("DB_PATH", DB_PATH, "config.py"),
    ], columns=["Parametro", "Valore", "Fonte"]).astype(str),
        width="stretch", hide_index=True)

    st.markdown("**\U0001f511 Quota Gemini per chiave**")
    _usage = gemini_key_usage()
    if _usage:
        st.dataframe(pd.DataFrame([
            {
                "Chiave": f"...{u['tail']}",
                "Chiamate oggi": u["calls"],
                "Budget": config.GEMINI_DAILY_LIMIT,
                "Residuo": max(0, config.GEMINI_DAILY_LIMIT - u["calls"]),
                "Stato": ("\U0001f534 esaurita" if u["exhausted"]
                          or u["calls"] >= config.GEMINI_DAILY_LIMIT
                          else "\U0001f7e2 attiva"),
            }
            for u in _usage
        ]), width="stretch", hide_index=True)
    else:
        st.caption("Nessuna chiave Gemini configurata.")

    st.divider()

    # ------------------------------------------------------------------
    # MONITOR PIPELINE LIVE (auto-refresh ogni 2s)
    # ------------------------------------------------------------------
    st.subheader("\U0001f4e1 Monitor Pipeline in Tempo Reale")

    _PIPELINE_LOG_PATH = os.path.join(os.path.dirname(DB_PATH),
                                      "pipeline_run.log")

    @st.fragment(run_every=2.0)
    def _pipeline_live_monitor():
        proc = st.session_state.get("pipeline_proc")
        rc = proc.poll() if proc is not None else None
        running = proc is not None and rc is None
        started_iso = st.session_state.get("pipeline_started")
        prov = st.session_state.get("pipeline_provider", "—")

        lines = []
        if os.path.exists(_PIPELINE_LOG_PATH):
            try:
                with open(_PIPELINE_LOG_PATH, "r", encoding="utf-8",
                          errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                pass

        # --- metriche di stato ---
        m1, m2, m3, m4 = st.columns(4)
        if running:
            stato = "🟡 IN ESECUZIONE"
        elif proc is None and not lines:
            stato = "⚪ MAI AVVIATA"
        elif rc == 0 or (rc is None and lines and
                         "PIPELINE COMPLETATA" in lines[-1]):
            stato = "🟢 COMPLETATA"
        elif rc is None:
            stato = "🟠 INTERROTTA"
        else:
            stato = "🔴 ERRORE"
        m1.metric("Stato", stato)
        m2.metric("Provider LLM", str(prov).upper())

        elapsed = "—"
        if started_iso:
            try:
                secs = int((datetime.now()
                            - datetime.fromisoformat(started_iso)).total_seconds())
                elapsed = f"{secs // 60}m {secs % 60}s"
            except ValueError:
                pass
        m3.metric("Tempo trascorso", elapsed)

        prog_txt, prog_val = "—", 0.0
        for ln in reversed(lines):
            mm = re.search(r"Scoring (\d+)/(\d+)", ln)
            if mm:
                prog_txt = f"{mm.group(1)}/{mm.group(2)}"
                prog_val = int(mm.group(1)) / max(1, int(mm.group(2)))
                break
        m4.metric("Scoring AI", prog_txt)

        if running:
            st.progress(prog_val, text="Avanzamento scoring…"
                      if prog_txt != "—" else "Raccolta fonti in corso…")

        # --- fase corrente ---
        last_line = lines[-1] if lines else ""
        if last_line:
            st.caption(f"**Ultima attività:** `{last_line.strip()}`")

        # --- stop button ---
        if running:
            if st.button("⛔ Interrompi Pipeline", type="secondary"):
                try:
                    proc.terminate()
                except Exception as exc:
                    st.error(f"Errore interruzione: {exc}")

        # --- log tail ---
        st.markdown("**📜 Output pipeline (live):**")
        tail = lines[-120:] if lines else ["(nessun output ancora)"]
        st.code("\n".join(tail), language="log", height=400)

    _pipeline_live_monitor()

    st.divider()

    # ------------------------------------------------------------------
    # STORICO ERRORI
    # ------------------------------------------------------------------
    st.subheader("🛠️ Storico Errori di Raccolta")
    st.caption("Errori da sistemare: indirizzi non raggiungibili, API in errore, "
               "feed malformati, fonti saltate. Gli errori risolti si possono "
               "eliminare dallo storico.")

    show_resolved = st.toggle("Mostra anche gli errori risolti", value=False)
    err_rows = db.get_error_log(include_resolved=show_resolved)

    if not err_rows:
        st.success("✅ Nessun errore registrato" +
                   (" nella vista corrente." if show_resolved else " — tutto ok."))
    else:
        df_err = pd.DataFrame([dict(r) for r in err_rows])

        k1, k2, k3 = st.columns(3)
        k1.metric("Errori in vista", len(df_err))
        k2.metric("Non risolti",
                  int((df_err["resolved"] == 0).sum()))
        k3.metric("Fonti coinvolte", df_err["source"].nunique())

        sel_sources = st.multiselect(
            "Filtra per fonte",
            sorted(df_err["source"].unique().tolist()),
            default=[],
            placeholder="Tutte le fonti")
        if sel_sources:
            df_err = df_err[df_err["source"].isin(sel_sources)]

        st.dataframe(
            df_err[["id", "ts", "source", "target", "url",
                    "error_type", "message", "resolved"]],
            width="stretch",
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "ts": st.column_config.DatetimeColumn("Data", format="DD/MM/YY HH:mm"),
                "source": st.column_config.TextColumn("Fonte", width="small"),
                "target": st.column_config.TextColumn("Contesto"),
                "url": st.column_config.LinkColumn("URL", display_text="link"),
                "error_type": st.column_config.TextColumn("Tipo", width="small"),
                "message": st.column_config.TextColumn("Messaggio"),
                "resolved": st.column_config.CheckboxColumn("Risolto", width="small"),
            },
        )

        c1, c2 = st.columns([3, 1])
        with c1:
            ids_open = df_err.loc[df_err["resolved"] == 0, "id"].tolist()
            ids_sel = st.multiselect("ID da segnare come risolti", ids_open)
            if st.button("✔️ Segna risolti", disabled=not ids_sel):
                db.mark_errors_resolved(ids_sel)
                st.rerun()
        with c2:
            n_res = int((df_err["resolved"] == 1).sum())
            if st.button(f"🗑️ Elimina risolti ({n_res})",
                         disabled=n_res == 0):
                db.delete_resolved_errors()
                st.rerun()

    st.divider()

    # ------------------------------------------------------------------
    # CONTROLLO & MANUTENZIONE DB
    # ------------------------------------------------------------------
    st.subheader("🗄️ Controllo & Manutenzione DB")
    st.caption("Stato delle code di scoring, azioni di manutenzione sicure e "
               "ispezione read-only di `data/opportunita.db`.")

    # A) Cruscotto stato code
    _qs = db.queue_stats()
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("⏳ PENDING (coda triage)", _qs.get("PENDING", 0))
    q2.metric("🧪 BATCH_PASSED (coda deep-dive)", _qs.get("BATCH_PASSED", 0))
    q3.metric("✅ COMPLETED (pronte)", _qs.get("COMPLETED", 0))
    q4.metric("🚫 DISCARDED (scartati)", _qs.get("DISCARDED", 0))

    # D) Backup scaricabile: punto di ripristino prima di azioni massive
    try:
        with open(DB_PATH, "rb") as _dbf:
            _db_bytes = _dbf.read()
        st.download_button(
            f"💾 Scarica backup DB ({len(_db_bytes) / 1048576:.1f} MB)",
            data=_db_bytes,
            file_name=f"opportunita_{datetime.now().strftime('%Y%m%d_%H%M')}.db",
            mime="application/octet-stream",
            help="Copia integrale del file SQLite: punto di ripristino "
                 "prima di operazioni massive.")
    except OSError:
        st.warning("File DB non leggibile: backup non disponibile.")

    # B) Azioni rapide sicure (UPDATE/DELETE pre-approvate in db.py)
    _MAINT = {
        "discard_old": (
            "🗓️ Scarta record obsoleti (Ante 2026)",
            "I BATCH_PASSED con published precedente al 2026 diventano "
            "DISCARDED: svuota la coda deep-dive e risparmia chiamate Gemini.",
            db.discard_pre_2026_passed, "record scartati"),
        "reset_heur": (
            "🔁 Rimetti in coda Triage i record Euristica",
            "I BATCH_PASSED promossi dall'euristica (fallback dopo errori "
            "API) tornano PENDING e saranno rivalutati dal batching Gemini.",
            db.reset_heuristic_passed, "record riportati in PENDING"),
        "reset_fail": (
            "🧯 Ricalcola record falliti / senza score",
            "I record con score NULL o stato ERROR (es. dopo un timeout di "
            "rete) tornano in PENDING.",
            db.reset_failed_records, "record recuperati"),
        "purge_err": (
            "🧹 Pulisci log errori vecchi (> 30 giorni)",
            "Elimina definitivamente le righe di fetch_errors piu' vecchie "
            "di 30 giorni per alleggerire il file SQLite.",
            db.purge_old_errors, "righe di log eliminate"),
    }
    b1, b2, b3, b4 = st.columns(4)
    for _col, _key in ((b1, "discard_old"), (b2, "reset_heur"),
                       (b3, "reset_fail"), (b4, "purge_err")):
        if _col.button(_MAINT[_key][0], key=f"maint_{_key}",
                       help=_MAINT[_key][1]):
            st.session_state["maint_armed"] = _key

    _armed = st.session_state.get("maint_armed")
    if _armed:
        _lbl, _help, _fn, _done = _MAINT[_armed]
        st.warning(f"⚠️ Confermi l'operazione **{_lbl}**? {_help}")
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ Conferma", key="maint_confirm"):
            _n = _fn()
            st.session_state.pop("maint_armed", None)
            st.success(f"Fatto: {_n} {_done}.")
            st.rerun()
        if cc2.button("✖️ Annulla", key="maint_cancel"):
            st.session_state.pop("maint_armed", None)
            st.rerun()

    # C) Console SQL in sola lettura
    st.markdown("**🔎 Console SQL (sola lettura)**")
    st.caption("Solo SELECT/PRAGMA: connessione `?mode=ro`, keyword di "
               "modifica e multi-statement bloccati lato backend.")
    _sql = st.text_area("Query", height=110, label_visibility="collapsed",
                        placeholder=("SELECT source, COUNT(*) AS n "
                                     "FROM opportunities GROUP BY source "
                                     "ORDER BY n DESC"))
    if st.button("▶️ Esegui Query di Lettura", key="ro_run"):
        try:
            st.session_state["ro_result"] = db.run_readonly_query(_sql)
            st.session_state.pop("ro_error", None)
        except (ValueError, Exception) as _e:  # noqa: BLE001
            st.session_state["ro_error"] = str(_e)
            st.session_state.pop("ro_result", None)

    if st.session_state.get("ro_error"):
        st.error(f"Query rifiutata: {st.session_state['ro_error']}")
    _ro_df = st.session_state.get("ro_result")
    if _ro_df is not None:
        st.dataframe(_ro_df, width="stretch", hide_index=True)
        st.download_button(
            "⬇️ Esporta CSV",
            _ro_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="query_result.csv", mime="text/csv")


# ==============================================================================
# SIDEBAR REFRESH ACTION (PIPELINE IN BACKGROUND + LOG LIVE)
# ==============================================================================
_PIPELINE_LOG_PATH = os.path.join(os.path.dirname(DB_PATH), "pipeline_run.log")


def _read_pipeline_log(tail: int = 300) -> list[str]:
    """Ultime `tail` righe del log di pipeline."""
    try:
        with open(_PIPELINE_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-tail:]
    except OSError:
        return []


def _pipeline_status() -> dict:
    """Stato corrente della pipeline lanciata dalla UI."""
    proc = st.session_state.get("pipeline_proc")
    if proc is None:
        return {"state": "idle", "rc": None}
    rc = proc.poll()
    if rc is None:
        return {"state": "running", "rc": None}
    return {"state": "done" if rc == 0 else "failed", "rc": rc}


def _start_pipeline():
    """Avvia main.py come sottoprocesso in background, output su file di log."""
    _main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "main.py")
    os.makedirs(os.path.dirname(_PIPELINE_LOG_PATH), exist_ok=True)
    env = os.environ.copy()
    env["LLM_PROVIDER"] = selected_provider
    env["DISABLE_OLLAMA_FALLBACK"] = (
        "1" if st.session_state.get("no_ollama_fallback") else "0")
    env["PYTHONUNBUFFERED"] = "1"
    if selected_provider == "gemini":
        if st.session_state.get("gemini_api_key"):
            env["GEMINI_API_KEY"] = st.session_state["gemini_api_key"]
        if st.session_state.get("gemini_extra_keys"):
            env["GEMINI_API_KEYS"] = ",".join(
                k.strip() for k in re.split(r"[,\s]+", st.session_state["gemini_extra_keys"])
                if k.strip())
        env["GEMINI_MODEL"] = selected_gemini_model
    elif selected_provider == "ollama" and selected_ollama_model:
        env["OLLAMA_MODEL"] = selected_ollama_model

    log_f = open(_PIPELINE_LOG_PATH, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, "-u", _main_py],
        stdout=log_f, stderr=subprocess.STDOUT,
        env=env, cwd=os.path.dirname(_main_py),
    )
    log_f.close()  # il figlio mantiene il proprio handle ereditato
    st.session_state["pipeline_proc"] = proc
    st.session_state["pipeline_started"] = datetime.now().isoformat()
    st.session_state["pipeline_provider"] = selected_provider


st.sidebar.divider()
_n_err = db.unresolved_error_count()
_pst = _pipeline_status()
if _pst["state"] == "running":
    st.sidebar.info("🔄 Pipeline in esecuzione...")
    st.sidebar.button("🚀 Aggiorna Pipeline", disabled=True, width="stretch")
else:
    if st.sidebar.button("🚀 Aggiorna Pipeline", width="stretch", type="primary"):
        _start_pipeline()
        st.toast("Pipeline avviata in background!", icon="🚀")
        st.rerun()

# Avvio pipeline richiesto dal pannello Sales Agent (Panoramica)
if st.session_state.get("pipeline_autostart"):
    st.session_state["pipeline_autostart"] = False
    if _pipeline_status()["state"] != "running":
        _start_pipeline()
        st.toast("Pipeline avviata in background!", icon="🚀")
        st.rerun()

ui_style.sidebar_footer(unresolved_count=_n_err)


