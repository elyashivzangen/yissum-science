from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

BOI_API_URL = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0/"


def to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(',', '')
    if s in {'', '--', 'nan', 'None'}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or '').strip().strip('"')
    if not s:
        return None
    s = s.split(',')[0].strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def period_for(d: date) -> str:
    return 'H1' if d.month <= 6 else 'H2'


def recognized_tax_gl(nominal_nis: float, usd_pl_sell_fx_nis: float) -> float:
    if nominal_nis > 0 and usd_pl_sell_fx_nis > 0:
        return min(nominal_nis, usd_pl_sell_fx_nis)
    if nominal_nis < 0 and usd_pl_sell_fx_nis < 0:
        return -min(abs(nominal_nis), abs(usd_pl_sell_fx_nis))
    return 0.0


def read_ibkr_file(file_bytes: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix in {'.xlsx', '.xls'}:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], dtype=str, header=None).fillna('')
        return df.astype(str).values.tolist()
    return list(csv.reader(io.StringIO(file_bytes.decode('utf-8-sig', errors='replace'))))


def parse_ibkr(file_bytes: bytes, filename: str):
    rows = read_ibkr_file(file_bytes, filename)
    header = {}
    account = ''
    period = ''
    sale = None
    lots, dividends, withholding = [], [], []
    seen_div, seen_wh = set(), set()

    for i, r in enumerate(rows, 1):
        if len(r) < 2:
            continue
        section, kind = str(r[0]).strip(), str(r[1]).strip()
        if kind == 'Header':
            header[section] = [str(x).strip() for x in r[2:]]
            if section != 'Trades':
                sale = None
            continue
        if kind not in {'Data', 'SubTotal', 'Total'}:
            continue
        h = header.get(section, [])
        data = {h[j]: (r[2+j] if 2+j < len(r) else '') for j in range(len(h))}

        if section == 'Statement' and data.get('Field Name') == 'Period':
            period = data.get('Field Value', '')
        if section == 'Account Information' and data.get('Field Name') == 'Account':
            account = data.get('Field Value', '')

        if section == 'Trades' and kind == 'Data':
            dd = data.get('DataDiscriminator', '')
            asset = data.get('Asset Category', '')
            currency = data.get('Currency', '')
            symbol = data.get('Symbol', '')
            if asset == 'Stocks' and currency == 'USD' and dd == 'Order':
                qty = to_float(data.get('Quantity'))
                if qty < 0:
                    sale = {
                        'row': i,
                        'symbol': symbol,
                        'sell_date': to_date(data.get('Date/Time')),
                        'sell_qty': abs(qty),
                        'gross_proceeds_usd': to_float(data.get('Proceeds')),
                        'sell_commission_usd': to_float(data.get('Comm/Fee')),
                    }
                continue
            if asset == 'Stocks' and currency == 'USD' and dd == 'ClosedLot' and sale and sale['symbol'] == symbol:
                qty = abs(to_float(data.get('Quantity')))
                alloc = qty / sale['sell_qty'] if sale['sell_qty'] else 1
                basis = abs(to_float(data.get('Basis')))
                ibkr_pl = to_float(data.get('Realized P/L'))
                lots.append({
                    'source_row': i,
                    'symbol': symbol,
                    'buy_date': to_date(data.get('Date/Time')),
                    'sell_date': sale['sell_date'],
                    'period': period_for(sale['sell_date']),
                    'quantity': qty,
                    'cost_basis_usd': basis,
                    'net_proceeds_usd': basis + ibkr_pl,
                    'gross_proceeds_usd_alloc': sale['gross_proceeds_usd'] * alloc,
                    'sell_commission_usd_alloc': sale['sell_commission_usd'] * alloc,
                    'ibkr_realized_pl_usd': ibkr_pl,
                    'code': data.get('Code', ''),
                })

        if section == 'Dividends' and kind == 'Data' and data.get('Currency') == 'USD':
            d = to_date(data.get('Date'))
            amt = to_float(data.get('Amount'))
            desc = data.get('Description', '')
            key = (d, desc, round(amt, 8))
            if d and key not in seen_div:
                dividends.append({'date': d, 'symbol': symbol_from_desc(desc), 'description': desc, 'amount_usd': amt, 'source_row': i})
                seen_div.add(key)
        if section == 'Withholding Tax' and kind == 'Data' and data.get('Currency') == 'USD':
            d = to_date(data.get('Date'))
            amt = to_float(data.get('Amount'))
            desc = data.get('Description', '')
            key = (d, desc, round(amt, 8))
            if d and key not in seen_wh:
                withholding.append({'date': d, 'symbol': symbol_from_desc(desc), 'description': desc, 'amount_usd': amt, 'source_row': i})
                seen_wh.add(key)

    return {
        'account': account,
        'period': period,
        'capital_lots': pd.DataFrame(lots),
        'dividends': pd.DataFrame(dividends),
        'withholding': pd.DataFrame(withholding),
    }


def symbol_from_desc(desc: str) -> str:
    m = re.match(r'([A-Z0-9.\-]+)\(', str(desc))
    return m.group(1) if m else ''


class BOIFx:
    def __init__(self):
        self.cache = {}

    def rates(self, dates: Iterable[date]):
        dates = sorted({d for d in dates if d})
        if not dates:
            return {}
        missing = [d for d in dates if d.isoformat() not in self.cache]
        if missing:
            self._download(min(missing) - timedelta(days=14), max(missing))
        out = {}
        for d in dates:
            cur = d
            while cur >= d - timedelta(days=30):
                if cur.isoformat() in self.cache:
                    out[d] = self.cache[cur.isoformat()]
                    break
                cur -= timedelta(days=1)
            if d not in out:
                raise RuntimeError(f'Missing BOI USD/ILS rate for {d}')
        return out

    def _download(self, start: date, end: date):
        params = {
            'c[BASE_CURRENCY]': 'USD',
            'c[COUNTER_CURRENCY]': 'ILS',
            'format': 'csv',
            'startPeriod': start.isoformat(),
            'endPeriod': end.isoformat(),
        }
        r = requests.get(BOI_API_URL, params=params, timeout=25)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        dcol = next((c for c in df.columns if str(c).upper() == 'TIME_PERIOD'), None)
        vcol = next((c for c in df.columns if str(c).upper() == 'OBS_VALUE'), None)
        if not dcol or not vcol:
            raise RuntimeError('BOI response missing TIME_PERIOD/OBS_VALUE')
        for _, row in df.iterrows():
            d = to_date(row[dcol])
            v = to_float(row[vcol])
            if d and v:
                self.cache[d.isoformat()] = v


def single_boi_url(d: date) -> str:
    return f'{BOI_API_URL}?c%5BBASE_CURRENCY%5D=USD&c%5BCOUNTER_CURRENCY%5D=ILS&format=csv&endPeriod={d.isoformat()}&lastNObservations=1'


def calculate(parsed, fx_rates: dict[date, float], capital_tax=0.25, dividend_tax=0.25, carried_loss=0.0, paid_advances=0.0):
    lots = parsed['capital_lots'].copy()
    if not lots.empty:
        lots['buy_fx'] = lots['buy_date'].map(fx_rates)
        lots['sell_fx'] = lots['sell_date'].map(fx_rates)
        lots['cost_nis_at_buy_fx'] = lots['cost_basis_usd'] * lots['buy_fx']
        lots['consideration_nis_at_sell_fx'] = lots['net_proceeds_usd'] * lots['sell_fx']
        lots['nominal_gain_loss_nis'] = lots['consideration_nis_at_sell_fx'] - lots['cost_nis_at_buy_fx']
        lots['usd_pl_at_sell_fx_nis'] = (lots['net_proceeds_usd'] - lots['cost_basis_usd']) * lots['sell_fx']
        lots['recognized_gain_loss_nis'] = lots.apply(lambda r: recognized_tax_gl(r['nominal_gain_loss_nis'], r['usd_pl_at_sell_fx_nis']), axis=1)
        lots['preliminary_tax_nis'] = lots['recognized_gain_loss_nis'].clip(lower=0) * capital_tax
    else:
        lots = pd.DataFrame()

    div = parsed['dividends'].copy()
    wh = parsed['withholding'].copy()
    if not div.empty:
        div['fx'] = div['date'].map(fx_rates)
        div['gross_nis'] = div['amount_usd'] * div['fx']
    if not wh.empty:
        wh['fx'] = wh['date'].map(fx_rates)
        wh['foreign_tax_nis'] = wh['amount_usd'].abs() * wh['fx']
    if not div.empty:
        whg = wh.groupby(['date', 'symbol'])['foreign_tax_nis'].sum().reset_index() if not wh.empty else pd.DataFrame(columns=['date', 'symbol', 'foreign_tax_nis'])
        div = div.merge(whg, on=['date', 'symbol'], how='left').fillna({'foreign_tax_nis': 0})
        div['israeli_tax_before_credit_nis'] = div['gross_nis'] * dividend_tax
        div['foreign_tax_credit_used_nis'] = div[['foreign_tax_nis', 'israeli_tax_before_credit_nis']].min(axis=1)
        div['additional_israeli_tax_nis'] = (div['israeli_tax_before_credit_nis'] - div['foreign_tax_credit_used_nis']).clip(lower=0)

    ytd = lots['recognized_gain_loss_nis'].sum() if not lots.empty else 0.0
    taxable_capital = max(ytd - max(carried_loss, 0), 0)
    capital_tax_nis = taxable_capital * capital_tax
    div_tax_nis = div['additional_israeli_tax_nis'].sum() if not div.empty else 0.0
    summary = pd.DataFrame([
        ['Recognized capital gains', lots['recognized_gain_loss_nis'].clip(lower=0).sum() if not lots.empty else 0.0],
        ['Recognized capital losses', lots['recognized_gain_loss_nis'].clip(upper=0).sum() if not lots.empty else 0.0],
        ['Net capital gain/loss before carried loss', ytd],
        ['Gross dividends', div['gross_nis'].sum() if not div.empty else 0.0],
        ['Foreign tax on dividends', div['foreign_tax_nis'].sum() if not div.empty and 'foreign_tax_nis' in div else 0.0],
        ['Additional Israeli tax on dividends', div_tax_nis],
        ['Taxable capital gain after carried loss', taxable_capital],
        ['Estimated capital gains tax', capital_tax_nis],
        ['Paid advances entered', paid_advances],
        ['Estimated total balance to pay', max(capital_tax_nis + div_tax_nis - paid_advances, 0)],
    ], columns=['metric', 'YTD'])
    fx = pd.DataFrame([{'event_date': d, 'usd_ils_rate': v, 'api_url': single_boi_url(d)} for d, v in sorted(fx_rates.items())])
    return {'summary': summary, 'capital_gains': lots, 'dividends_tax': div, 'withholding_tax': wh, 'fx_rates': fx}


def export_package(calc, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx = out_dir / 'ibkr_tax_authority_package.xlsx'
    html = out_dir / 'ibkr_tax_authority_package_summary.html'
    zip_path = out_dir / 'ibkr_tax_authority_package.zip'
    with pd.ExcelWriter(xlsx, engine='xlsxwriter') as writer:
        for name, df in [('Dashboard', calc['summary']), ('Capital_Gains', calc['capital_gains']), ('Dividends_Tax', calc['dividends_tax']), ('Withholding_Tax', calc['withholding_tax']), ('BOI_FX_Rates', calc['fx_rates'])]:
            df.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            if name == 'Dashboard':
                ws.right_to_left()
            ws.freeze_panes(1, 0)
            for col, c in enumerate(df.columns):
                ws.set_column(col, col, min(max(12, len(str(c)) + 2), 45))
    summary_html = calc['summary'].to_html(index=False, border=0, float_format=lambda x: f'{x:,.2f}')
    html.write_text(f"""<!doctype html><html lang='he' dir='rtl'><meta charset='utf-8'><style>body{{font-family:Arial;margin:28px}}table{{border-collapse:collapse;direction:ltr}}td,th{{border:1px solid #ccc;padding:6px}}th{{background:#1F4E78;color:white}}</style><h1>נספח עבודה - חישוב מס IBKR</h1><p>מסמך עבודה בלבד; לא מחליף טפסים רשמיים או ייעוץ מס.</p>{summary_html}</html>""", encoding='utf-8')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(xlsx, xlsx.name)
        z.write(html, html.name)
        for name, df in [('capital_gains_detail.csv', calc['capital_gains']), ('dividends_tax.csv', calc['dividends_tax']), ('boi_fx_rates.csv', calc['fx_rates']), ('summary.csv', calc['summary'])]:
            p = out_dir / name
            df.to_csv(p, index=False, encoding='utf-8-sig')
            z.write(p, name)
    return zip_path, xlsx, html
