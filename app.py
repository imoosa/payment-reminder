from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import pandas as pd
import os
from datetime import datetime, date
from dateutil import parser as dateparser
import traceback
import requests
import json
import re
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'wgs-payment-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///payments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# AiSensy Configuration
AISENSY_API_KEY = os.environ.get('AISENSY_API_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY5ZmM2NjdjMzYyODIyMGUyN2YzN2JmYyIsIm5hbWUiOiJWZXJvZXhpbXVzIiwiYXBwTmFtZSI6IkFpU2Vuc3kiLCJjbGllbnRJZCI6IjY5ZjlkZmMwMGE4NDk1Mzc4YmY1ZjI5YyIsImFjdGl2ZVBsYW4iOiJGUkVFX0ZPUkVWRVIiLCJpYXQiOjE3NzgxNDg5ODh9.vC-f2uQBFylXeQ0Gq1qUYn_u-qM9UDVqhxMqnO7I-aE')
AISENSY_BASE_URL = 'https://backend.aisensy.com/campaign/t1/api/v2'
WHATSAPP_TEMPLATE_NAME = 'payment_reminder'

db = SQLAlchemy(app)

# ── Models ──────────────────────────────────────────────────────────────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Party(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    party_name = db.Column(db.String(255), nullable=False)
    bill_no = db.Column(db.String(100))
    bill_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    amount = db.Column(db.Float, default=0)
    paid_amount = db.Column(db.Float, default=0)
    pending_amount = db.Column(db.Float, default=0)
    days_overdue = db.Column(db.Integer, default=0)
    bucket = db.Column(db.String(50))
    bucket_pending = db.Column(db.Float, default=0)
    contact = db.Column(db.String(100))
    email = db.Column(db.String(150))
    remarks = db.Column(db.String(500))
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class WhatsAppLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    party_id = db.Column(db.Integer, db.ForeignKey('party.id'), nullable=True)
    party_name = db.Column(db.String(255))
    phone_number = db.Column(db.String(20))
    message = db.Column(db.Text)
    status = db.Column(db.String(50))
    response = db.Column(db.Text)
    error_details = db.Column(db.Text)  # Added field for error details
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_bulk = db.Column(db.Boolean, default=False)
    bulk_id = db.Column(db.String(100))

with app.app_context():
    #db.drop_all() 
    db.create_all()
    # Create default admin user if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password_hash=generate_password_hash('admin123'))
        db.session.add(admin)
        db.session.commit()
        print("Default admin user created - Username: admin, Password: admin123")

# ── Authentication Decorator ──────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ── WhatsApp Helper Functions ──────────────────────────────────────────────
# In app.py, replace the existing WhatsApp helper functions with these:

# ── WhatsApp Helper Functions (Updated to match app_sqlalchemy.py) ──────────────

def clean_phone_number(phone):
    """Clean and validate phone number for WhatsApp"""
    if not phone:
        return None
    # Remove all non-digit characters
    cleaned = re.sub(r'\D', '', str(phone))
    # Ensure it starts with country code (assuming India +91)
    if len(cleaned) == 10:
        cleaned = '91' + cleaned
    elif len(cleaned) == 12 and cleaned.startswith('91'):
        pass
    elif len(cleaned) > 12:
        cleaned = cleaned[-12:]
    else:
        return None
    return cleaned

def send_whatsapp_message(party_id, party_name, phone_number, pending_amount, bucket_name, bucket_amount):
    """Send WhatsApp message using AiSensy API (matching app_sqlalchemy.py pattern)"""
    cleaned_phone = clean_phone_number(phone_number)
    if not cleaned_phone:
        error_msg = f'Invalid phone number: {phone_number}'
        logger.error(error_msg)
        return {'success': False, 'error': error_msg, 'phone': phone_number}
    
    # Format amount in Indian Rupees
    formatted_pending = f"₹{pending_amount:,.2f}"
    formatted_bucket_amount = f"₹{bucket_amount:,.2f}"
    
    # Template variables as per app_sqlalchemy.py pattern
    variables = [
        party_name,
        formatted_pending,
        bucket_name,
        formatted_bucket_amount
    ]
    
    # Payload structure matching app_sqlalchemy.py
    payload = {
        "apiKey": AISENSY_API_KEY,
        "campaignName": WHATSAPP_TEMPLATE_NAME,
        "destination": cleaned_phone,
        "userName": party_name,
        "source": "api",
        "templateParams": variables,  # Using templateParams (not templateParams in a different format)
        "tags": ["payment_reminder", "wgs_system"],
        "attributes": {}
    }
    
    logger.info(f"Sending WhatsApp to {cleaned_phone}")
    logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        # Use the same URL pattern as app_sqlalchemy.py - no '/send' suffix
        response = requests.post(
            AISENSY_BASE_URL,  # Already ends with /api/v2
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text[:500] if response.text else 'empty'}")
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Success response: {result}")
            return {
                'success': True, 
                'response': result, 
                'phone': cleaned_phone,
                'message_id': result.get('id', '')  # Some APIs return message ID
            }
        else:
            error_msg = f'HTTP {response.status_code}: {response.text[:200]}'
            logger.error(error_msg)
            return {
                'success': False, 
                'error': error_msg, 
                'response_text': response.text[:500], 
                'phone': cleaned_phone
            }
            
    except requests.exceptions.Timeout:
        error_msg = 'Request timeout - API took too long to respond'
        logger.error(error_msg)
        return {'success': False, 'error': error_msg, 'phone': cleaned_phone}
        
    except requests.exceptions.ConnectionError as e:
        error_msg = f'Connection error: {str(e)}'
        logger.error(error_msg)
        return {'success': False, 'error': error_msg, 'phone': cleaned_phone}
        
    except Exception as e:
        error_msg = f'Unexpected error: {str(e)}'
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return {'success': False, 'error': error_msg, 'phone': cleaned_phone}

def send_bulk_whatsapp_messages(parties, bulk_id=None):
    """Send bulk WhatsApp messages to multiple parties"""
    results = []
    success_count = 0
    fail_count = 0
    
    for party in parties:
        # Extract phone number (first one if multiple)
        phone = party.contact.split(',')[0].strip() if party.contact else None
        
        if not phone:
            error_msg = 'No phone number available'
            logger.warning(f"No phone for party {party.party_name}")
            
            # Log failure
            log = WhatsAppLog(
                party_id=party.id,
                party_name=party.party_name,
                phone_number='',
                message=f"Failed: {error_msg}",
                status='failed',
                response=json.dumps({'error': error_msg}),
                error_details=error_msg,
                is_bulk=True,
                bulk_id=bulk_id
            )
            db.session.add(log)
            
            results.append({
                'party_id': party.id,
                'party_name': party.party_name,
                'success': False,
                'error': error_msg
            })
            fail_count += 1
            continue
        
        # Get bucket amount for this party
        bucket_amount = party.bucket_pending if party.bucket_pending > 0 else party.pending_amount
        
        result = send_whatsapp_message(
            party.id,
            party.party_name,
            phone,
            party.pending_amount,
            party.bucket,
            bucket_amount
        )
        
        # Log the attempt
        error_detail = result.get('error') if not result['success'] else None
        response_detail = result.get('response') if result['success'] else result.get('response_text', result.get('error', ''))
        
        log = WhatsAppLog(
            party_id=party.id,
            party_name=party.party_name,
            phone_number=phone,
            message=f"Reminder for {party.party_name}: Pending ₹{party.pending_amount:,.2f}",
            status='success' if result['success'] else 'failed',
            response=json.dumps(result),
            error_details=error_detail,
            is_bulk=True,
            bulk_id=bulk_id
        )
        db.session.add(log)
        
        if result['success']:
            success_count += 1
            results.append({
                'party_id': party.id,
                'party_name': party.party_name,
                'success': True,
                'phone': phone
            })
            logger.info(f"Successfully sent to {party.party_name} at {phone}")
        else:
            fail_count += 1
            results.append({
                'party_id': party.id,
                'party_name': party.party_name,
                'success': False,
                'error': result.get('error', 'Unknown error'),
                'phone': phone
            })
            logger.error(f"Failed to send to {party.party_name}: {result.get('error')}")
    
    db.session.commit()
    
    return {
        'total': len(parties),
        'success': success_count,
        'failed': fail_count,
        'results': results
    }

# ── Helpers ──────────────────────────────────────────────────────────────
def parse_date_safe(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if str(val).strip() in ('', 'nan', 'NaT'):
        return None
    try:
        if isinstance(val, (datetime, date)):
            return val if isinstance(val, date) else val.date()
        return dateparser.parse(str(val)).date()
    except:
        return None

def safe_float(val):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return 0.0
        return float(str(val).replace(',', '').strip() or 0)
    except:
        return 0.0

def calc_bucket(days):
    if days is None or days < 0:
        return '< 30 DAYS'
    if days < 30:
        return '< 30 DAYS'
    if days < 60:
        return '30-60 DAYS'
    if days < 90:
        return '60-90 DAYS'
    if days < 120:
        return '90-120 DAYS'
    if days < 180:
        return '120-180 DAYS'
    return '> 180 DAYS'

BUCKET_ORDER = ['< 30 DAYS', '30-60 DAYS', '60-90 DAYS', '90-120 DAYS', '120-180 DAYS', '> 180 DAYS']

BUCKET_COL_MAP = {
    5:  ('< 30 DAYS',    15),
    7:  ('30-60 DAYS',   45),
    9:  ('60-90 DAYS',   75),
    11: ('90-120 DAYS',  105),
    13: ('120-180 DAYS', 150),
    15: ('> 180 DAYS',   200),
}

def get_dashboard_data():
    parties = Party.query.all()
    unique_names = set(p.party_name for p in parties)
    total_parties = len(unique_names)
    total_pending = sum(p.pending_amount for p in parties)
    total_bills = len(parties)

    buckets = {b: {'count': 0, 'amount': 0, 'parties': set()} for b in BUCKET_ORDER}
    for p in parties:
        b = p.bucket or calc_bucket(p.days_overdue)
        if b not in buckets:
            b = '> 180 DAYS'
        buckets[b]['count'] += 1
        buckets[b]['amount'] += p.pending_amount
        buckets[b]['parties'].add(p.party_name)

    bucket_list = []
    max_amt = max((buckets[b]['amount'] for b in BUCKET_ORDER), default=1) or 1
    for b in BUCKET_ORDER:
        bucket_list.append({
            'name': b,
            'count': buckets[b]['count'],
            'party_count': len(buckets[b]['parties']),
            'amount': buckets[b]['amount'],
            'pct': round(buckets[b]['amount'] / max_amt * 100, 1)
        })

    party_totals = {}
    for p in parties:
        if p.party_name not in party_totals:
            party_totals[p.party_name] = {'pending': 0, 'days': p.days_overdue}
        party_totals[p.party_name]['pending'] += p.pending_amount
        if p.days_overdue > party_totals[p.party_name]['days']:
            party_totals[p.party_name]['days'] = p.days_overdue

    top_parties = sorted(party_totals.items(), key=lambda x: x[1]['pending'], reverse=True)[:10]

    action_required = len(set(
        p.party_name for p in parties if p.days_overdue > 30
    ))

    return {
        'total_parties': total_parties,
        'total_pending': total_pending,
        'total_bills': total_bills,
        'action_required': action_required,
        'buckets': bucket_list,
        'top_parties': [{'name': k, 'pending': v['pending'], 'days': v['days']} for k, v in top_parties],
        'bucket_order': BUCKET_ORDER,
    }

def detect_erp_header_row(df_raw):
    for i in range(min(25, len(df_raw))):
        row_vals = [str(v).strip().lower() for v in df_raw.iloc[i] if str(v).strip().lower() not in ('nan', '')]
        if 'particulars' in row_vals:
            return i
    return None

def parse_erp_format(df_raw, header_row, user_id=None):
    data_start = header_row + 3
    records = []

    for idx in range(data_start, len(df_raw)):
        row = df_raw.iloc[idx]
        party_name = str(row.iloc[0]).strip()

        if not party_name or party_name.lower() in ('nan', 'none', '', 'particulars'):
            continue
        if not any(c.isalpha() for c in party_name):
            continue

        contact_person = str(row.iloc[1]).strip() if len(row) > 1 else ''
        phone = str(row.iloc[2]).strip() if len(row) > 2 else ''
        if contact_person.lower() == 'nan':
            contact_person = ''
        if phone.lower() == 'nan':
            phone = ''
        phone = phone.replace('/', ',').replace(';', ',')
        seen_phones = []
        for num in phone.split(','):
            n = num.strip()
            if n and n not in seen_phones:
                seen_phones.append(n)
        phone = ', '.join(seen_phones)

        pending_total = safe_float(row.iloc[3]) if len(row) > 3 else 0

        primary_bucket = '> 180 DAYS'
        days_overdue = 200
        bucket_amount = 0
        for col_idx, (bname, bdays) in BUCKET_COL_MAP.items():
            if len(row) > col_idx and safe_float(row.iloc[col_idx]) > 0:
                primary_bucket = bname
                days_overdue = bdays
                bucket_amount = safe_float(row.iloc[col_idx])
                break

        breakdown = []
        for col_idx, (bname, _) in BUCKET_COL_MAP.items():
            if len(row) > col_idx:
                val = safe_float(row.iloc[col_idx])
                if val > 0:
                    breakdown.append(f"{bname}: ₹{val:,.0f}")
        remarks = ' | '.join(breakdown) if breakdown else ''

        records.append(Party(
            party_name=party_name,
            bill_no='',
            bill_date=None,
            due_date=None,
            amount=pending_total,
            paid_amount=0,
            pending_amount=pending_total,
            days_overdue=days_overdue,
            bucket=primary_bucket,
            bucket_pending=bucket_amount,
            contact=phone or contact_person,
            email='',
            remarks=f"{contact_person} | {remarks}" if contact_person else remarks,
            last_updated=datetime.utcnow(),
            uploaded_by=user_id
        ))
    return records

def process_dataframe(df_raw, user_id=None):
    header_row = detect_erp_header_row(df_raw)
    if header_row is not None:
        return parse_erp_format(df_raw, header_row, user_id)

    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)

    col_map = {}
    for col in df.columns:
        low = str(col).lower().strip()
        if any(x in low for x in ['party', 'customer', 'vendor', 'name', 'client']):
            col_map[col] = 'party_name'
        elif any(x in low for x in ['bill no', 'invoice no', 'voucher']):
            col_map[col] = 'bill_no'
        elif any(x in low for x in ['bill date', 'invoice date']):
            col_map[col] = 'bill_date'
        elif any(x in low for x in ['due date', 'payment due']):
            col_map[col] = 'due_date'
        elif any(x in low for x in ['amount', 'total', 'gross']):
            col_map[col] = 'amount'
        elif any(x in low for x in ['paid', 'received']):
            col_map[col] = 'paid_amount'
        elif any(x in low for x in ['pending', 'balance', 'outstanding']):
            col_map[col] = 'pending_amount'
        elif any(x in low for x in ['contact', 'mobile', 'phone', 'telephone']):
            col_map[col] = 'contact'
        elif 'email' in low:
            col_map[col] = 'email'
        elif any(x in low for x in ['remark', 'note', 'comment']):
            col_map[col] = 'remarks'
    df = df.rename(columns=col_map)

    today = date.today()
    records = []
    for _, row in df.iterrows():
        pname = str(row.get('party_name', '')).strip()
        if not pname or pname.lower() in ('nan', 'none', ''):
            continue
        bill_date = parse_date_safe(row.get('bill_date'))
        due_date = parse_date_safe(row.get('due_date'))
        ref_date = due_date or bill_date
        days_overdue = (today - ref_date).days if ref_date else 0
        amt = safe_float(row.get('amount', 0))
        paid = safe_float(row.get('paid_amount', 0))
        pending = safe_float(row.get('pending_amount', 0)) or (amt - paid)
        
        raw_phone = str(row.get('contact', ''))
        raw_phone = raw_phone.replace('/', ',').replace(';', ',')
        seen_phones = []
        for num in raw_phone.split(','):
            n = num.strip()
            if n and n.lower() not in ('nan', 'none', '') and n not in seen_phones:
                seen_phones.append(n)
        clean_phone = ', '.join(seen_phones)
        
        bucket = calc_bucket(days_overdue)
        records.append(Party(
            party_name=pname,
            bill_no=str(row.get('bill_no', '')),
            bill_date=bill_date,
            due_date=due_date,
            amount=amt,
            paid_amount=paid,
            pending_amount=pending,
            days_overdue=days_overdue,
            bucket=bucket,
            bucket_pending=pending,
            contact=clean_phone,
            email=str(row.get('email', '')),
            remarks=str(row.get('remarks', '')),
            last_updated=datetime.utcnow(),
            uploaded_by=user_id
        ))
    return records

# ── Authentication Routes ───────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    current = request.form.get('current_password')
    new = request.form.get('new_password')
    confirm = request.form.get('confirm_password')
    
    user = User.query.get(session['user_id'])
    if not check_password_hash(user.password_hash, current):
        flash('Current password is incorrect', 'error')
    elif new != confirm:
        flash('New passwords do not match', 'error')
    elif len(new) < 4:
        flash('Password must be at least 4 characters', 'error')
    else:
        user.password_hash = generate_password_hash(new)
        db.session.commit()
        flash('Password changed successfully!', 'success')
    return redirect(url_for('index'))

# ── WhatsApp Routes ─────────────────────────────────────────────────────
@app.route('/send-whatsapp/<int:party_id>', methods=['POST'])
@login_required
def send_whatsapp_single(party_id):
    """Send single WhatsApp message to a specific party"""
    party = Party.query.get_or_404(party_id)
    
    # Get phone number from form (if selected from dropdown) or use first contact
    phone = request.form.get('phone_number')
    if not phone:
        # Fallback to first contact number
        phone = party.contact.split(',')[0].strip() if party.contact else None
    
    if not phone:
        flash(f'❌ No phone number found for {party.party_name}', 'error')
        return redirect(url_for('party_detail', pid=party_id))
    
    # Get bucket amount (use bucket_pending if available, otherwise pending_amount)
    bucket_amount = party.bucket_pending if party.bucket_pending > 0 else party.pending_amount
    
    result = send_whatsapp_message(
        party.id,
        party.party_name,
        phone,
        party.pending_amount,
        party.bucket,
        bucket_amount
    )
    
    # Log the attempt
    log = WhatsAppLog(
        party_id=party.id,
        party_name=party.party_name,
        phone_number=phone,
        message=f"Reminder: Pending ₹{party.pending_amount:,.2f}",
        status='success' if result['success'] else 'failed',
        response=json.dumps(result),
        error_details=result.get('error') if not result['success'] else None,
        is_bulk=False
    )
    db.session.add(log)
    db.session.commit()
    
    if result['success']:
        flash(f'✅ WhatsApp reminder sent to {party.party_name} at {phone}!', 'success')
    else:
        flash(f'❌ Failed to send message to {party.party_name}: {result.get("error", "Unknown error")}', 'error')
    
    return redirect(url_for('party_detail', pid=party_id))

@app.route('/send-whatsapp-bulk', methods=['POST'])
@login_required
def send_whatsapp_bulk():
    """Send bulk WhatsApp messages to selected parties"""
    party_ids = request.form.getlist('party_ids')
    
    if not party_ids:
        flash('❌ No parties selected', 'error')
        return redirect(url_for('parties'))
    
    parties = Party.query.filter(Party.id.in_(party_ids)).all()
    
    # Filter parties with phone numbers
    parties_with_phones = [p for p in parties if p.contact]
    parties_without_phones = [p for p in parties if not p.contact]
    
    if not parties_with_phones:
        flash('❌ None of the selected parties have phone numbers', 'error')
        return redirect(url_for('parties'))
    
    # Generate bulk ID
    bulk_id = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    
    # Send messages
    result = send_bulk_whatsapp_messages(parties_with_phones, bulk_id)
    
    # Show result message
    message = f"📱 Bulk WhatsApp Summary:\n"
    message += f"✅ Success: {result['success']} messages\n"
    message += f"❌ Failed: {result['failed']} messages\n"
    message += f"📊 Total selected: {len(parties)}\n"
    
    if parties_without_phones:
        message += f"⚠️ {len(parties_without_phones)} parties skipped (no phone number)"
    
    flash(message, 'success' if result['success'] > 0 else 'error')
    
    return redirect(url_for('parties'))

@app.route('/whatsapp-logs')
@login_required
def whatsapp_logs():
    """View WhatsApp message logs"""
    page = request.args.get('page', 1, type=int)
    logs = WhatsAppLog.query.order_by(WhatsAppLog.sent_at.desc()).paginate(page=page, per_page=50)
    return render_template('whatsapp_logs.html', logs=logs)

@app.route('/api/test-whatsapp', methods=['POST'])
@login_required
def test_whatsapp():
    """Test WhatsApp API connection"""
    test_number = request.form.get('test_number', '')
    if not test_number:
        return jsonify({'success': False, 'error': 'No test number provided'})
    
    result = send_whatsapp_message(
        0,
        'Test Customer',
        test_number,
        5000.00,
        '30-60 DAYS',
        2500.00
    )
    return jsonify(result)

# ── Main Routes ───────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    data = get_dashboard_data()
    return render_template('dashboard.html', data=data, username=session.get('username'), now=datetime.now())

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        f = request.files.get('excel_file')
        if not f or f.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('upload'))
        ext = f.filename.rsplit('.', 1)[-1].lower()
        if ext not in ('xlsx', 'xls', 'csv'):
            flash('Only .xlsx / .xls / .csv files allowed', 'error')
            return redirect(url_for('upload'))
        path = os.path.join(app.config['UPLOAD_FOLDER'], f.filename)
        f.save(path)
        try:
            df_raw = pd.read_csv(path, header=None) if ext == 'csv' else pd.read_excel(path, header=None)
            if request.form.get('replace') == '1':
                Party.query.delete()
            records = process_dataframe(df_raw, session['user_id'])
            db.session.bulk_save_objects(records)
            db.session.commit()
            
            # Delete the file after processing
            os.remove(path)
            
            flash(f'✅ Imported {len(records)} records successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Error: {str(e)}', 'error')
            traceback.print_exc()
        return redirect(url_for('index'))
    return render_template('upload.html')

@app.route('/parties')
@login_required
def parties():
    bucket = request.args.get('bucket', '')
    search = request.args.get('q', '')
    overdue = request.args.get('overdue', '')
    sort = request.args.get('sort', 'overdue_desc')
    page = request.args.get('page', 1, type=int)
    
    q = Party.query
    
    if bucket:
        q = q.filter_by(bucket=bucket)
    
    if search:
        q = q.filter(Party.party_name.ilike(f'%{search}%'))
    
    if overdue:
        if overdue == '0':
            q = q.filter(Party.days_overdue == 0)
        elif overdue == '30':
            q = q.filter(Party.days_overdue.between(1, 30))
        elif overdue == '60':
            q = q.filter(Party.days_overdue.between(31, 60))
        elif overdue == '90':
            q = q.filter(Party.days_overdue.between(61, 90))
        elif overdue == '120':
            q = q.filter(Party.days_overdue.between(91, 120))
        elif overdue == '180':
            q = q.filter(Party.days_overdue > 120)
    
    # Apply sorting
    if sort == 'overdue_desc':
        q = q.order_by(Party.days_overdue.desc())
    elif sort == 'overdue_asc':
        q = q.order_by(Party.days_overdue.asc())
    elif sort == 'amount_desc':
        q = q.order_by(Party.pending_amount.desc())
    elif sort == 'amount_asc':
        q = q.order_by(Party.pending_amount.asc())
    elif sort == 'name_asc':
        q = q.order_by(Party.party_name.asc())
    elif sort == 'name_desc':
        q = q.order_by(Party.party_name.desc())
    else:
        q = q.order_by(Party.days_overdue.desc())
    
    pagination = q.paginate(page=page, per_page=25)
    return render_template('parties.html', pagination=pagination, bucket=bucket, search=search, 
                         overdue_filter=overdue, sort=sort, bucket_order=BUCKET_ORDER)

@app.route('/party/<int:pid>')
@login_required
def party_detail(pid):
    p = Party.query.get_or_404(pid)
    # Get WhatsApp logs for this party
    logs = WhatsAppLog.query.filter_by(party_id=pid).order_by(WhatsAppLog.sent_at.desc()).limit(10).all()
    return render_template('party_detail.html', party=p, logs=logs)

@app.route('/party/<int:pid>/edit', methods=['POST'])
@login_required
def party_edit(pid):
    p = Party.query.get_or_404(pid)
    p.remarks = request.form.get('remarks', p.remarks)
    p.contact = request.form.get('contact', p.contact)
    p.email = request.form.get('email', p.email)
    db.session.commit()
    flash('Record updated', 'success')
    return redirect(url_for('party_detail', pid=pid))

@app.route('/party/<int:pid>/delete', methods=['POST'])
@login_required
def party_delete(pid):
    p = Party.query.get_or_404(pid)
    party_name = p.party_name
    db.session.delete(p)
    db.session.commit()
    flash(f'✅ Deleted record for {party_name}', 'success')
    return redirect(url_for('parties'))

@app.route('/party/add', methods=['GET', 'POST'])
@login_required
def party_add():
    if request.method == 'POST':
        try:
            # Calculate days overdue
            due_date = parse_date_safe(request.form.get('due_date'))
            days_overdue = (date.today() - due_date).days if due_date else 0
            pending = safe_float(request.form.get('pending_amount'))
            bucket = calc_bucket(days_overdue)
            
            party = Party(
                party_name=request.form.get('party_name'),
                bill_no=request.form.get('bill_no'),
                bill_date=parse_date_safe(request.form.get('bill_date')),
                due_date=due_date,
                amount=safe_float(request.form.get('amount')),
                paid_amount=safe_float(request.form.get('paid_amount')),
                pending_amount=pending,
                days_overdue=days_overdue,
                bucket=bucket,
                bucket_pending=pending,
                contact=request.form.get('contact'),
                email=request.form.get('email'),
                remarks=request.form.get('remarks'),
                uploaded_by=session['user_id']
            )
            db.session.add(party)
            db.session.commit()
            flash(f'✅ Added new party: {party.party_name}', 'success')
            return redirect(url_for('parties'))
        except Exception as e:
            flash(f'❌ Error adding party: {str(e)}', 'error')
    return render_template('party_add.html')

@app.route('/api/chart-data')
@login_required
def api_chart_data():
    parties = Party.query.all()
    buckets = {b: {'amount': 0, 'count': 0} for b in BUCKET_ORDER}
    for p in parties:
        b = p.bucket or '> 180 DAYS'
        if b in buckets:
            buckets[b]['amount'] += p.pending_amount
            buckets[b]['count'] += 1
    return jsonify({
        'labels': BUCKET_ORDER,
        'amounts': [round(buckets[b]['amount']) for b in BUCKET_ORDER],
        'counts': [buckets[b]['count'] for b in BUCKET_ORDER],
    })

@app.route('/api/clear-data', methods=['POST'])
@login_required
def api_clear_data():
    try:
        Party.query.delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.template_filter('inr')
def inr_filter(val):
    try:
        val = float(val)
        if val >= 1e7:
            return f'₹{val/1e7:.2f} Cr'
        if val >= 1e5:
            return f'₹{val/1e5:.2f} L'
        return f'₹{val:,.2f}'
    except:
        return '₹0'

if __name__ == '__main__':
    app.run(debug=True, port=5000)
