"""Layer di Data Masking e Anonimizzazione per chiamate LLM cloud (Gemini).

Dati sensibili ERP/CRM non devono mai comparire nei payload inviati a Google.

Flusso:  Mask -> LLM (cloud) -> Unmask (locale)
----------------------------------------------
1. Per ogni richiesta si istanzia un ``PrivacyMasker``: il vault (token ->
   valore reale) vive solo in RAM per la durata della chiamata e viene
   distrutto dal garbage collector. Mai persistito su disco/SQLite.
2. I prompt usano token effimeri (``[CLIENTE_01]``, ``[REFERENTE_01]``),
   fasce di fatturato (Tier A/B/C), famiglie tecniche al posto degli SKU
   interni e date quantizzate ("14 mesi fa") al posto delle date esatte.
3. ``unmask()`` / ``unmask_result()`` re-idratano la risposta prima della
   visualizzazione in dashboard.

``find_sensitive_patterns()`` implementa il guardrail usato da ``llm.py``
per bloccare prompt che contengano P.IVA, importi esatti in valuta o
indirizzi email prima di una chiamata cloud.
"""
import re
from datetime import date, datetime

from config import REVENUE_TIERS, SKU_FAMILY_FALLBACK, SKU_FAMILY_MAP

# ---------------------------------------------------------------------------
# Guardrail: pattern di dati sensibili vietati nei prompt verso API cloud
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: dict[str, re.Pattern] = {
    # P.IVA / codice fiscale / VAT number (con contesto o prefisso nazione)
    "vat": re.compile(
        r"(?:P\.?\s?I\.?\s?V\.?\s?A\.?|VAT|C\.?\s?F\.?|partita\s+iva"
        r"|codice\s+fiscale)[\s:.\-]*[A-Z]{0,2}\s?\d{8,16}"
        r"|\b[A-Z]{2}\d{11}\b",
        re.IGNORECASE),
    # Importi esatti in valuta: "€ 12.500", "12.500,00 EUR", "EUR 9000"
    "currency_amount": re.compile(
        r"[€$£]\s?\d[\d.,]*"
        r"|\b(?:EUR|euro|USD|GBP)\s?\d[\d.,]*"
        r"|\b\d[\d.,]{2,}\s?(?:EUR|euro|USD|GBP)\b",
        re.IGNORECASE),
    # Indirizzi email (qualsiasi dominio: aziende clienti o referenti)
    "email": re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # IBAN / coordinate bancarie
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    # Telefono in formato internazionale
    "phone": re.compile(r"\+(?:\d[\s().-]*){9,14}\d"),
}


def find_sensitive_patterns(text: str) -> list[str]:
    """Ritorna la lista dei tipi di dato sensibile rilevati nel testo.

    Lista vuota = prompt pulito, inviabile a API cloud.
    """
    if not text:
        return []
    return [name for name, pat in _SENSITIVE_PATTERNS.items()
            if pat.search(text)]


def scrub_text(text: str, replacement: str = "[DATO_RIMOSSO]") -> str:
    """Rimozione irreversibile: sostituisce i pattern sensibili dal testo
    (es. contesto scraped da siti web) prima di includerlo in un prompt."""
    if not text:
        return text or ""
    out = text
    for pat in _SENSITIVE_PATTERNS.values():
        out = pat.sub(replacement, out)
    return out


class PrivacyMasker:
    """Vault effimero in RAM che associa token anonimi a entita' reali.

    Istanziare un masker per ogni richiesta/sessione di analisi: la mappa
    non viene mai serializzata e muore con l'oggetto.
    """

    def __init__(self):
        self._vault: dict[str, str] = {}      # token -> valore reale
        self._counters: dict[str, int] = {}   # kind -> progressivo

    # -- tokenizzazione entita' ---------------------------------------------

    def mask_entity(self, value: str | None, kind: str = "CLIENTE") -> str:
        """Registra un'entita' sensibile e restituisce il suo token stabile.

        Chiamate ripetute sullo stesso valore restituiscono lo stesso token.
        kind: es. CLIENTE, REFERENTE, REFERENTE_ACQUISTI.
        """
        value = (value or "").strip()
        if not value:
            return ""
        for token, real in self._vault.items():
            if real == value:
                return token
        self._counters[kind] = self._counters.get(kind, 0) + 1
        token = f"[{kind}_{self._counters[kind]:02d}]"
        self._vault[token] = value
        return token

    def mask_text(self, text: str) -> str:
        """Sostituisce nel testo tutte le entita' note del vault coi token.

        Match sul valore piu' lungo prima, cosi' le sovrapposizioni
        (es. 'Alstom' dentro 'Alstom Ferroviaria S.p.A.') non rompono.
        """
        if not text:
            return text or ""
        out = text
        for token, real in sorted(self._vault.items(),
                                  key=lambda kv: len(kv[1]), reverse=True):
            out = out.replace(real, token)
        return out

    # -- re-idratazione ------------------------------------------------------

    def unmask(self, text: str) -> str:
        """Reidrata la risposta LLM: token -> valori reali (solo locale)."""
        if not text:
            return text or ""
        out = text
        for token, real in self._vault.items():
            out = out.replace(token, real)
        return out

    def unmask_result(self, obj):
        """Applica ``unmask`` ricorsivamente a str, dict e list."""
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, dict):
            return {k: self.unmask_result(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.unmask_result(v) for v in obj]
        return obj

    @property
    def vault(self) -> dict:
        """Copia della mappa token -> valore reale (debug/metriche)."""
        return dict(self._vault)

    # -- trasformazioni deterministiche --------------------------------------

    @staticmethod
    def revenue_tier(amount: float | int | None) -> str:
        """Bucketing del fatturato in fasce REVENUE_TIERS (config.py)."""
        amount = float(amount or 0.0)
        for threshold, label in REVENUE_TIERS:
            if amount >= threshold:
                return label
        return REVENUE_TIERS[-1][1]

    @staticmethod
    def months_ago(days: int | float | None) -> str:
        """Quantizza una distanza in giorni in mesi relativi.

        'Ultimo ordine: 14 mesi fa' invece della data puntuale.
        """
        if days is None:
            return "data non disponibile"
        months = int(round(float(days) / 30.44))
        if months <= 0:
            return "meno di 1 mese fa"
        return f"{months} mesi fa"

    @staticmethod
    def mtbo_label(mtbo_days: float | None) -> str:
        """MTBO in giorni -> ciclo espresso in mesi ('~4 mesi')."""
        if mtbo_days is None:
            return "ciclo non misurabile (ordine singolo)"
        months = float(mtbo_days) / 30.44
        return f"~{max(1, int(round(months)))} mesi"

    @staticmethod
    def sku_family(product_code: str | None,
                   description: str | None = None) -> str:
        """Codice articolo interno -> macro-famiglia tecnica (SKU_FAMILY_MAP).

        I prefissi piu' lunghi vincono ('FO-ARM' prima di 'FO'); se il codice
        non matcha, si tenta un riconoscimento lessicale sulla descrizione.
        """
        code = (product_code or "").strip().upper()
        for prefix in sorted(SKU_FAMILY_MAP, key=len, reverse=True):
            if code.startswith(prefix):
                return SKU_FAMILY_MAP[prefix]
        desc = (description or "").upper()
        if desc:
            if any(k in desc for k in ("FIBRA", "OPTIC", "F.O", "FO ")):
                return "Cavi in fibra ottica"
            if any(k in desc for k in ("RAME", "COPPER", "CAT.")):
                return "Cavi in rame"
        return SKU_FAMILY_FALLBACK


def relative_order_date(order_date) -> str:
    """Data ordine -> espressione relativa ('14 mesi fa')."""
    if not order_date:
        return "data non disponibile"
    try:
        if isinstance(order_date, str):
            dt = datetime.fromisoformat(order_date[:10]).date()
        elif isinstance(order_date, datetime):
            dt = order_date.date()
        elif isinstance(order_date, date):
            dt = order_date
        else:
            dt = datetime.fromisoformat(str(order_date)[:10]).date()
        return PrivacyMasker.months_ago((date.today() - dt).days)
    except (ValueError, TypeError):
        return "data non disponibile"
