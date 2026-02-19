import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import os
import time
from collections import Counter
import re
import snscrape.modules.twitter as sntwitter

# -----------------------------
# CONFIG
# -----------------------------
INITIAL_CAPITAL = 500
MIN_DTE = 7
MAX_DTE = 45
CALL_WEIGHT = 1.2
PUT_WEIGHT = 1.0
CACHE_DIR = "cache"

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

st.set_page_config(layout="wide")
st.title("Aggressive Monthly Options Sniper (Yahoo Finance)")

# -----------------------------
# Universe Setup (Dynamic 200 tickers)
# -----------------------------
UNIVERSE_FILE = "market_universe.csv"

def build_universe():
    seed = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
        "AMD","NFLX","AVGO","JPM","BAC","XOM","CVX",
        "UNH","LLY","HD","COST","WMT","KO","PEP",
        "INTC","CSCO","ADBE","CRM","PYPL","ORCL",
        "SPY","QQQ","IWM","DIA"
    ]
    qualified = []

    for ticker in seed:
        try:
            hist = yf.Ticker(ticker).history(period="60d")
            if len(hist) >= 40:
                qualified.append(ticker)
        except:
            continue

    # Expand from S&P 500 dynamically
    try:
        sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        table = pd.read_html(sp500_url)[0]
        sp500_tickers = table["Symbol"].tolist()
        for ticker in sp500_tickers:
            if len(qualified) >= 200:
                break
            if ticker in qualified:
                continue
            try:
                hist = yf.Ticker(ticker).history(period="60d")
                if len(hist) >= 40:
                    qualified.append(ticker)
            except:
                continue
    except:
        pass

    df_universe = pd.DataFrame({"Ticker": qualified})
    df_universe.to_csv(UNIVERSE_FILE, index=False)
    return qualified

if os.path.exists(UNIVERSE_FILE):
    tickers = pd.read_csv(UNIVERSE_FILE)["Ticker"].tolist()
else:
    tickers = build_universe()

st.write(f"Universe Size: {len(tickers)} tickers")

# -----------------------------
# OPTION SCORING FUNCTIONS
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
    return score

def score_option(row, stock_score):
    score = stock_score
    delta_val = abs(row.get("delta", 0.4))
    if 0.35 <= delta_val <= 0.55:
        score += 3
    elif delta_val < 0.25:
        score -= 2
    if row.get("volume", 0) > 1000:
        score += 2
    if row.get("openInterest", 0) > 2000:
        score += 2
    if row.get("openInterest", 0) > 5000 and row.get("volume", 0) > 2000:
        score += 4
    if row["contract_type"].upper() == "CALL":
        score *= CALL_WEIGHT
    else:
        score *= PUT_WEIGHT
    return score

# -----------------------------
# SCAN UNIVERSE
# -----------------------------
st.markdown("## Universe Options Scan")
all_options = []
portfolio = []
capital_sim = INITIAL_CAPITAL

for ticker in tickers:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 60:
            continue
        stock_score = score_stock(hist)
        current_price = hist["Close"].iloc[-1]

        for exp in stock.options:
            exp_date = datetime.datetime.strptime(exp, "%Y-%m-%d")
            dte = (exp_date - datetime.datetime.today()).days
            if dte < MIN_DTE or dte > MAX_DTE:
                continue
            chain = stock.option_chain(exp)
            for df, typ in [(chain.calls, "CALL"), (chain.puts, "PUT")]:
                for _, row in df.iterrows():
                    if typ == "CALL" and row["strike"] < current_price:
                        continue
                    if typ == "PUT" and row["strike"] > current_price:
                        continue
                    row_dict = row.to_dict()
                    row_dict["contract_type"] = typ
                    row_score = score_option(row_dict, stock_score)
                    if row_score < 3:
                        continue
                    row_dict["Score"] = row_score
                    row_dict["Ticker"] = ticker
                    row_dict["Expiration"] = exp
                    all_options.append(row_dict)

                    # Portfolio simulation
                    contract_cost = row.get("lastPrice",0) * 100
                    if row_score >= 5 and capital_sim >= contract_cost:
                        portfolio.append({
                            "Ticker": ticker,
                            "Type": typ,
                            "Strike": row.get("strike"),
                            "Expiration": exp,
                            "Contracts": 1,
                            "TotalCost": contract_cost,
                            "Score": row_score
                        })
                        capital_sim -= contract_cost
        time.sleep(0.1)
    except:
        continue

df_options = pd.DataFrame(all_options)
df_options = df_options.sort_values("Score", ascending=False)

# -----------------------------
# TOP 5 CALLS / PUTS
# -----------------------------
top_calls = df_options[df_options["contract_type"]=="CALL"].head(5)
top_puts = df_options[df_options["contract_type"]=="PUT"].head(5)

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
# MANUAL TICKER SCORING
# -----------------------------
st.sidebar.markdown("## Manual Ticker Scoring")
manual_ticker_input = st.sidebar.text_input("Enter Tickers (comma separated)")
if st.sidebar.button("Score Tickers"):
    manual_tickers = [t.strip().upper() for t in manual_ticker_input.split(",") if t.strip()]
    manual_results = []
    for ticker in manual_tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="6mo")
            if len(hist) < 60:
                continue
            stock_score = score_stock(hist)
            current_price = hist["Close"].iloc[-1]
            for exp in stock.options:
                exp_date = datetime.datetime.strptime(exp,"%Y-%m-%d")
                dte = (exp_date - datetime.datetime.today()).days
                if dte < MIN_DTE or dte > MAX_DTE:
                    continue
                chain = stock.option_chain(exp)
                for df, typ in [(chain.calls,"CALL"),(chain.puts,"PUT")]:
                    for _, row in df.iterrows():
                        row_dict = row.to_dict()
                        row_dict["contract_type"] = typ
                        row_dict["Score"] = score_option(row_dict, stock_score)
                        row_dict["Ticker"] = ticker
                        row_dict["Expiration"] = exp
                        manual_results.append(row_dict)
        except:
            continue
    if manual_results:
        manual_df = pd.DataFrame(manual_results).sort_values("Score", ascending=False)
        st.subheader("Manual Ticker Scoring Results")
        st.dataframe(manual_df, use_container_width=True)
    else:
        st.write("No options scored for the tickers entered.")

# -----------------------------
# INSIDER TRANSACTIONS CHART
# -----------------------------
st.subheader("Insider Big Buys/Sells (Yahoo Finance)")
insider_data = []
for ticker in tickers[:50]:  # limit to 50 for speed
    try:
        stock = yf.Ticker(ticker)
        ins = stock.insider_transactions
        if not ins.empty:
            ins["Ticker"] = ticker
            insider_data.append(ins)
    except:
        continue
if insider_data:
    insider_df = pd.concat(insider_data, ignore_index=True)
    st.dataframe(insider_df[["Ticker","Date","Type","Shares","Value"]].sort_values("Date", ascending=False))
else:
    st.write("No insider transactions found for selected tickers.")

# -----------------------------
# TRENDING OPTIONS FROM X
# -----------------------------
st.subheader("Trending Options (X/Twitter)")
trending_terms = st.text_input("Trending scan keywords (e.g., $AAPL, $TSLA, call, put)", "$AAPL,$TSLA")
keywords = [t.strip().upper() for t in trending_terms.split(",") if t.strip()]
tweet_limit = 200
ticker_counter = Counter()

for term in keywords:
    try:
        for i, tweet in enumerate(sntwitter.TwitterSearchScraper(f"{term} lang:en").get_items()):
            if i >= tweet_limit:
                break
            tickers_in_tweet = re.findall(r"\$[A-Z]{1,5}", tweet.content.upper())
            ticker_counter.update(tickers_in_tweet)
    except:
        continue

if ticker_counter:
    trending_df = pd.DataFrame(ticker_counter.items(), columns=["Ticker","Mentions"])
    trending_df = trending_df.sort_values("Mentions", ascending=False).reset_index(drop=True)
    st.dataframe(trending_df, use_container_width=True)
else:
    st.write("No trending tickers found in recent tweets.")
