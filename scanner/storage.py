import sqlite3
from datetime import datetime
from scanner.config import logger

DB_PATH = "data/signals/scanner_history.db"

def init_db():
    """Initialise la base de données SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table des scans (métadonnées)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT UNIQUE,
            market_regime TEXT,
            spy_price REAL,
            spy_ma200 REAL,
            universe_size INTEGER,
            eligible_count INTEGER
        )
    ''')
    
    # Table des signaux (Stocks & ETFs)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER,
            symbol TEXT,
            name TEXT,
            type TEXT, -- 'stock' or 'etf'
            rank INTEGER,
            score_global REAL,
            score_quality REAL,
            score_valuation REAL,
            score_momentum REAL,
            pe REAL,
            roe REAL,
            margin REAL,
            perf_6m REAL,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info(f"Base de données SQLite initialisée à {DB_PATH}")

def save_signals_to_db(top_stocks, top_etfs, all_data, universe_size, market_data=None):
    """Sauvegarde les signaux dans SQLite."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    scan_date = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Insérer le scan
    market_regime = market_data.get("regime", "unknown") if market_data else "unknown"
    spy_price = market_data.get("spy_price") if market_data else None
    spy_ma200 = market_data.get("spy_ma200") if market_data else None
    
    try:
        cursor.execute('''
            INSERT INTO scans (scan_date, market_regime, spy_price, spy_ma200, universe_size, eligible_count)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (scan_date, market_regime, spy_price, spy_ma200, universe_size, len(top_stocks)))
        scan_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        # Déjà un scan pour aujourd'hui, on le récupère
        cursor.execute('SELECT id FROM scans WHERE scan_date = ?', (scan_date,))
        scan_id = cursor.fetchone()[0]
        # On pourrait supprimer les anciens signaux pour ce scan_id si on veut écraser
        cursor.execute('DELETE FROM signals WHERE scan_id = ?', (scan_id,))

    # 2. Insérer les stocks
    for i, (_, row) in enumerate(top_stocks.iterrows()):
        cursor.execute('''
            INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, score_quality, score_valuation, score_momentum, pe, roe, margin, perf_6m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            scan_id, row["symbol"], row.get("name", ""), "stock", i+1,
            row["score_global"], row["score_quality"], row["score_valuation"], row["score_momentum"],
            row.get("pe"), row.get("roe"), row.get("margin"), row.get("perf_6m")
        ))
        
    # 3. Insérer les ETFs
    for i, (_, row) in enumerate(top_etfs.iterrows()):
        cursor.execute('''
            INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, score_quality, score_valuation, score_momentum, pe, roe, margin, perf_6m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            scan_id, row["symbol"], row.get("name", ""), "etf", i+1,
            row["score_global"], 0, 0, 0,
            None, None, None, row.get("perf_6m")
        ))

    conn.commit()
    conn.close()
    logger.info(f"Signaux sauvegardés dans SQLite (Scan ID: {scan_id})")

def save_signals(top_stocks, top_etfs, all_data, universe_size, market_data=None):
    """Ancien point d'entrée, maintenant redirigé vers SQLite."""
    save_signals_to_db(top_stocks, top_etfs, all_data, universe_size, market_data)
