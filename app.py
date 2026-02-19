import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime

st.set_page_config(layout="wide")
st.title("Aggressive Monthly Options Sniper")

MIN_DTE = 30
MAX_DTE = 45
CALL_WEIGHT = 1.2
PUT_WEIGHT = 1.0

tickers = [
    spy = yf.Ticker("SPY")
spy_hist = spy.history(period="6mo")
spy_return = spy_hist["Close"].pct_change(60).iloc[-1]
    "NVDA","AMD","TSLA","META","AAPL","COIN",
    "AMZN","MSFT","GOOGL","NFLX","PLTR","SHOP"
]

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

                        if row["volume"] > 1000:
                            option_score += 3

                        if row["openInterest"] > 2000:
                            option_score += 2

                        contract_cost = row["lastPrice"] * 100
                        if contract_cost > 250:
                            continue

                        results.append([
                            ticker,
                            "CALL",
                            exp,
                            row["strike"],
                            round(current_price,2),
                            round(row["bid"],2),
                            round(row["ask"],2),
                            round(row["lastPrice"],2),
                            int(row["volume"]),
                            int(row["openInterest"]),
                            int(dte),
                            round(option_score,2)
                        ])

                # PUTS
                for _, row in chain.puts.iterrows():
                    if row["strike"] < current_price * 0.97 and row["strike"] > current_price * 0.88:

                        option_score = stock_score * PUT_WEIGHT
                        option_score += row["volume"] / 1000
                        option_score += earnings_boost

                        if row["volume"] > 1000:
                            option_score += 3

                        if row["openInterest"] > 2000:
                            option_score += 2

                        contract_cost = row["lastPrice"] * 100
                        if contract_cost > 250:
                            continue

                        results.append([
                            ticker,
                            "PUT",
                            exp,
                            row["strike"],
                            round(current_price,2),
                            round(row["bid"],2),
                            round(row["ask"],2),
                            round(row["lastPrice"],2),
                            int(row["volume"]),
                            int(row["openInterest"]),
                            int(dte),
                            round(option_score,2)
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

st.subheader("Top 5 CALLS")
st.dataframe(top_calls, use_container_width=True)

st.subheader("Top 5 PUTS")
st.dataframe(top_puts, use_container_width=True)

st.subheader("Capital Deployment Plan ($500 Aggressive)")
st.write("""
Primary: Allocate $200 to top ranked contract  
Secondary: $150 to second highest  
Tactical: $150 to third ranked  
Cut at -50%  
Target 80%+
""")
