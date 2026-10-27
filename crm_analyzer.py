"""Modulo Retention, Periodicità Ordini (MTBO) & Cross-Selling (CRM / ERP Analyzer).

Funziona sia con SQL Server diretto (AGG_CLIENTI_TMP + AGG_MASTER_CLIENTE) che con export CSV.
Calcola:
1. Mean Time Between Orders (MTBO) per cliente
2. Giorni trascorsi dall'ultimo ordine e rapporto di ritardo (Delay Index)
3. Stato Churn:
   - 🟢 REGOLARE: Riordino nei tempi previsti
   - 🟡 IN RITARDO: Ritardo moderato (> MTBO * 1.2)
   - 🔴 RISCHIO CHURN: Ritardo critico (> MTBO * 1.6)
   - ⚪ DORMIENTE: Nessun ordine da oltre 365 giorni
   - 🆕 UNICO ORDINE: Cliente con 1 solo ordine storico
4. Opportunità di Cross-Selling (Fibra Ottica vs Rame vs Accessori)
"""
from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd


def calculate_customer_periodicity(df_orders: pd.DataFrame, reference_date: Optional[datetime] = None) -> pd.DataFrame:
    """Calcola la scheda di periodicita' e stato per ogni cliente.
    
    Richiede un DataFrame con colonne minime:
    ['client_id', 'client_name', 'order_date', 'amount']
    Opzionali: ['country', 'market_area', 'product_category', 'order_code']
    """
    if df_orders.empty:
        return pd.DataFrame()

    df = df_orders.copy()
    df["order_date"] = pd.to_datetime(df["order_date"])
    now = reference_date or datetime.now()

    group_keys = ["client_id"]
    for opt in ["client_name", "country", "market_area"]:
        if opt in df.columns:
            group_keys.append(opt)

    customer_records = []

    for keys, group in df.groupby(group_keys):
        if not isinstance(keys, tuple):
            keys = (keys,)
        
        client_id = keys[0]
        client_name = keys[1] if len(keys) > 1 else client_id
        country = keys[2] if len(keys) > 2 else "IT"
        market_area = keys[3] if len(keys) > 3 else "IT"

        group_sorted = group.sort_values("order_date")
        
        # Date uniche di ordine per calcolare intervalli effettivi
        unique_order_dates = sorted(group_sorted["order_date"].dt.date.unique())
        num_order_events = len(unique_order_dates)
        total_rows = len(group_sorted)
        total_revenue = group_sorted["amount"].sum() if "amount" in group_sorted.columns else 0.0

        first_order = unique_order_dates[0]
        last_order = unique_order_dates[-1]
        days_since_last = (now.date() - last_order).days

        # Calcolo MTBO (Mean Time Between Orders)
        if num_order_events >= 2:
            intervals = np.diff([d.toordinal() for d in unique_order_dates])
            mtbo = float(np.mean(intervals))
            median_interval = float(np.median(intervals))
            std_interval = float(np.std(intervals)) if len(intervals) > 1 else 0.0
        else:
            mtbo = None
            median_interval = None
            std_interval = None

        # Ripartizione categorie acquistate
        categories = set()
        fibra_val = 0.0
        rame_val = 0.0
        if "product_category" in group_sorted.columns:
            for _, r in group_sorted.iterrows():
                cat = str(r["product_category"]).lower()
                val = float(r.get("amount", 0.0))
                if "fibra" in cat or "optical" in cat:
                    categories.add("Fibra Ottica")
                    fibra_val += val
                elif "rame" in cat or "copper" in cat:
                    categories.add("Rame")
                    rame_val += val
                else:
                    categories.add("Altro / Accessori")

        # Determinazione Stato Rischio
        if num_order_events == 1:
            status = "🆕 UNICO ORDINE"
            status_code = "NEW"
            risk_score = 30
            delay_ratio = None
            action = "Programmare follow-up di secondo ordine per fidelizzare il cliente."
        elif mtbo is not None:
            delay_ratio = round(days_since_last / mtbo, 2) if mtbo > 0 else 1.0
            
            if days_since_last > 365:
                status = "⚪ DORMIENTE"
                status_code = "DORMANT"
                risk_score = 90
                action = f"Cliente inattivo da oltre 1 anno ({days_since_last} gg, ciclo storico: {int(mtbo)} gg). Riaprire il canale commerciale con offerta mirata."
            elif delay_ratio > 2.0 or (days_since_last > 90 and delay_ratio > 1.6):
                status = "🔴 RISCHIO CHURN"
                status_code = "CHURN_RISK"
                risk_score = 80
                action = f"Ritardo critico: {days_since_last} gg trascorsi vs ciclo abituale di {int(mtbo)} gg (indice: {delay_ratio}x). Contattare urgentemente il buyer."
            elif delay_ratio > 1.25:
                status = "🟡 IN RITARDO"
                status_code = "DELAYED"
                risk_score = 50
                action = f"Finestra di riordino superata ({days_since_last} gg vs {int(mtbo)} gg MTBO). Inviare disponibilità stock e quotazioni aggiornate."
            else:
                status = "🟢 REGOLARE"
                status_code = "REGULAR"
                risk_score = 10
                action = f"Flusso riordino regolare (prossimo ordine stimato tra ~{max(0, int(mtbo - days_since_last))} gg)."
        else:
            status = "🟢 REGOLARE"
            status_code = "REGULAR"
            risk_score = 10
            delay_ratio = None
            action = "Monitorare la relazione commerciale."

        # Cross-selling recommendation
        has_fibra = "Fibra Ottica" in categories or fibra_val > 0
        has_rame = "Rame" in categories or rame_val > 0

        if has_fibra and not has_rame:
            cross_sell = "🎯 Proporre Cavi Rame & Cablaggio Strutturato"
        elif has_rame and not has_fibra:
            cross_sell = "🎯 Proporre Dorsali & Cavi Fibra Ottica"
        elif has_fibra and has_rame:
            cross_sell = "✅ Fornitura Completa (Fibra + Rame)"
        else:
            cross_sell = "Analizzare fabbisogni specifici"

        customer_records.append({
            "client_id": client_id,
            "client_name": client_name,
            "country": country,
            "market_area": market_area,
            "total_orders": num_order_events,
            "total_lines": total_rows,
            "total_revenue": round(total_revenue, 2),
            "first_order": str(first_order),
            "last_order": str(last_order),
            "days_since_last": days_since_last,
            "mtbo_days": round(mtbo, 1) if mtbo is not None else None,
            "median_interval_days": round(median_interval, 1) if median_interval is not None else None,
            "delay_ratio": delay_ratio,
            "status": status,
            "status_code": status_code,
            "risk_score": risk_score,
            "fibra_amount": round(fibra_val, 2),
            "rame_amount": round(rame_val, 2),
            "categories": ", ".join(sorted(categories)) if categories else "N/D",
            "cross_sell_opportunity": cross_sell,
            "recommended_action": action,
        })

    result_df = pd.DataFrame(customer_records)
    if not result_df.empty:
        result_df = result_df.sort_values(
            by=["risk_score", "total_revenue"],
            ascending=[False, False]
        )
    return result_df


def analyze_client_technical_profile(client_orders: pd.DataFrame) -> dict:
    """Estrae l'identikit tecnico e le specifiche ricorrenti di un cliente.
    
    Analizza descrizioni articoli, codici, categorie, quantita' e importi per
    ricavare:
    - Conteggi fibre e formazioni ricorrenti
    - Standard ottici (G657A1, G652D, OM2/3/4, 200um) e sezioni rame
    - Classi di sicurezza e reazione al fuoco (CPR B2ca, Cca, Eca, LSZH)
    - Strutture cavi abituali (Micro, TOL, Armati, Duct)
    - Top 5 articoli storici per valore
    - Suggerimenti e linguaggio tecnico consigliato per la telefonata del commerciale
    """
    if client_orders.empty:
        return {
            "has_data": False,
            "summary": "Nessun dato storico disponibile per questo cliente.",
        }

    df = client_orders.copy()
    total_revenue = df["amount"].sum() if "amount" in df.columns else 0.0
    total_qty = df["qty_ordered"].sum() if "qty_ordered" in df.columns else 0.0
    num_orders = df["order_code"].nunique() if "order_code" in df.columns else len(df)
    num_lines = len(df)

    # Ripartizione Categorie
    cat_summary = {}
    if "product_category" in df.columns:
        for cat, grp in df.groupby("product_category"):
            val = grp["amount"].sum() if "amount" in grp.columns else 0.0
            cat_summary[cat] = {
                "amount": round(val, 2),
                "pct": round((val / total_revenue * 100), 1) if total_revenue > 0 else 0.0,
                "lines": len(grp),
            }

    descriptions = df["product_description"].dropna().astype(str).tolist() if "product_description" in df.columns else []
    all_text = " ".join(descriptions).upper()

    # 1. Rilevamento Conteggio Fibre
    fiber_counts = {}
    import re
    # Pattern per fibre: es. 12F, 24F, 48F, 96F, 144F, 192F, 288F, 432F o 'TOL... 96 ' o '24FO'
    fiber_patterns = [
        (r'\b(432)\s*(?:F|FO|SM)?\b', "432 Fibre"),
        (r'\b(288)\s*(?:F|FO|SM)?\b', "288 Fibre"),
        (r'\b(216)\s*(?:F|FO|SM)?\b', "216 Fibre"),
        (r'\b(192)\s*(?:F|FO|SM)?\b', "192 Fibre"),
        (r'\b(144)\s*(?:F|FO|SM)?\b', "144 Fibre"),
        (r'\b(96)\s*(?:F|FO|SM)?\b', "96 Fibre"),
        (r'\b(72)\s*(?:F|FO|SM)?\b', "72 Fibre"),
        (r'\b(48)\s*(?:F|FO|SM)?\b', "48 Fibre"),
        (r'\b(36)\s*(?:F|FO|SM)?\b', "36 Fibre"),
        (r'\b(24)\s*(?:F|FO|SM)?\b', "24 Fibre"),
        (r'\b(12)\s*(?:F|FO|SM)?\b', "12 Fibre"),
        (r'\b(8)\s*(?:F|FO|SM)?\b', "8 Fibre"),
        (r'\b(4)\s*(?:F|FO|SM)?\b', "4 Fibre"),
        (r'\b(2)\s*(?:F|FO|SM)?\b', "2 Fibre"),
    ]
    for d in descriptions:
        d_up = d.upper()
        for pat, label in fiber_patterns:
            if re.search(pat, d_up):
                fiber_counts[label] = fiber_counts.get(label, 0) + 1

    # 2. Standard Ottici e Tipi Fibra
    standards = []
    if "G657" in all_text or "G.657" in all_text:
        standards.append("G.657.A1 / A2 (Anti-piegatura / FTTH)")
    if "G652" in all_text or "G.652" in all_text:
        standards.append("G.652.D (Standard Singolomodo / Dorsali)")
    if "G655" in all_text or "G.655" in all_text:
        standards.append("G.655 (NZD / Lunga Distanza)")
    if "200" in all_text or "200UM" in all_text:
        standards.append("Fibra 200 µm (Microcavi ad alta densità)")
    if "OM2" in all_text:
        standards.append("Multimodo OM2")
    if "OM3" in all_text:
        standards.append("Multimodo OM3")
    if "OM4" in all_text:
        standards.append("Multimodo OM4")
    if "OM5" in all_text:
        standards.append("Multimodo OM5")

    # 3. Strutture e Costruzioni Cavo
    structures = []
    if "MICRO" in all_text or "DUCT" in all_text or "SOFFI" in all_text:
        structures.append("Microcavi per Soffiatura in Minitubo (Micro / Duct)")
    if "TOL" in all_text:
        structures.append("Miniguaina e Cavi a Tubetto Centrale (TOL1 / TOL6D / TOL8D)")
    if "A-DQ" in all_text or "LOOSE" in all_text:
        structures.append("Loose Tube Multitubo Esterno (A-DQ(ZN)2Y)")
    if "ARM" in all_text or "FRP" in all_text or "CORAZZ" in all_text or "STEEL" in all_text:
        structures.append("Cavi Armati / Antiroditore (FRP / Nastro Acciaio)")
    if "ATLAS" in all_text or "AEREO" in all_text or "ADSS" in all_text:
        structures.append("Cavi per Posa Aerea / Autoportanti (ADSS / Atlas)")

    # 4. Sicurezza, CPR e Guaine
    cpr_classes = []
    if "B2CA" in all_text:
        cpr_classes.append("CPR B2ca-s1a,d1,a1 (Alta Sicurezza / Gallerie / Edifici Pubblici)")
    if "CCA" in all_text:
        cpr_classes.append("CPR Cca (Media Sicurezza)")
    if "ECA" in all_text:
        cpr_classes.append("CPR Eca (Uso Standard / Esterno)")
    if "LSZH" in all_text or "LS0H" in all_text or "HALOGEN" in all_text:
        cpr_classes.append("Guaina LSZH (Zero Alogeni / Ritardante di Fiamma)")
    if " PE " in all_text or "PE " in all_text or "INNER PE" in all_text:
        cpr_classes.append("Guaina Polietilene (PE - Posa Interrata / Esterna)")
    if "PA" in all_text or "POLIAMMIDE" in all_text:
        cpr_classes.append("Guaina Poliammide (PA - Protezione Anti-Termiti/Roditori)")

    # 5. Sezioni Rame e Cavi Speciali
    copper_specs = []
    if re.search(r'\b\d+x\d+(?:,\d+)?\b', all_text) or "MMQ" in all_text:
        copper_specs.append("Cavi Energia / Bassa Tensione (mmq)")
    if "CAT" in all_text or "UTP" in all_text or "FTP" in all_text:
        copper_specs.append("Cablaggio Dati Rame (Cat. 6 / 6A / 7)")
    if "FG16" in all_text or "FROR" in all_text or "FTG10" in all_text:
        copper_specs.append("Cavi Industriali / Resistenti al Fuoco (FG16 / FTG10)")

    # 6. Top 5 Prodotti Storici
    top_products = []
    if "product_code" in df.columns:
        agg_rules = {
            "qty_ordered": "sum",
            "amount": "sum",
            "order_date": "max",
        }
        if "product_description" in df.columns:
            agg_rules["product_description"] = "first"
        if "uom" in df.columns:
            agg_rules["uom"] = "first"
        if "product_category" in df.columns:
            agg_rules["product_category"] = "first"

        prod_grp = df.groupby("product_code").agg(agg_rules).reset_index()
        prod_grp = prod_grp.sort_values("amount", ascending=False).head(5)

        for _, p in prod_grp.iterrows():
            top_products.append({
                "code": str(p["product_code"]),
                "description": str(p.get("product_description", "")) or "N/D",
                "category": str(p.get("product_category", "N/D")),
                "qty": float(p.get("qty_ordered", 0.0)),
                "uom": str(p.get("uom", "M")),
                "amount": float(p.get("amount", 0.0)),
                "last_order": str(p.get("order_date", ""))[:10],
            })

    # 7. Sintesi Applicativa & Linguaggio Tecnico per il Commerciale
    app_profile = []
    pitch_hooks = []
    tech_keywords = []

    has_ftth = ("G.657" in str(standards) or "TOL" in str(structures) or "MICRO" in str(structures))
    has_high_fiber = any(k in fiber_counts for k in ["144 Fibre", "192 Fibre", "288 Fibre", "432 Fibre"])
    has_b2ca = any("B2ca" in c for c in cpr_classes)

    if has_ftth and has_high_fiber:
        app_profile.append("Infrastrutture di Accesso FTTH / Dorsali Urbane ad Alta Densità")
        pitch_hooks.append("Focus su minicavi e microcavi 200µm per massimizzare la capienza dei minitubi da 10-12 mm.")
        tech_keywords.extend(["Microcavi 200µm", "G.657.A1", "Soffiatura in minitubo", "TOL miniguaina"])
    elif has_ftth:
        app_profile.append("Reti di Distribuzione FTTH / Posa Secondaria")
        pitch_hooks.append("Verificare fabbisogni di cavi di drop e miniguaine B2ca/Cca per posa interna ad edifici.")
        tech_keywords.extend(["Drop FTTH", "G.657.A1 Bending Insensitive", "Guaina CPR B2ca"])
    
    if has_b2ca:
        app_profile.append("Progetti con Elevati Standard di Sicurezza Antincendio (Gallerie / Ospedali / Centri Dati)")
        pitch_hooks.append("Sottolineare la certificazione CPR B2ca-s1a,d1,a1 e l'omologazione per ambienti a maggior rischio.")
        tech_keywords.append("Certificati CPR B2ca Euroclasse")

    if not app_profile:
        app_profile.append("Forniture Cavi per Impiantistica e Telecomunicazioni Generali")
        pitch_hooks.append("Proporre la gamma completa e richiedere i capitolati tecnici dei prossimi cantieri.")

    return {
        "has_data": True,
        "total_revenue": round(total_revenue, 2),
        "total_qty": round(total_qty, 2),
        "num_orders": num_orders,
        "num_lines": num_lines,
        "category_breakdown": cat_summary,
        "top_fibers": sorted(fiber_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        "standards": standards or ["Standard da verificare sui codici ordine"],
        "structures": structures or ["Cavi Standard"],
        "cpr_classes": cpr_classes or ["Classe Standard / Non specificata esplicitamente"],
        "copper_specs": copper_specs,
        "top_products": top_products,
        "application_profile": app_profile,
        "pitch_hooks": pitch_hooks,
        "tech_keywords": list(dict.fromkeys(tech_keywords)),
    }


def normalize_company_name(name: str) -> str:
    """Pulisce e normalizza la ragione sociale per il matching."""
    if not name:
        return ""
    import re
    n = name.upper()
    # Rimuove forme societarie
    n = re.sub(r'\b(S\.P\.A\.|SPA|S\.R\.L\.|SRL|S\.A\.S\.|SAS|GMBH|S\.A\.|SA|AG|LTD|LIMITED|INC|CORP|CO|KG|S\.P\.Z\.O\.O\.)\b', '', n)
    # Rimuove punteggiatura e spazi multipli
    n = re.sub(r'[^A-Z0-9]', '', n)
    return n.strip()


def match_company_with_erp_clients(company_name: str, periodicity_df: pd.DataFrame) -> Optional[dict]:
    """Cerca se un'azienda trovata in Tender/News corrisponde a un cliente ERP esistente."""
    if not company_name or periodicity_df.empty:
        return None

    target_norm = normalize_company_name(company_name)
    if not target_norm or len(target_norm) < 3:
        return None

    target_raw_lower = company_name.strip().lower()

    for _, row in periodicity_df.iterrows():
        c_name = str(row["client_name"]).strip()
        c_norm = normalize_company_name(c_name)
        c_lower = c_name.lower()

        # Match esatto normalizzato o contenimento reciproco significativo
        if target_norm == c_norm:
            return row.to_dict()
        if len(target_norm) >= 4 and len(c_norm) >= 4:
            if target_norm in c_norm or c_norm in target_norm:
                return row.to_dict()
            if target_raw_lower in c_lower or c_lower in target_raw_lower:
                return row.to_dict()

    return None


def get_suggested_cable_solution(sector: str, norms: str = "", text: str = "") -> dict:
    """Restituisce la soluzione cavi della gamma aziendale consigliata per il bando/notizia."""
    sec = str(sector).lower() if sector else ""
    comb = f"{sec} {str(norms).lower()} {str(text).lower()}"

    if "ferroviario" in comb or "treno" in comb or "45545" in comb or "rfi" in comb or "rotabil" in comb:
        return {
            "family": "🚆 Cavi Ferroviari & Segnalamento",
            "products": "Cavi per rotabili conformi EN 45545-2 (HL1/HL2/HL3), Cavi segnalamento e comando RFI, Dorsali in fibra ottica armate anti-roditore lungo binario",
            "certifications": "EN 45545-2, CEI 20-37, LSZH Zero Alogeni",
            "pitch": "Offrire schede tecniche omologate EN 45545-2 HL3 e flessibilità su lunghezze e sezioni di posa per cantieri ferroviari.",
        }
    elif "navale" in comb or "marine" in comb or "cantiere" in comb or "rina" in comb or "dnv" in comb or "fincantieri" in comb:
        return {
            "family": "⚓ Cavi Navali & Offshore",
            "products": "Cavi energia, controllo e fibra ottica per ambienti marini con certificazione navale, guaine resistenti a idrocarburi e fango (mud resistant)",
            "certifications": "RINA, DNV-GL, Bureau Veritas, Lloyd's Register",
            "pitch": "Presentare le omologazioni RINA/DNV e la resistenza all'ambiente marino salino per impianti di bordo e sale macchine.",
        }
    elif "data center" in comb or "datacenter" in comb or "hyperscale" in comb or "b2ca" in comb or "mpo" in comb:
        return {
            "family": "🖥️ Cavi per Data Center & High Density",
            "products": "Dorsali e bretelle MPO/MTP, Cavi ottici OM4/OM5 e Singolomodo ad altissima densità, Cavi rame Cat 6A / Cat 8, Euroclasse CPR B2ca-s1a,d0",
            "certifications": "CPR Euroclasse B2ca-s1a,d0 / s1a,d1,a1, TIA-942",
            "pitch": "Sottolineare la conformità CPR B2ca per locali ad alto affollamento/criticità e la bassa attenuazione sui link ad alta velocità.",
        }
    elif "telecom" in comb or "provider" in comb or "ftth" in comb or "fibra" in comb or "banda larga" in comb or "open fiber" in comb or "fibercop" in comb:
        return {
            "family": "🌐 Cavi Telecomunicazioni & FTTH",
            "products": "Microcavi 200µm per soffiatura (12F-288F), Miniguaine TOL, Cavi di allacciamento Drop B2ca/Cca, Cavi aerei autoportanti ADSS / Atlas",
            "certifications": "ITU-T G.657.A1 / A2, ITU-T G.652.D, CPR B2ca / Cca",
            "pitch": "Proporre microcavi 200µm ad alto stipamento per minitubi e tempi rapidi di consegna su bobine standard.",
        }
    elif "avio" in comb or "difesa" in comb or "aerospaz" in comb or "mil" in comb or "leonardo" in comb:
        return {
            "family": "✈️ Cavi Speciali Avio & Difesa",
            "products": "Cavi leggeri ad alta temperatura PTFE/ETFE, cavi dati schermati aerospaziali, fibre ottiche speciali resistenti a vibrazioni estreme",
            "certifications": "MIL-DTL, Norme EN aerospaziali, VG",
            "pitch": "Evidenziare l'affidabilità in condizioni termiche e meccaniche estreme con collaudi al 100%.",
        }
    else:
        return {
            "family": "⚡ Cavi Speciali Industria & Energia",
            "products": "Cavi energia Bassa Tensione resistenti al fuoco (FTG10/FG16), Cavi controllo e trasmissione dati Cat 6A/7 LSZH, Cavi fibra ottica dielettrici",
            "certifications": "CPR Euroclassi B2ca / Cca / Eca, CEI 20-22",
            "pitch": "Fornire preventivi rapidi e supporto ingegneristico sulle specifiche speciali di capitolato.",
        }


def analyze_crm_orders(df_orders: pd.DataFrame) -> list[dict]:
    """Genera la lista di alert operativi per i commerciali a partire dallo storico ordini."""
    periodicity_df = calculate_customer_periodicity(df_orders)
    if periodicity_df.empty:
        return []

    opportunities = []
    now_str = datetime.now().strftime("%Y-%m-%d")

    for _, row in periodicity_df.iterrows():
        # Genera alert per Churn, Ritardi e Cross-Selling
        if row["status_code"] in ["CHURN_RISK", "DELAYED", "DORMANT"]:
            opportunities.append({
                "source": "crm",
                "external_id": f"crm:{row['status_code'].lower()}:{row['client_id']}:{row['last_order'].replace('-', '')}",
                "title": f"{row['status']}: {row['client_name']}",
                "country": row["country"],
                "client_id": row["client_id"],
                "client_name": row["client_name"],
                "total_revenue": row["total_revenue"],
                "mtbo_days": row["mtbo_days"],
                "days_since_last": row["days_since_last"],
                "delay_ratio": row["delay_ratio"],
                "text": (
                    f"Cliente: {row['client_name']} ({row['country']}). "
                    f"Fatturato storico: €{row['total_revenue']:,.2f} su {row['total_orders']} ordini. "
                    f"Ciclo medio riordino (MTBO): {row['mtbo_days']} giorni. "
                    f"Ultimo ordine: {row['last_order']} ({row['days_since_last']} giorni fa, indice ritardo {row['delay_ratio']}x). "
                    f"Categorie acquistate: {row['categories']}."
                ),
                "recommended_action": row["recommended_action"],
                "cross_sell": row["cross_sell_opportunity"],
                "published": now_str,
            })

    return opportunities


def check_pipeline_health(df_deals: pd.DataFrame) -> list[dict]:
    """Valuta lo stato di salute delle trattative aperte (Deal Health Check).
    Colonne: ['deal_name', 'client_name', 'amount', 'stage', 'days_in_stage']
    """
    df = df_deals.copy()
    health_alerts = []

    for _, row in df.iterrows():
        days = int(row.get("days_in_stage", 0))
        stage = str(row.get("stage", ""))
        amount = float(row.get("amount", 0))

        risk_level = "BASSO"
        reason = "Trattativa nei parametri standard."
        action = "Monitorare la data di chiusura stimata."

        if days > 45 and stage in ["Offerta Inviata", "Negoziazione"]:
            risk_level = "ALTO"
            reason = f"Trattativa ferma nello stage '{stage}' da {days} giorni (soglia max 45gg)."
            action = "Organizzare un allineamento con il referente tecnico o verificare prezzi/condizioni."
        elif days > 30 and stage in ["Qualificazione", "Analisi Tecnica"]:
            risk_level = "MEDIO"
            reason = f"Qualificazione tecnica prolungata ({days} giorni)."
            action = "Inviare schede tecniche di confronto e fissare una call con il Sales Engineer."

        health_alerts.append({
            "deal_name": row.get("deal_name"),
            "client_name": row.get("client_name"),
            "amount": amount,
            "stage": stage,
            "days_in_stage": days,
            "risk_level": risk_level,
            "reason": reason,
            "action": action,
        })

    return health_alerts

