"""Dashboard Co-Pilota Commerciale AI B2B - Cavi Speciali (Fibra & Rame)."""
import io
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

import db
import config
import ui_style
from account_research import generate_account_dossier
from company_enrich import enrich_company, format_amount
from config import AREA_MAPPING, DB_PATH, SECTORS
from crm_analyzer import (
    analyze_crm_orders,
    analyze_client_technical_profile,
    calculate_customer_periodicity,
    check_pipeline_health,
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
    generate_multilingual_outreach,
    get_lookalike_prospects,
)
from rfp_analyzer import analyze_rfp
import sqlserver_orders as sso

st.set_page_config(
    page_title="Co-Pilota Commerciale AI - Cavi Speciali",
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
    "🔗  Processi & CRM",
    "📊  Analisi & New Business",
    "✨  AI & Agenti",
]
st.session_state.setdefault("nav_section", _SECTIONS[0])
ui_style.brand()
st.sidebar.caption("NAVIGAZIONE")
section = st.sidebar.radio("Sezioni", _SECTIONS, key="nav_section",
                           label_visibility="collapsed")


# ==============================================================================
# STATO MOTORE AI: eseguito a OGNI rerun (letto da session_state, non dai widget)
# ==============================================================================
llm_options = ["🦙 Ollama (Locale)", "☁️ Google Gemini (Aziendale)"]
gemini_models = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash",
                 "gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-latest",
                 "gemini-pro-latest"]

st.session_state.setdefault("provider_radio",
                            llm_options[1] if config.LLM_PROVIDER == "gemini" else llm_options[0])
st.session_state.setdefault("gemini_api_key", config.GEMINI_API_KEY)
st.session_state.setdefault("gemini_extra_keys", "")
st.session_state.setdefault("gemini_model_sel",
                            config.GEMINI_MODEL if config.GEMINI_MODEL in gemini_models
                            else "gemini-3.1-flash-lite")
st.session_state.setdefault("ollama_model_sel", config.OLLAMA_MODEL)
st.session_state.setdefault("no_ollama_fallback",
                            config.DISABLE_OLLAMA_FALLBACK)
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
    _SECTIONS[4]: ("Processi, CRM & Retention Ordini", "Analisi periodicità ordini (MTBO), churn e cross-selling ERP"),
    _SECTIONS[5]: ("Analisi & New Business Europa", "Clienti gemelli europei e outreach multilingua AI"),
    _SECTIONS[6]: ("AI & Agenti", "Motore LLM, quota API, monitor pipeline in tempo reale e log"),
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
        _n_unscored = _stats["total"] - _stats["scored"]
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
            _lbl = f"🎯 Top: {_top_opp['title'][:38]}… (score {_top_opp['score']})"
            if st.button(_lbl, width="stretch"):
                st.session_state["nav_section"] = _SECTIONS[1]
                st.rerun()

        if _n_err_agent > 0 and not _pipe_running:
            if st.button(f"⚠️ {_n_err_agent} errori fonti da verificare",
                         width="stretch"):
                st.session_state["nav_section"] = _SECTIONS[6]
                st.rerun()

        if st.button("📄 Analizza Capitolato RFP", width="stretch"):
            st.session_state["nav_section"] = _SECTIONS[2]
            st.rerun()

        if st.button("✉️ Genera Outreach AI", width="stretch"):
            st.session_state["nav_section"] = _SECTIONS[5]
            st.rerun()


# ==============================================================================
# SEZIONE ADMIN - MOTORE AI (widget config; lo stato arriva da session_state)
# ==============================================================================
if section == _SECTIONS[6]:
    st.subheader("🧠 Motore AI (LLM)")
    st.radio(
        "Provider attivo:",
        llm_options,
        horizontal=True,
        key="provider_radio",
        help="Scegli se usare il modello locale (Ollama) o l'AI cloud aziendale (Google Gemini)."
    )

    if selected_provider == "gemini":
        _k1, _k2 = st.columns(2)
        _k1.text_input(
            "Gemini API Key Aziendale",
            type="password",
            key="gemini_api_key",
            help="Inserisci la chiave API aziendale di Google Gemini (AI Studio o Vertex AI)."
        )
        _k2.text_input(
            "Chiavi extra rotazione (comma-separated)",
            type="password",
            key="gemini_extra_keys",
            help="Chiavi API aggiuntive da progetti diversi: quando una esaurisce la quota giornaliera, la successiva prende il suo posto."
        )
        st.selectbox("Modello Gemini", gemini_models, key="gemini_model_sel")

        st.checkbox(
            "⛔ Non usare Ollama se Gemini non funziona",
            key="no_ollama_fallback",
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
            help="Nome del modello in locale (es. llama3.1:8b, mistral:7b)."
        )
        if ollama_online:
            st.success(f"🟢 Ollama online ({selected_ollama_model})")
        else:
            st.warning("🔴 Ollama offline (fallback euristico attivo)")

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
                          motivation, action, email_draft, scored_by, created_at
                   FROM opportunities""",
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

        search_kw = st.sidebar.text_input("Cerca parola chiave / Normativa (es. CPR, EN 45545, Alstom)", "")

        filtered_df = df_all[df_all["score"].fillna(0) >= min_score].copy()

        if selected_area != "TUTTE":
            filtered_df = filtered_df[filtered_df["area_manager"] == selected_area]
        if selected_sector != "TUTTI":
            filtered_df = filtered_df[filtered_df["sector"] == selected_sector]
        if selected_source != "TUTTE":
            filtered_df = filtered_df[filtered_df["source"] == selected_source]
        if search_kw:
            kw = re.escape(search_kw.lower())
            mask = (
                filtered_df["title"].str.lower().str.contains(kw, na=False) |
                filtered_df["text"].str.lower().str.contains(kw, na=False) |
                filtered_df["norms"].str.lower().str.contains(kw, na=False) |
                filtered_df["target_company"].str.lower().str.contains(kw, na=False)
            )
            filtered_df = filtered_df[mask]

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
# TAB 4: CRM & PIPELINE HEALTH CHECK
# ==============================================================================
if section == _SECTIONS[4]:
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
if section == _SECTIONS[5]:
    st.subheader("🚀 New Business, Clienti Gemelli Europa & Outreach AI")
    st.caption("Espansione del portafoglio: identifica aziende gemelle dei tuoi clienti top all'estero e genera comunicazioni su misura in 4 lingue.")

    sub_t1, sub_t2 = st.tabs(["👥 Database Clienti Gemelli (Lookalike UE)", "✉️ Generatore Outreach Multilingua"])

    # --------------------------------------------------------------------------
    # SUB-TAB 1: DATABASE PROSPECT GEMELLI EUROPEI
    # --------------------------------------------------------------------------
    with sub_t1:
        st.markdown("### 🗺️ Mappa Prospect Europei per Settore & Nazione")
        st.write("Aziende primarie analoghe ai vostri clienti storici italiani (General Contractor, Installatori FTTH, Cantieri Navali, Operatori Ferroviari).")

        col_p1, col_p2, col_p3 = st.columns([1, 1, 2])
        with col_p1:
            country_choices = ["TUTTI", "Francia", "Germania", "Spagna", "Polonia", "Paesi Bassi"]
            sel_country = st.selectbox("Filtra per Nazione Target:", country_choices)
        with col_p2:
            sector_choices = ["TUTTI"] + SECTORS
            sel_sector = st.selectbox("Filtra per Settore Core:", sector_choices)
        with col_p3:
            search_prospect = st.text_input("🔍 Cerca per Nome, Cavi o Tipo Commessa:", "")

        prospects = get_lookalike_prospects(
            country_filter=sel_country,
            sector_filter=sel_sector,
            search_query=search_prospect,
        )

        st.markdown(f"**Trovati {len(prospects)} prospect target altamente qualificati:**")

        for p in prospects:
            with st.container():
                hdr_col1, hdr_col2 = st.columns([3, 1])
                with hdr_col1:
                    st.markdown(f"### 🏢 {p['company_name']} ({p['country']})")
                    st.caption(f"Settore: `{p['sector']}` | Profilo: **{p['company_type']}** | Volume Stimato: **{p['estimated_annual_volume']}**")
                with hdr_col2:
                    st.markdown(f"[🔗 **Cerca Buyer su LinkedIn**]({p['linkedin_url']})")

                c_d1, c_d2 = st.columns(2)
                with c_d1:
                    st.markdown(f"📦 **Pacchetto Cavi Consigliato:**\n- {p['target_cables']}")
                    st.markdown(f"🏗️ **Progetti Tipici & Ambiti:**\n- {p['typical_projects']}")
                with c_d2:
                    st.markdown("**🎯 Ruoli Decision Maker / Buyer Target:**")
                    for role in p["target_buyer_roles"]:
                        st.markdown(f"- 👤 *{role}*")

                st.divider()

    # --------------------------------------------------------------------------
    # SUB-TAB 2: GENERATORE OUTREACH MULTILINGUA
    # --------------------------------------------------------------------------
    with sub_t2:
        st.markdown("### ✉️ Generatore AI di Outreach Commerciale Personalizzato")
        st.caption("Crea istantaneamente email formali, messaggi InMail per LinkedIn e script per telefonata fredda, calibrati sul settore e sulle certificazioni dei cavi.")

        preset_names = [p["company_name"] for p in LOOKALIKE_PROSPECTS_DB]
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
                with st.spinner(f"Elaborazione outreach personalizzato per {final_company_target}..."):
                    outreach_res = generate_multilingual_outreach(
                        company_name=final_company_target,
                        country=outreach_country,
                        sector=outreach_sector,
                        language=outreach_lang,
                        specific_project=ctx_project,
                        cable_focus=ctx_cables,
                        provider=selected_provider,
                    )

                st.success(f"✅ Proposta commerciale generata per **{final_company_target}**!")

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
if section == _SECTIONS[6]:
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


