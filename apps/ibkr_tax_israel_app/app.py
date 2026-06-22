from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from tax_engine import BOIFx, calculate, export_package, parse_ibkr

st.set_page_config(page_title='IBKR Israel Tax App', page_icon='📊', layout='wide')
st.title('חישוב מס ישראלי ל-Interactive Brokers')
st.caption('העלה Activity Statement של IBKR, חשב רווחי הון לפי השיטה הישראלית, והורד חבילת עבודה לרשות המסים.')

with st.sidebar:
    st.header('הגדרות')
    capital_tax = st.number_input('שיעור מס רווח הון', min_value=0.0, max_value=1.0, value=0.25, step=0.01, format='%.2f')
    dividend_tax = st.number_input('שיעור מס דיבידנד', min_value=0.0, max_value=1.0, value=0.25, step=0.01, format='%.2f')
    carried_loss = st.number_input('הפסד הון מועבר בשח', value=0.0, step=100.0, format='%.2f')
    paid_advances = st.number_input('מקדמות ששולמו בשח', value=0.0, step=100.0, format='%.2f')

uploaded = st.file_uploader('העלה קובץ IBKR Activity Statement CSV/Excel', type=['csv', 'xlsx', 'xls'])
if not uploaded:
    st.info('העלה קובץ כדי להתחיל. מומלץ להפיק מ-IBKR גם CSV לעיבוד וגם PDF כאסמכתא.')
    st.stop()

parsed = parse_ibkr(uploaded.read(), uploaded.name)
st.subheader('זיהוי הדוח')
c1, c2, c3 = st.columns(3)
c1.metric('חשבון', parsed['account'] or 'לא זוהה')
c2.metric('תקופה', parsed['period'] or 'לא זוהתה')
c3.metric('שכבות Closed Lot', len(parsed['capital_lots']))

# Build list of all dates needed for Bank of Israel rates.
event_dates = set()
for df_name in ['capital_lots', 'dividends', 'withholding']:
    df = parsed[df_name]
    if not df.empty:
        for col in ['buy_date', 'sell_date', 'date']:
            if col in df:
                event_dates.update(df[col].dropna().tolist())

try:
    with st.spinner('שולף שערי בנק ישראל ומחשב...'):
        fx_rates = BOIFx().rates(event_dates)
        calc = calculate(parsed, fx_rates, capital_tax, dividend_tax, carried_loss, paid_advances)
except Exception as exc:
    st.error(f'שליפת שערי בנק ישראל או החישוב נכשלו: {exc}')
    st.stop()

st.subheader('סיכום')
st.dataframe(calc['summary'], use_container_width=True, hide_index=True)

if not calc['capital_gains'].empty:
    st.subheader('פירוט מכירות ממומשות')
    cols = [c for c in ['symbol','buy_date','sell_date','quantity','cost_basis_usd','net_proceeds_usd','buy_fx','sell_fx','nominal_gain_loss_nis','usd_pl_at_sell_fx_nis','recognized_gain_loss_nis'] if c in calc['capital_gains'].columns]
    st.dataframe(calc['capital_gains'][cols], use_container_width=True, hide_index=True)

if not calc['dividends_tax'].empty:
    st.subheader('דיבידנדים ומס זר')
    st.dataframe(calc['dividends_tax'], use_container_width=True, hide_index=True)

with tempfile.TemporaryDirectory() as d:
    zip_path, xlsx_path, html_path = export_package(calc, Path(d))
    st.subheader('הורדות')
    a, b, c = st.columns(3)
    a.download_button('הורד ZIP לרשות המסים/רו״ח', zip_path.read_bytes(), 'ibkr_tax_authority_package.zip', 'application/zip')
    b.download_button('הורד Excel', xlsx_path.read_bytes(), 'ibkr_tax_authority_package.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    c.download_button('הורד נספח HTML', html_path.read_bytes(), 'ibkr_tax_authority_package_summary.html', 'text/html')

st.caption('הפלט הוא נספח עבודה בלבד. הוא אינו מחליף את טפסי רשות המסים הרשמיים ואינו חוות דעת מס.')
