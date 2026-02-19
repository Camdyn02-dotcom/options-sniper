import subprocess
import sys

# -----------------------------
# Ensure snscrape is uninstalled
# -----------------------------
try:
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "snscrape"], check=True)
except Exception as e:
    pass  # ignore any errors if not installed

# -----------------------------
# Now import the rest
# -----------------------------
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import os
import time
st.set_page_config(layout="wide")
st.title("Aggressive Options Sniper Dashboard")

# -----------------------------
# Market Universe
# -----------------------------
UNIVERSE_FILE = "market_universe.csv"

def build_universe():
    # Top tickers: S&P 500 + Nasdaq + high-volume ETFs
    tickers = [
        "AAPL","MSFT","AMZN","GOOGL","META","TSLA","NVDA","NFLX","AMD","INTC",
        "CSCO","ADBE","CRM","PYPL","ORCL","AVGO","QCOM","IBM","TXN","SPY",
        "QQQ","IWM","DIA","XOM","CVX","UNH","LLY","HD","COST","WMT",
        "KO","PEP","JNJ","MRK","V","MA","SBUX","BKNG","ZM","NKE","GS","BA",
        "CAT","MMM","MCD","WBA","GM","F","GE","LMT","NEE","AXP","T","VZ",
        "MRNA","PFE","BNTX","QCOM","AMAT","MU","ADI","LRCX","TSM","INTU",
        "PYPL","SQ","SHOP","SNOW","ZM","DOCU","TEAM","DDOG","ROKU","SPOT"
    ]
    # Fill to 200 with additional tickers
    extra_tickers = ["BAC","C","JPM","MS","WFC","PNC","USB","TFC","SCHW","BK","COF","ALLY","FRC"]
    for t in extra_tickers:
        if len(tickers) < 200:
            tickers.append(t)

    qualified = []
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="60d")
            if hist.empty or len(hist) < 40:
                continue
            avg_volume = hist["Volume"].mean()
            price = hist["Close"].iloc[-1]
            if avg_volume > 500_000 and 5 < price < 800:
                qualified.append(ticker)
        except:
            continue

    df = pd.DataFrame({"Ticker": qualified})
    df.to_csv(UNIVERSE_FILE, index=False)
    return qualified

if os.path.exists(UNIVERSE_FILE):
    tickers = pd.read_csv(UNIVERSE_FILE)["Ticker"].tolist()
else:
    tickers = build_universe()

st.write(f"Universe Size: {len(tickers)}")

# -----------------------------
# Manual Ticker Scoring
# -----------------------------
st.subheader("Manual Ticker Scoring")
manual_ticker = st.text_input("Enter a ticker to score (e.g., AAPL)")
if st.button("Score Ticker") and manual_ticker:
    try:
        stock = yf.Ticker(manual_ticker.upper())
        hist = stock.history(period="6mo")
        if hist.empty:
            st.write("No historical data available.")
        else:
            last_price = hist["Close"].iloc[-1]
            score = 0
            if last_price > hist["Close"].rolling(50).mean().iloc[-1]:
                score += 3
            if last_price > hist["Close"].rolling(200).mean().iloc[-1]:
                score += 2
            st.write(f"{manual_ticker.upper()} Current Price: ${last_price:.2f}")
            st.write(f"{manual_ticker.upper()} Score: {score}")
    except:
        st.write("Ticker not valid or no data available.")

# -----------------------------
# Options Scanner
# -----------------------------
st.subheader("Options Scanner")
MIN_DTE_LONG = 7
MIN_DTE_SHORT = 1
MAX_DTE = 45

all_options_long = []
all_options_short = []

CACHE_DIR = "cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

for ticker in tickers:
    try:
        opt = yf.Ticker(ticker)
        expirations = opt.options
        if not expirations:
            continue

        hist_file = f"{CACHE_DIR}/{ticker}.csv"
        if os.path.exists(hist_file):
            hist = pd.read_csv(hist_file, index_col=0, parse_dates=True)
        else:
            hist = opt.history(period="60d")
            hist.to_csv(hist_file)
        if hist.empty:
            continue

        current_price = hist["Close"].iloc[-1]
        high20 = hist["High"].rolling(20).max().iloc[-1]

        for exp in expirations:
            try:
                exp_date = datetime.datetime.strptime(exp, "%Y-%m-%d")
            except:
                continue
            dte = (exp_date - datetime.datetime.today()).days
            if dte < MIN_DTE_SHORT or dte > MAX_DTE:
                continue

            try:
                chain = opt.option_chain(exp)
            except:
                continue

            for df, typ in [(chain.calls, "CALL"), (chain.puts, "PUT")]:
                for _, row in df.iterrows():
                    try:
                        last_price = row.get("lastPrice", 0)
                        if pd.isna(last_price) or last_price == 0:
                            continue
                        score = 0
                        if row.get("volume", 0) > 2000:
                            score += 2
                        if row.get("openInterest", 0) > 5000:
                            score += 3
                        delta_val = abs(row.get("delta", 0.4))
                        if 0.35 <= delta_val <= 0.55:
                            score += 3
                        elif delta_val < 0.25:
                            score -= 2
                        if "impliedVolatility" in row and row["impliedVolatility"] > 0.5:
                            score += 2
                        if row["strike"] > high20:
                            score += 1

                        contract = {
                            "Ticker": ticker,
                            "Type": typ,
                            "Strike": row["strike"],
                            "Expiration": exp,
                            "LastPrice": last_price,
                            "Volume": row.get("volume", 0),
                            "OpenInterest": row.get("openInterest", 0),
                            "Delta": delta_val,
                            "IV": row.get("impliedVolatility", 0),
                            "Score": score,
                            "DTE": dte
                        }

                        if dte >= MIN_DTE_LONG:
                            all_options_long.append(contract)
                        if dte >= MIN_DTE_SHORT:
                            all_options_short.append(contract)

                    except:
                        continue
        time.sleep(0.1)
    except:
        continue

df_long = pd.DataFrame(all_options_long)
df_short = pd.DataFrame(all_options_short)

st.markdown("### Long-term Options (DTE ≥ 7 days)")
if not df_long.empty:
    st.dataframe(df_long.sort_values("Score", ascending=False), use_container_width=True)
else:
    st.write("No long-term options scored today.")

st.markdown("### Short-term Options (DTE ≥ 1 day)")
if not df_short.empty:
    st.dataframe(df_short.sort_values("Score", ascending=False), use_container_width=True)
else:
    st.write("No short-term options scored today.")

# -----------------------------
# Trending / Most Active Options
# -----------------------------
st.subheader("Trending / Most Active Options (Yahoo Finance)")
try:
    calls_url = "https://finance.yahoo.com/options/most-active?count=100"
    calls_tables = pd.read_html(calls_url)
    calls_df = calls_tables[0]
    calls_df = calls_df.rename(columns=lambda x: x.replace("\n", " "))
    calls_df = calls_df[["Symbol", "Last Price", "Volume", "Open Interest"]].head(20)
    calls_df["Type"] = "CALL"

    puts_url = "https://finance.yahoo.com/options/most-active?count=100&putCall=PUT"
    puts_tables = pd.read_html(puts_url)
    puts_df = puts_tables[0]
    puts_df = puts_df.rename(columns=lambda x: x.replace("\n", " "))
    puts_df = puts_df[["Symbol", "Last Price", "Volume", "Open Interest"]].head(20)
    puts_df["Type"] = "PUT"

    trending_df = pd.concat([calls_df, puts_df], ignore_index=True)
    st.dataframe(trending_df, use_container_width=True)
except Exception as e:
    st.write("Could not fetch trending options:", e)

# -----------------------------
# Portfolio Simulation
# -----------------------------
st.subheader("Portfolio Simulation ($500 Aggressive)")
capital = 500
allocation = []

top_options = pd.concat([df_long, df_short]).sort_values("Score", ascending=False).head(5) if not df_long.empty or not df_short.empty else pd.DataFrame()
for _, row in top_options.iterrows():
    contract_price = row["LastPrice"] * 100
    if row["Score"] >= 10:
        allocation_size = 0.4
    elif row["Score"] >= 7:
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

if allocation:
    sim_df = pd.DataFrame(allocation)
    st.dataframe(sim_df, use_container_width=True)
    st.write(f"Remaining Capital: ${round(capital,2)}")
else:
    st.write("No contracts fit capital allocation rules today.")

# -----------------------------
# Insider Buys/Sells Placeholder
# -----------------------------
st.subheader("Insider Buys / Sells")
insider_df = pd.DataFrame(columns=["Ticker","Type","Date","Shares","Transaction"])
st.write("Currently placeholder — add Yahoo Finance or SEC scraping logic here.")
st.dataframe(insider_df, use_container_width=True)

# -----------------------------
# Save Snapshot
# -----------------------------
if st.button("Save Today's Snapshot"):
    today = datetime.datetime.today().strftime("%Y%m%d")
    df_long.to_csv(f"options_snapshot_long_{today}.csv", index=False)
    df_short.to_csv(f"options_snapshot_short_{today}.csv", index=False)
    st.success("Snapshots saved successfully.")
