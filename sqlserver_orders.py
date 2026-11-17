"""Connettore SQL Server in sola lettura per Anagrafica Clienti e Storico Ordini.

Utilizza il database GP_NX_AGG (lo stesso del progetto ARGUS):
- AGG_CLIENTI_TMP (Anagrafica Clienti)
- AGG_MASTER_CLIENTE (Testate & Righe Ordini Clienti)
- AGG_PRODOTTI_TMP (Anagrafica Articoli e Materiali)
"""
import logging
from typing import Optional
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import (MATERIAL_CATEGORY_MAP, SQLSERVER_DB_URL,
                    SQLSERVER_PWD)

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """Restituisce il singleton Engine SQLAlchemy per SQL Server."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            SQLSERVER_DB_URL,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def test_connection() -> dict:
    """Verifica la raggiungibilita' del database SQL Server."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT @@VERSION AS ver, DB_NAME() AS db")).fetchone()
            return {
                "ok": True,
                "database": result[1] if result else "N/D",
                "message": "Connessione SQL Server stabilita con successo.",
            }
    except Exception as e:
        logger.error(f"Errore connessione SQL Server: {e}")
        return {
            "ok": False,
            "database": "N/D",
            "message": str(e),
        }


def fetch_raw_orders(limit: Optional[int] = None) -> pd.DataFrame:
    """Estrae lo storico ordini con anagrafica cliente e categoria materiale."""
    if not SQLSERVER_PWD:
        logger.warning("SQL Server non configurato (SQLSERVER_PWD assente): "
                       "lettura ordini saltata.")
        return pd.DataFrame()
    engine = get_engine()
    top_clause = f"TOP {int(limit)} " if limit else ""
    # Data minimization (privacy policy ERP->LLM):
    # si selezionano SOLO le colonne necessarie ai calcoli locali (MTBO,
    # periodo ordini, fascia fatturato, categorie prodotto). Le colonne
    # finanziarie sensibili presenti su AGG_MASTER_CLIENTE - costo
    # industriale, margine, sconti extra-fattura, condizioni di pagamento -
    # NON vengono lette. O.Valore serve al bucketing in Tier e non lascia
    # mai la macchina in forma puntuale.
    query = f"""
        SELECT {top_clause}
            LTRIM(RTRIM(O.cdCliente))            AS client_id,
            LTRIM(RTRIM(ISNULL(C.dsCliente, 'CLIENTE ' + O.cdCliente))) AS client_name,
            LTRIM(RTRIM(ISNULL(C.Nazione, 'IT'))) AS country,
            LTRIM(RTRIM(ISNULL(CAST(C.ITEUEX AS VARCHAR(20)), 'IT')))  AS market_area,
            LTRIM(RTRIM(O.cdOrdine))             AS order_code,
            LTRIM(RTRIM(O.cdProdotto))           AS product_code,
            LTRIM(RTRIM(ISNULL(P.cdMateriale, ''))) AS material_code,
            LTRIM(RTRIM(ISNULL(P.dsProdotto, '')))  AS product_description,
            LTRIM(RTRIM(ISNULL(O.cdUM, '')))        AS uom,
            ISNULL(O.QtaOrdinata, 0)             AS qty_ordered,
            ISNULL(O.QtaSpedita, 0)              AS qty_shipped,
            CAST(O.dtOrdine AS DATE)             AS order_date,
            CAST(O.dtConsegnaRichiesta AS DATE)  AS requested_delivery_date,
            CAST(O.dtConsegnaConfermata AS DATE) AS confirmed_delivery_date,
            ISNULL(O.Valore, 0.0)                AS amount
        FROM [AGG_MASTER_CLIENTE] O WITH (NOLOCK)
        LEFT JOIN [AGG_CLIENTI_TMP] C WITH (NOLOCK) ON C.cdCliente = O.cdCliente
        LEFT JOIN [AGG_PRODOTTI_TMP] P WITH (NOLOCK) ON P.cdProdotto = O.cdProdotto
        WHERE O.dtOrdine IS NOT NULL
        ORDER BY O.cdCliente, O.dtOrdine ASC
    """
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query(text(query), con=conn)
        
        if df.empty:
            return df

        # Mappatura categoria prodotto (Fibra Ottica, Rame, Altro)
        df["order_date"] = pd.to_datetime(df["order_date"])
        df["product_category"] = df["material_code"].astype(str).map(
            lambda c: MATERIAL_CATEGORY_MAP.get(c.strip(), "Fibra Ottica" if c.strip() == "20" else ("Rame" if c.strip() == "41" else "Altro / Accessori"))
        )
        return df
    except Exception as e:
        logger.error(f"Errore lettura ordini da SQL Server: {e}")
        return pd.DataFrame()


def fetch_clients_list() -> pd.DataFrame:
    """Estrae l'anagrafica clienti completa."""
    if not SQLSERVER_PWD:
        logger.warning("SQL Server non configurato (SQLSERVER_PWD assente): "
                       "lettura clienti saltata.")
        return pd.DataFrame()
    engine = get_engine()
    query = """
        SELECT 
            LTRIM(RTRIM(cdCliente)) AS client_id,
            LTRIM(RTRIM(dsCliente)) AS client_name,
            LTRIM(RTRIM(ISNULL(Nazione, 'IT'))) AS country,
            LTRIM(RTRIM(ISNULL(Indirizzo, ''))) AS address,
            LTRIM(RTRIM(ISNULL(CAST(ITEUEX AS VARCHAR(20)), 'IT'))) AS market_area
        FROM [AGG_CLIENTI_TMP] WITH (NOLOCK)
        ORDER BY dsCliente ASC
    """
    try:
        with engine.connect() as conn:
            return pd.read_sql_query(text(query), con=conn)
    except Exception as e:
        logger.error(f"Errore lettura clienti da SQL Server: {e}")
        return pd.DataFrame()


def fetch_client_history(client_id: str) -> pd.DataFrame:
    """Storico ordini di UN solo cliente ERP (Company Intelligence on-demand).

    Colonne: order_code, product_code, product_description, material_code,
    product_category, qty_ordered, order_date, amount.
    DataFrame vuoto se ERP non configurato / errore."""
    if not SQLSERVER_PWD or not client_id:
        return pd.DataFrame()
    engine = get_engine()
    query = """
        SELECT
            LTRIM(RTRIM(O.cdOrdine))            AS order_code,
            LTRIM(RTRIM(O.cdProdotto))          AS product_code,
            LTRIM(RTRIM(ISNULL(P.cdMateriale,''))) AS material_code,
            LTRIM(RTRIM(ISNULL(P.dsProdotto,'')))  AS product_description,
            ISNULL(O.QtaOrdinata, 0)            AS qty_ordered,
            CAST(O.dtOrdine AS DATE)            AS order_date,
            ISNULL(O.Valore, 0.0)               AS amount
        FROM [AGG_MASTER_CLIENTE] O WITH (NOLOCK)
        LEFT JOIN [AGG_PRODOTTI_TMP] P WITH (NOLOCK)
               ON P.cdProdotto = O.cdProdotto
        WHERE O.cdCliente = :cid AND O.dtOrdine IS NOT NULL
        ORDER BY O.dtOrdine DESC
    """
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query(text(query), con=conn,
                                   params={"cid": str(client_id).strip()})
        if df.empty:
            return df
        df["order_date"] = pd.to_datetime(df["order_date"])
        df["product_category"] = df["material_code"].astype(str).map(
            lambda c: MATERIAL_CATEGORY_MAP.get(c.strip(),
                                                "Altro / Accessori"))
        return df
    except Exception as e:
        logger.error(f"Errore lettura storico cliente {client_id} "
                     f"da SQL Server: {e}")
        return pd.DataFrame()
