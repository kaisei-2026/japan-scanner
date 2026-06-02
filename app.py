import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import requests

st.set_page_config(
    page_title="Japan Stock Scanner",
    page_icon="🇯🇵",
    layout="wide"
)

st.title("🇯🇵 Japan Stock Scanner")
st.caption("グロース市場対応 | VWAP・EMA・出来高スクリーナー")

# --- Sidebar: Screening filters ---
with st.sidebar:
    st.header("📊 スクリーニング条件")

    gap_min = st.slider("最小ギャップ率 (%)", 0, 30, 5)
    rvol_min = st.slider("最小RVOL（出来高倍率）", 1.0, 20.0, 3.0, step=0.5)
    price_min = st.number_input("最小株価 (円)", value=300, step=100)
    price_max = st.number_input("最大株価 (円)", value=5000, step=100)

    st.divider()
    st.header("⚠️ 注意事項")
    st.warning(
        "投資はご自身の判断と責任でお願いします。"
        "このツールは情報提供のみを目的としており、"
        "投資助言ではありません。"
    )

# --- Default watchlist (TSE Growth stocks) ---
DEFAULT_TICKERS = [
    "4563.T",  # アンジェス
    "4385.T",  # メルカリ
    "4565.T",  # そーせい
    "3696.T",  # セレス
    "4480.T",  # メドレー
    "4880.T",  # セルソース
    "4194.T",  # ウィルゲート
    "5032.T",  # アスタリスク
    "4011.T",  # ヘッドウォータース
    "4243.T",  # ニッスイ (sample)
    "7011.T",  # 三菱重工
    "9984.T",  # ソフトバンクG
    "6861.T",  # キーエンス
]

# --- Custom ticker input ---
st.subheader("🔍 監視銘柄リスト")
col1, col2 = st.columns([3, 1])
with col1:
    custom_input = st.text_input(
        "銘柄コードを追加（例: 4385.T）",
        placeholder="ティッカーを入力してEnter"
    )
with col2:
    if st.button("➕ 追加"):
        if custom_input and custom_input not in st.session_state.get("tickers", DEFAULT_TICKERS):
            if "tickers" not in st.session_state:
                st.session_state.tickers = DEFAULT_TICKERS.copy()
            st.session_state.tickers.append(custom_input.upper())

if "tickers" not in st.session_state:
    st.session_state.tickers = DEFAULT_TICKERS.copy()

# --- Screening function ---
@st.cache_data(ttl=300)
def screen_stocks(tickers, gap_min, rvol_min, price_min, price_max):
    results = []
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="30d", interval="1d")
            if hist.empty or len(hist) < 5:
                continue

            today = hist.iloc[-1]
            prev = hist.iloc[-2]

            price = today["Close"]
            gap_pct = ((today["Open"] - prev["Close"]) / prev["Close"]) * 100
            avg_vol = hist["Volume"].iloc[:-1].mean()
            rvol = today["Volume"] / avg_vol if avg_vol > 0 else 0
            change_pct = ((price - prev["Close"]) / prev["Close"]) * 100

            # Filter
            if gap_pct < gap_min:
                continue
            if rvol < rvol_min:
                continue
            if not (price_min <= price <= price_max):
                continue

            info = tk.info
            market_cap = info.get("marketCap", 0)
            market_cap_b = market_cap / 1e8 if market_cap else 0  # 億円

            results.append({
                "ティッカー": ticker,
                "銘柄名": info.get("longName", ticker),
                "株価": f"¥{price:,.0f}",
                "前日比(%)": round(change_pct, 2),
                "ギャップ(%)": round(gap_pct, 2),
                "RVOL": round(rvol, 1),
                "時価総額(億円)": round(market_cap_b, 0),
                "_ticker": ticker,
                "_price": price,
                "_change": change_pct,
            })
        except Exception:
            continue

    df = pd.DataFrame(results) if results else pd.DataFrame()
    return df

# --- Run scan ---
col_scan, col_refresh = st.columns([2, 1])
with col_scan:
    run_scan = st.button("🚀 スキャン実行", type="primary", use_container_width=True)
with col_refresh:
    if st.button("🔄 キャッシュクリア", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if run_scan or "scan_results" in st.session_state:
    if run_scan:
        with st.spinner("スクリーニング中..."):
            df = screen_stocks(
                tuple(st.session_state.tickers),
                gap_min, rvol_min, price_min, price_max
            )
            st.session_state.scan_results = df

    df = st.session_state.get("scan_results", pd.DataFrame())

    if df.empty:
        st.info("条件に合う銘柄が見つかりませんでした。フィルターを緩めてみてください。")
    else:
        st.success(f"✅ {len(df)} 銘柄がヒットしました")

        display_df = df.drop(columns=["_ticker", "_price", "_change"], errors="ignore")

        def highlight_row(row):
            change = float(str(row["前日比(%)"]))
            if change > 5:
                return ["background-color: rgba(0,200,100,0.15)"] * len(row)
            elif change < -5:
                return ["background-color: rgba(255,80,80,0.15)"] * len(row)
            return [""] * len(row)

        st.dataframe(
            display_df.style.apply(highlight_row, axis=1),
            use_container_width=True,
            height=300
        )

        # --- Chart section ---
        st.divider()
        st.subheader("📈 チャート表示（VWAP・EMA9・EMA20）")

        ticker_options = df["ティッカー"].tolist()
        selected = st.selectbox("銘柄を選択", ticker_options)

        interval = st.radio(
            "時間足",
            ["5m", "15m", "1h", "1d"],
            horizontal=True,
            index=1
        )

        period_map = {"5m": "5d", "15m": "5d", "1h": "30d", "1d": "90d"}

        @st.cache_data(ttl=120)
        def get_chart_data(ticker, interval, period):
            tk = yf.Ticker(ticker)
            hist = tk.history(period=period, interval=interval)
            return hist

        with st.spinner("チャートデータ取得中..."):
            hist = get_chart_data(selected, interval, period_map[interval])

        if not hist.empty:
            # VWAP calculation
            hist["TP"] = (hist["High"] + hist["Low"] + hist["Close"]) / 3
            hist["Cum_TPV"] = (hist["TP"] * hist["Volume"]).cumsum()
            hist["Cum_Vol"] = hist["Volume"].cumsum()
            hist["VWAP"] = hist["Cum_TPV"] / hist["Cum_Vol"]

            # EMA
            hist["EMA9"] = hist["Close"].ewm(span=9, adjust=False).mean()
            hist["EMA20"] = hist["Close"].ewm(span=20, adjust=False).mean()

            # PDH (previous day high)
            if interval in ["5m", "15m", "1h"]:
                hist.index = pd.to_datetime(hist.index)
                yesterday = hist[hist.index.date < hist.index.date[-1]].copy()
                pdh = yesterday["High"].max() if not yesterday.empty else None
            else:
                pdh = None

            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                row_heights=[0.75, 0.25],
                vertical_spacing=0.02
            )

            # Candlestick
            fig.add_trace(
                go.Candlestick(
                    x=hist.index,
                    open=hist["Open"],
                    high=hist["High"],
                    low=hist["Low"],
                    close=hist["Close"],
                    name="価格",
                    increasing_line_color="#00C853",
                    decreasing_line_color="#FF3D3D",
                ),
                row=1, col=1
            )

            # VWAP
            fig.add_trace(
                go.Scatter(
                    x=hist.index, y=hist["VWAP"],
                    name="VWAP", line=dict(color="#FFD600", width=2)
                ),
                row=1, col=1
            )

            # EMA9
            fig.add_trace(
                go.Scatter(
                    x=hist.index, y=hist["EMA9"],
                    name="EMA9", line=dict(color="#40C4FF", width=1.5, dash="dash")
                ),
                row=1, col=1
            )

            # EMA20
            fig.add_trace(
                go.Scatter(
                    x=hist.index, y=hist["EMA20"],
                    name="EMA20", line=dict(color="#FF6D00", width=1.5, dash="dot")
                ),
                row=1, col=1
            )

            # PDH line
            if pdh:
                fig.add_hline(
                    y=pdh,
                    line=dict(color="#E040FB", width=1.5, dash="longdash"),
                    annotation_text=f"PDH ¥{pdh:,.0f}",
                    annotation_position="top right",
                    row=1, col=1
                )

            # Volume
            colors = ["#00C853" if c >= o else "#FF3D3D"
                      for c, o in zip(hist["Close"], hist["Open"])]
            fig.add_trace(
                go.Bar(
                    x=hist.index, y=hist["Volume"],
                    name="出来高", marker_color=colors, opacity=0.7
                ),
                row=2, col=1
            )

            fig.update_layout(
                height=600,
                template="plotly_dark",
                xaxis_rangeslider_visible=False,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0.3)",
            )

            fig.update_xaxes(
                gridcolor="rgba(255,255,255,0.05)",
                showgrid=True
            )
            fig.update_yaxes(
                gridcolor="rgba(255,255,255,0.05)",
                showgrid=True
            )

            st.plotly_chart(fig, use_container_width=True)

            # Key stats
            latest = hist.iloc[-1]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("現在値", f"¥{latest['Close']:,.0f}")
            c2.metric("VWAP", f"¥{latest['VWAP']:,.0f}",
                      delta=f"{'上' if latest['Close'] > latest['VWAP'] else '下'}にある")
            c3.metric("EMA9", f"¥{latest['EMA9']:,.0f}")
            c4.metric("EMA20", f"¥{latest['EMA20']:,.0f}")

            # VWAP signal
            if latest["Close"] > latest["VWAP"]:
                st.success("📈 VWAP上 → ロングバイアス")
            else:
                st.error("📉 VWAP下 → ショートバイアス / 様子見")

        else:
            st.warning("チャートデータが取得できませんでした。")

# Footer
st.divider()
st.caption(
    "⚠️ 本ツールは情報提供目的のみです。投資判断はご自身の責任で行ってください（Invest at your own risk）。"
    " | データソース: Yahoo Finance"
)
