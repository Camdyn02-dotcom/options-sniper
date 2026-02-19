import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime
import os
UNIVERSE_FILE = "market_universe.csv"
def build_universe():
 if os.path.exists(UNIVERSE_FILE):
    tickers = pd.read_csv(UNIVERSE_FILE)["Ticker"].tolist()
 else:
    tickers = build_universe()
    # Use major US ETFs to pull large holdings
    seed_etfs = ["SPY", "QQQ", "IWM", "DIA"]

    all_symbols = set()

    for etf in seed_etfs:
        try:
            holdings = yf.Ticker(etf).history(period="1d")
            all_symbols.add(etf)
        except:
            continue

    # Hard-seed high liquidity list (top traded names)
    liquidity_core = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
        "AMD","NFLX","AVGO","JPM","BAC","XOM","CVX",
        "UNH","LLY","HD","COST","WMT","KO","PEP",
        "INTC","CSCO","ADBE","CRM","PYPL","ORCL",
        "SPY","QQQ","IWM","DIA""NVDA","AMD","TSLA","META","AAPL","COIN",
    "AMZN","MSFT","GOOGL","NFLX","PLTR","SHOP"
    ]

    all_symbols.update(liquidity_core)

    qualified = []

    for ticker in all_symbols:

        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="60d")

            if len(hist) < 40:
                continue

            avg_volume = hist["Volume"].mean()
            price = hist["Close"].iloc[-1]

            if avg_volume > 500000 and 5 < price < 800:
                qualified.append(ticker)

        except:
            continue
 df_universe = pd.DataFrame({"Ticker": qualified})
 df_universe.to_csv(UNIVERSE_FILE, index=False)
        
 return qualified

st.set_page_config(layout="wide")
st.title("Aggressive Monthly Options Sniper")

MIN_DTE = 30
MAX_DTE = 45
CALL_WEIGHT = 1.2
PUT_WEIGHT = 1.0

# =============================
# MARKET ENGINE (Phases 7 & 9)
# =============================

spy = yf.Ticker("SPY")
spy_hist = spy.history(period="6mo")

spy_return = spy_hist["Close"].pct_change(60).iloc[-1]

# Market regime detection
if spy_hist["Close"].ewm(span=50).mean().iloc[-1] > spy_hist["Close"].ewm(span=200).mean().iloc[-1]:
    market_trend = "Bull"
else:
    market_trend = "Bear"

# Dynamic expiration logic
volatility = spy_hist["Close"].pct_change().rolling(20).std().iloc[-1]

if volatility > 0.025:
    MIN_DTE = 20
    MAX_DTE = 35
else:
    MIN_DTE = 30
    MAX_DTE = 50

# Directional weighting
if market_trend == "Bull":
    CALL_WEIGHT = 1.5
    PUT_WEIGHT = 0.9
else:
    CALL_WEIGHT = 1.0
    PUT_WEIGHT = 1.4

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

    # Trend strength
    if hist["ema50"].iloc[-1] > hist["ema200"].iloc[-1]:
        score += 3

    # RSI momentum
    if 55 <= hist["rsi"].iloc[-1] <= 70:
        score += 2

    # ATR expansion
    if hist["atr"].iloc[-1] > hist["atr"].rolling(20).mean().iloc[-1]:
        score += 2

    # Breakout detection
    recent_high = hist["High"].rolling(20).max().iloc[-2]
    if hist["Close"].iloc[-1] > recent_high:
        score += 4

    # Volatility spike detection
    recent_vol = hist["Close"].pct_change().rolling(10).std().iloc[-1]
    long_vol = hist["Close"].pct_change().rolling(30).std().iloc[-1]
    if recent_vol > long_vol * 1.5:
        score += 3

    # Relative strength vs SPY
    stock_return = hist["Close"].pct_change(60).iloc[-1]
    if stock_return > spy_return:
        score += 3
    return score

results = []

for ticker in tickers:
    try:
        stock = yf.Ticker(ticker)

        # Earnings detection
        earnings_date = None
        try:
            cal = stock.calendar
            if not cal.empty:
                earnings_date = cal.index[0]
        except:
            pass

        hist = stock.history(period="6mo")
        if len(hist) < 100:
            continue

        stock_score = score_stock(hist)
        current_price = hist["Close"].iloc[-1]

        for exp in stock.options:
            exp_date = datetime.strptime(exp,"%Y-%m-%d")
            dte = (exp_date - datetime.today()).days

            if MIN_DTE <= dte <= MAX_DTE:

                earnings_boost = 0
                if earnings_date is not None:
                    days_to_earnings = (earnings_date - datetime.today()).days
                    if 0 < days_to_earnings <= dte:
                        earnings_boost = 3

                chain = stock.option_chain(exp)

                 # CALLS
                for _, row in chain.calls.iterrows():
                    if row["strike"] > current_price * 1.03 and row["strike"] < current_price * 1.12:

                        option_score = stock_score * CALL_WEIGHT
                        option_score += row["volume"] / 1000
                        option_score += earnings_boost

                        # Delta probability scoring
                        if "delta" in row:
                            delta_val = abs(row["delta"])
                        else:
                            delta_val = 0.4

                        if 0.35 <= delta_val <= 0.55:
                            option_score += 3
                        elif delta_val < 0.25:
                            option_score -= 2
                        if row["volume"] > 1000:
                            option_score += 3

                        if row["openInterest"] > 2000:
                            option_score += 2

                        # Gamma squeeze detection
                        if row["openInterest"] > 5000 and row["volume"] > 2000:
                            option_score += 4

                        contract_cost = row["lastPrice"] * 100
                        if contract_cost > 250:
                            continue

                        results.append([
                            ticker,
                            "CALL",
                            exp,
                            row["strike"],
                            round(current_price, 2),
                            round(row["bid"], 2),
                            round(row["ask"], 2),
                            round(row["lastPrice"], 2),
                            int(row["volume"]),
                            int(row["openInterest"]),
                            int(dte),
                            round(option_score, 2)
                        ])

                # PUTS
                for _, row in chain.puts.iterrows():
                    if row["strike"] < current_price * 0.97 and row["strike"] > current_price * 0.88:

                        option_score = stock_score * PUT_WEIGHT
                        option_score += row["volume"] / 1000
                        option_score += earnings_boost
                        # Delta probability scoring
                        if "impliedVolatility" in row and "delta" in row:
                            delta_val = abs(row["delta"])
                        else:
                            delta_val = 0.4  # fallback estimate

                        # Reward ideal aggressive swing zone
                        if 0.35 <= delta_val <= 0.55:
                            option_score += 3
                        elif delta_val < 0.25:
                            option_score -= 2
                        

                        if row["volume"] > 1000:
                            option_score += 3

                        if row["openInterest"] > 2000:
                            option_score += 2

                        # Gamma squeeze detection
                        if row["openInterest"] > 5000 and row["volume"] > 2000:
                            option_score += 4

                        contract_cost = row["lastPrice"] * 100
                        if contract_cost > 250:
                            continue

                        results.append([
                            ticker,
                            "PUT",
                            exp,
                            row["strike"],
                            round(current_price, 2),
                            round(row["bid"], 2),
                            round(row["ask"], 2),
                            round(row["lastPrice"], 2),
                            int(row["volume"]),
                            int(row["openInterest"]),
                            int(dte),
                            round(option_score, 2)
                        ])
    except:
        pass

df = pd.DataFrame(results, columns=[
    "Ticker","Type","Expiration","Strike",
    "StockPrice","Bid","Ask","LastPrice",
    "Volume","OpenInterest","DTE","Score"
])

df = df.sort_values("Score", ascending=False)
df = df[df["Score"] > 6]

top_calls = df[df["Type"]=="CALL"].head(5)
top_puts = df[df["Type"]=="PUT"].head(5)
st.markdown("### Market Summary")
st.write(f"Market Regime: {market_trend}")
st.write(f"Volatility Level: {round(volatility,4)}")

st.subheader("Top 5 CALLS")
st.dataframe(top_calls, use_container_width=True)

st.subheader("Top 5 PUTS")
st.dataframe(top_puts, use_container_width=True)
# =============================
# DASHBOARD METRICS
# =============================

st.markdown("## Market Summary Metrics")

total_contracts = len(df)
avg_score = df["Score"].mean()
top_score = df["Score"].max()

col1, col2, col3 = st.columns(3)

col1.metric("Contracts Scanned", total_contracts)
col2.metric("Average Score", round(avg_score,2))
col3.metric("Top Score Today", round(top_score,2))
# =============================
# DAILY SNAPSHOT EXPORT
# =============================

import datetime

if st.button("Save Today's Snapshot"):

    filename = f"options_snapshot_{datetime.datetime.today().strftime('%Y%m%d')}.csv"
    df.to_csv(filename, index=False)
    st.success(f"Snapshot saved as {filename}")

st.subheader("Capital Deployment Plan ($500 Aggressive)")
st.write("""
Primary: Allocate $200 to top ranked contract  
Secondary: $150 to second highest  
Tactical: $150 to third ranked  
Cut at -50%  
Target 80%+
""")
st.markdown("### Trade Logger & Performance Tracker")

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

if len(st.session_state.trade_log) > 0:
    trade_df = pd.DataFrame(st.session_state.trade_log)
    st.dataframe(trade_df, use_container_width=True)

    win_rate = len(trade_df[trade_df["PnL"] > 0]) / len(trade_df)
    avg_gain = trade_df["PnL"].mean()

    st.write(f"Win Rate: {round(win_rate*100,1)}%")
    st.write(f"Average PnL: {round(avg_gain,2)}")
# =============================
# PORTFOLIO SIMULATION ENGINE
# =============================

st.markdown("## Portfolio Simulation ($500 Aggressive Intelligent Allocation)")

capital = 500
allocation = []

# Use top 5 highest scoring contracts
top_combined = df.sort_values("Score", ascending=False).head(5)

for _, row in top_combined.iterrows():
    contract_price = row["LastPrice"] * 100

    # Allocation scaling based on score strength
    if row["Score"] >= 15:
        allocation_size = 0.4
    elif row["Score"] >= 10:
        allocation_size = 0.3
    else:
        allocation_size = 0.2

    max_alloc = capital * allocation_size

    if contract_price <= max_alloc:
        contracts = int(max_alloc // contract_price)
        if contracts > 0:
            total_cost = contracts * contract_price

            allocation.append({
                "Ticker": row["Ticker"],
                "Type": row["Type"],
                "Strike": row["Strike"],
                "Expiration": row["Expiration"],
                "Contracts": contracts,
                "Total Cost": round(total_cost, 2)
            })

            capital -= total_cost

if len(allocation) > 0:
    sim_df = pd.DataFrame(allocation)
    st.dataframe(sim_df, use_container_width=True)
    st.write(f"Remaining Capital: ${round(capital,2)}")
else:
    st.write("No contracts fit capital allocation rules today.")
   # =============================
# TRUE ROLLING BACKTEST ENGINE
# =============================

st.markdown("## Historical Backtest (90 Day Rolling Simulation)")

import datetime

if st.button("Run 90 Day Backtest"):

    initial_capital = 500
    capital_bt = initial_capital
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

            # Rolling 5-day forward test
            for i in range(10, len(hist) - 5):

                entry_price = hist["Close"].iloc[i]
                exit_price = hist["Close"].iloc[i + 5]

                pct_move = (exit_price - entry_price) / entry_price

                # Only take trades where movement exceeds 2%
                if abs(pct_move) > 0.02:

                    position_size = capital_bt * 0.2
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
        total_return = (capital_bt - initial_capital) / initial_capital

        st.write(f"Trades Simulated: {trades}")
        st.write(f"Win Rate: {round(win_rate*100,2)}%")
        st.write(f"Total Return: {round(total_return*100,2)}%")
        st.write(f"Ending Capital: ${round(capital_bt,2)}")

    else:
        st.write("No qualifying trades found.") 
