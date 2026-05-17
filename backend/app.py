import os
import json
import hashlib
import hmac
import time
import random
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import threading

app = Flask(__name__, static_folder='../tma', static_url_path='')
CORS(app)

# Config
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_WALLET = "UQCfdyrb0Fj8lA32OfizTwGY829tTzihsEYl1FrpBzeVKdi0"
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x]
PLATFORM_FEE = 0.05  # 5%
MIN_STAKE = 1  # stars

# In-memory DB (for MVP — replace with SQLite/Postgres in prod)
bets = {}
users = {}
votes = {}
transactions = []
treasury = {"balance": 0, "total_volume": 0}

bet_counter = 1

# ─── Helpers ───────────────────────────────────────────────────────────────

def validate_tg_data(init_data: str) -> dict | None:
    """Validate Telegram Web App init data"""
    if not BOT_TOKEN:
        # Dev mode: parse without validation
        try:
            params = dict(x.split('=', 1) for x in init_data.split('&') if '=' in x)
            user_str = params.get('user', '{}')
            return json.loads(requests.utils.unquote(user_str))
        except:
            return None
    try:
        params = dict(x.split('=', 1) for x in init_data.split('&') if '=' in x)
        hash_val = params.pop('hash', '')
        data_check = '\n'.join(f"{k}={v}" for k, v in sorted(params.items()))
        secret = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, hash_val):
            return None
        return json.loads(requests.utils.unquote(params.get('user', '{}')))
    except:
        return None

def get_ton_price():
    try:
        r = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd', timeout=5)
        return r.json()['the-open-network']['usd']
    except:
        return None

def get_crypto_price(coin_id: str):
    try:
        r = requests.get(f'https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd', timeout=5)
        return r.json()[coin_id]['usd']
    except:
        return None

def ensure_user(user_id: int, username: str = '', ref_id: int = None):
    if user_id not in users:
        users[user_id] = {
            "id": user_id,
            "username": username,
            "balance": 0,  # stars
            "reputation": 100,
            "bets_created": [],
            "bets_joined": [],
            "votes_cast": [],
            "referrals": [],
            "referred_by": ref_id,
            "total_won": 0,
            "total_wagered": 0,
            "created_at": datetime.utcnow().isoformat()
        }
        if ref_id and ref_id in users:
            users[ref_id]["referrals"].append(user_id)
    return users[user_id]

# ─── Routes: Static ────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('../tma', 'index.html')

@app.route('/health')
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})

# ─── Routes: User ──────────────────────────────────────────────────────────

@app.route('/api/user', methods=['POST'])
def get_user():
    data = request.json
    init_data = data.get('initData', '')
    ref_id = data.get('ref')
    
    # Dev/demo mode
    user_info = validate_tg_data(init_data) or {"id": 12345, "username": "demo_user", "first_name": "Demo"}
    
    user_id = user_info.get('id', 12345)
    username = user_info.get('username', user_info.get('first_name', 'User'))
    user = ensure_user(user_id, username, ref_id)
    user['username'] = username
    
    is_admin = user_id in ADMIN_IDS
    
    return jsonify({
        **user,
        "is_admin": is_admin,
        "bets_count": len(user['bets_joined']),
        "win_rate": round(user['total_won'] / max(user['total_wagered'], 1) * 100, 1)
    })

@app.route('/api/user/<int:user_id>/stats', methods=['GET'])
def user_stats(user_id):
    u = users.get(user_id, {})
    return jsonify(u)

# ─── Routes: Bets ──────────────────────────────────────────────────────────

@app.route('/api/bets', methods=['GET'])
def list_bets():
    status_filter = request.args.get('status', 'all')
    result = []
    for b in bets.values():
        if status_filter != 'all' and b['status'] != status_filter:
            continue
        result.append(b)
    result.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(result)

@app.route('/api/bets', methods=['POST'])
def create_bet():
    global bet_counter
    data = request.json
    
    user_info = validate_tg_data(data.get('initData', '')) or {"id": 12345, "username": "demo_user"}
    user_id = user_info.get('id', 12345)
    user = ensure_user(user_id, user_info.get('username', 'User'))
    
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    category = data.get('category', 'custom')
    options = data.get('options', ['Yes', 'No'])
    end_time = data.get('end_time')
    oracle_type = data.get('oracle_type', 'vote')  # vote | price
    oracle_params = data.get('oracle_params', {})
    
    if not title or len(options) < 2:
        return jsonify({"error": "Invalid bet data"}), 400
    
    bet_id = f"bet_{bet_counter}"
    bet_counter += 1
    
    bet = {
        "id": bet_id,
        "title": title,
        "description": description,
        "category": category,
        "options": options,
        "stakes": {opt: 0 for opt in options},
        "participants": {opt: [] for opt in options},
        "status": "pending",  # pending -> active -> voting -> resolved
        "creator_id": user_id,
        "creator": user.get('username', 'User'),
        "end_time": end_time,
        "oracle_type": oracle_type,
        "oracle_params": oracle_params,
        "total_pool": 0,
        "resolved_option": None,
        "votes": {},
        "created_at": datetime.utcnow().isoformat(),
        "approved_by": None
    }
    
    bets[bet_id] = bet
    user['bets_created'].append(bet_id)
    
    return jsonify(bet)

@app.route('/api/bets/<bet_id>', methods=['GET'])
def get_bet(bet_id):
    bet = bets.get(bet_id)
    if not bet:
        return jsonify({"error": "Not found"}), 404
    return jsonify(bet)

@app.route('/api/bets/<bet_id>/join', methods=['POST'])
def join_bet(bet_id):
    data = request.json
    bet = bets.get(bet_id)
    if not bet:
        return jsonify({"error": "Not found"}), 404
    if bet['status'] != 'active':
        return jsonify({"error": "Bet not active"}), 400
    
    user_info = validate_tg_data(data.get('initData', '')) or {"id": 12345, "username": "demo_user"}
    user_id = user_info.get('id', 12345)
    user = ensure_user(user_id, user_info.get('username', 'User'))
    
    option = data.get('option')
    amount = int(data.get('amount', 1))
    
    if option not in bet['options']:
        return jsonify({"error": "Invalid option"}), 400
    if amount < MIN_STAKE:
        return jsonify({"error": f"Minimum stake is {MIN_STAKE} stars"}), 400
    if user['balance'] < amount:
        return jsonify({"error": "Insufficient balance"}), 400
    
    # Deduct from user
    user['balance'] -= amount
    user['total_wagered'] += amount
    user['bets_joined'].append(bet_id)
    
    # Add to pool
    bet['stakes'][option] += amount
    bet['total_pool'] += amount
    bet['participants'][option].append({"user_id": user_id, "amount": amount})
    
    # Platform fee
    fee = int(amount * PLATFORM_FEE)
    treasury['balance'] += fee
    treasury['total_volume'] += amount
    
    transactions.append({
        "type": "bet",
        "user_id": user_id,
        "bet_id": bet_id,
        "option": option,
        "amount": amount,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return jsonify({"success": True, "bet": bet, "new_balance": user['balance']})

# ─── Routes: Admin ─────────────────────────────────────────────────────────

@app.route('/api/admin/bets/<bet_id>/approve', methods=['POST'])
def admin_approve_bet(bet_id):
    data = request.json
    user_info = validate_tg_data(data.get('initData', '')) or {"id": 12345}
    user_id = user_info.get('id', 12345)
    
    if user_id not in ADMIN_IDS and ADMIN_IDS:
        return jsonify({"error": "Unauthorized"}), 403
    
    bet = bets.get(bet_id)
    if not bet:
        return jsonify({"error": "Not found"}), 404
    
    bet['status'] = 'active'
    bet['approved_by'] = user_id
    bet['approved_at'] = datetime.utcnow().isoformat()
    
    return jsonify({"success": True, "bet": bet})

@app.route('/api/admin/bets/<bet_id>/reject', methods=['POST'])
def admin_reject_bet(bet_id):
    data = request.json
    user_info = validate_tg_data(data.get('initData', '')) or {"id": 12345}
    user_id = user_info.get('id', 12345)
    
    if user_id not in ADMIN_IDS and ADMIN_IDS:
        return jsonify({"error": "Unauthorized"}), 403
    
    bet = bets.get(bet_id)
    if not bet:
        return jsonify({"error": "Not found"}), 404
    
    bet['status'] = 'rejected'
    return jsonify({"success": True})

@app.route('/api/admin/bets/<bet_id>/resolve', methods=['POST'])
def admin_resolve_bet(bet_id):
    data = request.json
    user_info = validate_tg_data(data.get('initData', '')) or {"id": 12345}
    user_id = user_info.get('id', 12345)
    
    if user_id not in ADMIN_IDS and ADMIN_IDS:
        return jsonify({"error": "Unauthorized"}), 403
    
    bet = bets.get(bet_id)
    if not bet:
        return jsonify({"error": "Not found"}), 404
    
    winning_option = data.get('option')
    if winning_option not in bet['options']:
        return jsonify({"error": "Invalid option"}), 400
    
    resolve_bet(bet_id, winning_option)
    return jsonify({"success": True, "bet": bets[bet_id]})

@app.route('/api/admin/treasury', methods=['GET'])
def admin_treasury():
    data = request.args
    # Public treasury info
    return jsonify({
        **treasury,
        "admin_wallet": ADMIN_WALLET,
        "transactions_count": len(transactions)
    })

# ─── Routes: Voting ────────────────────────────────────────────────────────

@app.route('/api/bets/<bet_id>/vote', methods=['POST'])
def cast_vote(bet_id):
    data = request.json
    bet = bets.get(bet_id)
    if not bet:
        return jsonify({"error": "Not found"}), 404
    if bet['status'] != 'voting':
        return jsonify({"error": "Not in voting phase"}), 400
    
    user_info = validate_tg_data(data.get('initData', '')) or {"id": 12345}
    user_id = user_info.get('id', 12345)
    user = users.get(user_id)
    
    # Only participants can vote
    all_participants = []
    for p_list in bet['participants'].values():
        all_participants.extend([p['user_id'] for p in p_list])
    
    if user_id not in all_participants:
        return jsonify({"error": "Must be a participant to vote"}), 403
    
    if user_id in bet['votes']:
        return jsonify({"error": "Already voted"}), 400
    
    option = data.get('option')
    if option not in bet['options']:
        return jsonify({"error": "Invalid option"}), 400
    
    # Stake-weighted vote
    stake = sum(p['amount'] for opt_parts in bet['participants'].values() 
                for p in opt_parts if p['user_id'] == user_id)
    
    bet['votes'][str(user_id)] = {"option": option, "weight": stake + user.get('reputation', 100)}
    
    # Check if enough votes
    total_voters = len(all_participants)
    votes_cast = len(bet['votes'])
    
    if votes_cast >= max(3, total_voters * 0.6):
        # Tally
        tally = {}
        for v in bet['votes'].values():
            tally[v['option']] = tally.get(v['option'], 0) + v['weight']
        winning_option = max(tally, key=tally.get)
        resolve_bet(bet_id, winning_option)
        # Reward voters who chose correctly
        for uid_str, vdata in bet['votes'].items():
            if vdata['option'] == winning_option:
                uid = int(uid_str)
                if uid in users:
                    users[uid]['reputation'] = min(1000, users[uid]['reputation'] + 10)
                    users[uid]['balance'] += 1  # small reward
    
    return jsonify({"success": True, "votes_cast": votes_cast, "total_voters": total_voters})

# ─── Routes: Oracle ────────────────────────────────────────────────────────

@app.route('/api/oracle/price/<coin_id>', methods=['GET'])
def oracle_price(coin_id):
    price = get_crypto_price(coin_id)
    return jsonify({"coin": coin_id, "price_usd": price, "timestamp": datetime.utcnow().isoformat()})

@app.route('/api/oracle/check/<bet_id>', methods=['POST'])
def oracle_check(bet_id):
    """Auto-check price bets"""
    bet = bets.get(bet_id)
    if not bet or bet['oracle_type'] != 'price':
        return jsonify({"error": "Not a price bet"}), 400
    
    params = bet['oracle_params']
    coin_id = params.get('coin_id', 'the-open-network')
    target_price = float(params.get('target_price', 0))
    direction = params.get('direction', 'above')  # above | below
    
    current_price = get_crypto_price(coin_id)
    if current_price is None:
        return jsonify({"error": "Price unavailable"}), 503
    
    if direction == 'above':
        won = current_price >= target_price
    else:
        won = current_price <= target_price
    
    winning_option = 'Yes' if won else 'No'
    
    if bet['status'] == 'active':
        bet['status'] = 'voting'
        resolve_bet(bet_id, winning_option)
    
    return jsonify({"current_price": current_price, "target_price": target_price, 
                    "winner": winning_option, "bet": bets[bet_id]})

# ─── Routes: Treasury ──────────────────────────────────────────────────────

@app.route('/api/treasury', methods=['GET'])
def get_treasury():
    return jsonify({
        **treasury,
        "admin_wallet": ADMIN_WALLET,
        "recent_transactions": transactions[-20:]
    })

# ─── Routes: Charts ────────────────────────────────────────────────────────

@app.route('/api/prices', methods=['GET'])
def get_prices():
    coins = ['bitcoin', 'ethereum', 'the-open-network']
    prices = {}
    for c in coins:
        prices[c] = get_crypto_price(c)
    return jsonify(prices)

# ─── Core Logic ────────────────────────────────────────────────────────────

def resolve_bet(bet_id: str, winning_option: str):
    bet = bets.get(bet_id)
    if not bet:
        return
    
    bet['status'] = 'resolved'
    bet['resolved_option'] = winning_option
    bet['resolved_at'] = datetime.utcnow().isoformat()
    
    total_pool = bet['total_pool']
    winning_pool = bet['stakes'].get(winning_option, 0)
    
    if winning_pool == 0:
        return
    
    # Distribute winnings
    for p in bet['participants'].get(winning_option, []):
        user_id = p['user_id']
        stake = p['amount']
        share = stake / winning_pool
        payout = int(total_pool * share * (1 - PLATFORM_FEE))
        
        if user_id in users:
            users[user_id]['balance'] += payout
            users[user_id]['total_won'] += payout
            transactions.append({
                "type": "payout",
                "user_id": user_id,
                "bet_id": bet_id,
                "amount": payout,
                "timestamp": datetime.utcnow().isoformat()
            })

# ─── Demo data ─────────────────────────────────────────────────────────────

def seed_demo():
    global bet_counter
    ensure_user(99999, "alice")
    ensure_user(88888, "bob")
    users[99999]['balance'] = 500
    users[88888]['balance'] = 300
    
    demo_bets = [
        {
            "title": "BTC выше $100k до конца июня?",
            "description": "Достигнет ли Bitcoin отметки $100,000 USD до 30 июня 2026?",
            "category": "crypto",
            "options": ["Да", "Нет"],
            "oracle_type": "price",
            "oracle_params": {"coin_id": "bitcoin", "target_price": 100000, "direction": "above"},
            "status": "active",
            "stakes": {"Да": 420, "Нет": 180},
            "total_pool": 600,
            "end_time": (datetime.utcnow() + timedelta(days=14)).isoformat()
        },
        {
            "title": "TON войдёт в топ-5 по капитализации?",
            "description": "Попадёт ли TON в топ-5 криптовалют по рыночной капитализации до конца 2026?",
            "category": "crypto",
            "options": ["Да", "Нет"],
            "status": "active",
            "stakes": {"Да": 310, "Нет": 290},
            "total_pool": 600,
            "end_time": (datetime.utcnow() + timedelta(days=60)).isoformat()
        },
        {
            "title": "Завтра в Москве будет дождь?",
            "description": "Выпадут ли осадки в Москве 18 мая 2026?",
            "category": "weather",
            "options": ["Да", "Нет"],
            "status": "active",
            "stakes": {"Да": 150, "Нет": 250},
            "total_pool": 400,
            "end_time": (datetime.utcnow() + timedelta(days=1)).isoformat()
        },
    ]
    
    for i, bd in enumerate(demo_bets):
        bid = f"bet_{bet_counter}"
        bet_counter += 1
        bet = {
            "id": bid,
            "creator_id": 99999,
            "creator": "alice",
            "votes": {},
            "participants": {opt: [] for opt in bd['options']},
            "resolved_option": None,
            "approved_by": "admin",
            "created_at": (datetime.utcnow() - timedelta(hours=i*3)).isoformat(),
            **bd
        }
        if "oracle_params" not in bet:
            bet["oracle_params"] = {}
        bets[bid] = bet

seed_demo()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
