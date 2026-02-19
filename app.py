import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import os
import time

# =============================
# PAGE SETTINGS
# =============================
st.set_page_config(layout="wide")
st.title("Aggressive Monthly Options Sniper")

# =============================
# MARKET UNIVERSE (~200 tickers)
# =============================
UNIVERSE_FILE = "market_universe.csv"
CACHE_DIR = "cache"

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def build_universe():
    # Base core ETFs / stocks
    base_symbols = [
        "SPY","QQQ","IWM","DIA","XLF","XLY","XLC","XLK","XLV","XLI","XLE","XLB","XLU",
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","INTC","CSCO","ADBE","CRM",
        "PYPL","ORCL","NFLX","V","MA","JPM","BAC","C","WFC","GS","BRK-B","UNH","LLY","PFE",
        "MRK","ABBV","TMO","DHR","LMT","BA","RTX","DIS","TMUS","VZ","CMCSA","KO","PEP","MCD",
        "SBUX","XOM","CVX","COP","SLB"
    ]

    extra_symbols = [
        "BMY","AMAT","ASML","QCOM","TXN","IBM","HON","MMM","CAT","DE","GS","MS",
        "SPGI","ICE","ADP","NOW","SNOW","TEAM","ZM","UBER","LYFT","SHOP","SQ","ROKU",
        "DOCU","PLTR","PINS","TWTR","SNAP","DDOG","CRWD","NET","OKTA","FISV","PAYC",
        "DXCM","MRNA","REGN","BIIB","VRTX","ALGN","ISRG","EW","MNST","PEP","KO","MO",
        "PM","NKE","LULU","TJX","ROST","HD","LOW","COST","WMT","TGT","DG","DLTR",
        "RCL","CCL","NCLH","MGM","WYNN","MAR","HLT","HST","SPG","VTR","EQR","AVB",
        "DLR","PLD","EXR","O","EQIX","COST","WMT","HD","LOW","KMB","CL","PG","EL",
        "KO","PEP","MO","PM","BF-B","ADM","GIS","CPB","K","HSY","MDLZ","MNST"
    ]

    universe_candidates = list(set(base_symbols + extra_symbols))[:200]
    qualified = []

    for ticker in universe_candidates:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="60d")
            if len(hist) < 40:
                continue
            avg_volume = hist["Volume"].mean()
            price = hist["Close"].iloc[-1]
            if avg_volume > 100_000 and 1 < price < 800:  # relaxed filters
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

st.write(f"Universe Size: {len(tickers)}")

# =============================
# OPTIONS SCORING & TOP CALLS/PUTS
# =============================
st.markdown("## Options Scanner (Top Calls & Puts)")

all_options = []

for ticker in tickers:
    try:
        opt = yf.Ticker(ticker)
        expirations = opt.options
        if not expirations:
            continue
        exp = expirations[0]
        chain = opt.option_chain(exp)
        calls, puts = chain.calls, chain.puts

        hist_file = f"{CACHE_DIR}/{ticker}.csv"
        if os.path.exists(hist_file):
            hist = pd.read_csv(hist_file, index_col=0, parse_dates=True)
        else:
            hist = opt.history(period="60d")
            hist.to_csv(hist_file)
        if hist.empty:
            continue

        high20 = hist["High"].rolling(20).max().iloc[-1]
        low20 = hist["Low"].rolling(20).min().iloc[-1]
        current_price = hist["Close"].iloc[-1]

        for df_opts, typ in [(calls, "CALL"), (puts, "PUT")]:
            for _, row in df_opts.iterrows():
                try:
                    # ------------------------
                    # Minimum expiration filter
                    # ------------------------
                    exp_date = datetime.datetime.strptime(exp, "%Y-%m-%d")
                    dte = (exp_date - datetime.datetime.today()).days
                    if dte < 7:
                        continue  # skip short-term options

                    score = 0
                    volume = row.get("volume",0)
                    oi = row.get("openInterest",0)

                    # Liquidity scoring
                    if volume > 1000:
                        score += 2
                    if oi > 2000:
                        score += 3
                    if oi > 5000 and volume > 2000:
                        score += 4  # gamma squeeze

                    # Delta scoring
                    delta_val = abs(row.get("delta",0.4))
                    if 0.35 <= delta_val <= 0.55:
                        score += 3
                    elif delta_val < 0.25:
                        score -= 2

                    # IV spike
                    if row.get("impliedVolatility",0) > 0.5:
                        score += 2

                    # Breakout detection
                    if typ=="CALL" and row["strike"] > high20:
                        score += 1
                    elif typ=="PUT" and row["strike"] < low20:
                        score += 1

                    # Skip expensive contracts
                    if row["lastPrice"]*100 > 250:
                        continue

                    all_options.append({
                        "Ticker": ticker,
                        "Type": typ,
                        "Expiration": exp,
                        "Strike": row["strike"],
                        "StockPrice": round(current_price,2),
                        "Bid": round(row["bid"],2),
                        "Ask": round(row["ask"],2),
                        "LastPrice": round(row["lastPrice"],2),
                        "Volume": int(volume),
                        "OpenInterest": int(oi),
                        "Score": score,
                        "DTE": dte
                    })
                except:
                    continue
        time.sleep(0.3)
    except:
        continue

# Create dataframe
if not all_options:
    st.warning("No options scored today. Relax filters or check universe.")
    df = pd.DataFrame(columns=[
        "Ticker","Type","Expiration","Strike",
        "StockPrice","Bid","Ask","LastPrice",
        "Volume","OpenInterest","Score","DTE"
    ])
else:
    df = pd.DataFrame(all_options)
    df = df.sort_values("Score", ascending=False)
    df = df[df["Score"] > 4]  # threshold to ensure top options

top_calls = df[df["Type"]=="CALL"].head(5)
top_puts = df[df["Type"]=="PUT"].head(5)

st.subheader("Top 5 CALLS")
st.dataframe(top_calls, use_container_width=True)

st.subheader("Top 5 PUTS")
st.dataframe(top_puts, use_container_width=True)

# =============================
# PORTFOLIO SIMULATION
# =============================
st.markdown("## Portfolio Simulation ($500 Aggressive Allocation)")

capital = 500
allocation = []

top_combined = pd.concat([top_calls, top_puts]).sort_values("Score", ascending=False)

for _, row in top_combined.iterrows():
    contract_price = row["LastPrice"]*100
    # Allocation scaling
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
            total_cost = contracts * contract_price
            allocation.append({
                "Ticker": row["Ticker"],
                "Type": row["Type"],
                "Strike": row["Strike"],
                "Expiration": row["Expiration"],
                "Contracts": contracts,
                "Total Cost": round(total_cost,2),
                "DTE": row["DTE"]
            })
            capital -= total_cost

if allocation:
    sim_df = pd.DataFrame(allocation)
    st.dataframe(sim_df, use_container_width=True)
    st.write(f"Remaining Capital: ${round(capital,2)}")
else:
    st.write("No contracts fit capital allocation rules today.")

# =============================
# BACKTEST (90-day rolling)
# =============================
st.markdown("## Historical Backtest (90-Day Rolling Simulation)")

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
            for i in range(10, len(hist)-5):
                entry = hist["Close"].iloc[i]
                exit = hist["Close"].iloc[i+5]
                pct_move = (exit-entry)/entry
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

    if trades>0:
        win_rate = wins/trades
        total_return = (capital_bt - initial_capital)/initial_capital
        st.write(f"Trades Simulated: {trades}")
        st.write(f"Win Rate: {round(win_rate*100,2)}%")
        st.write(f"Total Return: {round(total_return*100,2)}%")
        st.write(f"Ending Capital: ${round(capital_bt,2)}")
    else:
        st.write("No qualifying trades found.")
