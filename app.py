"""Dashboard Co-Pilota Commerciale AI B2B - Cavi Speciali (Fibra & Rame)."""
import io
import re
import sqlite3
import subprocess
import sys

import pandas as pd
import streamlit as st

import db
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
    except Exception:
        pass
    return pd.DataFrame()

st.title("⚡ Co-Pilota Commerciale AI - Cavi Speciali B2B")
st.caption("Intelligence Europea, Analisi Capitolati (RFP), Account Dossier, CRM Storico & New Business Lookalike — Dati 100% On-Premise.")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 Tender Intelligence & News",
    "📄 RFP & Capitolati Analyzer",
    "🏢 Account Research & Dossier",
    "📊 CRM & Retention Ordini",
    "🚀 New Business & Lookalike UE",
])


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
with tab1:
    def load_data() -> pd.DataFrame:
        with sqlite3.connect(DB_PATH) as conn:
            return pd.read_sql_query(
                """SELECT id, source, title, url, published, text, country,
                          area_manager, score, sector, target_company, norms,
                          motivation, action, email_draft, scored_by, created_at
                   FROM opportunities
                   ORDER BY score DESC, id DESC""",
                conn,
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
                        st.caption(f"📝 **Estratto Bando / News:** {row['text'][:400]}...")

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
with tab2:
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
        with st.spinner("Estrazione requisiti tecnici con AI locale in corso..."):
            rfp_res = analyze_rfp(rfp_input)

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
with tab3:
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
            dossier = generate_account_dossier(target_company, target_country, _notes)

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
with tab4:
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
with tab5:
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


# ==============================================================================
# SIDEBAR REFRESH ACTION
# ==============================================================================
st.sidebar.divider()
st.sidebar.subheader("⚙️ Aggiornamento Dati")
if st.sidebar.button("🚀 Aggiorna Fonti & Pipeline"):
    with st.spinner("Raccolta bandi TED & News europee in corso..."):
        proc = subprocess.run([sys.executable, "main.py"],
                              capture_output=True, text=True, timeout=1800)
    if proc.returncode == 0:
        st.sidebar.success("Pipeline completata con successo!")
    else:
        st.sidebar.error("Errore durante l'esecuzione.")
    st.rerun()


