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
    GRANT SELECT ON gpw_notowania, p1_mv_sma, p1_mv_crosses TO dashboard_ro;

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
    q = """
        SELECT kod_isin, nazwa
        FROM p1_mv_sma
        GROUP BY kod_isin, nazwa
        ORDER BY nazwa
    """
    with get_engine().connect() as conn:
        return pd.read_sql(text(q), conn)


@st.cache_data(ttl=300)  # 5 min cache -- adjust to taste
def get_sma_data(kod_isin: str, start: date, end: date) -> pd.DataFrame:
    q = """
        SELECT date, close, sma_50, sma_200
        FROM p1_mv_sma
        WHERE kod_isin = :kod_isin
          AND date BETWEEN :start AND :end
        ORDER BY date
    """
    with get_engine().connect() as conn:
        df = pd.read_sql(
            text(q), conn, params={"kod_isin": kod_isin, "start": start, "end": end}
        )
    if not df.empty:
        df["sma_ratio"] = (df["close"] / df["sma_200"]) * 100
    return df


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.header("Controls")

tickers = get_ticker_list()
default_idx = int(tickers.index[tickers["kod_isin"] == "PLPZU0000011"][0]) if (
    tickers["kod_isin"] == "PLPZU0000011"
).any() else 0

label_map = {row.kod_isin: f"{row.nazwa} ({row.kod_isin})" for row in tickers.itertuples()}
selected_isin = st.sidebar.selectbox(
    "Ticker",
    options=tickers["kod_isin"],
    format_func=lambda isin: label_map.get(isin, isin),
    index=default_idx,
)

default_start = date.today() - timedelta(days=500)
start_date = st.sidebar.date_input("Start date", value=default_start)
end_date = st.sidebar.date_input("End date", value=date.today())

if st.sidebar.button("Force refresh (clear cache)"):
    get_sma_data.clear()
    st.rerun()

st.sidebar.caption("Data auto-refreshes every 5 minutes. Use the button above to force it sooner.")


# ---------------------------------------------------------------------------
# Main chart
# ---------------------------------------------------------------------------
df = get_sma_data(selected_isin, start_date, end_date)
selected_name = label_map.get(selected_isin, selected_isin)

st.title(f"{selected_name}")

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
            title="close / sma_200 (%)",
            overlaying="y",
            side="right",
            tickformat=".0%",
            ticksuffix="",
        ),
        margin=dict(t=30, b=10),
    )
    # sma_ratio is computed as a plain percentage number (e.g. 116.3);
    # convert to fraction so the percent tick format above reads correctly.
    fig.data[3].y = df["sma_ratio"] / 100

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)

st.caption("Source: Neon Postgres `market` DB · view `p1_mv_sma`")
