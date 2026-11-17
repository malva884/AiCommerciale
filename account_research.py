"""Modulo Account Research & Dossier Pre-Meeting."""
import json
import re
from config import AZIENDA
from llm import generate_json_completion, is_llm_available
from privacy_masker import PrivacyMasker, scrub_text

DOSSIER_SYSTEM_PROMPT = f"""Sei il Senior Sales Intelligence Specialist per un produttore di cavi speciali (Fibra & Rame).
{AZIENDA}

Genera un Dossier Strategico Pre-Meeting per preparare il commerciale all'incontro con un'azienda prospect o cliente europeo.
Rispondi SOLO con un JSON strutturato su una riga:
{{
  "company_name": "<nome azienda>",
  "industry_positioning": "<profilo e posizionamento di mercato in 2 frasi>",
  "target_sector": "<Data Center|Ferroviario|Navale|Telecom/Provider|Avio/Difesa>",
  "key_challenges": ["<sfida 1 es. transizione sostenibilità/cavi CPR>", "<sfida 2 es. rispetto tempi commesse>"],
  "buying_signals": ["<segnale 1 es. espansione rete/nuovo cantiere>", "<segnale 2 es. revamping impianti>"],
  "recommended_stakeholders": [
    {{"role": "Head of Procurement / Procurement Manager", "focus": "Affidabilità fornitura, certificazioni e lead time"}},
    {{"role": "Chief Electrical Engineer / Technical Director", "focus": "Conformità normative CPR / EN 45545, isolamento LSZH"}}
  ],
  "value_proposition_pitch": "<discorso di apertura di 3 frasi per catturare l'interesse>",
  "tailored_outreach_email": "<bozza email di primo contatto scritta con il tono formale appropriato>"
}}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def generate_account_dossier(company_name: str, country: str = "Europa", notes: str = "",
                             provider: str | None = None) -> dict:
    """Genera il dossier account strategico per il commerciale."""
    if is_llm_available(provider) and company_name.strip():
        # Data masking: il nome azienda esce come token effimero; le note
        # utente (possono contenere email/telefoni/importi) vengono ripulite.
        masker = PrivacyMasker()
        company_tok = masker.mask_entity(company_name, "CLIENTE")
        data, used_p = generate_json_completion(
            DOSSIER_SYSTEM_PROMPT,
            f"AZIENDA TARGET: {company_tok}\n"
            f"PAESE: {country}\n"
            f"NOTE/CONTESTO: {scrub_text(notes)}\n"
            f"IMPORTANTE: nel campo company_name usa il segnaposto "
            f"{company_tok} e citalo cosi' nei testi.",
            provider=provider,
            sensitive_guard=True
        )
        if data:
            data = masker.unmask_result(data)  # re-idratazione solo locale
            data["generated_by"] = used_p
            return data

    # Fallback euristico
    return {
        "company_name": company_name,
        "industry_positioning": f"{company_name} è un operatore/contractor di rilievo attivo nel mercato ({country}).",
        "target_sector": "Infrastrutture & Cavi Speciali",
        "key_challenges": [
            "Approvvigionamento di cavi conformi a specifiche severe con ridotti tempi di consegna",
            "Gestione delle oscillazioni materie prime (rame/polimeri) nei contratti a lungo termine"
        ],
        "buying_signals": [
            "Espansione di nuovi siti produttivi o progetti infrastrutturali a livello europeo",
            "Adeguamento a normative antincendio e sicurezza più stringenti"
        ],
        "recommended_stakeholders": [
            {"role": "Responsabile Acquisti Cavi & Impianti", "focus": "Lead time certi, accordi quadro su materie prime e certificazioni"},
            {"role": "Ingegnere di Progetto / Direttore Tecnico", "focus": "Omologazioni tecniche EN/CPR/RINA e schede tecniche dettagliate"}
        ],
        "value_proposition_pitch": f"In qualità di produttori specializzati di cavi in fibra ottica e rame, supportiamo aziende come {company_name} fornendo cavi customizzati, collaudati e certificati per i più esigenti standard europei con consegne puntuali e flessibilità produttiva.",
        "tailored_outreach_email": (
            f"Gentile Team Acquisti e Progettazione di {company_name},\n\n"
            f"vi contatto da parte della nostra divisione cavi speciali in merito ai vostri progetti in corso in ambito {country}.\n"
            "Produciamo cavi in fibra ottica e rame ad alte prestazioni omologati secondo le principali normative europee (CPR, EN 45545, RINA/DNV).\n\n"
            "Saremmo lieti di inviarvi le schede tecniche e verificare insieme come ottimizzare le forniture per i vostri prossimi lotti.\n\n"
            "Cordiali saluti,\nTeam Commerciale"
        )
    }
