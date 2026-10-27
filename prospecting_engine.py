"""Modulo New Business & Prospecting Europeo (Clienti Gemelli & Outreach Multilingua).

Fornisce:
1. Database e motore di Lookalike Prospecting per trovare 'clienti gemelli' in Europa
   (Installatori FTTH, Contractor Ferroviari, Cantieri Navali, Data Center EPC).
2. Generatore AI di Outreach Multilingua (Email formale, Messaggio LinkedIn, Script Telefonico)
   in Italiano, Inglese, Francese e Tedesco tramite Ollama locale (o fallback euristico professionale).
3. Ricerca referenti target LinkedIn e match con gamma prodotti cavi.
"""
import json
import re
from typing import Optional
import requests

from config import AZIENDA, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL
from llm import ollama_available

# ==============================================================================
# DATABASE PROSPECT EUROPEI (LOOKALIKE PROSPECTING)
# ==============================================================================
LOOKALIKE_PROSPECTS_DB = [
    # --- FRANCIA ---
    {
        "company_name": "Circet France",
        "country": "Francia",
        "country_code": "FRA",
        "sector": "Telecom/Provider",
        "company_type": "Primo Contractor Infrastrutture TLC & Fibra",
        "estimated_annual_volume": "Elevato (> 20.000 km/anno)",
        "target_cables": "Microcavi 144F-288F 200µm G.657.A1, Cavi drop B2ca, Miniguaine TOL",
        "typical_projects": "Rollout FTTH reti RIP francesi, posa fibra per Orange e SFR",
        "target_buyer_roles": ["Directeur des Achats Réseaux", "Responsable Approvisionnement Câbles"],
        "linkedin_search_query": "Circet France Achats Cables Fibre",
    },
    {
        "company_name": "SPIE CityNetworks",
        "country": "Francia",
        "country_code": "FRA",
        "sector": "Telecom/Provider",
        "company_type": "System Integrator & Installatore Reti Digitali",
        "estimated_annual_volume": "Elevato",
        "target_cables": "Cavi fibra armati dielettrici, cavi dati Cat 6A/7 LSZH, cavi energia CPR B2ca",
        "typical_projects": "Smart city, videosorveglianza urbana, dorsali metropolitane",
        "target_buyer_roles": ["Responsable Achats Matériel Électrique & Télécom", "Acheteur Réseaux"],
        "linkedin_search_query": "SPIE CityNetworks Achats Cables Telecom",
    },
    {
        "company_name": "Eiffage Énergie Systèmes",
        "country": "Francia",
        "country_code": "FRA",
        "sector": "Ferroviario",
        "company_type": "General Contractor Grandi Opere Elettriche & Ferroviarie",
        "estimated_annual_volume": "Molto Elevato",
        "target_cables": "Cavi segnalamento ferroviario, cavi EN 45545-2 HL3, dorsali fibra ottica lungo linea",
        "typical_projects": "Progetti SNCF Réseau, Grand Paris Express, linee tramviarie",
        "target_buyer_roles": ["Directeur Achats Ferroviaire", "Acheteur Projet Énergie"],
        "linkedin_search_query": "Eiffage Energie Achats Ferroviaire Cables",
    },
    {
        "company_name": "Chantiers de l'Atlantique",
        "country": "Francia",
        "country_code": "FRA",
        "sector": "Navale",
        "company_type": "Cantiere Navale Grandi Navi da Crociera & Militari",
        "estimated_annual_volume": "Molto Elevato",
        "target_cables": "Cavi navali omologati Bureau Veritas / DNV / RINA, cavi ottici leggeri resistenti a fiamma",
        "typical_projects": "Costruzione navi da crociera classe Oasis/World, navi militari rifornimento",
        "target_buyer_roles": ["Responsable Achats Électriques Marine", "Acheteur Équipements Bord"],
        "linkedin_search_query": "Chantiers Atlantique Achats Marine Cables",
    },

    # --- GERMANIA (DACH) ---
    {
        "company_name": "Deutsche Glasfaser Bau GmbH",
        "country": "Germania",
        "country_code": "DEU",
        "sector": "Telecom/Provider",
        "company_type": "Operatore & General Contractor FTTH Rurale",
        "estimated_annual_volume": "Molto Elevato (> 30.000 km/anno)",
        "target_cables": "Microcavi G.657.A1 200µm per minitubi 7-10mm, minicavi 24F-96F, cavi di allacciamento",
        "typical_projects": "Posa FTTH aree bianche e rurali Germania, cluster FTTH comunali",
        "target_buyer_roles": ["Leiter Einkauf Glasfaser / Passive Infrastruktur", "Strategischer Einkäufer Kabel"],
        "linkedin_search_query": "Deutsche Glasfaser Einkauf Kabel Glasfaser",
    },
    {
        "company_name": "Leonhard Weiss GmbH",
        "country": "Germania",
        "country_code": "DEU",
        "sector": "Ferroviario",
        "company_type": "Contractor Infrastrutture Ferroviarie & Linee Elettriche",
        "estimated_annual_volume": "Elevato",
        "target_cables": "Cavi per trazione, segnalamento Deutsche Bahn, cavi ottici corazzati lungo binario",
        "typical_projects": "Rinnovamento corridoi DB Netz, elettrificazione tratte regionali",
        "target_buyer_roles": ["Einkaufsleiter Bahntechnik", "Technischer Einkäufer Kabel"],
        "linkedin_search_query": "Leonhard Weiss Einkauf Bahntechnik Kabel",
    },
    {
        "company_name": "Meyer Werft Papenburg",
        "country": "Germania",
        "country_code": "DEU",
        "sector": "Navale",
        "company_type": "Cantiere Navale Navi da Crociera & Navi Speciali",
        "estimated_annual_volume": "Molto Elevato",
        "target_cables": "Cavi marine DNV/Lloyds, cablaggi multimediali e dorsali dati navali",
        "typical_projects": "Costruzione mega-navi da crociera e navi da ricerca ecologiche",
        "target_buyer_roles": ["Einkäufer Elektrotechnik & Kabel Schiffbau", "Head of Marine Procurement"],
        "linkedin_search_query": "Meyer Werft Einkauf Elektrotechnik Kabel",
    },
    {
        "company_name": "Data4 Group (DACH & CEE)",
        "country": "Germania",
        "country_code": "DEU",
        "sector": "Data Center",
        "company_type": "Sviluppatore & Costruttore Campus Hyperscale",
        "estimated_annual_volume": "Elevato",
        "target_cables": "Cavi fibra ad altissima densità MPO/MTP, OM4/OM5, CPR B2ca-s1a,d0, Cat 8",
        "typical_projects": "Nuovi campus Data Center a Francoforte, Berlino e Varsavia",
        "target_buyer_roles": ["Procurement Director Data Center Infrastructure", "Electrical Package Manager"],
        "linkedin_search_query": "Data4 Procurement Cables Data Center",
    },

    # --- SPAGNA (IBERIA) ---
    {
        "company_name": "Elecnor Deimos / Telecom",
        "country": "Spagna",
        "country_code": "ESP",
        "sector": "Telecom/Provider",
        "company_type": "EPC Contractor Infrastrutture Reti & Energia",
        "estimated_annual_volume": "Elevato",
        "target_cables": "Cavi fibra ottica posa aerea ADSS/Atlas, cavi interrati anti-roditore, cavi rame energia",
        "typical_projects": "Reti fibra per Telefónica e Vodafone, impianti fotovoltaici ed eolici",
        "target_buyer_roles": ["Director de Compras Telecomunicaciones", "Jefe de Aprovisionamiento Cables"],
        "linkedin_search_query": "Elecnor Compras Cables Telecom",
    },
    {
        "company_name": "Navantia S.A.",
        "country": "Spagna",
        "country_code": "ESP",
        "sector": "Navale",
        "company_type": "Costruttore Navale Militare & Offshore Wind",
        "estimated_annual_volume": "Molto Elevato",
        "target_cables": "Cavi navali militari e civili (DNV/BV), cavi resistenti a idrocarburi e fiamme",
        "typical_projects": "Fregate F-110, sottomarini S-80, sottostazioni eoliche marine",
        "target_buyer_roles": ["Jefe de Compras Área Eléctrica y Electrónica", "Responsable Compras Buques"],
        "linkedin_search_query": "Navantia Compras Electricidad Cables",
    },
    {
        "company_name": "CAF (Construcciones y Auxiliar de Ferrocarriles)",
        "country": "Spagna",
        "country_code": "ESP",
        "sector": "Ferroviario",
        "company_type": "Costruttore Materiale Rotabile & Treni Alta Velocità",
        "estimated_annual_volume": "Molto Elevato",
        "target_cables": "Cavi per rotabili conformi EN 45545-2 (HL3), cavi controllo e dorsali Ethernet di bordo",
        "typical_projects": "Fornitura convogli regionali e metropolitane in tutta Europa e UK",
        "target_buyer_roles": ["Comprador Estratégico Cables y Material Eléctrico", "Procurement Rail Rolling Stock"],
        "linkedin_search_query": "CAF Compras Cables Ferroviario",
    },

    # --- POLONIA & CEE ---
    {
        "company_name": "Grupa Trakcja S.A.",
        "country": "Polonia",
        "country_code": "POL",
        "sector": "Ferroviario",
        "company_type": "Contractor Costruzioni e Segnalamento Ferroviario",
        "estimated_annual_volume": "Elevato",
        "target_cables": "Cavi per trazione elettrica, cavi segnalamento PKP PLK, cavi ottici lungo linea",
        "typical_projects": "Modernizzazione linee ferroviarie corridoi UE Polonia ed est Europa",
        "target_buyer_roles": ["Dyrektor Działu Zakupów Kolejowych", "Specjalista ds. Zakupów Kabli"],
        "linkedin_search_query": "Trakcja Zakupy Kable Kolejowe",
    },
    {
        "company_name": "PGE Dystrybucja & Telco",
        "country": "Polonia",
        "country_code": "POL",
        "sector": "Telecom/Provider",
        "company_type": "Operatore Infrastrutture TLC e Reti di Smart Grid",
        "estimated_annual_volume": "Elevato",
        "target_cables": "Cavi ottici OPGW, ADSS aerei per linee elettriche, microcavi per condotte",
        "typical_projects": "Digitalizzazione reti elettriche nazionali e backbone in fibra",
        "target_buyer_roles": ["Kierownik Zakupów Telekomunikacja", "Inżynier Kontraktu Kable"],
        "linkedin_search_query": "PGE Zakupy Kable Swiatlowodowe",
    },

    # --- BENELUX & NORDICS ---
    {
        "company_name": "Eurofiber Group",
        "country": "Paesi Bassi",
        "country_code": "NLD",
        "sector": "Data Center",
        "company_type": "Operatore Dorsali Fibra Ottica & Interconnessione Data Center",
        "estimated_annual_volume": "Molto Elevato",
        "target_cables": "Cavi 288F-432F alta densità G.652.D / G.657.A1, microcavi soffiatura minitubo",
        "typical_projects": "Anelli di interconnessione Data Center Amsterdam/Rotterdam/Bruxelles",
        "target_buyer_roles": ["Head of Network Procurement", "Category Buyer Fiber & Passive Infrastructure"],
        "linkedin_search_query": "Eurofiber Procurement Fiber Cables",
    },
    {
        "company_name": "Damen Shipyards Group",
        "country": "Paesi Bassi",
        "country_code": "NLD",
        "sector": "Navale",
        "company_type": "Costruttore Navale Rimorchiatori, Navi da Lavoro e Difesa",
        "estimated_annual_volume": "Elevato",
        "target_cables": "Cavi marini omologati DNV/Lloyd's, cavi resistenti a olii e fiamme",
        "typical_projects": "Flotta navi da lavoro, rimorchiatori elettrici e pattugliatori marittimi",
        "target_buyer_roles": ["Category Buyer Electrical & Cable Systems", "Marine Procurement Specialist"],
        "linkedin_search_query": "Damen Shipyards Buyer Electrical Cables",
    },
]


def get_lookalike_prospects(
    country_filter: Optional[str] = None,
    sector_filter: Optional[str] = None,
    search_query: str = "",
) -> list[dict]:
    """Filtra e restituisce la lista di aziende prospect gemelle europee."""
    results = []
    q = search_query.strip().lower()

    for p in LOOKALIKE_PROSPECTS_DB:
        if country_filter and country_filter != "TUTTI":
            if p["country"] != country_filter and p["country_code"] != country_filter:
                continue

        if sector_filter and sector_filter != "TUTTI":
            if p["sector"] != sector_filter:
                continue

        if q:
            match = (
                q in p["company_name"].lower()
                or q in p["country"].lower()
                or q in p["sector"].lower()
                or q in p["target_cables"].lower()
                or q in p["typical_projects"].lower()
            )
            if not match:
                continue

        p_copy = dict(p)
        # Costruzione URL di ricerca diretta LinkedIn
        encoded_q = requests.utils.quote(p["linkedin_search_query"])
        p_copy["linkedin_url"] = f"https://www.linkedin.com/search/results/people/?keywords={encoded_q}"
        results.append(p_copy)

    return results


# ==============================================================================
# GENERATORE OUTREACH AI MULTILINGUA
# ==============================================================================

OUTREACH_PROMPTS = {
    "it": {
        "email_subject_sample": "Fornitura Cavi Speciali (Fibra & Rame) omologati per i vostri progetti",
        "system": f"""Sei il Senior International Sales Executive per un produttore europeo primario di cavi speciali in fibra ottica e rame.
{AZIENDA}
Scrivi messaggi commerciali persuasivi, tecnici, formali e concreti per il Responsabile Acquisti / Direttore Tecnico dell'azienda target.
Includi sempre:
1. Gancio sul loro settore o commesse attuali.
2. Perché i nostri cavi (certificazioni CPR B2ca, EN 45545-2 HL3, RINA/DNV, microcavi 200µm G.657.A1) risolvono i loro problemi di qualità, flessibilità e tempi di consegna.
3. Call-to-action chiara e non invasiva (es. invio schede tecniche comparative o campionatura).
Rispondi con un JSON valido con i campi:
{{
  "subject": "<Oggetto email accattivante>",
  "email_body": "<Corpo email formale e strutturato in paragrafi>",
  "linkedin_message": "<Messaggio breve per LinkedIn o InMail max 120 parole>",
  "cold_call_script": "<Traccia per chiamata telefonica: apertura, 2 domande di qualificazione e gestione obiezione 'abbiamo già un fornitore'>"
}}""",
    },
    "en": {
        "email_subject_sample": "High-Performance Special Cables (Fiber & Copper) for your upcoming projects",
        "system": f"""You are the Senior International Business Development Manager for a leading European manufacturer of specialized optical fiber and copper cables.
{AZIENDA}
Draft a highly persuasive, technically credible, and professional cold outreach proposal for the Head of Procurement or Technical Director of the target company.
Respond in ENGLISH with a valid JSON containing:
{{
  "subject": "<Compelling Email Subject Line>",
  "email_body": "<Professional Cold Email Body with clear value proposition and certifications>",
  "linkedin_message": "<Direct LinkedIn / InMail message under 120 words>",
  "cold_call_script": "<Concise phone pitch: hook, 2 qualifying questions, objection handling for 'we already have a supplier'>"
}}""",
    },
    "fr": {
        "email_subject_sample": "Fourniture Câbles Spéciaux (Fibre & Cuivre) certifiés pour vos projets",
        "system": f"""Vous êtes le Directeur Commercial Export d'un fabricant européen majeur de câbles spéciaux en fibre optique et cuivre.
{AZIENDA}
Rédigez une proposition commerciale percutante et professionnelle en FRANÇAIS destinée au Directeur des Achats ou Responsable Technique de l'entreprise cible.
Répondez avec un JSON valide contenant:
{{
  "subject": "<Objet de l'email accrocheur>",
  "email_body": "<Corps de l'email professionnel et argumenté>",
  "linkedin_message": "<Message court LinkedIn / InMail>",
  "cold_call_script": "<Script téléphonique: introduction, questions clés et traitement des objections>"
}}""",
    },
    "de": {
        "email_subject_sample": "Spezialkabel (LWL & Kupfer) zertifiziert nach EN/CPR für Ihre aktuellen Projekte",
        "system": f"""Sie sind der Senior Key Account Manager International für einen führenden europäischen Hersteller von Spezialkabeln (Lichtwellenleiter & Kupfer).
{AZIENDA}
Erstellen Sie ein professionelles und überzeugendes Akquise-Schreiben auf DEUTSCH für den Einkaufsleiter oder Technischen Leiter des Zielunternehmens.
Antworten Sie mit einem gültigen JSON mit folgenden Feldern:
{{
  "subject": "<Aussagekräftige E-Mail-Betreffzeile>",
  "email_body": "<Formeller und technisch fundierter E-Mail-Text>",
  "linkedin_message": "<Kurze LinkedIn / InMail-Nachricht unter 120 Wörtern>",
  "cold_call_script": "<Telefonleitfaden: Einstieg, 2 Qualifizierungsfragen und Einwandbehandlung>"
}}""",
    },
}

_JSON_EXTRACT_RE = re.compile(r"\{.*\}", re.DOTALL)


def generate_multilingual_outreach(
    company_name: str,
    country: str = "Europa",
    sector: str = "Telecom/Provider",
    language: str = "it",
    specific_project: str = "",
    cable_focus: str = "",
) -> dict:
    """Genera bozze email, LinkedIn e script telefonico personalizzati."""
    lang = language.lower() if language.lower() in OUTREACH_PROMPTS else "it"
    prompt_cfg = OUTREACH_PROMPTS[lang]

    user_context = (
        f"AZIENDA TARGET: {company_name}\n"
        f"PAESE: {country}\n"
        f"SETTORE CORE: {sector}\n"
        f"PROGETTO O COMMESSA RILEVATA: {specific_project or 'Progetti e cantieri in corso nel mercato'}\n"
        f"GAMMA CAVI DI INTERESSE: {cable_focus or 'Fibra ottica ad alta densità G.657.A1 / Rame CPR B2ca / Cavi speciali'}\n"
    )

    if ollama_available() and company_name.strip():
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": prompt_cfg["system"]},
                        {"role": "user", "content": user_context},
                    ],
                },
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            raw_text = resp.json()["message"]["content"]
            parsed = json.loads(_JSON_EXTRACT_RE.search(raw_text).group(0))
            if "email_body" in parsed and "subject" in parsed:
                return parsed
        except Exception:
            pass

    # Fallback euristico professionale per lingua
    if lang == "en":
        return {
            "subject": f"Special Cables & Optical Fiber Supply Partnership for {company_name}",
            "email_body": (
                f"Dear Procurement and Technical Team at {company_name},\n\n"
                f"I am reaching out from our European special cables division regarding your ongoing developments in the {sector} sector across {country}.\n\n"
                f"As a specialized European manufacturer of high-performance fiber optic and copper cables, we support prime contractors and network integrators by providing certified cables (CPR B2ca-s1a,d0, EN 45545-2 HL3, RINA/DNV, and high-density 200µm micro-cables) with dependable lead times and custom production flexibility.\n\n"
                f"Given your active projects in {specific_project or 'infrastructure and system integration'}, we would welcome the opportunity to share our technical datasheets and provide a benchmark quotation for your upcoming cable lots.\n\n"
                "Would you be open to a brief 10-minute introductory call next week?\n\n"
                "Best regards,\nInternational Sales Team"
            ),
            "linkedin_message": (
                f"Hello, I noticed your key role in {company_name}'s {sector} projects in {country}. As a European manufacturer of specialized optical fiber and copper cables (CPR B2ca, EN 45545, Marine certified), we help technical teams secure high-spec cables with flexible production lead times. Happy to connect and share our latest technical catalog."
            ),
            "cold_call_script": (
                f"📞 APERTURA: 'Buongiorno, la contatto dalla divisione commerciale cavi speciali. Abbiamo visto i vostri recenti sviluppi nel settore {sector} in {country} e collaboriamo con primari contractor per la fornitura di cavi omologati.'\n"
                "❓ DOMANDA 1: 'Su quali specifiche di cavo (fibra micro, CPR B2ca, cavi rotabili/navali) riscontrate maggiori sfide di reperibilità o tempi di consegna?'\n"
                "❓ DOMANDA 2: 'Avete gare o lotti di fornitura aperti nei prossimi 60-90 giorni dove avrebbe senso valutare una quotazione comparativa diretta da fabbrica?'\n"
                "🛡️ OBIEZIONE 'Abbiamo già fornitori': 'Comprendo perfettamente; molti nostri attuali clienti lavoravano già con altri brand prima di testare la nostra flessibilità sui lotti custom e i lead time certi. Possiamo inviarle una scheda tecnica comparativa per il prossimo riordino?'"
            ),
        }
    elif lang == "fr":
        return {
            "subject": f"Partenariat Câbles Spéciaux & Fibre Optique pour les projets {company_name}",
            "email_body": (
                f"Madame, Monsieur du Département Achats et Projets de {company_name},\n\n"
                f"Je me permets de vous contacter de la part de notre division européenne de câbles spéciaux concernant vos projets récents dans le secteur {sector} en {country}.\n\n"
                f"En tant que fabricant européen de câbles à haute performance (fibre optique micro-câbles 200µm G.657.A1, câbles CPR B2ca-s1a,d0, ferroviaire EN 45545 et marine), nous accompagnons les maîtres d'œuvre et intégrateurs dans la sécurisation de leurs approvisionnements avec des délais maîtrisés.\n\n"
                f"Nous serions ravis de vous transmettre nos fiches techniques et d'étudier une cotation comparative pour vos prochains approvisionnements sur {specific_project or 'vos chantiers en cours'}.\n\n"
                "Seriez-vous disponible pour un bref échange téléphonique de 10 minutes cette semaine ?\n\n"
                "Cordialement,\nDirection Commerciale Export"
            ),
            "linkedin_message": (
                f"Bonjour, je constate votre rôle clé dans les projets {sector} de {company_name}. En tant que fabricant européen de câbles spéciaux en fibre optique et cuivre (normes CPR B2ca, EN 45545, marine), nous aidons les équipes achats à optimiser leurs approvisionnements. Au plaisir d'échanger et de vous partager nos fiches techniques."
            ),
            "cold_call_script": (
                "📞 INTRODUCTION: 'Bonjour, je vous contacte de la part de notre division câbles spéciaux suite à vos projets en cours dans le secteur ferroviaire/télécom.'\n"
                "❓ QUESTION CLÉ: 'Quels sont vos principaux besoins en câbles certifiés pour vos prochains jalons de déploiement?'\n"
                "🛡️ TRAITEMENT OBJECTION: 'Nous respectons vos accords existants; notre valeur réside dans notre réactivité sur les longueurs spécifiques et les homologations européennes directes d'usine.'"
            ),
        }
    elif lang == "de":
        return {
            "subject": f"Direktbezug Spezialkabel (LWL & Kupfer) für Ihre Projekte bei {company_name}",
            "email_body": (
                f"Sehr geehrtes Einkaufs- und Projektteam von {company_name},\n\n"
                f"ich wende mich an Sie bezüglich Ihrer aktuellen Ausbau- und Infrastrukturprojekte im Bereich {sector} in {country}.\n\n"
                f"Als europäischer Hersteller von hochwertigen Glasfaser- und Kupfer-Spezialkabeln (Mikrokabel 200µm G.657.A1, CPR Euroklasse B2ca-s1a,d0, Bahnkabel nach EN 45545-2 HL3) unterstützen wir Generalunternehmer und Netzbetreiber mit verlässlichen Lieferzeiten und flexibler Auftragsfertigung.\n\n"
                f"Für Ihre anstehenden Ausschreibungen und Bauabschnitte bei {specific_project or 'Ihren aktuellen Projekten'} möchten wir Ihnen gerne unsere technischen Datenblätter vorstellen und ein unverbindliches Vergleichsangebot unterbreiten.\n\n"
                "Wann würde Ihnen ein kurzes, 10-minütiges Telefonat in den nächsten Tagen passen?\n\n"
                "Mit freundlichen Grüßen,\nInternational Sales Team"
            ),
            "linkedin_message": (
                f"Guten Tag, ich verfolge mit Interesse Ihre Projekte im Bereich {sector} bei {company_name}. Als europäischer Hersteller von zertifizierten LWL- und Kupferkabeln (CPR B2ca, EN 45545, Marine) unterstützen wir Einkäufer mit kurzen Lieferzeiten ab Werk. Ich freue mich auf die Vernetzung."
            ),
            "cold_call_script": (
                "📞 EINSTIEG: 'Guten Tag, ich rufe von unserem Werk für LWL- und Spezialkabel an. Wir beliefern führende europäische Netzbetreiber und Bahncontractor.'\n"
                "❓ QUALIFIZIERUNG: 'Gibt es bei Ihren aktuellen Projekten Bedarf an hochdichten Mikrokabeln oder B2ca-Spezifikationen mit schnellen Lieferzeiten?'\n"
                "🛡️ EINWAND 'Wir haben bereits Rahmenverträge': 'Sehr gerne. Viele Kunden nutzen uns als zuverlässigen Zweitlieferanten für kurzfristige Sonderlängen. Darf ich Ihnen unsere Übersicht zukommen lassen?'"
            ),
        }
    else:  # Italiano
        return {
            "subject": f"Fornitura Diretta Cavi Speciali (Fibra & Rame) per i progetti {company_name}",
            "email_body": (
                f"Gentile Team Acquisti e Direzione Tecnica di {company_name},\n\n"
                f"vi contatto dalla nostra divisione cavi speciali in merito ai vostri progetti in corso nel settore {sector} in ambito {country}.\n\n"
                f"In qualità di produttori specializzati di cavi in fibra ottica e rame (microcavi 200µm G.657.A1 per minitubi, cavi CPR B2ca-s1a,d1,a1, cavi ferroviari EN 45545-2 HL3 e navali RINA/DNV), supportiamo prime contractor e installatori garantendo flessibilità produttiva, collaudi certificati e tempi di consegna certi.\n\n"
                f"In vista delle prossime forniture per {specific_project or 'i vostri cantieri e appalti in corso'}, saremmo lieti di inviarvi le nostre schede tecniche e formulare una quotazione comparativa diretta da fabbrica.\n\n"
                "Sareste disponibili per un breve colloquio conoscitivo di 10 minuti nei prossimi giorni?\n\n"
                "Cordiali saluti,\nTeam Sviluppo Commerciale"
            ),
            "linkedin_message": (
                f"Buongiorno, ho notato il vostro ruolo nello sviluppo dei progetti {sector} per {company_name}. In qualità di produttori europei di cavi speciali (Fibra micro 200µm, CPR B2ca, EN 45545, RINA), affianchiamo i responsabili acquisti con consegne flessibili e schede tecniche dirette da stabilimento. Sarei felice di collegarmi."
            ),
            "cold_call_script": (
                f"📞 APERTURA: 'Buongiorno, la contatto dal nostro stabilimento di cavi speciali in fibra e rame. Abbiamo visto i vostri cantieri attivi nel settore {sector} in {country} e riforniamo i principali installatori europei.'\n"
                "❓ DOMANDA 1: 'Sulle formazioni ad alta densità o sui cavi con normative severe (CPR B2ca / EN 45545), riscontrate difficoltà di disponibilità dai vostri canali abituali?'\n"
                "❓ DOMANDA 2: 'Avete fabbisogni aperti nelle prossime settimane su cui potreste valutare un confronto economico e tecnico diretto con il nostro ufficio vendite?'\n"
                "🛡️ GESTIONE OBIEZIONE 'Abbiamo già accordi quadro': 'Comprendo benissimo; molti dei nostri clienti ci hanno inizialmente testato su lotti specifici o per ridurre i tempi di attesa. Le lascio la nostra scheda di gamma così da averci come punto di riferimento immediato per il prossimo capitolato.'"
            ),
        }
