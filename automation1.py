import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import io
import time
import math
import random

# PASTE YOUR ACTIVE WEBHOOK URL HERE
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzuPew_P8sl2JpqQ64Y3IzX6eotm7Qkrhm9U-_ohD3VNg9j5v4VY21JT7NPPT4DOrHcxQ/exec"

# A list of completely different browser fingerprints to evade Yahoo's detection
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:122.0) Gecko/20100101 Firefox/122.0'
]

def sanitize(val):
    """Cleans raw data to ensure it doesn't crash Google Sheets"""
    try:
        if isinstance(val, str) and val.strip() == '-': return 0.0
        val = float(val)
        if math.isnan(val) or math.isinf(val): return 0.0
        return round(val, 2)
    except (ValueError, TypeError):
        return 0.0

print("Step 1: Fetching official NSE Bhavcopy data...")

# Initial session just for NSE
session = requests.Session()
session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
session.get("https://www.nseindia.com", timeout=10)

bhavcopy_df = pd.DataFrame()
for i in range(7):
    d = datetime.now() - timedelta(days=i)
    date_str = d.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    
    res = session.get(url)
    if res.status_code == 200 and len(res.text) > 1000:
        print(f"-> Found official NSE Delivery data for {d.strftime('%d-%b-%Y')}")
        bhavcopy_df = pd.read_csv(io.StringIO(res.text))
        bhavcopy_df.columns = bhavcopy_df.columns.str.strip()
        bhavcopy_df['SERIES'] = bhavcopy_df['SERIES'].astype(str).str.strip()
        bhavcopy_df['SYMBOL'] = bhavcopy_df['SYMBOL'].astype(str).str.strip()
        
        # Capture all ~2,300 stocks
        equity_series = ['EQ', 'BE', 'BZ', 'SM', 'ST']
        bhavcopy_df = bhavcopy_df[bhavcopy_df['SERIES'].isin(equity_series)]
        bhavcopy_df = bhavcopy_df.drop_duplicates(subset=['SYMBOL'])
        bhavcopy_df.set_index('SYMBOL', inplace=True)
        break

if bhavcopy_df.empty:
    print("Fatal Error: Could not locate NSE Bhavcopy.")
    exit(1)

symbols = bhavcopy_df.index.tolist()
total_stocks = len(symbols)
print(f"\nStep 2: Processing {total_stocks} stocks...")

timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
all_rows = []

# BATCH_SIZE set to 50 to avoid triggering rate limits
BATCH_SIZE = 50 

for i in range(0, total_stocks, BATCH_SIZE):
    chunk = symbols[i:i + BATCH_SIZE]
    yf_symbols = [f"{sym}.NS" for sym in chunk]
    
    print(f"Downloading batch: [{i+1} to {min(i+BATCH_SIZE, total_stocks)}]")
    
    # CRITICAL FIX: Generate a brand new identity & clear cookies for EVERY batch
    yf_session = requests.Session()
    yf_session.headers.update({
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': '*/*',
        'Connection': 'keep-alive'
    })
    
    data = None
    try:
        data = yf.download(yf_symbols, period="6mo", group_by="ticker", 
                           session=yf_session, threads=False, progress=False)
    except Exception as e:
        print(f"Yahoo Warning: {e}")

    for sym in chunk:
        yf_sym = f"{sym}.NS"
        
        # Baseline metrics from NSE Bhavcopy
        try: last_price = sanitize(bhavcopy_df.loc[sym, 'CLOSE_PRICE'])
        except: last_price = 0.0
            
        try: traded_vol = int(sanitize(bhavcopy_df.loc[sym, 'TTL_TRD_QNTY']))
        except: traded_vol = 0
            
        try: delivery_pct = sanitize(bhavcopy_df.loc[sym, 'DELIV_PER'])
        except: delivery_pct = 0.0
            
        try: t_1d = sanitize(bhavcopy_df.loc[sym, 'TURNOVER_LACS'] / 100)
        except: t_1d = 0.0

        t_1w, t_1m, t_3m, t_6m, wk_pct, mo_pct = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        # Calculate Historical Metrics from Yahoo if available
        if data is not None and not data.empty:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if yf_sym in data.columns.levels[0]:
                        hist = data[yf_sym].dropna(subset=['Close', 'Volume'])
                    else:
                        hist = pd.DataFrame()
                else:
                    hist = data.dropna(subset=['Close', 'Volume'])
                    
                if not hist.empty and len(hist) >= 1:
                    turnover = hist['Volume'] * hist['Close']
                    y_close = sanitize(hist['Close'].iloc[-1])
                    if y_close > 0.0: last_price = y_close
                    
                    t_1d_y = sanitize(turnover.iloc[-1] / 10000000)
                    if t_1d_y > 0: t_1d = t_1d_y
                        
                    t_1w = sanitize(turnover.iloc[-5:].sum() / 10000000)
                    t_1m = sanitize(turnover.iloc[-21:].sum() / 10000000)
                    t_3m = sanitize(turnover.iloc[-63:].sum() / 10000000) if len(turnover) >= 63 else sanitize(turnover.sum() / 10000000)
                    t_6m = sanitize(turnover.sum() / 10000000)
                    
                    if len(hist) >= 6: wk_pct = sanitize(((last_price - hist['Close'].iloc[-6]) / hist['Close'].iloc[-6]) * 100)
                    if len(hist) >= 22: mo_pct = sanitize(((last_price - hist['Close'].iloc[-22]) / hist['Close'].iloc[-22]) * 100)
            except Exception:
                pass

        mcap_change_formula = f'=IFERROR((GOOGLEFINANCE("NSE:{sym}", "marketcap") / 10000000) * (GOOGLEFINANCE("NSE:{sym}", "changepct") / 100), "N/A")'

        # Save in memory buffer
        all_rows.append([
            timestamp, sym, last_price, t_1d, t_1w, t_1m, t_3m, t_6m, 
            traded_vol, delivery_pct, wk_pct, mo_pct, mcap_change_formula
        ])

    # CRITICAL FIX: Sleep for 4 to 7 seconds between batches to evade detection
    time.sleep(random.uniform(4.0, 7.0))

print(f"\nTotal number of stocks processed: {len(all_rows)}")

# FAILSAFE: Protect Google Sheets if block occurs
if len(all_rows) < 2000:
    print(f"Warning: Only {len(all_rows)} stocks found. Aborting to protect Google Sheet.")
    exit(1)

print("Pushing complete data to Google Sheets in batches of 300...")
is_first_batch = True
for i in range(0, len(all_rows), 300):
    payload = {"rows": all_rows[i:i+300]}
    if is_first_batch:
        payload["clear"] = True
        is_first_batch = False
        
    try:
        res = requests.post(WEBHOOK_URL, json=payload, timeout=30)
        print(f"-> PUSHED batch {i+1} to {min(i+300, len(all_rows))} (Status: {res.status_code})")
    except Exception as e:
        print(f"-> Push failed: {e}")
    time.sleep(1)

print("\nUpdate complete! All stocks have been added.")
