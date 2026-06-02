import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Japan Stock Scanner", page_icon="🇯🇵", layout="wide")
st.title("🇯🇵 Japan Stock Scanner")
st.caption("グロース市場対応 | VWAP・EMA・出来高スクリーナー")

# --- デバッグパネル ---
with st.expander("🛠️ データ取得テスト（問題調査用）", expanded=True):
    test_ticker = st.text_input("テスト銘柄", value="7203.T")
    if st.button("テスト実行"):
        try:
            tk = yf.Ticker(test_ticker)
            hist = tk.history(period="10d", interval="1d")
            if hist.empty:
                st.error("❌ データが空です。yfinanceが日本株を取得できていません。")
            else:
                st.success(f"✅ {len(hist)}行取得成功！")
                st.dataframe(hist.tail(3))
                today = hist.iloc[-1]
                prev  = hist.iloc[-2]
                gap   = ((today["Open"] - prev["Close"]) / prev["Close"]) * 100
                avg_v = hist["Volume"].iloc[:-1].mean()
                rvol  = today["Volume"] / avg_v if avg_v > 0 else 0
                st.write(f"株価: ¥{today['Close']:,.0f} | ギャップ: {gap:.2f}% | RVOL: {rvol:.2f}x")
        except Exception as e:
            st.error(f"❌ エラー: {e}")

st.divider()

# --- Sidebar ---
with st.sidebar:
    st.header("📊 スクリーニング条件")
    gap_min   = st.slider("最小ギャップ率 (%)", -20, 30, 0)
    rvol_min  = st.slider("最小RVOL", 0.1, 20.0, 1.0, step=0.1)
    price_min = st.number_input("最小株価 (円)", value=0, step=100)
    price_max = st.number_input("最大株価 (円)", value=100000, step=1000)
    st.divider()
    st.warning("投資はご自身の判断と責任でお願いします。このツールは情報提供のみを目的としており、投資助言ではありません。")

DEFAULT_TICKERS = [
    "4385.T", "4565.T", "3696.T", "4480.T",
    "4880.T", "4011.T", "9984.T", "6861.T",
    "7203.T", "6758.T", "9432.T", "8306.T",
]

if "tickers" not in st.session_state:
    st.session_state.tickers = DEFAULT_TICKERS.copy()

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

st.caption(f"監視中: {len(st.session_state.tickers)} 銘柄 | " + "　".join(st.session_state.tickers[:6]) + ("..." if len(st.session_state.tickers) > 6 else ""))

@st.cache_data(ttl=300)
def screen_stocks(tickers, gap_min, rvol_min, price_min, price_max):
    results = []
    errors  = []
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="30d", interval="1d")
            if hist.empty or len(hist) < 3:
                errors.append(f"{ticker}: データなし (行数={len(hist)})")
                continue

            today      = hist.iloc[-1]
            prev       = hist.iloc[-2]
            price      = float(today["Close"])
            open_price = float(today["Open"])
            prev_close = float(prev["Close"])
            volume     = float(today["Volume"])

            if prev_close <= 0:
                errors.append(f"{ticker}: prev_close={prev_close}")
                continue

            gap_pct    = ((open_price - prev_close) / prev_close) * 100
            avg_vol    = float(hist["Volume"].iloc[:-1].mean())
            rvol       = volume / avg_vol if avg_vol > 0 else 0
            change_pct = ((price - prev_close) / prev_close) * 100

            errors.append(f"{ticker}: 株価={price:.0f} gap={gap_pct:.1f}% rvol={rvol:.1f}x → {'✅通過' if (gap_pct >= gap_min and rvol >= rvol_min and price_min <= price <= price_max) else '❌フィルタ除外'}")

            if gap_pct < gap_min:
                continue
            if rvol < rvol_min:
                continue
            if not (price_min <= price <= price_max):
                continue

            results.append({
                "ティッカー": ticker,
                "株価":       f"¥{price:,.0f}",
                "前日比(%)":  round(change_pct, 2),
                "ギャップ(%)": round(gap_pct, 2),
                "RVOL":       round(rvol, 2),
                "出来高":     f"{int(volume):,}",
                "_ticker":    ticker,
                "_price":     price,
                "_change":    change_pct,
            })
        except Exception as e:
            errors.append(f"{ticker}: 例外 {str(e)[:60]}")

    return pd.DataFrame(results) if results else pd.DataFrame(), errors

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
            df, errors = screen_stocks(
                tuple(st.session_state.tickers),
                gap_min, rvol_min, price_min, price_max
            )
            st.session_state.scan_results = df
            st.session_state.scan_errors  = errors

    df     = st.session_state.get("scan_results", pd.DataFrame())
    errors = st.session_state.get("scan_errors", [])

    # 常に詳細ログ表示
    with st.expander(f"📋 スクリーニングログ ({len(errors)}件)", expanded=df.empty):
        for e in errors:
            st.caption(e)

    if df.empty:
        st.info("条件に合う銘柄が見つかりませんでした。上のログで各銘柄の状況を確認してください。")
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

        st.divider()
        st.subheader("📈 チャート（VWAP・EMA9・EMA20）")
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
                              annotation_text=f"PDH ¥{pdh:,.0f}", annotation_position="top right", row=1, col=1)
            colors = ["#00C853" if c >= o else "#FF3D3D" for c, o in zip(hist["Close"], hist["Open"])]
            fig.add_trace(go.Bar(x=hist.index, y=hist["Volume"],
                name="出来高", marker_color=colors, opacity=0.7), row=2, col=1)
            fig.update_layout(height=600, template="plotly_dark",
                xaxis_rangeslider_visible=False,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.3)")
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
st.caption("⚠️ 本ツールは情報提供目的のみです。投資判断はご自身の責任で行ってください（Invest at your own risk）。 | データソース: Yahoo Finance")
