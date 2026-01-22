import os
import json
import sqlite3
import io
import base64
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS

# QR-Code Bibliotheken
try:
    import qrcode
    from PIL import Image
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
    print("⚠️ QR-Code Bibliotheken nicht verfügbar", flush=True)

# BIG Synchronisation Import
try:
    import big_sync
    BIG_SYNC_AVAILABLE = True
    print("✅ BIG Synchronisation verfügbar", flush=True)
except ImportError:
    BIG_SYNC_AVAILABLE = False
    print("⚠️ BIG Synchronisation nicht verfügbar", flush=True)

# Konfiguration
DB_PATH = '/app/data/spital_logistik.db'

app = Flask(__name__)
CORS(app)

def get_next_id(prefix, table, id_column):
    """Generiert nächste ID mit 4-stelliger Nummer"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {id_column} FROM {table} WHERE {id_column} LIKE ? ORDER BY {id_column} DESC LIMIT 1", (f"{prefix}%",))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        last_num = int(result[0].replace(prefix, ''))
        return f"{prefix}{str(last_num + 1).zfill(4)}"
    return f"{prefix}0001"

def get_next_behaelter_id(areal):
    """Generiert nächste Behälter-ID: ISN-000-M001-BEH001"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    prefix = f"{areal}-000-M001-BEH"
    cursor.execute("SELECT behaelter_id FROM behaelter_aktuell WHERE behaelter_id LIKE ? ORDER BY behaelter_id DESC LIMIT 1", (f"{prefix}%",))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        last_num = int(result[0].split('-')[-1].replace('BEH', ''))
        return f"{prefix}{str(last_num + 1).zfill(3)}"
    return f"{prefix}001"

def create_testdata_with_big_rooms():
    """Erstellt Testdaten unter Verwendung der tatsächlichen BIG-Räume und -Behälter"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n📦 Erstelle Testdaten mit BIG-Räumen...", flush=True)
    
    # Hole logistikrelevante Räume aus DB
    cursor.execute("""
        SELECT raum_id, raumtyp FROM raeume 
        WHERE logistikrelevant=1 AND aktiv=1 
        ORDER BY raum_id LIMIT 10
    """)
    logistik_raeume = cursor.fetchall()
    
    if not logistik_raeume:
        print("⚠️  Keine logistikrelevanten Räume gefunden - überspringe Testdaten-Erstellung", flush=True)
        conn.close()
        return
    
    print(f"✅ Verwende {len(logistik_raeume)} logistikrelevante Räume für Testdaten", flush=True)
    
    # Hole vorhandene Behälter aus BIG
    cursor.execute("SELECT behaelter_id FROM behaelter_aktuell ORDER BY behaelter_id LIMIT 15")
    big_behaelter = [row[0] for row in cursor.fetchall()]
    
    if not big_behaelter:
        print("⚠️  Keine Behälter aus BIG gefunden", flush=True)
        conn.close()
        return
    
    print(f"✅ Verwende {len(big_behaelter)} Behälter aus BIG für Testdaten", flush=True)
    
    # Erweiterte Bestellungen (BS0004-BS0008)
    bestellungen = [
        ('BS0004', 'BEST20250004', 'CarePlus', '2025-01-18'),
        ('BS0005', 'BEST20250005', 'MedSupply', '2025-01-20'),
        ('BS0006', 'BEST20250006', 'RespiCare', '2025-01-22'),
        ('BS0007', 'BEST20250007', 'Medtec', '2025-01-25'),
        ('BS0008', 'BEST20250008', 'MedSupply', '2025-01-28')
    ]
    cursor.executemany("INSERT OR IGNORE INTO bestellungen (bestell_id, bestellnummer, lieferant, bestelldatum) VALUES (?,?,?,?)", bestellungen)
    
    # Erweiterte Bestellpositionen
    positionen = [
        ('BS0004', 'VG0004', 600),
        ('BS0004', 'VG0007', 400),
        ('BS0005', 'VG0001', 800),
        ('BS0005', 'VG0006', 600),
        ('BS0006', 'VG0009', 100),
        ('BS0007', 'VG0003', 250),
        ('BS0007', 'VG0010', 400),
        ('BS0008', 'VG0001', 1200),
        ('BS0008', 'VG0005', 700)
    ]
    cursor.executemany("INSERT OR IGNORE INTO bestellpositionen (bestell_id, versorgungs_id, menge) VALUES (?,?,?)", positionen)
    
    # Befülle Behälter mit Testdaten
    befuellungen = []
    behaelter_updates = []
    
    versorgungsgueter = ['VG0001', 'VG0002', 'VG0003', 'VG0004', 'VG0005', 
                         'VG0006', 'VG0007', 'VG0008', 'VG0009', 'VG0010']
    bestellnummern = ['BEST20250001', 'BEST20250002', 'BEST20250003', 'BEST20250004', 'BEST20250005']
    
    for idx, behaelter_id in enumerate(big_behaelter[:15]):
        raum_id = logistik_raeume[idx % len(logistik_raeume)][0]
        versorgungs_id = versorgungsgueter[idx % len(versorgungsgueter)]
        bestellnummer = bestellnummern[idx % len(bestellnummern)]
        menge = 50 + (idx * 10)
        
        befuellungen.append((
            'AL0001', behaelter_id, bestellnummer,
            versorgungs_id, menge, datetime.now().isoformat()
        ))
        
        behaelter_updates.append((
            raum_id, versorgungs_id, menge,
            datetime.now().isoformat(), behaelter_id
        ))
    
    cursor.executemany("""
        INSERT OR IGNORE INTO befuellung 
        (nutzer_id, behaelter_id, bestellnummer, versorgungs_id, menge, timestamp)
        VALUES (?,?,?,?,?,?)
    """, befuellungen)
    
    cursor.executemany("""
        UPDATE behaelter_aktuell 
        SET raum_id=?, versorgungs_id=?, aktueller_bestand=?, letzte_aktion=?
        WHERE behaelter_id=?
    """, behaelter_updates)
    
    # Minimalmengen für Stationslogistik-Räume
    minimalmengen = []
    for raum_id, raumtyp in logistik_raeume[:5]:
        if 'logistik' in raumtyp.lower():
            for versorgungs_id in ['VG0001', 'VG0002', 'VG0004', 'VG0007']:
                minimalmengen.append((raum_id, versorgungs_id, 30))
    
    cursor.executemany("""
        INSERT OR IGNORE INTO minimalmengen (raum_id, versorgungs_id, minimalmenge)
        VALUES (?,?,?)
    """, minimalmengen)
    
    conn.commit()
    conn.close()
    
    print(f"✅ {len(befuellungen)} Befüllungen erstellt", flush=True)
    print(f"✅ {len(behaelter_updates)} Behälter aktualisiert", flush=True)
    print(f"✅ {len(minimalmengen)} Minimalmengen erstellt", flush=True)

def init_database():
    """Initialisiert die Datenbank mit BIG-Daten und erweiterten Test-Daten"""
    os.makedirs('/app/data', exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabellen erstellen
    cursor.execute("""CREATE TABLE IF NOT EXISTS nutzer (
        nutzer_id TEXT PRIMARY KEY,
        funktion TEXT,
        vorname TEXT,
        nachname TEXT,
        geschlecht TEXT,
        email TEXT,
        passwort TEXT DEFAULT 'password123',
        aktiv INTEGER DEFAULT 1
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS versorgungsgueter (
        versorgungs_id TEXT PRIMARY KEY,
        name TEXT,
        hersteller TEXT,
        einheit TEXT DEFAULT 'Stück',
        aktiv INTEGER DEFAULT 1
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS bestellungen (
        bestell_id TEXT PRIMARY KEY,
        bestellnummer TEXT UNIQUE,
        lieferant TEXT,
        bestelldatum DATE,
        aktiv INTEGER DEFAULT 1
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS bestellpositionen (
        position_id INTEGER PRIMARY KEY AUTOINCREMENT,
        bestell_id TEXT,
        versorgungs_id TEXT,
        menge INTEGER
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS behaelter_aktuell (
        behaelter_id TEXT PRIMARY KEY,
        raum_id TEXT,
        versorgungs_id TEXT,
        aktueller_bestand INTEGER DEFAULT 0,
        letzte_aktion TIMESTAMP,
        big_instance_id INTEGER UNIQUE
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS raeume (
        raum_id TEXT PRIMARY KEY,
        bezeichnung TEXT,
        raumtyp TEXT,
        logistikrelevant INTEGER DEFAULT 1,
        aktiv INTEGER DEFAULT 1,
        big_instance_id INTEGER UNIQUE
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS minimalmengen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raum_id TEXT,
        versorgungs_id TEXT,
        minimalmenge INTEGER,
        UNIQUE(raum_id, versorgungs_id)
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS befuellung (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nutzer_id TEXT,
        behaelter_id TEXT,
        bestellnummer TEXT,
        versorgungs_id TEXT,
        menge INTEGER,
        timestamp TEXT,
        FOREIGN KEY(nutzer_id) REFERENCES nutzer(nutzer_id),
        FOREIGN KEY(behaelter_id) REFERENCES behaelter_aktuell(behaelter_id),
        FOREIGN KEY(versorgungs_id) REFERENCES versorgungsgueter(versorgungs_id)
    )""")
    
    conn.commit()
    
    # Prüfe ob Daten bereits existieren
    cursor.execute("SELECT COUNT(*) FROM nutzer")
    if cursor.fetchone()[0] == 0:
        print("📝 Initialisiere Datenbank...", flush=True)
        
        # === 1. INITIAL IMPORT VON BIG (Räume & Behälter) ===
        if BIG_SYNC_AVAILABLE:
            big_sync.initial_import_from_big()
        else:
            print("⚠️  BIG Sync nicht verfügbar", flush=True)
        
        # === 2. BASIS-TESTDATEN (Nutzer, Güter, Basis-Bestellungen) ===
        print("\n📝 Erstelle Basis-Testdaten...", flush=True)
        
        # Nutzer
        nutzer = [
            ('AL0001', 'Areallogistiker', 'Hans', 'Müller', 'Männlich', 'hans@spital.ch', 'pass123'),
            ('AL0002', 'Areallogistiker', 'Peter', 'Huber', 'Männlich', 'peter@spital.ch', 'pass123'),
            ('SL0001', 'Stationslogistiker', 'Anna', 'Schmidt', 'Weiblich', 'anna@spital.ch', 'pass123'),
            ('SL0002', 'Stationslogistiker', 'Sophie', 'Meier', 'Weiblich', 'sophie@spital.ch', 'pass123'),
            ('PF0001', 'Pflegefachperson', 'Maria', 'Weber', 'Weiblich', 'maria@spital.ch', 'pass123'),
            ('PF0002', 'Pflegefachperson', 'Lisa', 'Keller', 'Weiblich', 'lisa@spital.ch', 'pass123'),
            ('LP0001', 'Logistikplaner', 'Thomas', 'Steiner', 'Männlich', 'thomas@spital.ch', 'admin123')
        ]
        cursor.executemany("INSERT INTO nutzer VALUES (?,?,?,?,?,?,?,1)", nutzer)
        
        # Versorgungsgüter
        gueter = [
            ('VG0001', 'Einmalhandschuhe Latex Gr. M', 'MedSupply', 'Stück'),
            ('VG0002', 'Desinfektionsmittel 500ml', 'CleanCare', 'Stück'),
            ('VG0003', 'Infusionsset Standard', 'Medtec', 'Stück'),
            ('VG0004', 'Wundverband steril 10x10cm', 'CarePlus', 'Packung'),
            ('VG0005', 'Spritzen 10ml', 'MedSupply', 'Packung'),
            ('VG0006', 'Kanülen 21G', 'MedSupply', 'Packung'),
            ('VG0007', 'Kompressen steril 10x10cm', 'CarePlus', 'Packung'),
            ('VG0008', 'Pflaster wasserfest', 'CarePlus', 'Rolle'),
            ('VG0009', 'Beatmungsmasken', 'RespiCare', 'Stück'),
            ('VG0010', 'Infusionslösung NaCl 0.9%', 'Medtec', 'Stück')
        ]
        cursor.executemany("INSERT INTO versorgungsgueter VALUES (?,?,?,?,1)", gueter)
        
        # Basis-Bestellungen (die ersten 3)
        bestellungen = [
            ('BS0001', 'BEST20250001', 'MedSupply', '2025-01-15'),
            ('BS0002', 'BEST20250002', 'CleanCare', '2025-01-16'),
            ('BS0003', 'BEST20250003', 'Medtec', '2025-01-17'),
        ]
        cursor.executemany("INSERT INTO bestellungen (bestell_id, bestellnummer, lieferant, bestelldatum) VALUES (?,?,?,?)", bestellungen)
        
        # Basis-Bestellpositionen
        positionen = [
            ('BS0001', 'VG0001', 1000),
            ('BS0001', 'VG0005', 500),
            ('BS0002', 'VG0002', 200),
            ('BS0003', 'VG0003', 300),
        ]
        cursor.executemany("INSERT INTO bestellpositionen (bestell_id, versorgungs_id, menge) VALUES (?,?,?)", positionen)
        
        conn.commit()
        print("✅ Basis-Testdaten erstellt", flush=True)
        
        # === 3. VERKNÜPFE TESTDATEN MIT BIG-RÄUMEN/BEHÄLTERN ===
        create_testdata_with_big_rooms()
        
        print("✓ Datenbank vollständig initialisiert", flush=True)
    
    conn.close()
    
    # === 4. STARTE BIG BACKGROUND-SYNC ===
    if BIG_SYNC_AVAILABLE:
        big_sync.start_background_sync()

# ===== API ROUTES =====

# Login
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nutzer WHERE nutzer_id=? AND passwort=? AND aktiv=1",
                  (data.get('nutzer_id', '').upper(), data.get('passwort', '')))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        user_dict = dict(user)
        return jsonify({"success": True, "user": user_dict})
    return jsonify({"success": False}), 401

# Areallogistiklager
@app.route('/api/areallogistiklager', methods=['GET'])
def get_areallogistiklager():
    """Gibt NUR Areallogistiklager zurück"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT raum_id, bezeichnung FROM raeume WHERE raumtyp = 'Areallogistik' AND logistikrelevant=1 AND aktiv=1 ORDER BY raum_id")
    lager = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(lager)

# Übersicht
@app.route('/api/admin/uebersicht', methods=['GET'])
def get_uebersicht():
    """Übersicht aller Räume gruppiert nach Raumtyp mit Behältern"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT raum_id, bezeichnung, raumtyp
        FROM raeume 
        WHERE logistikrelevant=1 AND aktiv=1
        ORDER BY raumtyp, bezeichnung
    """)
    raeume = [dict(row) for row in cursor.fetchall()]
    
    for raum in raeume:
        cursor.execute("""
            SELECT 
                b.behaelter_id,
                b.versorgungs_id,
                v.name as versorgungsgut_name,
                b.aktueller_bestand,
                m.minimalmenge,
                bf.bestellnummer
            FROM behaelter_aktuell b
            LEFT JOIN versorgungsgueter v ON b.versorgungs_id = v.versorgungs_id
            LEFT JOIN minimalmengen m ON m.raum_id = ? AND m.versorgungs_id = b.versorgungs_id
            LEFT JOIN (
                SELECT behaelter_id, bestellnummer, timestamp
                FROM befuellung
                WHERE (behaelter_id, timestamp) IN (
                    SELECT behaelter_id, MAX(timestamp)
                    FROM befuellung
                    GROUP BY behaelter_id
                )
            ) bf ON b.behaelter_id = bf.behaelter_id
            WHERE b.raum_id = ? AND b.aktueller_bestand > 0
            ORDER BY v.name
        """, (raum['raum_id'], raum['raum_id']))
        raum['behaelter'] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    # Gruppiere nach Raumtyp
    grouped = {}
    for raum in raeume:
        raumtyp = raum['raumtyp'] or 'Ohne Zuordnung'
        if raumtyp not in grouped:
            grouped[raumtyp] = []
        grouped[raumtyp].append(raum)
    
    return jsonify(grouped)

@app.route('/api/admin/raum/<raum_id>/detail', methods=['GET'])
def get_raum_detail(raum_id):
    """Detail-Ansicht eines Raums"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM raeume WHERE raum_id=?", (raum_id,))
    raum = dict(cursor.fetchone())
    
    cursor.execute("""
        SELECT 
            v.versorgungs_id,
            v.name as versorgungsgut_name,
            v.einheit,
            SUM(b.aktueller_bestand) as gesamt_bestand,
            GROUP_CONCAT(b.behaelter_id || ':' || b.aktueller_bestand) as behaelter_details,
            m.minimalmenge
        FROM versorgungsgueter v
        LEFT JOIN behaelter_aktuell b ON v.versorgungs_id = b.versorgungs_id AND b.raum_id = ?
        LEFT JOIN minimalmengen m ON m.raum_id = ? AND m.versorgungs_id = v.versorgungs_id
        WHERE b.aktueller_bestand > 0
        GROUP BY v.versorgungs_id
        ORDER BY v.name
    """, (raum_id, raum_id))
    
    gueter = []
    for row in cursor.fetchall():
        item = dict(row)
        behaelter_list = []
        if item['behaelter_details']:
            for beh in item['behaelter_details'].split(','):
                beh_id, menge = beh.split(':')
                behaelter_list.append({'behaelter_id': beh_id, 'menge': int(menge)})
        item['behaelter'] = behaelter_list
        gueter.append(item)
    
    conn.close()
    return jsonify({'raum': raum, 'gueter': gueter})

# Räume
@app.route('/api/admin/raeume', methods=['GET'])
def get_raeume():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM raeume WHERE aktiv=1 ORDER BY raum_id")
    raeume = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(raeume)

@app.route('/api/admin/raeume/<raum_id>/logistikrelevant', methods=['PUT'])
def update_logistikrelevant(raum_id):
    """Update Logistikrelevant-Status"""
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    logistikrelevant = data['logistikrelevant']
    cursor.execute("UPDATE raeume SET logistikrelevant=? WHERE raum_id=?",
                  (logistikrelevant, raum_id))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True})


# Nutzer
@app.route('/api/admin/nutzer', methods=['GET'])
def get_nutzer():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nutzer WHERE aktiv=1 ORDER BY nutzer_id")
    nutzer = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(nutzer)

@app.route('/api/admin/nutzer', methods=['POST'])
def add_nutzer():
    data = request.get_json()
    nutzer_id = get_next_id(data['funktion'][:2].upper(), 'nutzer', 'nutzer_id')
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO nutzer 
        (nutzer_id, funktion, vorname, nachname, geschlecht, email, passwort, aktiv)
        VALUES (?,?,?,?,?,?,?,1)""",
        (nutzer_id, data['funktion'], data['vorname'], data['nachname'],
         data['geschlecht'], data['email'], data.get('passwort', 'pass123')))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "nutzer_id": nutzer_id})

@app.route('/api/admin/nutzer/<nutzer_id>', methods=['PUT'])
def update_nutzer(nutzer_id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""UPDATE nutzer SET 
            funktion=?, vorname=?, nachname=?, geschlecht=?, email=?, passwort=?
            WHERE nutzer_id=?""",
            (data['funktion'], data['vorname'], data['nachname'],
             data['geschlecht'], data['email'], data.get('passwort', 'password123'),
             nutzer_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/admin/nutzer/<nutzer_id>', methods=['DELETE'])
def delete_nutzer(nutzer_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM nutzer WHERE nutzer_id=?", (nutzer_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

# Versorgungsgüter
@app.route('/api/admin/versorgungsgueter', methods=['GET'])
def get_versorgungsgueter():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM versorgungsgueter WHERE aktiv=1 ORDER BY versorgungs_id")
    gueter = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(gueter)

@app.route('/api/admin/versorgungsgueter', methods=['POST'])
def add_versorgungsgut():
    data = request.get_json()
    versorgungs_id = get_next_id('VG', 'versorgungsgueter', 'versorgungs_id')
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO versorgungsgueter 
        (versorgungs_id, name, hersteller, einheit, aktiv)
        VALUES (?,?,?,?,1)""",
        (versorgungs_id, data['name'], data['hersteller'], data.get('einheit', 'Stück')))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "versorgungs_id": versorgungs_id})

@app.route('/api/admin/versorgungsgueter/<versorgungs_id>', methods=['PUT'])
def update_versorgungsgut(versorgungs_id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""UPDATE versorgungsgueter SET 
            name=?, hersteller=?, einheit=?
            WHERE versorgungs_id=?""",
            (data['name'], data['hersteller'], data.get('einheit', 'Stück'), versorgungs_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/admin/versorgungsgueter/<versorgungs_id>', methods=['DELETE'])
def delete_versorgungsgut(versorgungs_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM versorgungsgueter WHERE versorgungs_id=?", (versorgungs_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

# Bestellungen
@app.route('/api/admin/bestellungen', methods=['GET', 'POST'])
def bestellungen_api():
    if request.method == 'GET':
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.*, 
                   COUNT(bp.position_id) as anzahl_positionen,
                   SUM(bp.menge) as total_menge
            FROM bestellungen b
            LEFT JOIN bestellpositionen bp ON b.bestell_id = bp.bestell_id
            WHERE b.aktiv=1
            GROUP BY b.bestell_id
            ORDER BY b.bestelldatum DESC
        """)
        bestellungen = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(bestellungen)
    
    elif request.method == 'POST':
        data = request.json
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        bestell_id = get_next_id('BS', 'bestellungen', 'bestell_id')
        
        try:
            cursor.execute("""
                INSERT INTO bestellungen (bestell_id, bestellnummer, lieferant, bestelldatum)
                VALUES (?, ?, ?, ?)
            """, (bestell_id, data['bestellnummer'], data['lieferant'], data['bestelldatum']))
            
            if 'positionen' in data and data['positionen']:
                for pos in data['positionen']:
                    cursor.execute("""
                        INSERT INTO bestellpositionen (bestell_id, versorgungs_id, menge)
                        VALUES (?, ?, ?)
                    """, (bestell_id, pos['versorgungs_id'], pos['menge']))
            
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'bestell_id': bestell_id})
        except Exception as e:
            conn.rollback()
            conn.close()
            return jsonify({'error': str(e)}), 400

@app.route('/api/admin/bestellung/<bestell_id>', methods=['GET'])
def get_bestellung_detail(bestell_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM bestellungen WHERE bestell_id=?", (bestell_id,))
    bestellung = dict(cursor.fetchone())
    
    cursor.execute("""
        SELECT bp.*, v.name as versorgungs_name
        FROM bestellpositionen bp
        LEFT JOIN versorgungsgueter v ON bp.versorgungs_id = v.versorgungs_id
        WHERE bp.bestell_id=?
    """, (bestell_id,))
    positionen = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jsonify({
        "bestellung": bestellung,
        "positionen": positionen
    })

@app.route('/api/admin/bestellungen/<bestell_id>', methods=['PUT'])
def update_bestellung(bestell_id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""UPDATE bestellungen SET 
            lieferant=?, bestelldatum=?
            WHERE bestell_id=?""",
            (data['lieferant'], data['bestelldatum'], bestell_id))
        
        cursor.execute("DELETE FROM bestellpositionen WHERE bestell_id=?", (bestell_id,))
        
        if 'positionen' in data and data['positionen']:
            for pos in data['positionen']:
                cursor.execute("""INSERT INTO bestellpositionen 
                    (bestell_id, versorgungs_id, menge) VALUES (?,?,?)""",
                    (bestell_id, pos['versorgungs_id'], pos['menge']))
        
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/admin/bestellungen/<bestell_id>', methods=['DELETE'])
def delete_bestellung(bestell_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM bestellpositionen WHERE bestell_id=?", (bestell_id,))
        cursor.execute("DELETE FROM bestellungen WHERE bestell_id=?", (bestell_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

# Behälter
@app.route('/api/admin/behaelter', methods=['GET'])
def get_behaelter():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, r.bezeichnung as raum_name, v.name as versorgungs_name
        FROM behaelter_aktuell b
        LEFT JOIN raeume r ON b.raum_id = r.raum_id
        LEFT JOIN versorgungsgueter v ON b.versorgungs_id = v.versorgungs_id
        ORDER BY b.behaelter_id
    """)
    behaelter = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(behaelter)

@app.route('/api/behaelter/<behaelter_id>/validate', methods=['GET'])
def validate_behaelter(behaelter_id):
    """Prüft ob Behälter in DB existiert"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM behaelter_aktuell WHERE behaelter_id=?", (behaelter_id,))
    exists = cursor.fetchone()[0] > 0
    conn.close()
    return jsonify({"exists": exists, "behaelter_id": behaelter_id})

@app.route('/api/admin/behaelter', methods=['POST'])
def add_behaelter():
    """Erstellt neuen Behälter - synchronisiert SOFORT mit BIG"""
    data = request.get_json()
    areal = data['behaelter_id'][:3]
    behaelter_id = get_next_behaelter_id(areal)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO behaelter_aktuell 
        (behaelter_id, raum_id, versorgungs_id, aktueller_bestand, letzte_aktion)
        VALUES (?,NULL,NULL,0,?)""",
        (behaelter_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    # SOFORTIGE SYNCHRONISATION MIT BIG
    if BIG_SYNC_AVAILABLE:
        big_sync.sync_new_container_to_big(behaelter_id)
    
    return jsonify({"success": True, "behaelter_id": behaelter_id})

@app.route('/api/admin/behaelter/<behaelter_id>', methods=['DELETE'])
def delete_behaelter(behaelter_id):
    """Löscht Behälter - synchronisiert SOFORT mit BIG"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM behaelter_aktuell WHERE behaelter_id=?", (behaelter_id,))
        conn.commit()
        conn.close()
        
        # SOFORTIGE SYNCHRONISATION MIT BIG
        if BIG_SYNC_AVAILABLE:
            big_sync.sync_deleted_container_to_big(behaelter_id)
        
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

# Minimalmengen
@app.route('/api/admin/minimalmengen', methods=['GET'])
def get_minimalmengen():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            m.*,
            r.bezeichnung as raum_bezeichnung,
            v.name as versorgungsgut_name,
            v.einheit
        FROM minimalmengen m
        LEFT JOIN raeume r ON m.raum_id = r.raum_id
        LEFT JOIN versorgungsgueter v ON m.versorgungs_id = v.versorgungs_id
        ORDER BY r.bezeichnung, v.name
    """)
    minimalmengen = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(minimalmengen)

@app.route('/api/admin/minimalmengen', methods=['POST'])
def add_minimalmenge():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""INSERT INTO minimalmengen 
            (raum_id, versorgungs_id, minimalmenge)
            VALUES (?,?,?)""",
            (data['raum_id'], data['versorgungs_id'], data['minimalmenge']))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"success": False, "error": "Kombination existiert bereits"}), 400

@app.route('/api/admin/minimalmengen/<int:id>', methods=['PUT'])
def update_minimalmenge(id):
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""UPDATE minimalmengen SET 
            raum_id=?, versorgungs_id=?, minimalmenge=?
            WHERE id=?""",
            (data['raum_id'], data['versorgungs_id'], data['minimalmenge'], id))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/admin/minimalmengen/<int:id>', methods=['DELETE'])
def delete_minimalmenge(id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM minimalmengen WHERE id=?", (id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400


# QR-Code Generation
@app.route('/api/admin/qrcode/<typ>/<path:code>')
def generate_qr(typ, code):
    """Generiert QR-Code als Base64 Bild"""
    if not QR_AVAILABLE:
        return jsonify({"error": "QR-Code Bibliothek nicht verfügbar"}), 500
    
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(code)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        if hasattr(img, 'convert'):
            img = img.convert('RGB')
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        print(f"✓ QR-Code generiert für {typ}: {code}", flush=True)
        
        return jsonify({"image": f"data:image/png;base64,{img_base64}"})
        
    except Exception as e:
        print(f"❌ QR-Code Fehler: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

# Mobile App API Endpoints
@app.route('/api/befuellung', methods=['POST'])
def api_befuellung():
    """API Endpoint für Befüllung"""
    data = request.json
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""INSERT INTO befuellung 
            (nutzer_id, behaelter_id, bestellnummer, versorgungs_id, menge, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (data["nutzer_id"], data["behaelter_id"], data["bestellnummer"],
             data["versorgungs_id"], int(data["menge"]), data["timestamp"]))
        
        raum_id = data.get("raum_id")
        cursor.execute("""INSERT OR REPLACE INTO behaelter_aktuell 
            (behaelter_id, versorgungs_id, raum_id, aktueller_bestand, letzte_aktion)
            VALUES (?, ?, ?, ?, ?)""",
            (data["behaelter_id"], data["versorgungs_id"], raum_id,
             int(data["menge"]), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        print(f"✓ Befuellung gespeichert: {data['behaelter_id']} → {raum_id}", flush=True)
        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ Fehler bei Befuellung: {e}", flush=True)
        return jsonify({'error': str(e)}), 400

@app.route('/api/bewegung', methods=['POST'])
def api_bewegung():
    """API Endpoint für Bewegung"""
    data = request.json
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""UPDATE behaelter_aktuell 
            SET raum_id=?, letzte_aktion=? 
            WHERE behaelter_id=?""",
            (data["raum_id"], datetime.now().isoformat(), data["behaelter_id"]))
        
        conn.commit()
        conn.close()
        
        print(f"✓ Bewegung gespeichert: {data['behaelter_id']} → {data['raum_id']}", flush=True)
        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ Fehler bei Bewegung: {e}", flush=True)
        return jsonify({'error': str(e)}), 400

@app.route('/api/entnahme', methods=['POST'])
def api_entnahme():
    """API Endpoint für Entnahme"""
    data = request.json
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""UPDATE behaelter_aktuell 
            SET aktueller_bestand = aktueller_bestand - ?, letzte_aktion=? 
            WHERE behaelter_id=?""",
            (int(data["menge"]), datetime.now().isoformat(), data["behaelter_id"]))
        
        conn.commit()
        conn.close()
        
        print(f"✓ Entnahme gespeichert: {data['behaelter_id']} -{data['menge']}", flush=True)
        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ Fehler bei Entnahme: {e}", flush=True)
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    print("🚀 Backend startet...", flush=True)
    init_database()
    print("🌐 Flask startet...", flush=True)
    app.run(host='0.0.0.0', port=5000)
