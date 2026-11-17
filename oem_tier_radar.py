"""OEM Tier Radar — Doppio Binario (Binario 1: colossi OEM/Tier-0).

Logica:
  1.1 Watchlist colossi (oem_watchlist): ~35 OEM/EPC europei con aliases,
      stabilimenti produttivi e standard cavi rilevanti.
  1.2 Radar Commesse Madre (job giornaliero): per ogni OEM attivo esegue
      Google News RSS localizzato (piu' Search API se configurata) con
      query booleane per settore; l'LLM scarta notizie finanziarie e
      conferma solo ordini produttivi reali -> oem_contract_alerts.
  1.3 Tier 1/2 Discovery (job settimanale): query per standard tecnico
      (VG95218, EN 45545, RINA, MIL-DTL, CPR) x paese target; l'LLM filtra
      portali lavoro/directory/distributori, l'ERP esclude i gia' clienti;
      i nuovi cablisti entrano in prospects_europa come TIER1_DISCOVERY
      e da li passano al Binario 2 (profiling + outreach).

I subfornitori scoperti alimentano il Binario 2 (Company Intelligence
360 + News Intelligence + Outreach AI) come aziende medie.
"""
import re

import company_intelligence as ci
import db
import news_intelligence as ni
from llm import generate_json_completion
from prospecting_engine import check_erp_customer

# ---------------------------------------------------------------------------
# 1.1 — WATCHLIST SEED: colossi OEM/EPC europei per settore
# ---------------------------------------------------------------------------

OEM_WATCHLIST_SEED = [
    # --- Ferroviario -----------------------------------------------------
    {"oem_name": "Alstom", "sector": "Ferroviario",
     "aliases": ["Alstom Transport", "Bombardier Transportation"],
     "production_sites": ["Savigliano (IT)", "Sesto San Giovanni (IT)",
                          "Valenciennes (FR)", "La Rochelle (FR)",
                          "Salzgitter (DE)", "Katowice Chorzów (PL)"],
     "target_standards": ["EN 45545-2", "EN 50306", "NF F63-826"]},
    {"oem_name": "Siemens Mobility", "sector": "Ferroviario",
     "aliases": ["Siemens Mobility GmbH"],
     "production_sites": ["Krefeld-Uerdingen (DE)", "München Allach (DE)",
                          "Kassel (DE)", "Wien (AT)", "Kralovice (CZ)"],
     "target_standards": ["EN 45545-2", "EN 50306"]},
    {"oem_name": "Stadler Rail", "sector": "Ferroviario",
     "aliases": ["Stadler Rail AG", "Stadler Bussnang"],
     "production_sites": ["Bussnang (CH)", "Berlin-Pankow (DE)",
                          "Albuixech Valencia (ES)", "Szolnok (HU)",
                          "Siedlce (PL)"],
     "target_standards": ["EN 45545-2", "EN 50306"]},
    {"oem_name": "Hitachi Rail", "sector": "Ferroviario",
     "aliases": ["Hitachi Rail Italy", "ex AnsaldoBreda"],
     "production_sites": ["Pistoia (IT)", "Reggio Calabria (IT)",
                          "Napoli (IT)", "Hensol (UK)"],
     "target_standards": ["EN 45545-2", "EN 50306"]},
    {"oem_name": "CAF", "sector": "Ferroviario",
     "aliases": ["Construcciones y Auxiliar de Ferrocarriles",
                 "CAF Rolling Stock"],
     "production_sites": ["Beasain (ES)", "Zaragoza (ES)", "Irun (ES)"],
     "target_standards": ["EN 45545-2", "EN 50306"]},
    {"oem_name": "Talgo", "sector": "Ferroviario",
     "aliases": ["Talgo S.A."],
     "production_sites": ["Rivabellosa (ES)", "Las Matas Madrid (ES)"],
     "target_standards": ["EN 45545-2"]},
    {"oem_name": "Škoda Transportation", "sector": "Ferroviario",
     "aliases": ["Skoda Transportation", "Skoda Group"],
     "production_sites": ["Plzeň (CZ)", "Ostrava (CZ)"],
     "target_standards": ["EN 45545-2", "EN 50306"]},
    {"oem_name": "Pesa", "sector": "Ferroviario",
     "aliases": ["Pojazdy Szynowe PESA Bydgoszcz"],
     "production_sites": ["Bydgoszcz (PL)"],
     "target_standards": ["EN 45545-2"]},
    # --- Navale/Offshore --------------------------------------------------
    {"oem_name": "Fincantieri", "sector": "Navale/Offshore",
     "aliases": ["Fincantieri S.p.A.", "Fincantieri Naval"],
     "production_sites": ["Monfalcone (IT)", "Marghera (IT)",
                          "Sestri Ponente (IT)", "Muggiano La Spezia (IT)",
                          "Castellammare di Stabia (IT)",
                          "Riva Trigoso (IT)"],
     "target_standards": ["RINA", "DNV", "MIL-DTL-24643", "Lloyd's Register"]},
    {"oem_name": "Naval Group", "sector": "Navale/Offshore",
     "aliases": ["DCNS", "Naval Group France"],
     "production_sites": ["Lorient (FR)", "Cherbourg (FR)",
                          "Brest (FR)", "Toulon (FR)"],
     "target_standards": ["MIL-DTL-24643", "DEF-STAN", "RINA"]},
    {"oem_name": "ThyssenKrupp Marine Systems", "sector": "Navale/Offshore",
     "aliases": ["TKMS", "Howaldtswerke-Deutsche Werft", "HDW"],
     "production_sites": ["Kiel (DE)", "Wismar (DE)", "Emden (DE)"],
     "target_standards": ["VG95218", "MIL-DTL-24643"]},
    {"oem_name": "Damen Shipyards", "sector": "Navale/Offshore",
     "aliases": ["Damen Shipyards Group"],
     "production_sites": ["Gorinchem (NL)", "Galați (RO)",
                          "Mangalia (RO)"],
     "target_standards": ["RINA", "DNV", "BV"]},
    {"oem_name": "Meyer Werft", "sector": "Navale/Offshore",
     "aliases": ["Meyer Werft Papenburg", "Meyer Turku"],
     "production_sites": ["Papenburg (DE)", "Turku (FI)",
                          "Rostock (DE)"],
     "target_standards": ["RINA", "DNV", "SOLAS"]},
    {"oem_name": "Ferretti Group", "sector": "Navale/Offshore",
     "aliases": ["Ferretti", "Riva Yachts", "CRN Ancona"],
     "production_sites": ["Forlì (IT)", "Ancona (IT)", "La Spezia (IT)",
                          "Mondolfo (IT)"],
     "target_standards": ["RINA", "ISO 8846"]},
    # --- Avio/Difesa ------------------------------------------------------
    {"oem_name": "Leonardo", "sector": "Avio/Difesa",
     "aliases": ["Leonardo S.p.A.", "Finmeccanica", "Leonardo Defence"],
     "production_sites": ["Vergiate/Cascina Costa (IT)",
                          "Torino Caselle (IT)", "Pomigliano d'Arco (IT)",
                          "La Spezia (IT)", "Brescia (IT)"],
     "target_standards": ["MIL-DTL-24643", "VG95218", "EN 3475",
                          "MIL-STD-810"]},
    {"oem_name": "Iveco Defence Vehicles", "sector": "Avio/Difesa",
     "aliases": ["IDV Defence", "Leonardo IDV", "Iveco DV Bolzano"],
     "production_sites": ["Bolzano (IT)", "Vittorio Veneto (IT)",
                          "Piacenza (IT)", "Ulm (DE)"],
     "target_standards": ["VG95218", "MIL-DTL", "NATO STANAG"]},
    {"oem_name": "Rheinmetall", "sector": "Avio/Difesa",
     "aliases": ["Rheinmetall Defence", "Rheinmetall Landsysteme"],
     "production_sites": ["Kassel (DE)", "Unterlüß (DE)",
                          "Bremen (DE)", "Zaragoza (ES)"],
     "target_standards": ["VG95218", "MIL-DTL"]},
    {"oem_name": "Airbus Defence and Space", "sector": "Avio/Difesa",
     "aliases": ["Airbus Defence", "Airbus DS"],
     "production_sites": ["Manching (DE)", "Ottobrunn (DE)",
                          "Getafe (ES)", "Toulouse (FR)"],
     "target_standards": ["EN 3475", "MIL-DTL", "AS9100"]},
    {"oem_name": "Thales", "sector": "Avio/Difesa",
     "aliases": ["Thales Group", "Thales Alenia Space"],
     "production_sites": ["Toulouse (FR)", "Bordeaux (FR)",
                          "Ditzingen (DE)", "Hengelo (NL)",
                          "L'Aquila (IT)"],
     "target_standards": ["EN 3475", "MIL-DTL"]},
    {"oem_name": "KNDS", "sector": "Avio/Difesa",
     "aliases": ["KMW", "Krauss-Maffei Wegmann", "Nexter"],
     "production_sites": ["München (DE)", "Kassel (DE)",
                          "Roanne (FR)", "Versailles (FR)"],
     "target_standards": ["VG95218", "MIL-DTL"]},
    {"oem_name": "GDELS", "sector": "Avio/Difesa",
     "aliases": ["General Dynamics European Land Systems",
                 "GDELS Santa Bárbara", "GDELS-Mowag"],
     "production_sites": ["Steyr (AT)", "Trubia (ES)",
                          "Kaiserslautern (DE)", "Kreuzlingen (CH)"],
     "target_standards": ["VG95218", "MIL-DTL"]},
    # --- Telecom/Provider -------------------------------------------------
    {"oem_name": "Nokia", "sector": "Telecom/Provider",
     "aliases": ["Nokia Networks", "Nokia Solutions"],
     "production_sites": ["Espoo (FI)", "Oulu (FI)",
                          "Tallinn (EE)"],
     "target_standards": ["GR-326", "IEC 60794", "CPR B2ca"]},
    {"oem_name": "Ericsson", "sector": "Telecom/Provider",
     "aliases": ["Ericsson AB", "Ericsson Radio"],
     "production_sites": ["Kista Stockholm (SE)", "Tallinn (EE)",
                          "Genova (IT)"],
     "target_standards": ["GR-326", "IEC 60794", "CPR B2ca"]},
    {"oem_name": "Cellnex", "sector": "Telecom/Provider",
     "aliases": ["Cellnex Telecom"],
     "production_sites": ["Barcelona (ES) HQ", "Torri DACH/FR/IT/NL/PL"],
     "target_standards": ["CPR B2ca", "IEC 60332"]},
    {"oem_name": "Open Fiber", "sector": "Telecom/Provider",
     "aliases": ["Open Fiber S.p.A."],
     "production_sites": ["Milano (IT)", "Roma (IT)"],
     "target_standards": ["CPR B2ca", "G.657.A1"]},
    # --- Data Center ------------------------------------------------------
    {"oem_name": "Equinix", "sector": "Data Center",
     "aliases": ["Equinix Inc", "Equinix EMEA"],
     "production_sites": ["Milano (IT)", "Frankfurt (DE)",
                          "Paris (FR)", "Amsterdam (NL)", "Zurich (CH)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4", "Cat 6A"]},
    {"oem_name": "Digital Realty", "sector": "Data Center",
     "aliases": ["Digital Realty Trust", "Interxion"],
     "production_sites": ["Frankfurt (DE)", "Amsterdam (NL)",
                          "Madrid (ES)", "Dublin (IE)", "Milano (IT)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "NTT Global Data Centers", "sector": "Data Center",
     "aliases": ["NTT GDC", "NTT DATA Centers EMEA"],
     "production_sites": ["Frankfurt (DE)", "Berlin (DE)",
                          "Wien (AT)", "Zurich (CH)", "Madrid (ES)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "Vantage Data Centers", "sector": "Data Center",
     "aliases": ["Vantage DC", "Vantage EMEA"],
     "production_sites": ["Frankfurt (DE)", "Berlin (DE)",
                          "Zurich (CH)", "Warsaw (PL)", "Milano (IT)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "STACK Infrastructure", "sector": "Data Center",
     "aliases": ["STACK DC", "Stack EMEA"],
     "production_sites": ["Milano (IT)", "Frankfurt (DE)",
                          "Zurich (CH)", "Oslo (NO)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "Colt DCS", "sector": "Data Center",
     "aliases": ["Colt Data Centre Services"],
     "production_sites": ["London (UK)", "Frankfurt (DE)",
                          "Paris (FR)", "Milano (IT)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "CyrusOne", "sector": "Data Center",
     "aliases": ["CyrusOne Europe", "CyrusOne KEP"],
     "production_sites": ["Frankfurt (DE)", "Amsterdam (NL)",
                          "Dublin (IE)", "London (UK)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "maincubes", "sector": "Data Center",
     "aliases": ["maincubes GmbH"],
     "production_sites": ["Frankfurt (DE)", "Berlin (DE)",
                          "Amsterdam (NL)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "Green Mountain", "sector": "Data Center",
     "aliases": ["Green Mountain AS"],
     "production_sites": ["Stavanger (NO)", "Rjukan (NO)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
    {"oem_name": "Bulk Infrastructure", "sector": "Data Center",
     "aliases": ["Bulk Data Centers"],
     "production_sites": ["Oslo (NO)", "Kristiansand (NO)",
                          "Esbjerg (DK)"],
     "target_standards": ["CPR B2ca", "MPO/MTP OM4"]},
]

# Keyword di commessa per settore (query booleane Logica 1.2)
_SECTOR_QUERY = {
    "Avio/Difesa": '("contract" OR "order" OR "procurement" OR "vehicles" '
                   'OR "consortium" OR "MoU")',
    "Ferroviario": '("rolling stock" OR "trains" OR "framework agreement" '
                   'OR "refurbishment")',
    "Navale/Offshore": '("newbuild" OR "vessel order" OR "cruise ship" '
                       'OR "frigate" OR "shipyard")',
    "Data Center": '("MW" OR "campus" OR "groundbreaking" '
                    'OR "data center")',
    "Telecom/Provider": '("network" OR "rollout" OR "tower" OR "fiber" '
                         'OR "5G" OR "contract")',
}


def seed_watchlist() -> int:
    """Popola oem_watchlist con i colossi seed (idempotente)."""
    n = 0
    for d in OEM_WATCHLIST_SEED:
        db.upsert_oem(d)
        n += 1
    return n


# ---------------------------------------------------------------------------
# 1.2 — RADAR COMMESSE MADRE
# ---------------------------------------------------------------------------

_CONFIRM_PROMPT = """Sei il Sales Intelligence Analyst di un produttore europeo di cavi speciali (EN 45545, VG95218, RINA/DNV, MIL-DTL, CPR B2ca, fibra MPO/MTP).

Ricevi titoli+snippet di articoli su un colosso OEM. SCARTA notizie finanziarie/borsistiche, analisi di mercato, opinioni, ricorsi legali.
CONFERMA (nuova_commessa_rilevata=true) SOLO se l'articolo descrive un ordine produttivo reale: appalto vinto, ordine veicoli/vagoni/navi, framework agreement, commessa di costruzione, nuovo data center.

Rispondi SOLO con JSON:
{
 "nuova_commessa_rilevata": true|false,
 "article_index": <indice articolo confermante o null>,
 "contract_summary": "<cliente finale, volumi/mezzi/MW, cosa si produce>",
 "probable_site": "<stabilimento produttivo plausibile tra quelli noti o 'da verificare'>",
 "suggested_mb_cables": ["<2-4 famiglie cavi MB coerenti con gli standard dell'OEM>"],
 "time_window": "<stima finestra fornitura: es. 2026-2028 o null>"
}"""


def _collect_oem_articles(oem: dict, days: int = 30) -> list[dict]:
    """News RSS localizzato (multi-alias) + Search API se configurata."""
    names = [oem["oem_name"]] + (oem.get("aliases") or [])[:2]
    articles, seen = [], set()
    for name in names:
        for a in ni.google_news_rss(
                name, None, days=days, max_items=8):
            if a["url"] not in seen:
                seen.add(a["url"])
                a["matched_alias"] = name
                articles.append(a)
    if ci.search_api_configured():
        kw = _SECTOR_QUERY.get(oem.get("sector") or "", '"contract"')
        for a in ci.web_search(
                f'"{oem["oem_name"]}" {kw}', max_results=8, days=days):
            if a["url"] not in seen:
                seen.add(a["url"])
                a["source"] = "search_api"
                articles.append(a)
    return articles


def scan_oem_for_contract(oem: dict, days: int = 30,
                          provider: str | None = None) -> dict | None:
    """Radar su un singolo OEM. Ritorna l'alert confermato o None."""
    articles = _collect_oem_articles(oem, days=days)
    if not articles:
        return None
    listing = "\n".join(
        f"[{i}] ({a.get('published') or 'n.d.'}) {a['title']} — "
        f"{a.get('content', '')[:150]}"
        for i, a in enumerate(articles[:20]))
    sites = ", ".join(oem.get("production_sites") or [])
    std = ", ".join(oem.get("target_standards") or [])
    user = (f"OEM: {oem['oem_name']} (settore {oem.get('sector')})\n"
            f"Stabilimenti noti: {sites or 'n/d'}\n"
            f"Standard cavi OEM: {std or 'n/d'}\n\nARTICOLI:\n{listing}")
    data, _p = generate_json_completion(_CONFIRM_PROMPT, user,
                                        provider=provider, timeout=60)
    if not isinstance(data, dict) or not data.get(
            "nuova_commessa_rilevata"):
        return None
    art = {}
    try:
        art = articles[int(data.get("article_index"))]
    except (TypeError, ValueError, IndexError):
        return None
    return {"oem_id": oem["oem_id"],
            "contract_summary": str(data.get("contract_summary") or ""),
            "probable_site": data.get("probable_site"),
            "suggested_mb_cables": data.get("suggested_mb_cables") or [],
            "source_url": art.get("url") or "",
            "source_title": art.get("title") or "",
            "time_window": data.get("time_window")}


def run_radar(days: int = 30, provider: str | None = None,
              verbose: bool = True) -> dict:
    """Job giornaliero: scansiona tutti gli OEM attivi, dedup per URL,
    notifica le nuove commesse madre."""
    rep = {"scanned": 0, "articles": 0, "new_alerts": 0, "errors": 0}
    for oem in db.list_oems(active_only=True):
        try:
            alert = scan_oem_for_contract(oem, days=days,
                                          provider=provider)
            rep["scanned"] += 1
            if alert:
                aid = db.insert_contract_alert(alert)
                if aid:
                    rep["new_alerts"] += 1
                    if verbose:
                        print(f"  [oem_radar] COMMESSA {oem['oem_name']}: "
                              f"{alert['contract_summary'][:100]}",
                              flush=True)
                    _notify_key_account(oem, alert)
            db.mark_oem_scanned(oem["oem_id"])
        except Exception as exc:
            rep["errors"] += 1
            db.log_error("oem_radar", target=oem.get("oem_name"),
                         error_type=type(exc).__name__, message=str(exc))
    return rep


def _notify_key_account(oem: dict, alert: dict):
    """Best-effort email al Key Account del settore via notifier SMTP."""
    try:
        import notifier
        cfg = notifier.smtp_config()
        if not cfg.get("host") or not cfg.get("sender"):
            return
        rules = [r for r in db.get_notification_rules()
                 if r.get("active") and r.get("recipient_email")]
        sector_rules = [r for r in rules
                        if oem.get("sector") in (r.get("sectors") or [])]
        to = (sector_rules or rules)[0]["recipient_email"]
        body = (f"<h3>Commessa Madre rilevata: {oem['oem_name']}</h3>"
                f"<p><b>Sintesi:</b> {alert['contract_summary']}</p>"
                f"<p><b>Sito produttivo stimato:</b> "
                f"{alert.get('probable_site') or 'da verificare'}</p>"
                f"<p><b>Cavi MB consigliati:</b> "
                f"{', '.join(alert.get('suggested_mb_cables') or [])}</p>"
                f"<p><b>Finestra stimata:</b> "
                f"{alert.get('time_window') or 'n/d'}</p>"
                f"<p><a href='{alert['source_url']}'>Fonte: "
                f"{alert['source_title'][:100]}</a></p>")
        notifier._send_smtp(
            cfg, to,
            f"🎯 Commessa Madre: {oem['oem_name']} "
            f"({oem.get('sector')})", body)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1.3 — TIER 1/2 DISCOVERY: cablisti europei per standard tecnico
# ---------------------------------------------------------------------------

_TIER_DISCOVERY_TERMS = {
    "VG95218": '("wiring harness" OR "cable assembly" OR '
               '"Kabelkonfektion" OR "MIL-DTL cable")',
    "EN 45545": '("wiring harness" OR "cable assembly" OR '
                '"electrical cabinets" OR "train wiring")',
    "RINA": '("marine cable" OR "ship wiring" OR "naval harness" OR '
            '"cable assembly marine")',
    "MIL-DTL": '("defense wiring" OR "military cable assembly" OR '
               '"aerospace harness")',
    "CPR B2ca": '("structured cabling" OR "data center cabling" OR '
                '"pre-terminated fiber")',
}

_DISCOVERY_AREAS = {
    "DACH": "Germany OR Austria OR Switzerland",
    "FRANCE": "France",
    "IBERIA": "Spain OR Portugal",
    "NORDICS": "Sweden OR Norway OR Denmark OR Finland",
    "BENELUX": "Netherlands OR Belgium",
    "CEE": "Poland OR Czech Republic",
    "ITALY": "Italy",
}

_AREA_COUNTRIES = {
    "DACH": ["DEU", "AUT", "CHE"], "FRANCE": ["FRA"],
    "IBERIA": ["ESP", "PRT"],
    "NORDICS": ["SWE", "NOR", "DNK", "FIN"],
    "BENELUX": ["NLD", "BEL"], "CEE": ["POL", "CZE"],
    "ITALY": ["ITA"],
}

_FILTER_PROMPT = """Sei un analista supply-chain B2B. Ricevi risultati di ricerca web per identificare VERI assemblatori/cablisti europei (aziende 50-300 dipendenti che producono cablaggi per conto terzi).
SCARTA: portali di annunci lavoro (Indeed, Glassdoor...), directory (Kompass, Europages liste generiche), distributori di soli connettori, e-commerce cavi, articoli/news che non sono aziende.
MANTIENI solo i veri produttori/assemblatori di cablaggi.
Rispondi SOLO con JSON:
{"companies": [{"name": "<ragione sociale>", "domain": "<dominio web>", "country": "<paese>", "why": "<perche' e' un cablista reale, 1 riga>"}]}"""


def discover_tier_suppliers(standards: list[str] | None = None,
                            areas: list[str] | None = None,
                            limit: int = 15,
                            provider: str | None = None,
                            verbose: bool = True) -> dict:
    """Discovery cablisti Tier1/2 per standard x area. Richiede Search API.
    Salva in prospects_europa come source_type=TIER1_DISCOVERY."""
    if not ci.search_api_configured():
        if verbose:
            print("[tier_discovery] Search API non configurata: skip.",
                  flush=True)
        return {"queries": 0, "found": 0, "new_prospects": 0,
                "skipped_erp": 0, "error": "search_api_missing"}

    standards = standards or ["EN 45545", "VG95218", "RINA"]
    areas = areas or ["DACH", "FRANCE", "ITALY", "BENELUX", "CEE"]
    rep = {"queries": 0, "found": 0, "new_prospects": 0,
           "skipped_erp": 0}

    for std in standards:
        terms = _TIER_DISCOVERY_TERMS.get(std)
        if not terms:
            continue
        for area in areas:
            geo = _DISCOVERY_AREAS.get(area)
            if not geo:
                continue
            query = f'{terms} "{std}" ({geo}) -jobs -indeed -linkedin'
            results = ci.web_search(query, max_results=8)
            rep["queries"] += 1
            if not results:
                continue
            listing = "\n".join(
                f"[{i}] {r['title']} | {r['url']} | "
                f"{r.get('content', '')[:120]}"
                for i, r in enumerate(results))
            data, _p = generate_json_completion(
                _FILTER_PROMPT,
                f"RISULTATI RICERCA (standard {std}, area {area}):\n{listing}",
                provider=provider, timeout=60)
            for comp in ((data or {}).get("companies") or [])[:limit]:
                name = (comp.get("name") or "").strip()
                if not name or len(name) < 4:
                    continue
                rep["found"] += 1
                # Dedup ERP: escludi gia' clienti attivi
                try:
                    is_erp, erp_name = check_erp_customer(name)
                except Exception:
                    is_erp, erp_name = False, ""
                if is_erp:
                    rep["skipped_erp"] += 1
                    continue
                # Paese stimato dall'area di discovery
                cc = _AREA_COUNTRIES.get(area, [""])[0]
                sector = ("Ferroviario" if "45545" in std else
                          "Navale/Offshore" if std == "RINA" else
                          "Avio/Difesa" if "VG" in std or "MIL" in std
                          else "Data Center")
                site = comp.get("domain") or ""
                db.save_prospect({
                    "company_name": name,
                    "country_code": cc,
                    "sector": sector,
                    "website_url": (f"https://{site}" if site else None),
                    "source_type": "TIER1_DISCOVERY",
                    "is_erp_customer": False,
                    "match_score": 60,
                    "score_reasons": (
                        f"Cablista Tier1/2 scoperto per standard {std} "
                        f"({area}): {comp.get('why', '')[:200]}"),
                    "suggested_cables": std,
                })
                rep["new_prospects"] += 1
                if verbose:
                    print(f"  [tier_discovery] {name} ({cc}) via {std}",
                          flush=True)
    return rep


# ---------------------------------------------------------------------------
# ORCHESTRATORE / CLI
# ---------------------------------------------------------------------------

def is_tier0_oem(company_name: str) -> dict | None:
    """True->dict watchlist se l'azienda e' un colosso in watchlist."""
    from crm_analyzer import normalize_company_name
    target = normalize_company_name(company_name)
    for oem in db.list_oems(active_only=True):
        if normalize_company_name(oem["oem_name"]) == target:
            return oem
        for alias in oem.get("aliases") or []:
            if normalize_company_name(alias) == target:
                return oem
    return None


if __name__ == "__main__":
    import sys
    db.init_db()
    seed_watchlist()
    if "--discover" in sys.argv:
        print(discover_tier_suppliers())
    else:
        print(run_radar())
