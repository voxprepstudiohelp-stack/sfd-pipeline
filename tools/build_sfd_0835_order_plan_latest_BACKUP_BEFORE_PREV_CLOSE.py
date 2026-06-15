import pandas as pd
from pathlib import Path

BASE = Path(r'D:\AI_WorkSpace\I_SFC\09_Implementation\SFC_DataPipeline')

HOLD = BASE / 'outputs/latest/sfd_account_execution_latest.csv'
WATCH = BASE / 'inputs/sfd_0835_watchlist_input.csv'
CASH = BASE / 'inputs/sfd_cash_status_input.csv'
OUT = BASE / 'outputs/sfd_0835_order_plan_latest.csv'

hold = pd.read_csv(HOLD, encoding='utf-8-sig', dtype={'stock_code': str})
watch = pd.read_csv(WATCH, encoding='utf-8-sig', dtype={'stock_code': str})
cash = pd.read_csv(CASH, encoding='utf-8-sig', dtype={'stock_code': str})

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

def pnl_status(x):
    x = str(x)
    if '-' in x:
        return 'LOSS'
    if any(c.isdigit() for c in x):
        return 'PROFIT'
    return 'NO_POSITION'

out['pnl_status'] = out['pnl_amount'].apply(pnl_status)

out['price_change_direction'] = 'NEEDS_PREV_CLOSE'

final = pd.concat([out, watch, cash], ignore_index=True)

for c in cols:
    if c not in final.columns:
        final[c] = None

final = final[cols]

final.to_csv(OUT, index=False, encoding='utf-8-sig')

print("DONE:", OUT)
print("rows:", len(final))