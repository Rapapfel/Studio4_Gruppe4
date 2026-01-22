#!/usr/bin/env python3
"""
BIG Synchronisation für Spitallogistik
- Synchronisiert Räume und Behälter zwischen BIG und lokaler DB
- Initial-Import beim DB-Setup
- Kontinuierliche Sync im Minutentakt (BIG → Logistik)
- Sofortige Sync bei Änderungen (Logistik → BIG)
"""

import requests
import sqlite3
import time
import threading
from datetime import datetime

# ===== BIG KONFIGURATION =====
BIG_INSTANCE = "hslu"
BIG_CLIENT_ID = "d9549950-1a9b-4318-97c6-d797e748cdb1"
BIG_CLIENT_SECRET = "Os7eOdE3jlhevnfLvBHIOzMywIPqGfp6vAnP7NYH"
BIG_PROJECT_ID = "107"

BIG_BASE_URL = f"https://{BIG_INSTANCE}.build-big.ch"
BIG_TOKEN_URL = f"{BIG_BASE_URL}/auth/login/token"
BIG_API_URL = f"{BIG_BASE_URL}/api/entity"

# Cache für Element-IDs
RAUM_ELEMENT_ID = None
BEHAELTER_ELEMENT_ID = None
ACCESS_TOKEN = None
TOKEN_EXPIRY = None

DB_PATH = '/app/data/spital_logistik.db'

# ===== AUTHENTIFIZIERUNG =====
def get_access_token():
    """Holt neuen Access Token von BIG"""
    global ACCESS_TOKEN, TOKEN_EXPIRY
    
    try:
        print("🔑 BIG Login...", flush=True)
        data = {
            'client_id': BIG_CLIENT_ID,
            'client_secret': BIG_CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        response = requests.post(BIG_TOKEN_URL, data=data, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        ACCESS_TOKEN = result['access_token']
        TOKEN_EXPIRY = time.time() + 3000
        
        print("✅ BIG Token erhalten", flush=True)
        return ACCESS_TOKEN
    except Exception as e:
        print(f"❌ BIG Login fehlgeschlagen: {e}", flush=True)
        return None


def get_valid_token():
    """Gibt gültigen Token zurück, erneuert wenn nötig"""
    global ACCESS_TOKEN, TOKEN_EXPIRY
    
    if not ACCESS_TOKEN or not TOKEN_EXPIRY or time.time() >= TOKEN_EXPIRY:
        return get_access_token()
    return ACCESS_TOKEN


def get_headers():
    """Gibt Standard-Headers für BIG API zurück"""
    token = get_valid_token()
    if not token:
        return None
    
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'X-PROJECT-ID': BIG_PROJECT_ID
    }


# ===== ELEMENT-IDs CACHEN =====
def get_element_ids():
    """Holt und cached Element-IDs für Räume und Behälter"""
    global RAUM_ELEMENT_ID, BEHAELTER_ELEMENT_ID
    
    if RAUM_ELEMENT_ID and BEHAELTER_ELEMENT_ID:
        return True
    
    try:
        headers = get_headers()
        if not headers:
            return False
        
        response = requests.get(f"{BIG_API_URL}/elements", headers=headers, timeout=10)
        response.raise_for_status()
        elements = response.json()['elements']
        
        for elem in elements:
            name_lower = elem['name'].lower()
            if 'raum' in name_lower and not RAUM_ELEMENT_ID:
                RAUM_ELEMENT_ID = elem['id']
                print(f"✅ Raum-Element: {elem['name']} (ID: {elem['id']})", flush=True)
            elif any(kw in name_lower for kw in ['behälter', 'behaelter']) and not BEHAELTER_ELEMENT_ID:
                BEHAELTER_ELEMENT_ID = elem['id']
                print(f"✅ Behälter-Element: {elem['name']} (ID: {elem['id']})", flush=True)
        
        return RAUM_ELEMENT_ID and BEHAELTER_ELEMENT_ID
    except Exception as e:
        print(f"❌ Fehler beim Laden der Element-IDs: {e}", flush=True)
        return False


# ===== RÄUME SYNCHRONISATION =====
def fetch_rooms_from_big():
    """Holt alle Räume von BIG"""
    try:
        if not get_element_ids():
            return []
        
        headers = get_headers()
        if not headers:
            return []
        
        response = requests.get(f"{BIG_API_URL}/{RAUM_ELEMENT_ID}", headers=headers, timeout=15)
        response.raise_for_status()
        entities = response.json()['entities']
        
        print(f"✅ {len(entities)} Räume von BIG geladen", flush=True)
        return entities
    except Exception as e:
        print(f"❌ Fehler beim Laden der Räume: {e}", flush=True)
        return []


def determine_logistikrelevant(raumtyp):
    """Bestimmt ob Raum logistikrelevant ist basierend auf Raumtyp - FIXED VERSION"""
    if not raumtyp or raumtyp == 'N/A':
        return 0
    
    raumtyp_lower = raumtyp.lower()
    
    # ERWEITERT: BIG hat "Stationslogistik" statt "Stationslager"!
    relevant_types = [
        'stationslager',
        'stationslogistik',      # ← FIX: BIG verwendet "logistik"
        'areallogistiklager',
        'areallogistik',         # ← FIX: Generisch
        'zentrallager',
        'logistik',              # ← FIX: Generisch
        'lager'
    ]
    
    for relevant in relevant_types:
        if relevant in raumtyp_lower:
            return 1
    
    return 0


def sync_rooms_to_db(rooms):
    """Synchronisiert Räume von BIG in lokale DB - MIT BIG Instance ID Tracking"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    synced_count = 0
    updated_count = 0
    skipped_count = 0
    
    for room in rooms:
        attrs = room.get('attributes', {})
        big_instance_id = room.get('id')  # BIG interne Instance-ID
        
        raum_id = attrs.get('RKS', 'N/A')
        if raum_id == 'N/A' or not raum_id or not big_instance_id:
            skipped_count += 1
            continue
        
        bezeichnung = attrs.get('Raumtyp', 'Raum')
        raumtyp = attrs.get('Raumtyp', 'Unbekannt')
        logistikrelevant = determine_logistikrelevant(raumtyp)
        
        try:
            # Prüfe ob Raum bereits existiert (nach big_instance_id!)
            cursor.execute("SELECT raum_id FROM raeume WHERE big_instance_id=?", (big_instance_id,))
            existing = cursor.fetchone()
            
            if existing:
                # UPDATE - auch wenn RKS geändert wurde!
                cursor.execute("""
                    UPDATE raeume 
                    SET raum_id=?, bezeichnung=?, raumtyp=?, logistikrelevant=?, aktiv=1
                    WHERE big_instance_id=?
                """, (raum_id, bezeichnung, raumtyp, logistikrelevant, big_instance_id))
                updated_count += 1
            else:
                # INSERT - neuer Raum
                cursor.execute("""
                    INSERT INTO raeume (raum_id, bezeichnung, raumtyp, logistikrelevant, aktiv, big_instance_id)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (raum_id, bezeichnung, raumtyp, logistikrelevant, big_instance_id))
                synced_count += 1
        except Exception as e:
            print(f"⚠️  Fehler bei Raum {raum_id} (BIG-ID: {big_instance_id}): {e}", flush=True)
    
    conn.commit()
    conn.close()
    
    print(f"✅ {synced_count} neue Räume eingefügt", flush=True)
    if updated_count > 0:
        print(f"✅ {updated_count} Räume aktualisiert", flush=True)
    if skipped_count > 0:
        print(f"ℹ️  {skipped_count} Räume übersprungen (kein RKS oder BIG-ID)", flush=True)
    return synced_count + updated_count


# ===== BEHÄLTER SYNCHRONISATION =====
def fetch_containers_from_big():
    """Holt alle Behälter von BIG"""
    try:
        if not get_element_ids():
            return []
        
        headers = get_headers()
        if not headers:
            return []
        
        response = requests.get(f"{BIG_API_URL}/{BEHAELTER_ELEMENT_ID}", headers=headers, timeout=15)
        response.raise_for_status()
        entities = response.json()['entities']
        
        print(f"✅ {len(entities)} Behälter von BIG geladen", flush=True)
        return entities
    except Exception as e:
        print(f"❌ Fehler beim Laden der Behälter: {e}", flush=True)
        return []


def sync_containers_to_db(containers):
    """Synchronisiert Behälter von BIG in lokale DB - MIT BIG Instance ID Tracking"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    synced_count = 0
    updated_count = 0
    
    for container in containers:
        attrs = container.get('attributes', {})
        big_instance_id = container.get('id')  # BIG interne Instance-ID
        
        behaelter_id = attrs.get('BKS', 'N/A')
        if behaelter_id == 'N/A' or not behaelter_id or not big_instance_id:
            continue
        
        try:
            # Prüfe ob Behälter bereits existiert (nach big_instance_id!)
            cursor.execute("SELECT behaelter_id FROM behaelter_aktuell WHERE big_instance_id=?", (big_instance_id,))
            existing = cursor.fetchone()
            
            if existing:
                # UPDATE - BKS könnte geändert worden sein!
                cursor.execute("""
                    UPDATE behaelter_aktuell 
                    SET behaelter_id=?
                    WHERE big_instance_id=?
                """, (behaelter_id, big_instance_id))
                updated_count += 1
            else:
                # INSERT - neuer Behälter
                cursor.execute("""
                    INSERT INTO behaelter_aktuell 
                    (behaelter_id, raum_id, versorgungs_id, aktueller_bestand, letzte_aktion, big_instance_id)
                    VALUES (?, NULL, NULL, 0, ?, ?)
                """, (behaelter_id, datetime.now().isoformat(), big_instance_id))
                synced_count += 1
        except Exception as e:
            print(f"⚠️  Fehler bei Behälter {behaelter_id} (BIG-ID: {big_instance_id}): {e}", flush=True)
    
    conn.commit()
    conn.close()
    
    print(f"✅ {synced_count} neue Behälter eingefügt", flush=True)
    if updated_count > 0:
        print(f"✅ {updated_count} Behälter aktualisiert (BKS-Änderung)", flush=True)
    return synced_count + updated_count


def create_container_in_big(behaelter_id):
    """Erstellt neuen Behälter in BIG und gibt big_instance_id zurück"""
    try:
        if not get_element_ids():
            return None
        
        headers = get_headers()
        if not headers:
            return None
        
        parts = behaelter_id.split('-')
        if len(parts) != 4:
            print(f"❌ Ungültiges BKS-Format: {behaelter_id}", flush=True)
            return None
        
        areal = parts[0]
        gebaeude = parts[1]
        gewerk_nr = parts[2]
        betriebs = parts[3]
        
        gewerk = gewerk_nr[0]
        gewerknummer = gewerk_nr[1:]
        betriebsmittel = betriebs[:3]
        betriebsmittelnummer = betriebs[3:]
        
        payload = {
            "entity_type_name": "Logistik",
            "attributes": {
                "Areal": areal,
                "Gebäude": gebaeude,
                "Betriebsmittel": betriebsmittel,
                "Gewerknummer": gewerknummer,
                "Betriebsmittelnummer": betriebsmittelnummer,
                "Gewerk": gewerk
            }
        }
        
        response = requests.post(
            f"{BIG_API_URL}/{BEHAELTER_ELEMENT_ID}",
            headers=headers,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        big_instance_id = result.get('id')
        
        if big_instance_id:
            # Speichere big_instance_id in lokaler DB
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE behaelter_aktuell 
                SET big_instance_id=? 
                WHERE behaelter_id=?
            """, (big_instance_id, behaelter_id))
            conn.commit()
            conn.close()
            
            print(f"✅ Behälter {behaelter_id} in BIG erstellt (Instance-ID: {big_instance_id})", flush=True)
            return big_instance_id
        else:
            print(f"⚠️  Behälter erstellt aber keine Instance-ID erhalten", flush=True)
            return None
            
    except Exception as e:
        print(f"❌ Fehler beim Erstellen von Behälter {behaelter_id} in BIG: {e}", flush=True)
        return None


def delete_container_in_big(behaelter_id):
    """Löscht Behälter in BIG - verwendet big_instance_id für sichere Identifikation"""
    try:
        # Hole big_instance_id aus lokaler DB
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT big_instance_id FROM behaelter_aktuell WHERE behaelter_id=?", (behaelter_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            big_instance_id = result[0]
            print(f"🔍 Lösche Behälter über Instance-ID: {big_instance_id}", flush=True)
        else:
            # Fallback: Suche in BIG über BKS
            print(f"⚠️  Keine Instance-ID gespeichert, suche in BIG über BKS...", flush=True)
            if not get_element_ids():
                return False
            
            headers = get_headers()
            if not headers:
                return False
            
            containers = fetch_containers_from_big()
            big_instance_id = None
            
            for container in containers:
                attrs = container.get('attributes', {})
                if attrs.get('BKS') == behaelter_id:
                    big_instance_id = container.get('id')
                    break
            
            if not big_instance_id:
                print(f"⚠️  Behälter {behaelter_id} nicht in BIG gefunden", flush=True)
                return False
        
        # Lösche über Instance-ID
        headers = get_headers()
        if not headers:
            return False
            
        response = requests.delete(
            f"{BIG_API_URL}/instance/{big_instance_id}",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        
        print(f"✅ Behälter {behaelter_id} in BIG gelöscht (Instance-ID: {big_instance_id})", flush=True)
        return True
    except Exception as e:
        print(f"❌ Fehler beim Löschen von Behälter {behaelter_id} in BIG: {e}", flush=True)
        return False


# ===== INITIAL IMPORT =====
def initial_import_from_big():
    """Initiales Laden von Räumen und Behältern aus BIG beim DB-Setup"""
    print("\n" + "="*80, flush=True)
    print("🔄 INITIAL-IMPORT von BIG", flush=True)
    print("="*80, flush=True)
    
    print("\n📋 Importiere Räume...", flush=True)
    rooms = fetch_rooms_from_big()
    if rooms:
        sync_rooms_to_db(rooms)
    
    print("\n📦 Importiere Behälter...", flush=True)
    containers = fetch_containers_from_big()
    if containers:
        sync_containers_to_db(containers)
    
    print("\n✅ Initial-Import abgeschlossen", flush=True)
    print("="*80 + "\n", flush=True)


# ===== KONTINUIERLICHE SYNCHRONISATION =====
def continuous_sync():
    """Läuft im Hintergrund und synchronisiert alle 60 Sekunden"""
    print("🔄 Starte kontinuierliche BIG-Synchronisation (60s Intervall)...", flush=True)
    
    while True:
        try:
            time.sleep(60)
            
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 Synchronisiere mit BIG...", flush=True)
            
            rooms = fetch_rooms_from_big()
            if rooms:
                sync_rooms_to_db(rooms)
            
            containers = fetch_containers_from_big()
            if containers:
                sync_containers_to_db(containers)
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Sync abgeschlossen\n", flush=True)
            
        except Exception as e:
            print(f"❌ Fehler in kontinuierlicher Sync: {e}", flush=True)


def start_background_sync():
    """Startet Background-Thread für kontinuierliche Synchronisation"""
    sync_thread = threading.Thread(target=continuous_sync, daemon=True)
    sync_thread.start()
    print("✅ Background-Sync Thread gestartet", flush=True)


# ===== ÖFFENTLICHE API =====
def sync_new_container_to_big(behaelter_id):
    """
    Wird aufgerufen wenn ein neuer Behälter im Logistik-System erstellt wird.
    Synchronisiert SOFORT mit BIG.
    """
    print(f"🔄 Synchronisiere neuen Behälter {behaelter_id} mit BIG...", flush=True)
    return create_container_in_big(behaelter_id)


def sync_deleted_container_to_big(behaelter_id):
    """
    Wird aufgerufen wenn ein Behälter im Logistik-System gelöscht wird.
    Synchronisiert SOFORT mit BIG.
    """
    print(f"🔄 Lösche Behälter {behaelter_id} in BIG...", flush=True)
    return delete_container_in_big(behaelter_id)


if __name__ == "__main__":
    print("🧪 BIG Sync Test", flush=True)
    initial_import_from_big()