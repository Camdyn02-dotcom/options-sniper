# =============================
# app.py — Full Options Sniper App
# =============================

import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import os
import time

# -----------------------------
# Settings
# -----------------------------
UNIVERSE_FILE = "market_universe.csv"
CACHE_DIR = "cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

initial_capital = 500
top_n_contracts = 5  # number of top calls/puts per ticker to allocate

# -----------------------------
# Build / Load Market Universe
# -----------------------------
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

# Load universe
if os.path.exists(UNIVERSE_FILE):
    tickers = pd.read_csv(UNIVERSE_FILE)["Ticker"].tolist()
else:
    tickers = build_universe()

st.write("Universe Size:", len(tickers))

# -----------------------------
# OPTIONS SCANNER + TOP CONTRACTS + PORTFOLIO
# -----------------------------
st.markdown("## Options Scanner & Portfolio Simulation")

all_options = []
capital_sim = initial_capital
portfolio = []

for ticker in tickers:
    try:
        # --------------------------
        # Fetch options safely
        # --------------------------
        opt = yf.Ticker(ticker)
        expirations = opt.options
        if not expirations:
            continue
        exp = expirations[0]
        chain = opt.option_chain(exp)
        calls, puts = chain.calls, chain.puts

        # --------------------------
        # Fetch historical data with caching
        # --------------------------
        hist_file = f"{CACHE_DIR}/{ticker}.csv"
        if os.path.exists(hist_file):
            hist = pd.read_csv(hist_file, index_col=0, parse_dates=True)
        else:
            hist = yf.Ticker(ticker).history(period="60d")
            hist.to_csv(hist_file)
        if hist.empty:
            continue
        high20 = hist["High"].max()

        # --------------------------
        # Process contracts
        # --------------------------
        for df, typ in [(calls, "Call"), (puts, "Put")]:
            for _, row in df.iterrows():
                try:
                    score = 0

                    # Momentum / liquidity
                    if row.get("volume",0) > 2000:
                        score += 2
                    if row.get("openInterest",0) > 5000:
                        score += 3

                    # Delta scoring
                    delta_val = abs(row.get("delta",0.4))
                    if 0.35 <= delta_val <= 0.55:
                        score += 3
                    elif delta_val < 0.25:
                        score -= 2

                    # IV spike
                    if "impliedVolatility" in row and row["impliedVolatility"] > 0.5:
                        score += 2

                    # Breakout detection
                    if row["strike"] > high20:
                        score += 1

                    # Append to all_options
                    all_options.append({
                        "Ticker": ticker,
                        "Type": typ,
                        "Strike": row["strike"],
                        "Expiration": exp,
                        "LastPrice": row["lastPrice"],
                        "Volume": row.get("volume",0),
                        "OpenInterest": row.get("openInterest",0),
                        "Delta": delta_val,
                        "IV": row.get("impliedVolatility",0),
                        "Score": score
                    })

                except:
                    continue

        # --------------------------
        # Throttle to avoid rate limit
        # --------------------------
        time.sleep(0.5)

    except Exception as e:
        print(f"{ticker} failed: {e}")
        continue

# -----------------------------
# Convert to dataframe
# -----------------------------
df = pd.DataFrame(all_options)

# -----------------------------
# Top 5 Calls / Puts
# -----------------------------
top_calls = df[df["Type"]=="Call"].sort_values(by="Score", ascending=False).head(top_n_contracts)
top_puts  = df[df["Type"]=="Put"].sort_values(by="Score", ascending=False).head(top_n_contracts)

st.markdown("### Top 5 Calls")
st.dataframe(top_calls[["Ticker","Strike","Expiration","LastPrice","Volume","OpenInterest","Delta","IV","Score"]], use_container_width=True)

st.markdown("### Top 5 Puts")
st.dataframe(top_puts[["Ticker","Strike","Expiration","LastPrice","Volume","OpenInterest","Delta","IV","Score"]], use_container_width=True)

# -----------------------------
# Portfolio simulation using top contracts
# -----------------------------
top_contracts = pd.concat([top_calls, top_puts])

for _, contract in top_contracts.iterrows():
    if capital_sim <= 0:
        break
    entry_price = contract["LastPrice"]
    if entry_price <= 0:
        continue
    position_size = min(capital_sim*0.2, entry_price*1)
    portfolio.append({
        "Ticker": contract["Ticker"],
        "Type": contract["Type"],
        "Strike": contract["Strike"],
        "Expiration": contract["Expiration"],
        "EntryPrice": entry_price,
        "Score": contract["Score"],
        "PositionSize": position_size
    })
    capital_sim -= position_size

# -----------------------------
# Display main options table
# -----------------------------
st.dataframe(df, use_container_width=True)

# -----------------------------
# Dashboard metrics
# -----------------------------
st.markdown("## Dashboard Metrics")
total_contracts = len(df)
avg_score = df["Score"].mean() if not df.empty else 0
top_score = df["Score"].max() if not df.empty else 0
capital_remaining = capital_sim

col1, col2, col3, col4 = st.columns(4)
col1.metric("Contracts Scanned", total_contracts)
col2.metric("Average Score", round(avg_score,2))
col3.metric("Top Score Today", top_score)
col4.metric("Capital Remaining", f"${round(capital_remaining,2)}")

# -----------------------------
# Save daily snapshot
# -----------------------------
if st.button("Save Today's Snapshot"):
    df.to_csv(f"options_snapshot_{datetime.datetime.today().strftime('%Y%m%d')}.csv", index=False)
    st.success("Snapshot saved successfully.")

# -----------------------------
# 90-Day Rolling Backtest
# -----------------------------
st.markdown("## 90-Day Backtest Simulation")
if st.button("Run 90 Day Backtest"):

    capital_bt = initial_capital
    wins = 0
    losses = 0
    trades = 0

    for ticker in tickers:
        try:
            hist_file = f"{CACHE_DIR}/{ticker}.csv"
            if os.path.exists(hist_file):
                hist = pd.read_csv(hist_file, index_col=0, parse_dates=True)
            else:
                hist = yf.Ticker(ticker).history(period="120d")
                hist.to_csv(hist_file)

            if len(hist) < 20:
                continue

            # Rolling 5-day simulation
            for i in range(10, len(hist)-5):
                entry = hist["Close"].iloc[i]
                exit = hist["Close"].iloc[i+5]
                pct_move = (exit - entry)/entry

                if abs(pct_move) > 0.01:
                    position_size = capital_bt*0.2
                    pnl = position_size * pct_move
                    capital_bt += pnl
                    trades += 1
                    if pnl > 0:
                        wins += 1
                    else:
                        losses += 1

        except:
            continue

    if trades > 0:
        win_rate = wins / trades
        total_return = (capital_bt - initial_capital)/initial_capital
        st.write(f"Trades Simulated: {trades}")
        st.write(f"Win Rate: {round(win_rate*100,2)}%")
        st.write(f"Total Return: {round(total_return*100,2)}%")
        st.write(f"Ending Capital: ${round(capital_bt,2)}")
    else:
        st.write("No qualifying trades found.")
