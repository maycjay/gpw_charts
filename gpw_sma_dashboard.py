"""
GPW SMA Dashboard
------------------
Replaces the Excel chart (close / sma_50 / sma_200 / sma_ratio) with a fast,
web-hosted Streamlit app that queries your Neon Postgres `market` database
directly.

DEPLOY (Streamlit Community Cloud, free):
  1. Push this file + requirements.txt to a GitHub repo (public or private).
  2. Go to https://share.streamlit.io -> "New app" -> point at the repo/file.
  3. In the app's Settings -> Secrets, add (TOML format):

       [connection]
       host = "your-neon-host.neon.tech"
       port = 5432
       dbname = "market"
       user = "readonly_user"      # see security note below
       password = "your-password"
       sslmode = "require"

  4. Deploy. You'll get a public/private URL you can open on any device.

SECURITY NOTE:
  Create a dedicated READ-ONLY Postgres role for this app instead of reusing
  your main Neon credentials, e.g.:

    CREATE ROLE dashboard_ro WITH LOGIN PASSWORD 'choose-a-strong-password';
    GRANT CONNECT ON DATABASE market TO dashboard_ro;
    GRANT USAGE ON SCHEMA public TO dashboard_ro;
    GRANT SELECT ON gpw_notowania, p1_mv_sma, p1_mv_crosses, v_signals, stock_list, wolumen_by_rok TO dashboard_ro;

  Never commit the secrets.toml file to git -- Streamlit Cloud stores it
  separately from your repo.

LOCAL TEST:
  pip install -r requirements.txt
  Create .streamlit/secrets.toml locally with the same [connection] block.
  streamlit run gpw_sma_dashboard.py
"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="GPW SMA Dashboard", layout="wide")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
@st.cache_resource
def get_engine():
    c = st.secrets["connection"]
    url = (
        f"postgresql+psycopg2://{c['user']}:{c['password']}"
        f"@{c['host']}:{c.get('port', 5432)}/{c['dbname']}"
        f"?sslmode={c.get('sslmode', 'require')}"
    )
    return create_engine(url, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Data access (cached so re-runs / dropdown changes are fast)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_ticker_list() -> pd.DataFrame:
    # Orders by traded volume (wolumen_by_rok.sum), highest first; stocks
    # with no volume row (e.g. not yet ranked) sort last.
    q = """
        SELECT sl.stock
        FROM stock_list sl
        LEFT JOIN wolumen_by_rok wbr ON wbr.nazwa = sl.stock
        ORDER BY wbr.rank NULLS LAST
    """
    with get_engine().connect() as conn:
        return pd.read_sql(text(q), conn)


@st.cache_data(ttl=300)  # 5 min cache -- adjust to taste
def get_sma_data(nazwa: str, start: date, end: date) -> pd.DataFrame:
    # Mirrors chart.sql: filters on nazwa (name) rather than kod_isin.
    q = """
        SELECT date, close, sma_50, sma_200, sma_50 / sma_200 AS sma_ratio
        FROM v_signals
        WHERE nazwa = :nazwa
          AND date BETWEEN :start AND :end
        ORDER BY date
    """
    with get_engine().connect() as conn:
        df = pd.read_sql(
            text(q), conn, params={"nazwa": nazwa, "start": start, "end": end}
        )
    return df


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.header("Controls")

tickers = get_ticker_list()
DEFAULT_NAZWA = "KGHM"
default_idx = int(tickers.index[tickers["stock"] == DEFAULT_NAZWA][0]) if (
    tickers["stock"] == DEFAULT_NAZWA
).any() else 0

selected_nazwa = st.sidebar.selectbox(
    "Ticker",
    options=tickers["stock"],
    index=default_idx,
)

default_start = date.today() - timedelta(days=365)
start_date = st.sidebar.date_input("Start date", value=default_start)
end_date = st.sidebar.date_input("End date", value=date.today())

if st.sidebar.button("Force refresh (clear cache)"):
    get_sma_data.clear()
    st.rerun()

st.sidebar.caption("Data auto-refreshes every 5 minutes. Use the button above to force it sooner.")


# ---------------------------------------------------------------------------
# Main chart
# ---------------------------------------------------------------------------
df = get_sma_data(selected_nazwa, start_date, end_date)

st.title(f"{selected_nazwa}")

if df.empty:
    st.warning("No data for this ticker / date range.")
else:
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["close"], name="close",
        line=dict(color="#1f4e79", width=2.5), yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["sma_50"], name="sma_50",
        line=dict(color="#ed7d31", width=1.5, dash="dash"), yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["sma_200"], name="sma_200",
        line=dict(color="#548235", width=1.5, dash="dash"), yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["sma_ratio"], name="sma_ratio",
        line=dict(color="#a6a6a6", width=1), yaxis="y2",
    ))

    fig.update_layout(
        height=600,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
        yaxis=dict(title="Price (PLN)", side="left"),
        yaxis2=dict(
            title="sma_50 / sma_200",
            overlaying="y",
            side="right",
            tickformat=".0%",
        ),
        margin=dict(t=30, b=10),
    )
    # sma_ratio comes straight from SQL as sma_50/sma_200 (~1.0 = 100%),
    # which is already the fraction Plotly's percent tick format expects.

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)

st.caption("Source: Neon Postgres `market` DB · view `v_signals`")
