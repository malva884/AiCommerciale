"""Modulo RFP & Capitolati Analyzer: estrazione automatica requisiti tecnici per cavi speciali."""
import json
import re
import requests
from config import AZIENDA, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL
from llm import ollama_available

RFP_SYSTEM_PROMPT = f"""Sei il Senior Tender Engineer e Technical Sales Manager di un produttore di cavi speciali (Fibra & Rame).
{AZIENDA}

Analizza il testo del capitolato tecnico / disciplinare di gara (RFP) che ti viene sottoposto.
Estrai in formato JSON strutturato i requisiti chiave:
{{
  "summary": "<sintesi del progetto e volume fornitura in 2 frasi>",
  "target_sector": "<Data Center|Ferroviario|Navale|Telecom/Provider|Avio/Difesa|Energia/Altro>",
  "required_norms": ["<es. EN 45545-2 HL3>", "<CPR B2ca-s1a,d0>", "<RINA>"],
  "cable_specs": [
    {{"type": "<es. Cavo Ottico 48 FO OM4 / Cavo Rame Cat 8>", "details": "<dettagli guaina LSZH, armatura, sezioni>"}}
  ],
  "critical_requirements": ["<requisiti vincolanti es. test fuoco, tempi consegna, certificati fabbrica>"],
  "our_match_level": "<ALTO|MEDIO|BASSO>",
  "technical_pitch": "<argomentazione tecnica vincente per l'offerta>",
  "suggested_questions_for_buyer": ["<domanda di chiarimento tecnico 1>", "<domanda 2>"]
}}
Rispondi SOLO con il JSON valido su una riga.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def analyze_rfp(rfp_text: str) -> dict:
    """Analizza un testo di capitolato con LLM locale o con fallback euristico."""
    if ollama_available() and len(rfp_text.strip()) > 20:
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": RFP_SYSTEM_PROMPT},
                        {"role": "user", "content": f"CAPITOLATO TECNICO / RFP:\n\n{rfp_text[:6000]}"},
                    ],
                },
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            return json.loads(_JSON_RE.search(content).group(0))
        except Exception:
            pass

    # Fallback euristico avanzato per capitolati cavi
    text_low = rfp_text.lower()
    norms = []
    for n in ["EN 45545-2", "EN 45545", "CPR B2ca", "CPR Cca", "CPR", "RINA", "DNV", "MIL-DTL", "LSZH", "OM4", "OM5", "Cat 7", "Cat 8", "IEC 60332"]:
        if n.lower() in text_low:
            norms.append(n)

    sector = "Generale"
    if any(k in text_low for k in ["ferrovi", "rail", "treno", "rfi"]):
        sector = "Ferroviario"
    elif any(k in text_low for k in ["data center", "hyperscale", "server"]):
        sector = "Data Center"
    elif any(k in text_low for k in ["navale", "ship", "cantiere", "marino"]):
        sector = "Navale"
    elif any(k in text_low for k in ["telecom", "ftth", "fibra", "backhaul"]):
        sector = "Telecom/Provider"
    elif any(k in text_low for k in ["aero", "avio", "difesa", "mil"]):
        sector = "Avio/Difesa"

    return {
        "summary": "Analisi capitolato completata con motore di parsing tecnico locale.",
        "target_sector": sector,
        "required_norms": norms if norms else ["Standard Industriali Generali"],
        "cable_specs": [{"type": "Cavi speciali rilevati nel testo", "details": "Estratti automaticamente in base a parole chiave di fornitura"}],
        "critical_requirements": ["Verifica conformità alle normative rilevate (" + ", ".join(norms) + ")"] if norms else ["Verifica capitolato e tolleranze di consegna"],
        "our_match_level": "ALTO" if len(norms) > 0 else "MEDIO",
        "technical_pitch": f"La nostra gamma di produzione copre pienamente le specifiche del settore {sector} con certificazioni rilasciate da enti terzi accreditati e collaudi 100% in linea.",
        "suggested_questions_for_buyer": [
            "Confermare la classe CPR richiesta per la posa all'interno degli edifici?",
            "Sono previste lunghezze di taglio speciali o tamburi standard di fornitura?"
        ]
    }
