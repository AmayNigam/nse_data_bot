import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
import io
import time
import math

# PASTE YOUR NEW DEPLOYMENT URL HERE
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzuPew_P8sl2JpqQ64Y3IzX6eotm7Qkrhm9U-_ohD3VNg9j5v4VY21JT7NPPT4DOrHcxQ/exec"

def sanitize(val):
    try:
        val = float(val)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return round(val, 2)
    except (ValueError, TypeError):
        return 0.0

print("Fetching dynamic master list from NSE Archives...")
session = requests.Session()
headers = {'User-Agent': 'Mozilla/5.0'}

session.get("https://www.nseindia.com", headers=headers, timeout=10)
csv_url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
response = session.get(csv_url, headers=headers, timeout=15)

df_nse = pd.read_csv(io.StringIO(response.text))
df_nse.columns = df_nse.columns.str.strip()
symbols = df_nse[df_nse['SERIES'] == 'EQ']['SYMBOL'].tolist()
total_stocks = len(symbols)

timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
yf_session = requests.Session()
yf_session.headers.update(headers)

buffer = []
BATCH_SIZE = 200
is_first_batch = True  # Tells Google to overwrite the old data

for i in range(0, total_stocks, BATCH_SIZE):
    chunk = symbols[i:i + BATCH_SIZE]
    yf_symbols = [f"{sym}.NS" for sym in chunk]
    
    print(f"Downloading batch: [{i+1} to {min(i+BATCH_SIZE, total_stocks)}]")
    data = yf.download(yf_symbols, period="3mo", group_by="ticker", 
                       session=yf_session, threads=True, progress=False)
    
    for sym in chunk:
        yf_sym = f"{sym}.NS"
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if yf_sym not in data.columns.levels[0]:
                    continue
                hist = data[yf_sym]
            else:
                hist = data
                
            hist = hist.dropna(subset=['Close', 'Volume'])
            if hist.empty or len(hist) < 1:
                continue
                
            turnover = hist['Volume'] * hist['Close']
            last_price = sanitize(hist['Close'].iloc[-1])
            
            if last_price == 0.0:
                continue
                
            t_1d = sanitize(turnover.iloc[-1] / 10000000)
            t_1w = sanitize(turnover.iloc[-5:].sum() / 10000000)
            t_1m = sanitize(turnover.iloc[-21:].sum() / 10000000)
            t_3m = sanitize(turnover.sum() / 10000000)
            
            buffer.append([timestamp, sym, last_price, t_1d, t_1w, t_1m, t_3m])
            
        except Exception:
            continue
            
    if len(buffer) >= 100 or i + BATCH_SIZE >= total_stocks:
        if len(buffer) > 0:
            payload = {"rows": buffer}
            
            # Send the wipe command only on the very first upload
            if is_first_batch:
                payload["clear"] = True
                is_first_batch = False
                
            try:
                res = requests.post(WEBHOOK_URL, json=payload, timeout=30)
                print(f"-> PUSHED {len(buffer)} stocks to Sheets. (Status: {res.status_code})")
            except Exception as e:
                print(f"-> Push failed: {e}")
            buffer = []
            
    time.sleep(2)

print("\nUpdate complete. All stocks processed successfully.")
