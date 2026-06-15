import pandas as pd
from pathlib import Path

BASE = Path(r'D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline')

HOLD = BASE / 'outputs/latest/sfd_account_execution_latest.csv'
WATCH = BASE / 'inputs/sfd_0835_watchlist_input.csv'
CASH = BASE / 'inputs/sfd_cash_status_input.csv'
PREV = BASE / 'inputs/sfd_prev_close_input.csv'
OUT = BASE / 'outputs/sfd_0835_order_plan_latest.csv'

hold = pd.read_csv(HOLD, encoding='utf-8-sig', dtype={'stock_code': str})
watch = pd.read_csv(WATCH, encoding='utf-8-sig', dtype={'stock_code': str})
cash = pd.read_csv(CASH, encoding='utf-8-sig', dtype={'stock_code': str})
prev = pd.read_csv(PREV, encoding='utf-8-sig', dtype={'stock_code': str})

cols = watch.columns.tolist()

out = pd.DataFrame(columns=cols)

out['stock_code'] = hold['stock_code']
out['corp_name'] = hold['corp_name']
out['corp_name_kr'] = hold['corp_name']
out['action_type'] = hold['execution_signal']
out['sfd_signal'] = hold['execution_signal']
out['prev_close_or_current'] = hold['current_price']
out['avg_price'] = hold['avg_price']
out['holding_qty'] = hold['quantity']
out['available_qty'] = hold['quantity']
out['sell_price_1'] = hold['first_sell_price']
out['sell_qty_1'] = hold['first_sell_qty']
out['sell_price_2'] = hold['second_sell_price']
out['sell_qty_2'] = hold['second_sell_qty']
out['buy_price_1'] = hold['add_buy_price']
out['buy_qty_1'] = hold['add_buy_qty']
out['hard_stop_price'] = hold['hard_stop_price']
out['execution_signal'] = hold['execution_signal']
out['execution_reason'] = hold['execution_reason']
out['pnl_amount'] = hold['pnl_amount']
out['pnl_rate_pct'] = hold['pnl_rate']

def clean_num(x):
    if pd.isna(x):
        return None
    text = str(x).replace(',', '').replace('원', '').replace('%', '').strip()
    if text in ['', '-', 'nan', 'NaN']:
        return None
    try:
        return float(text)
    except Exception:
        return None

def pnl_status(x):
    value = clean_num(x)
    if value is None:
        return 'NO_POSITION'
    if value < 0:
        return 'LOSS'
    if value > 0:
        return 'PROFIT'
    return 'NO_POSITION'

out['pnl_status'] = out['pnl_amount'].apply(pnl_status)
out['pnl_font_color'] = out['pnl_status'].map({
    'PROFIT': '#DC2626',
    'LOSS': '#2563EB',
    'NO_POSITION': '#6B7280'
}).fillna('#6B7280')

final = pd.concat([out, watch, cash], ignore_index=True)

prev_map = prev.set_index('stock_code')['prev_close'].to_dict()

def get_prev_close(code):
    value = prev_map.get(str(code), None)
    return clean_num(value)

def get_current(row):
    return clean_num(row.get('prev_close_or_current'))

final['prev_close'] = final['stock_code'].apply(get_prev_close)

def direction(row):
    current = get_current(row)
    prev_close = clean_num(row.get('prev_close'))
    if current is None or prev_close is None:
        return 'NEEDS_PREV_CLOSE'
    if current > prev_close:
        return 'UP'
    if current < prev_close:
        return 'DOWN'
    return 'FLAT'

def direction_basis(row):
    current = get_current(row)
    prev_close = clean_num(row.get('prev_close'))
    if current is None or prev_close is None:
        return 'prev_close_missing'
    return f"current={current}, prev_close={prev_close}"

final['price_change_direction'] = final.apply(direction, axis=1)
final['price_direction_basis'] = final.apply(direction_basis, axis=1)
final['price_direction_font_color'] = final['price_change_direction'].map({
    'UP': '#DC2626',
    'DOWN': '#2563EB',
    'FLAT': '#6B7280',
    'NEEDS_PREV_CLOSE': '#6B7280'
}).fillna('#6B7280')

for c in cols:
    if c not in final.columns:
        final[c] = None

extra_cols = ['prev_close']
final_cols = cols + [c for c in extra_cols if c not in cols]

final = final[final_cols]
final.to_csv(OUT, index=False, encoding='utf-8-sig')

print("DONE:", OUT)
print("rows:", len(final))
print("cols:", len(final.columns))
print(final[['stock_code','corp_name_kr','prev_close_or_current','prev_close','price_change_direction','price_direction_basis']].to_string(index=False))