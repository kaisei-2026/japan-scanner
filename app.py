import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
import time

st.set_page_config(page_title="Japan Stock Scanner", page_icon="🇯🇵", layout="wide")
st.title("🇯🇵 Japan Stock Scanner")
st.caption("グロース市場対応 | VWAP・EMA・同時間帯RVOL・J-Quants対応")

# ============================================================
# J-Quants API ヘルパー
# ============================================================
JQUANTS_EMAIL    = st.secrets.get("tomimizu.s@gmail.com", "")
JQUANTS_PASSWORD = st.secrets.get("#fnEsjdzH@y2SKu", "")

@st.cache_data(ttl=3600)
def jquants_get_refresh_token(email, password):
    if not email or not password:
        return None
    try:
        r = requests.post(
            "https://api.jquants.com/v1/token/auth_user",
            json={"mailaddress": email, "password": password},
            timeout=10
        )
        return r.json().get("refreshToken")
    except:
        return None

@st.cache_data(ttl=600)
def jquants_get_id_token(refresh_token):
    if not refresh_token:
        return None
    try:
        r = requests.post(
            "https://api.jquants.com/v1/token/auth_refresh",
            params={"refreshtoken": refresh_token},
            timeout=10
        )
        return r.json().get("idToken")
    except:
        return None

@st.cache_data(ttl=300)
def jquants_get_prices(code, id_token):
    """J-Quantsから日足データ取得（コードは4桁数字）"""
    if not id_token:
        return pd.DataFrame()
    try:
        headers = {"Authorization": f"Bearer {id_token}"}
        date_from = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
        r = requests.get(
            f"https://api.jquants.com/v1/prices/daily_quotes",
            params={"code": code, "from": date_from},
            headers=headers,
            timeout=15
        )
        data = r.json().get("daily_quotes", [])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def jquants_get_listed_info(id_token):
    """上場銘柄一覧取得"""
    if not id_token:
        return pd.DataFrame()
    try:
        headers = {"Authorization": f"Bearer {id_token}"}
        r = requests.get(
            "https://api.jquants.com/v1/listed/info",
            headers=headers, timeout=15
        )
        data = r.json().get("info", [])
        return pd.DataFrame(data) if data else pd.DataFrame()
    except:
        return pd.DataFrame()

# ============================================================
# J-Quants接続状態
# ============================================================
jquants_available = False
id_token = None

if JQUANTS_EMAIL and JQUANTS_PASSWORD:
    refresh_token = jquants_get_refresh_token(JQUANTS_EMAIL, JQUANTS_PASSWORD)
    if refresh_token:
        id_token = jquants_get_id_token(refresh_token)
        jquants_available = id_token is not None

# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.header("📊 スクリーニング条件")
    gap_min   = st.slider("最小ギャップ率 (%)", -20, 30, 0)
    rvol_min  = st.slider("最小RVOL（同時間帯比）", 0.1, 20.0, 1.5, step=0.1)
    price_min = st.number_input("最小株価 (円)", value=300, step=100)
    price_max = st.number_input("最大株価 (円)", value=10000, step=500)

    st.divider()

    # J-Quants設定
    st.header("🔑 J-Quants API")
    if jquants_available:
        st.success("✅ J-Quants 接続済み")
    else:
        st.warning("未接続 - Secretsに設定してください")
        with st.expander("設定方法"):
            st.code("""# Streamlit Cloud > Settings > Secrets
JQUANTS_EMAIL = "tomimizu.s@email.com"
JQUANTS_PASSWORD = "#fnEsjdzH@y2SKu"
""")

    st.divider()
    st.warning("⚠️ 投資はご自身の判断と責任でお願いします。このツールは情報提供のみです。")

# ============================================================
# 同時間帯RVOL計算（yfinance）
# ============================================================
def calc_intraday_rvol(ticker: str, lookback_days: int = 10) -> dict:
    """
    現在の時間帯（例: 9:30時点）と過去N日の同時間帯出来高を比較するRVOL
    """
    try:
        tk   = yf.Ticker(ticker)
        hist = tk.history(period=f"{lookback_days + 3}d", interval="1h")
        if hist.empty or len(hist) < 4:
            return {"rvol": None, "method": "error"}

        hist.index = pd.to_datetime(hist.index)
        now_hour   = datetime.now().hour

        # 今日のデータ
        today_str  = datetime.now().strftime("%Y-%m-%d")
        today_data = hist[hist.index.strftime("%Y-%m-%d") == today_str]
        if today_data.empty:
            return {"rvol": None, "method": "no_today"}

        today_vol  = float(today_data["Volume"].sum())

        # 過去N日の同時間帯までの累積出来高
        past_vols = []
        for i in range(1, lookback_days + 1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            day_data = hist[hist.index.strftime("%Y-%m-%d") == d]
            if day_data.empty:
                continue
            # 同時間帯まで
            same_time = day_data[day_data.index.hour <= now_hour]
            if not same_time.empty:
                past_vols.append(float(same_time["Volume"].sum()))

        if not past_vols:
            # フォールバック: 日足の平均出来高比
            daily = tk.history(period="30d", interval="1d")
            if len(daily) >= 3:
                avg = float(daily["Volume"].iloc[:-1].mean())
                cur = float(daily["Volume"].iloc[-1])
                return {"rvol": cur / avg if avg > 0 else 0, "method": "daily_fallback"}
            return {"rvol": None, "method": "no_past"}

        avg_past_vol = np.mean(past_vols)
        rvol = today_vol / avg_past_vol if avg_past_vol > 0 else 0
        return {"rvol": round(rvol, 2), "method": "intraday"}

    except Exception as e:
        return {"rvol": None, "method": f"error: {str(e)[:30]}"}

# ============================================================
# スクリーニング本体
# ============================================================
DEFAULT_TICKERS = [
    "4385.T", "4565.T", "3696.T", "4480.T",
    "4880.T", "4011.T", "9984.T", "6861.T",
    "7203.T", "6758.T", "9432.T", "8306.T",
]

if "tickers" not in st.session_state:
    st.session_state.tickers = DEFAULT_TICKERS.copy()

@st.cache_data(ttl=180)
def screen_stocks(tickers, gap_min, rvol_min, price_min, price_max, use_jquants, _id_token):
    results = []
    logs    = []

    for ticker in tickers:
        try:
            # --- 日足データ取得 ---
            if use_jquants and _id_token:
                code = ticker.replace(".T", "")
                jdf  = jquants_get_prices(code, _id_token)
                if jdf.empty or len(jdf) < 3:
                    # フォールバック
                    hist = yf.Ticker(ticker).history(period="30d", interval="1d")
                    source = "yfinance(fallback)"
                else:
                    # J-Quantsデータをyfinance形式に変換
                    hist = pd.DataFrame({
                        "Open":   jdf["AdjustmentOpen"].values,
                        "High":   jdf["AdjustmentHigh"].values,
                        "Low":    jdf["AdjustmentLow"].values,
                        "Close":  jdf["AdjustmentClose"].values,
                        "Volume": jdf["Volume"].values,
                    }, index=jdf["Date"].values)
                    source = "J-Quants"
            else:
                hist   = yf.Ticker(ticker).history(period="30d", interval="1d")
                source = "yfinance"

            if hist.empty or len(hist) < 3:
                logs.append(f"{ticker}: データなし ({source})")
                continue

            today      = hist.iloc[-1]
            prev       = hist.iloc[-2]
            price      = float(today["Close"])
            open_price = float(today["Open"])
            prev_close = float(prev["Close"])
            volume     = float(today["Volume"])

            if prev_close <= 0:
                logs.append(f"{ticker}: prev_close異常")
                continue

            gap_pct    = ((open_price - prev_close) / prev_close) * 100
            change_pct = ((price - prev_close) / prev_close) * 100

            # --- 同時間帯RVOL ---
            rvol_data = calc_intraday_rvol(ticker)
            rvol      = rvol_data["rvol"]
            if rvol is None:
                # 日足フォールバック
                avg_vol = float(hist["Volume"].iloc[:-1].mean())
                rvol    = volume / avg_vol if avg_vol > 0 else 0
                rvol_method = "daily"
            else:
                rvol_method = rvol_data["method"]

            passed = (gap_pct >= gap_min and rvol >= rvol_min and price_min <= price <= price_max)
            logs.append(
                f"{ticker}: ¥{price:.0f} gap={gap_pct:.1f}% rvol={rvol:.1f}x({rvol_method}) [{source}] → {'✅' if passed else '❌フィルタ除外'}"
            )

            if not passed:
                continue

            results.append({
                "ティッカー":    ticker,
                "株価":         f"¥{price:,.0f}",
                "前日比(%)":    round(change_pct, 2),
                "ギャップ(%)":  round(gap_pct, 2),
                "RVOL":        round(rvol, 2),
                "RVOL方式":    rvol_method,
                "出来高":       f"{int(volume):,}",
                "データソース": source,
                "_ticker":     ticker,
                "_price":      price,
                "_change":     change_pct,
            })

        except Exception as e:
            logs.append(f"{ticker}: 例外 {str(e)[:60]}")

    return pd.DataFrame(results) if results else pd.DataFrame(), logs

# ============================================================
# UI
# ============================================================
st.subheader("🔍 監視銘柄リスト")
col1, col2 = st.columns([3, 1])
with col1:
    custom_input = st.text_input("銘柄コードを追加（例: 4385.T）", placeholder="ティッカーを入力")
with col2:
    if st.button("➕ 追加"):
        t = custom_input.strip().upper()
        if t and t not in st.session_state.tickers:
            st.session_state.tickers.append(t)
            st.rerun()

st.caption(
    f"監視中: {len(st.session_state.tickers)} 銘柄 | "
    + "　".join(st.session_state.tickers[:6])
    + ("..." if len(st.session_state.tickers) > 6 else "")
    + f" | データ: {'J-Quants + yfinance' if jquants_available else 'yfinance（同時間帯RVOL）'}"
)

col_scan, col_refresh = st.columns([2, 1])
with col_scan:
    run_scan = st.button("🚀 スキャン実行", type="primary", use_container_width=True)
with col_refresh:
    if st.button("🔄 キャッシュクリア", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if run_scan or "scan_results" in st.session_state:
    if run_scan:
        with st.spinner("スクリーニング中（同時間帯RVOL計算中）..."):
            df, logs = screen_stocks(
                tuple(st.session_state.tickers),
                gap_min, rvol_min, price_min, price_max,
                jquants_available, id_token
            )
            st.session_state.scan_results = df
            st.session_state.scan_logs    = logs

    df   = st.session_state.get("scan_results", pd.DataFrame())
    logs = st.session_state.get("scan_logs", [])

    with st.expander(f"📋 スクリーニングログ ({len(logs)}件)", expanded=df.empty):
        for l in logs:
            st.caption(l)

    if df.empty:
        st.info("条件に合う銘柄が見つかりませんでした。フィルターを調整してください。")
        st.caption(f"ギャップ≥{gap_min}% / RVOL≥{rvol_min} / 株価 {price_min}〜{price_max}円")
    else:
        st.success(f"✅ {len(df)} 銘柄ヒット")
        display_df = df.drop(columns=["_ticker", "_price", "_change"], errors="ignore")

        def highlight_row(row):
            try:
                c = float(str(row["前日比(%)"]))
                if c > 3:  return ["background-color: rgba(0,200,100,0.15)"] * len(row)
                if c < -3: return ["background-color: rgba(255,80,80,0.15)"] * len(row)
            except: pass
            return [""] * len(row)

        st.dataframe(display_df.style.apply(highlight_row, axis=1), use_container_width=True, height=350)

        # ============================================================
        # チャート
        # ============================================================
        st.divider()
        st.subheader("📈 チャート（VWAP・EMA9・EMA20・PDH）")
        selected = st.selectbox("銘柄を選択", df["ティッカー"].tolist())
        interval = st.radio("時間足", ["5m", "15m", "1h", "1d"], horizontal=True, index=1)
        period_map = {"5m": "5d", "15m": "5d", "1h": "30d", "1d": "90d"}

        @st.cache_data(ttl=120)
        def get_chart_data(ticker, interval, period):
            return yf.Ticker(ticker).history(period=period, interval=interval)

        with st.spinner("チャート取得中..."):
            hist = get_chart_data(selected, interval, period_map[interval])

        if not hist.empty:
            hist["TP"]      = (hist["High"] + hist["Low"] + hist["Close"]) / 3
            hist["Cum_TPV"] = (hist["TP"] * hist["Volume"]).cumsum()
            hist["Cum_Vol"] = hist["Volume"].cumsum()
            hist["VWAP"]    = hist["Cum_TPV"] / hist["Cum_Vol"]
            hist["EMA9"]    = hist["Close"].ewm(span=9,  adjust=False).mean()
            hist["EMA20"]   = hist["Close"].ewm(span=20, adjust=False).mean()

            pdh = None
            if interval in ["5m", "15m", "1h"]:
                hist.index = pd.to_datetime(hist.index)
                yesterday  = hist[hist.index.date < hist.index.date[-1]]
                if not yesterday.empty:
                    pdh = float(yesterday["High"].max())

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.75, 0.25], vertical_spacing=0.02)

            fig.add_trace(go.Candlestick(
                x=hist.index, open=hist["Open"], high=hist["High"],
                low=hist["Low"], close=hist["Close"], name="価格",
                increasing_line_color="#00C853", decreasing_line_color="#FF3D3D"
            ), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist["VWAP"],
                name="VWAP", line=dict(color="#FFD600", width=2)), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist["EMA9"],
                name="EMA9", line=dict(color="#40C4FF", width=1.5, dash="dash")), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist["EMA20"],
                name="EMA20", line=dict(color="#FF6D00", width=1.5, dash="dot")), row=1, col=1)

            if pdh:
                fig.add_hline(y=pdh, line=dict(color="#E040FB", width=1.5, dash="longdash"),
                              annotation_text=f"PDH ¥{pdh:,.0f}",
                              annotation_position="top right", row=1, col=1)

            colors = ["#00C853" if c >= o else "#FF3D3D"
                      for c, o in zip(hist["Close"], hist["Open"])]
            fig.add_trace(go.Bar(x=hist.index, y=hist["Volume"],
                name="出来高", marker_color=colors, opacity=0.7), row=2, col=1)

            fig.update_layout(
                height=600, template="plotly_dark",
                xaxis_rangeslider_visible=False,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.3)"
            )
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.05)")
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.05)")
            st.plotly_chart(fig, use_container_width=True)

            latest = hist.iloc[-1]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("現在値", f"¥{latest['Close']:,.0f}")
            c2.metric("VWAP",  f"¥{latest['VWAP']:,.0f}",
                      delta="VWAP上 ↑" if latest["Close"] > latest["VWAP"] else "VWAP下 ↓")
            c3.metric("EMA9",  f"¥{latest['EMA9']:,.0f}")
            c4.metric("EMA20", f"¥{latest['EMA20']:,.0f}")

            if latest["Close"] > latest["VWAP"]:
                st.success("📈 VWAP上 → ロングバイアス")
            else:
                st.error("📉 VWAP下 → ショートバイアス / 様子見")
        else:
            st.warning("チャートデータが取得できませんでした。")

st.divider()
st.caption("⚠️ 本ツールは情報提供目的のみです。投資判断はご自身の責任で行ってください（Invest at your own risk）。 | データソース: J-Quants / Yahoo Finance")
