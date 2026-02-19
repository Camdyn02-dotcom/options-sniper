import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import os
import time

# -----------------------------
# Streamlit Settings
# -----------------------------
st.set_page_config(layout="wide")
st.title("Aggressive Monthly Options Sniper")

# -----------------------------
# Market Universe Settings
# -----------------------------
UNIVERSE_FILE = "market_universe.csv"
CACHE_DIR = "cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def build_universe():
    liquidity_core = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
        "AMD","NFLX","AVGO","JPM","BAC","XOM","CVX",
        "UNH","LLY","HD","COST","WMT","KO","PEP",
        "INTC","CSCO","ADBE","CRM","PYPL","ORCL",
        "SPY","QQQ","IWM","DIA"
    ]
    qualified = []
    for ticker in liquidity_core:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="60d")
            if len(hist) < 40:
                continue
            avg_volume = hist["Volume"].mean()
            price = hist["Close"].iloc[-1]
            if avg_volume > 500_000 and 5 < price < 800:
                qualified.append(ticker)
        except:
            continue
    df_universe = pd.DataFrame({"Ticker": qualified})
    df_universe.to_csv(UNIVERSE_FILE, index=False)
    return qualified

# Load or build universe
if os.path.exists(UNIVERSE_FILE):
    tickers = pd.read_csv(UNIVERSE_FILE)["Ticker"].tolist()
else:
    tickers = build_universe()
st.write(f"Universe Size: {len(tickers)}")

# -----------------------------
# Market Regime & Volatility
# -----------------------------
spy = yf.Ticker("SPY")
spy_hist = spy.history(period="6mo")
spy_return = spy_hist["Close"].pct_change(60).iloc[-1]

if spy_hist["Close"].ewm(span=50).mean().iloc[-1] > spy_hist["Close"].ewm(span=200).mean().iloc[-1]:
    market_trend = "Bull"
else:
    market_trend = "Bear"

volatility = spy_hist["Close"].pct_change().rolling(20).std().iloc[-1]
MIN_DTE = 20 if volatility > 0.025 else 30
MAX_DTE = 35 if volatility > 0.025 else 50

CALL_WEIGHT = 1.5 if market_trend == "Bull" else 1.0
PUT_WEIGHT  = 0.9 if market_trend == "Bull" else 1.4

# -----------------------------
# Options Scoring Functions
# -----------------------------
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def score_stock(hist):
    hist["ema50"] = hist["Close"].ewm(span=50).mean()
    hist["ema200"] = hist["Close"].ewm(span=200).mean()
    hist["rsi"] = compute_rsi(hist["Close"])
    hist["atr"] = hist["High"] - hist["Low"]
    score = 0
    if hist["ema50"].iloc[-1] > hist["ema200"].iloc[-1]:
        score += 3
    if 55 <= hist["rsi"].iloc[-1] <= 70:
        score += 2
    if hist["atr"].iloc[-1] > hist["atr"].rolling(20).mean().iloc[-1]:
        score += 2
    recent_high = hist["High"].rolling(20).max().iloc[-2]
    if hist["Close"].iloc[-1] > recent_high:
        score += 4
    recent_vol = hist["Close"].pct_change().rolling(10).std().iloc[-1]
    long_vol = hist["Close"].pct_change().rolling(30).std().iloc[-1]
    if recent_vol > long_vol * 1.5:
        score += 3
    stock_return = hist["Close"].pct_change(60).iloc[-1]
    if stock_return > spy_return:
        score += 3
    return score

# -----------------------------
# Scan Options
# -----------------------------
all_options = []
initial_capital = 500
capital_sim = initial_capital
portfolio = []

for ticker in tickers:
    try:
        stock = yf.Ticker(ticker)
        hist_file = f"{CACHE_DIR}/{ticker}.csv"
        if os.path.exists(hist_file):
            hist = pd.read_csv(hist_file, index_col=0, parse_dates=True)
        else:
            hist = stock.history(period="6mo")
            hist.to_csv(hist_file)

        if len(hist) < 60:
            continue

        stock_score = score_stock(hist)
        current_price = hist["Close"].iloc[-1]

        # Earnings proximity
        try:
            cal = stock.calendar
            earnings_date = cal.index[0] if not cal.empty else None
        except:
            earnings_date = None

        for exp in stock.options:
            exp_date = datetime.datetime.strptime(exp,"%Y-%m-%d")
            dte = (exp_date - datetime.datetime.today()).days
            if not (MIN_DTE <= dte <= MAX_DTE):
                continue
            earnings_boost = 0
            if earnings_date is not None:
                days_to_earnings = (earnings_date - datetime.datetime.today()).days
                if 0 < days_to_earnings <= dte:
                    earnings_boost = 3

            chain = stock.option_chain(exp)

            for typ, df in [("CALL", chain.calls), ("PUT", chain.puts)]:
                weight = CALL_WEIGHT if typ=="CALL" else PUT_WEIGHT
                for _, row in df.iterrows():
                    option_score = stock_score * weight
                    option_score += row.get("volume",0)/1000 + earnings_boost
                    delta_val = abs(row.get("delta",0.4))
                    if 0.35 <= delta_val <= 0.55:
                        option_score += 3
                    elif delta_val < 0.25:
                        option_score -= 2
                    if row.get("volume",0) > 1000:
                        option_score += 3
                    if row.get("openInterest",0) > 2000:
                        option_score += 2
                    if row.get("openInterest",0) > 5000 and row.get("volume",0) > 2000:
                        option_score += 4
                    contract_cost = row["lastPrice"]*100
                    if contract_cost > 250:
                        continue
                    all_options.append({
                        "Ticker": ticker,
                        "Type": typ,
                        "Expiration": exp,
                        "Strike": row["strike"],
                        "StockPrice": current_price,
                        "Bid": row["bid"],
                        "Ask": row["ask"],
                        "LastPrice": row["lastPrice"],
                        "Volume": row.get("volume",0),
                        "OpenInterest": row.get("openInterest",0),
                        "DTE": dte,
                        "Score": option_score
                    })

        time.sleep(0.1)  # light throttle

    except:
        continue

df = pd.DataFrame(all_options)
df = df[df["Score"] > 6]
df = df.sort_values("Score", ascending=False)

top_calls = df[df["Type"]=="CALL"].head(5)
top_puts  = df[df["Type"]=="PUT"].head(5)

st.markdown("### Top Market Options")
st.write(f"Market Regime: {market_trend}, Volatility: {round(volatility,4)}")
st.subheader("Top 5 CALLS")
st.dataframe(top_calls, use_container_width=True)
st.subheader("Top 5 PUTS")
st.dataframe(top_puts, use_container_width=True)

# -----------------------------
# Dashboard Metrics
# -----------------------------
st.markdown("## Market Summary Metrics")
total_contracts = len(df)
avg_score = df["Score"].mean() if not df.empty else 0
top_score = df["Score"].max() if not df.empty else 0
col1, col2, col3 = st.columns(3)
col1.metric("Contracts Scanned", total_contracts)
col2.metric("Average Score", round(avg_score,2))
col3.metric("Top Score Today", round(top_score,2))

# -----------------------------
# Daily Snapshot Export
# -----------------------------
if st.button("Save Today's Snapshot"):
    filename = f"options_snapshot_{datetime.datetime.today().strftime('%Y%m%d')}.csv"
    df.to_csv(filename, index=False)
    st.success(f"Snapshot saved as {filename}")

# -----------------------------
# Portfolio Allocation (Risk-Based)
# -----------------------------
st.markdown("## Portfolio Simulation ($500 Aggressive)")

capital = 500
allocation = []

top_combined = df.head(5)  # top 5 contracts

for _, row in top_combined.iterrows():
    contract_price = row["LastPrice"]*100
    if row["Score"] >= 15:
        alloc_pct = 0.4
    elif row["Score"] >= 10:
        alloc_pct = 0.3
    else:
        alloc_pct = 0.2
    max_alloc = capital * alloc_pct
    if contract_price <= max_alloc:
        contracts = int(max_alloc // contract_price)
        if contracts > 0:
            total_cost = contracts*contract_price
            allocation.append({
                "Ticker": row["Ticker"],
                "Type": row["Type"],
                "Strike": row["Strike"],
                "Expiration": row["Expiration"],
                "Contracts": contracts,
                "Total Cost": round(total_cost,2)
            })
            capital -= total_cost

if allocation:
    sim_df = pd.DataFrame(allocation)
    st.dataframe(sim_df, use_container_width=True)
    st.write(f"Remaining Capital: ${round(capital,2)}")
else:
    st.write("No contracts fit capital allocation rules today.")

# -----------------------------
# Historical 90-Day Backtest
# -----------------------------
st.markdown("## Historical Backtest (90-Day Rolling)")

if st.button("Run 90 Day Backtest"):
    capital_bt = 500
    wins = 0
    losses = 0
    trades = 0
    end_date = datetime.datetime.today()
    start_date = end_date - datetime.timedelta(days=120)

    for ticker in tickers:
        try:
            hist = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if len(hist) < 30:
                continue
            for i in range(10, len(hist)-5):
                entry = hist["Close"].iloc[i]
                exit = hist["Close"].iloc[i+5]
                pct_move = (exit-entry)/entry
                if abs(pct_move) > 0.02:
                    pos_size = capital_bt*0.2
                    pnl = pos_size*pct_move
                    capital_bt += pnl
                    trades +=1
                    if pnl>0: wins+=1
                    else: losses+=1
        except:
            continue

    if trades>0:
        win_rate = wins/trades
        total_return = (capital_bt-500)/500
        st.write(f"Trades Simulated: {trades}")
        st.write(f"Win Rate: {round(win_rate*100,2)}%")
        st.write(f"Total Return: {round(total_return*100,2)}%")
        st.write(f"Ending Capital: ${round(capital_bt,2)}")
    else:
        st.write("No qualifying trades found.")
