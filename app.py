from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import pandas as pd
import json
import os
from datetime import datetime, date, timedelta
import hashlib
import tempfile
import re
import requests

app = Flask(__name__)
app.secret_key = 'maktronic_secret_2024_change_in_production'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# ── Auth ──────────────────────────────────────────────────────────────────────
USERS = {
    'admin': hashlib.sha256('admin123'.encode()).hexdigest(),
    'manager': hashlib.sha256('manager123'.encode()).hexdigest(),
}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# Global variables for auto-refresh
last_gsheet_url = None
last_sync_time = None
last_sync_hash = None

# ── Data helpers ──────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DATA_FILE = os.path.join(DATA_DIR, 'debtors.json')

BUCKETS = [
    {'key': 'lt30',    'label': '< 30 Days',     'col': 5,  'min': 0,   'max': 29},
    {'key': '30_60',   'label': '30 – 60 Days',  'col': 7,  'min': 30,  'max': 59},
    {'key': '60_90',   'label': '60 – 90 Days',  'col': 9,  'min': 60,  'max': 89},
    {'key': '90_120',  'label': '90 – 120 Days', 'col': 11, 'min': 90,  'max': 119},
    {'key': '120_180', 'label': '120 – 180 Days','col': 13, 'min': 120, 'max': 179},
    {'key': 'gt180',   'label': '> 180 Days',    'col': 15, 'min': 180, 'max': 9999},
]

def parse_excel(filepath):
    """Parse Excel file with proper error handling and column detection"""
    try:
        # Try to read the Excel file with header detection
        df = pd.read_excel(filepath, sheet_name=None)  # Read all sheets
        
        # Find the Sundry Debtors sheet or use first sheet
        sheet_name = 'Sundry Debtors'
        if sheet_name not in df:
            sheet_name = list(df.keys())[0]  # Use first sheet if not found
        
        df = pd.read_excel(filepath, sheet_name=sheet_name, header=None)
        
        parties = []
        
        # Find the start of data (look for first non-empty row with party name)
        start_row = 0
        for idx, row in df.iterrows():
            first_col = str(row[0]) if pd.notna(row[0]) else ''
            # Look for actual party data (not headers)
            if first_col and first_col != 'nan' and len(first_col.strip()) > 2:
                start_row = idx
                break
        
        if start_row == 0:
            start_row = 16  # fallback to original offset if detection fails
        
        # Process rows from start_row onwards
        for idx, row in df.iloc[start_row:].iterrows():
            name_raw = str(row[0]) if pd.notna(row[0]) else ''
            if not name_raw or name_raw == 'nan' or len(name_raw.strip()) == 0:
                continue
            
            # Get total from column 3
            try:
                total = float(row[3]) if pd.notna(row[3]) else 0
            except (ValueError, TypeError):
                total = 0
            
            # Skip if no pending amount
            if total == 0:
                continue

            # Split name and location (format: "Party Name - Location")
            parts = name_raw.rsplit(' - ', 1)
            name = parts[0].strip()
            location = parts[1].strip() if len(parts) == 2 else ''

            # Get contact info
            contact_person = str(row[1]).strip() if pd.notna(row[1]) and str(row[1]) != 'nan' else ''
            phone = str(row[2]).strip() if pd.notna(row[2]) and str(row[2]) != 'nan' else ''

            # Parse bucket amounts
            buckets = {}
            for b in BUCKETS:
                try:
                    val = float(row[b['col']]) if pd.notna(row[b['col']]) else 0
                    if val > 0:
                        buckets[b['key']] = round(val, 2)
                except (ValueError, TypeError):
                    val = 0
            
            # Skip if no bucket amounts
            if not buckets:
                # Calculate from total if needed (fallback)
                if total > 0:
                    buckets = {'lt30': round(total, 2)}

            parties.append({
                'name': name,
                'location': location,
                'contact_person': contact_person,
                'phone': phone,
                'total_pending': round(total, 2),
                'buckets': buckets,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })
        
        # Remove duplicates (keep the one with more data)
        unique_parties = {}
        for p in parties:
            if p['name'] not in unique_parties:
                unique_parties[p['name']] = p
            else:
                # Merge bucket amounts if party exists
                existing = unique_parties[p['name']]
                for k, v in p['buckets'].items():
                    existing['buckets'][k] = existing['buckets'].get(k, 0) + v
                existing['total_pending'] = sum(existing['buckets'].values())
        
        return list(unique_parties.values())
    
    except Exception as e:
        raise Exception(f"Error parsing Excel: {str(e)}")

def load_data():
    """Load data from JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_data(parties):
    """Save data to JSON file"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(parties, f, indent=2, ensure_ascii=False)

def get_summary(parties):
    """Calculate summary statistics"""
    totals = {b['key']: 0.0 for b in BUCKETS}
    counts = {b['key']: 0 for b in BUCKETS}
    grand_total = 0.0
    
    for p in parties:
        grand_total += p['total_pending']
        for bkey, bval in p['buckets'].items():
            if bkey in totals:
                totals[bkey] = round(totals.get(bkey, 0) + bval, 2)
                counts[bkey] = counts.get(bkey, 0) + 1
    
    return {
        'totals': totals, 
        'counts': counts, 
        'grand_total': round(grand_total, 2), 
        'total_parties': len(parties)
    }

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username', '')
        p = hashlib.sha256(request.form.get('password', '').encode()).hexdigest()
        if USERS.get(u) == p:
            session['user'] = u
            return redirect(url_for('dashboard'))
        error = 'Invalid credentials'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    parties = load_data()
    summary = get_summary(parties)
    return render_template('dashboard.html', summary=summary, buckets=BUCKETS, user=session['user'])

@app.route('/bucket/<bucket_key>')
@login_required
def bucket_view(bucket_key):
    parties = load_data()
    label = next((b['label'] for b in BUCKETS if b['key'] == bucket_key), bucket_key)
    bucket_parties = []
    for p in parties:
        if bucket_key in p['buckets']:
            bucket_parties.append({**p, 'bucket_amount': p['buckets'][bucket_key]})
    bucket_parties.sort(key=lambda x: x['bucket_amount'], reverse=True)
    bucket_total = sum(p['bucket_amount'] for p in bucket_parties)
    return render_template('bucket.html', parties=bucket_parties, bucket_key=bucket_key,
                           bucket_label=label, bucket_total=bucket_total,
                           buckets=BUCKETS, user=session['user'],
                           parties_json=json.dumps(bucket_parties))

@app.route('/party/<path:party_name>')
@login_required
def party_detail(party_name):
    parties = load_data()
    party = next((p for p in parties if p['name'] == party_name), None)
    if not party:
        return redirect(url_for('dashboard'))
    bucket_map = {b['key']: b['label'] for b in BUCKETS}
    return render_template('party_detail.html', party=party, bucket_map=bucket_map,
                           buckets=BUCKETS, user=session['user'])

@app.route('/api/summary')
@login_required
def api_summary():
    parties = load_data()
    return jsonify(get_summary(parties))

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_excel():
    """Handle Excel file upload"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not f.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'Please upload an Excel file (.xlsx or .xls)'}), 400
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name
    
    try:
        parties = parse_excel(tmp_path)
        if not parties:
            return jsonify({'error': 'No valid data found in the file. Please check the file format.'}), 400
        
        save_data(parties)
        summary = get_summary(parties)
        
        return jsonify({
            'success': True, 
            'message': f'Successfully loaded {len(parties)} parties',
            'summary': summary
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except:
            pass

@app.route('/api/google-sheet', methods=['POST'])
@login_required
def sync_google_sheet():
    """Sync from Google Sheets with URL storage and auto-refresh support"""
    global last_gsheet_url, last_sync_time, last_sync_hash
    
    data = request.get_json()
    sheet_url = data.get('url', '').strip()
    
    if not sheet_url:
        return jsonify({'error': 'No URL provided'}), 400
    
    # Extract sheet ID from URL
    sheet_id = None
    patterns = [
        r'/spreadsheets/d/([a-zA-Z0-9-_]+)',
        r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]+)',
        r'spreadsheets/d/([a-zA-Z0-9-_]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, sheet_url)
        if match:
            sheet_id = match.group(1)
            break
    
    if not sheet_id:
        return jsonify({'error': 'Could not extract sheet ID from URL. Please check the URL format.'}), 400
    
    try:
        # Download and parse the sheet
        export_url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream'
        }
        
        response = requests.get(export_url, headers=headers, allow_redirects=True, timeout=30)
        
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' in content_type or '<html' in response.text[:200].lower():
            return jsonify({
                'error': 'Google Sheets access denied. Please ensure the sheet is shared with "Anyone with the link can view". Go to File → Share → Change to "Anyone with the link" → Viewer.'
            }), 400
        
        if response.status_code != 200:
            return jsonify({
                'error': f'Failed to download sheet (HTTP {response.status_code}). Make sure the sheet is publicly shared.'
            }), 400
        
        if len(response.content) < 1000:
            return jsonify({
                'error': 'Downloaded file is empty. Please check if the sheet contains data.'
            }), 400
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        
        try:
            parties = parse_excel(tmp_path)
            
            if not parties:
                return jsonify({
                    'error': 'No valid party data found in the sheet. Please check the format matches the expected template.'
                }), 400
            
            # Calculate hash of the data for change detection
            data_hash = hashlib.md5(json.dumps(parties, sort_keys=True).encode()).hexdigest()
            
            save_data(parties)
            
            # Store sync info
            last_gsheet_url = sheet_url
            last_sync_time = datetime.now().isoformat()
            last_sync_hash = data_hash
            
            summary = get_summary(parties)
            
            return jsonify({
                'success': True,
                'message': f'Successfully synced {len(parties)} parties from Google Sheets',
                'summary': summary,
                'sync_time': last_sync_time,
                'data_hash': data_hash
            })
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass
                
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timeout. Please check your internet connection.'}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Connection error. Please check your internet connection.'}), 500
    except Exception as e:
        return jsonify({'error': f'Error syncing sheet: {str(e)}'}), 500

@app.route('/api/auto-refresh', methods=['POST'])
@login_required
def auto_refresh():
    """Auto-refresh data from last used Google Sheet"""
    global last_gsheet_url
    
    if not last_gsheet_url:
        return jsonify({'success': False, 'error': 'No Google Sheet configured'}), 400
    
    # Reuse the sync logic
    try:
        # Extract sheet ID
        sheet_id = None
        patterns = [
            r'/spreadsheets/d/([a-zA-Z0-9-_]+)',
            r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, last_gsheet_url)
            if match:
                sheet_id = match.group(1)
                break
        
        if not sheet_id:
            return jsonify({'success': False, 'error': 'Invalid sheet URL'}), 400
        
        # Download and parse
        export_url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(export_url, headers=headers, allow_redirects=True, timeout=30)
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': 'Cannot access sheet'}), 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        
        try:
            parties = parse_excel(tmp_path)
            if parties:
                save_data(parties)
                summary = get_summary(parties)
                return jsonify({
                    'success': True,
                    'message': f'Auto-refreshed {len(parties)} parties',
                    'summary': summary
                })
            else:
                return jsonify({'success': False, 'error': 'No data found'}), 400
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass
                
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/check-updates', methods=['POST'])
@login_required
def check_updates():
    """Check if Google Sheet has been updated"""
    global last_gsheet_url, last_sync_hash
    
    data = request.get_json()
    sheet_url = data.get('url', '')
    
    if not sheet_url and last_gsheet_url:
        sheet_url = last_gsheet_url
    
    if not sheet_url:
        return jsonify({'has_updates': False, 'error': 'No sheet URL configured'}), 400
    
    # Extract sheet ID
    sheet_id = None
    patterns = [
        r'/spreadsheets/d/([a-zA-Z0-9-_]+)',
        r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, sheet_url)
        if match:
            sheet_id = match.group(1)
            break
    
    if not sheet_id:
        return jsonify({'has_updates': False, 'error': 'Invalid sheet URL'}), 400
    
    try:
        export_url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(export_url, headers=headers, allow_redirects=True, timeout=15)
        
        if response.status_code != 200:
            return jsonify({'has_updates': False, 'error': 'Cannot access sheet'}), 400
        
        # Quick check - just get first few rows to see if data changed
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        
        try:
            # Read just first 50 rows for quick comparison
            df = pd.read_excel(tmp_path, nrows=50)
            current_hash = hashlib.md5(df.to_string().encode()).hexdigest()
            
            has_updates = (last_sync_hash != current_hash) if last_sync_hash else True
            
            return jsonify({
                'has_updates': has_updates,
                'last_sync_time': last_sync_time,
                'message': 'Updates available!' if has_updates else 'Data is up to date'
            })
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass
                
    except Exception as e:
        return jsonify({'has_updates': False, 'error': str(e)}), 500

@app.route('/api/search')
@login_required
def search():
    q = request.args.get('q', '').lower().strip()
    if not q:
        return jsonify([])
    
    parties = load_data()
    results = []
    for p in parties:
        if (q in p['name'].lower() or 
            q in p.get('location', '').lower() or 
            q in p.get('contact_person', '').lower() or
            q in p.get('phone', '').lower()):
            results.append(p)
    
    return jsonify(results[:20])

@app.route('/api/send-reminder', methods=['POST'])
@login_required
def send_reminder():
    data = request.get_json()
    party_name = data.get('party_name')
    
    if not party_name:
        return jsonify({'error': 'Party name required'}), 400
    
    parties = load_data()
    party = next((p for p in parties if p['name'] == party_name), None)
    
    if not party:
        return jsonify({'error': 'Party not found'}), 404
    
    # Here you would integrate actual email/WhatsApp API
    # For now, just return success
    return jsonify({
        'success': True, 
        'message': f'Reminder sent to {party_name}',
        'party': party
    })

@app.route('/api/bucket-parties/<bucket_key>')
@login_required
def api_bucket_parties(bucket_key):
    """Return all parties in a bucket as JSON (used by frontend for WhatsApp)"""
    parties = load_data()
    result = []
    for p in parties:
        if bucket_key in p['buckets']:
            result.append({
                'name': p['name'],
                'phone': p.get('phone', ''),
                'location': p.get('location', ''),
                'contact_person': p.get('contact_person', ''),
                'bucket_amount': p['buckets'][bucket_key],
                'total_pending': p['total_pending'],
            })
    result.sort(key=lambda x: x['bucket_amount'], reverse=True)
    return jsonify(result)


@app.route('/api/send-whatsapp-bulk', methods=['POST'])
@login_required
def send_whatsapp_bulk():
    """
    Returns the list of parties with their WhatsApp URLs ready.
    Actual opening is done client-side via wa.me links.
    This endpoint validates phones and prepares the payload.
    """
    data = request.get_json()
    bucket_key = data.get('bucket_key', '')
    message_template = data.get('message', '')
    selected_names = data.get('selected_names', [])

    if not message_template:
        return jsonify({'error': 'Message template is required'}), 400
    if not selected_names:
        return jsonify({'error': 'No parties selected'}), 400

    parties = load_data()
    results = []
    skipped = []

    for p in parties:
        if p['name'] not in selected_names:
            continue
        phone_raw = p.get('phone', '').strip()
        if not phone_raw:
            skipped.append({'name': p['name'], 'reason': 'No phone number'})
            continue

        # Normalize phone: strip symbols, ensure 91 prefix for India
        phone = phone_raw.replace(' ', '').replace('-', '').replace('.', '').replace('(', '').replace(')', '')
        phone = phone.lstrip('+')
        if phone.startswith('91') and len(phone) == 12:
            phone = phone[2:]  # strip country code before re-adding
        phone = '91' + phone

        bucket_amount = p['buckets'].get(bucket_key, 0)
        msg = (message_template
               .replace('{name}', p['name'])
               .replace('{bucket_amount}', f"₹{bucket_amount:,.2f}")
               .replace('{total_pending}', f"₹{p['total_pending']:,.2f}"))

        results.append({
            'name': p['name'],
            'phone': phone,
            'whatsapp_url': f"https://wa.me/{phone}?text={requests.utils.quote(msg)}",
            'message': msg
        })

    return jsonify({
        'success': True,
        'sent': len(results),
        'skipped': len(skipped),
        'skipped_parties': skipped,
        'parties': results
    })


if __name__ == '__main__':
    # Create data directory if it doesn't exist
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Load sample data if available
    if not os.path.exists(DATA_FILE):
        try:
            sample_paths = [
                '/mnt/user-data/uploads/SUNDRY_DEBTOTS_09-05-2026__2_.xlsx',
                os.path.join(os.path.dirname(__file__), 'sample_data.xlsx')
            ]
            
            for sample in sample_paths:
                if os.path.exists(sample):
                    parties = parse_excel(sample)
                    if parties:
                        save_data(parties)
                        print(f'✓ Pre-loaded {len(parties)} parties from {sample}')
                        break
        except Exception as e:
            print(f'Note: Could not pre-load sample data: {e}')
    
    print(f'✓ Server running on http://localhost:5050')
    app.run(debug=True, port=5050, host='0.0.0.0')
