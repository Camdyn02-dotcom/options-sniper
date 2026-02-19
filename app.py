import streamlit as st
import pandas as pd
import datetime
import os
from polygon import RESTClient
import time

# -----------------------------
# CONFIG
# -----------------------------
POLY_KEY = "hpUPn03weRAxrRp2Z0aBli3fSIjXi6xh"
client = RESTClient(POLY_KEY)

INITIAL_CAPITAL = 500
MIN_DTE = 7
MAX_DTE = 45
CALL_WEIGHT = 1.2
PUT_WEIGHT = 1.0
CACHE_DIR = "cache"

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

st.set_page_config(layout="wide")
st.title("Aggressive Monthly Options Sniper (Polygon.io)")

# -----------------------------
# Universe (top 200 tickers)
# -----------------------------
UNIVERSE_FILE = "market_universe.csv"

def build_universe():
    # Hard-coded top tickers by liquidity / volume
    tickers = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
        "AMD","NFLX","AVGO","JPM","BAC","XOM","CVX",
        "UNH","LLY","HD","COST","WMT","KO","PEP",
        "INTC","CSCO","ADBE","CRM","PYPL","ORCL",
        "SPY","QQQ","IWM","DIA",
        # add more until 200
    ]
    # For demo: repeat list to reach ~200
    tickers = (tickers * 6)[:200]
    df = pd.DataFrame({"Ticker": tickers})
    df.to_csv(UNIVERSE_FILE, index=False)
    return tickers

if os.path.exists(UNIVERSE_FILE):
    tickers = pd.read_csv(UNIVERSE_FILE)["Ticker"].tolist()
else:
    tickers = build_universe()

st.write(f"Universe Size: {len(tickers)} tickers")

# -----------------------------
# Polygon Option Chain Fetch
# -----------------------------
def fetch_option_chain(symbol, min_dte=MIN_DTE):
    today = datetime.datetime.today()
    options_data = []

    try:
        snapshot = client.get_snapshot_options_underlying(symbol)

        for opt in snapshot.get('options', []):
            exp_date = datetime.datetime.strptime(opt['expiration_date'], '%Y-%m-%d')
            dte = (exp_date - today).days
            if dte < min_dte:
                continue

            options_data.append({
                "Ticker": symbol,
                "Type": opt['contract_type'].upper(),
                "Strike": opt['strike_price'],
                "Expiration": exp_date.strftime("%Y-%m-%d"),
                "LastPrice": opt.get('last_quote', {}).get('price', 0),
                "Bid": opt.get('last_quote', {}).get('bid', 0),
                "Ask": opt.get('last_quote', {}).get('ask', 0),
                "Volume": opt.get('day', {}).get('volume', 0),
                "OpenInterest": opt.get('open_interest', 0),
                "IV": opt.get('implied_volatility', 0),
                "Delta": opt.get('greeks', {}).get('delta', 0.4)
            })

        return pd.DataFrame(options_data)

    except Exception as e:
        print(f"{symbol} failed: {e}")
        return pd.DataFrame()

# -----------------------------
# SCORING FUNCTION
# -----------------------------
def score_option(row, stock_score, call_weight=CALL_WEIGHT, put_weight=PUT_WEIGHT):
    score = stock_score
    # Delta scoring
    delta_val = abs(row.get("Delta", 0.4))
    if 0.35 <= delta_val <= 0.55:
        score += 3
    elif delta_val < 0.25:
        score -= 2

    # Volume/OI
    if row.get("Volume", 0) > 1000:
        score += 2
    if row.get("OpenInterest", 0) > 2000:
        score += 2
    if row.get("OpenInterest", 0) > 5000 and row.get("Volume", 0) > 2000:
        score += 4

    # Type weighting
    if row["Type"] == "CALL":
        score *= call_weight
    else:
        score *= put_weight

    return score

# -----------------------------
# FETCH & SCORE ALL OPTIONS
# -----------------------------
all_options = []
portfolio = []
capital_sim = INITIAL_CAPITAL

for ticker in tickers:
    df_chain = fetch_option_chain(ticker)
    if df_chain.empty:
        continue

    # Simple stock score (momentum proxy)
    stock_score = 5  # can enhance later with RSI, EMA, ATR

    for _, row in df_chain.iterrows():
        row_score = score_option(row, stock_score)
        if row_score < 3:
            continue  # skip low scoring options

        all_options.append({**row, "Score": row_score})

        # Portfolio simulation
        contract_cost = row["LastPrice"] * 100
        if row_score >= 5 and capital_sim >= contract_cost:
            portfolio.append({
                "Ticker": row["Ticker"],
                "Type": row["Type"],
                "Strike": row["Strike"],
                "Expiration": row["Expiration"],
                "Contracts": 1,
                "TotalCost": contract_cost,
                "Score": row_score
            })
            capital_sim -= contract_cost

    time.sleep(0.1)  # throttle

df_options = pd.DataFrame(all_options)
df_options = df_options.sort_values("Score", ascending=False)

# -----------------------------
# TOP 5 CALLS / PUTS
# -----------------------------
top_calls = df_options[df_options["Type"]=="CALL"].head(5)
top_puts = df_options[df_options["Type"]=="PUT"].head(5)

st.subheader("Top 5 CALLS")
st.dataframe(top_calls, use_container_width=True)

st.subheader("Top 5 PUTS")
st.dataframe(top_puts, use_container_width=True)

# -----------------------------
# PORTFOLIO SIMULATION DISPLAY
# -----------------------------
st.subheader("Portfolio Simulation")
if portfolio:
    sim_df = pd.DataFrame(portfolio)
    st.dataframe(sim_df, use_container_width=True)
    st.write(f"Remaining Capital: ${round(capital_sim,2)}")
else:
    st.write("No contracts fit capital allocation rules today.")

# -----------------------------
# DASHBOARD METRICS
# -----------------------------
st.subheader("Dashboard Metrics")
st.metric("Contracts Scanned", len(df_options))
st.metric("Capital Remaining", f"${round(capital_sim,2)}")
st.metric("Top Score Today", round(df_options["Score"].max() if not df_options.empty else 0,2))

# -----------------------------
# SNAPSHOT EXPORT
# -----------------------------
if st.button("Save Today's Snapshot"):
    filename = f"options_snapshot_{datetime.datetime.today().strftime('%Y%m%d')}.csv"
    df_options.to_csv(filename, index=False)
    st.success(f"Snapshot saved as {filename}")

# -----------------------------
# TRADE LOGGER
# -----------------------------
st.subheader("Trade Logger")
if "trade_log" not in st.session_state:
    st.session_state.trade_log = []

col1, col2, col3, col4 = st.columns(4)

with col1:
    log_ticker = st.text_input("Ticker")
with col2:
    log_entry = st.number_input("Entry Price", min_value=0.0)
with col3:
    log_exit = st.number_input("Exit Price", min_value=0.0)
with col4:
    if st.button("Log Trade"):
        pnl = log_exit - log_entry
        st.session_state.trade_log.append({
            "Ticker": log_ticker,
            "Entry": log_entry,
            "Exit": log_exit,
            "PnL": pnl
        })

if st.session_state.trade_log:
    trade_df = pd.DataFrame(st.session_state.trade_log)
    st.dataframe(trade_df, use_container_width=True)
    st.write(f"Win Rate: {round(len(trade_df[trade_df['PnL']>0])/len(trade_df)*100,2)}%")
    st.write(f"Average PnL: {round(trade_df['PnL'].mean(),2)}")
