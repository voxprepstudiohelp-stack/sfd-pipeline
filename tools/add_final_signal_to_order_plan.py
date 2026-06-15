import pandas as pd

p = 'outputs/sfd_0835_order_plan_latest.csv'
df = pd.read_csv(p, encoding='utf-8-sig', dtype={'stock_code': str})

def final_signal(row):
    direction = str(row.get('price_change_direction', '')).strip()
    pnl = str(row.get('pnl_status', '')).strip()
    code = str(row.get('stock_code', '')).strip()

    if code == 'CASH':
        return 'CASH_PROTECT'
    if direction == 'DOWN' and pnl == 'PROFIT':
        return 'PROFIT_PROTECT_SELL'
    if direction == 'DOWN' and pnl == 'LOSS':
        return 'RISK_WATCH_NO_ADD'
    if direction == 'UP' and pnl == 'PROFIT':
        return 'TREND_HOLD_PARTIAL_PROFIT'
    if direction == 'UP' and pnl == 'LOSS':
        return 'RECOVERY_WATCH_SELL'
    if direction == 'FLAT' and pnl == 'PROFIT':
        return 'HOLD_PROFIT_CHECK'
    if direction == 'FLAT' and pnl == 'LOSS':
        return 'HOLD_LOSS_CHECK'
    return 'WATCH_ONLY'

df['final_signal'] = df.apply(final_signal, axis=1)

df['final_signal_font_color'] = df['final_signal'].map({
    'PROFIT_PROTECT_SELL': '#DC2626',
    'TREND_HOLD_PARTIAL_PROFIT': '#DC2626',
    'RECOVERY_WATCH_SELL': '#F59E0B',
    'RISK_WATCH_NO_ADD': '#2563EB',
    'CASH_PROTECT': '#374151',
    'WATCH_ONLY': '#6B7280',
    'HOLD_PROFIT_CHECK': '#6B7280',
    'HOLD_LOSS_CHECK': '#6B7280'
}).fillna('#6B7280')

df.to_csv(p, index=False, encoding='utf-8-sig')

print(df[['stock_code','corp_name_kr','pnl_status','price_change_direction','final_signal','final_signal_font_color']].to_string(index=False))