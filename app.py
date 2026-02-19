import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(layout="wide")
st.title("Aggressive $500 Options Sniper Dashboard")

# ---- Universe ----
tickers = [
    "NVDA","AMD","TSLA","META","AAPL","COIN",
    "AMZN","MSFT","GOOGL","NFLX","BA","PLTR",
    "SHOP","SNOW","RIVN","FSLY","SOFI","VAL"
]

def trend_score(df):
    df["ema50"] = df["Close"].ewm(span=50).mean()
    df["ema200"] = df["Close"].ewm(span=200).mean()
    df["rsi"] = 100 - (100/(1 + df["Close"].pct_change().rolling(14).mean()))
    score = 0
    if df["ema50"].iloc[-1] > df["ema200"].iloc[-1]:
        score += 2
    if df["rsi"].iloc[-1] > 55:
        score += 2
    return score

results = []

for ticker in tickers:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 50:
            continue
        
        score = trend_score(hist)

        options_dates = stock.options
        for exp in options_dates:
            exp_date = datetime.strptime(exp,"%Y-%m-%d")
            if 30 <= (exp_date - datetime.today()).days <= 45:
                opt = stock.option_chain(exp)
                calls = opt.calls
                puts = opt.puts

                # Calls
                for _, row in calls.iterrows():
                    if 0.4 <= row["delta"] <= 0.65:
                        results.append([
                            ticker,"CALL",exp,row["strike"],
                            row["lastPrice"],score
                        ])

                # Puts
                for _, row in puts.iterrows():
                    if -0.65 <= row["delta"] <= -0.4:
                        results.append([
                            ticker,"PUT",exp,row["strike"],
                            row["lastPrice"],score
                        ])
    except:
        pass

df = pd.DataFrame(results, columns=[
    "Ticker","Type","Expiration","Strike","Premium","Score"
])

df = df.sort_values("Score",ascending=False).head(10)

st.dataframe(df)
