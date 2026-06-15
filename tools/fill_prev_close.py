import pandas as pd
import datetime as dt
from pykrx import stock

p = 'inputs/sfd_prev_close_input.csv'
df = pd.read_csv(p, encoding='utf-8-sig', dtype={'stock_code': str})

today = dt.datetime.now().strftime('%Y%m%d')
start = (dt.datetime.now() - dt.timedelta(days=14)).strftime('%Y%m%d')

vals = []
dates = []

for code in df['stock_code']:
    try:
        o = stock.get_market_ohlcv_by_date(start, today, code)
        o = o[o.index.strftime('%Y%m%d') < today]

        if len(o) > 0:
            vals.append(int(o['종가'].iloc[-1]))
            dates.append(o.index[-1].strftime('%Y-%m-%d'))
        else:
            vals.append('')
            dates.append('')
    except:
        vals.append('')
        dates.append('ERROR')

df['prev_close'] = vals
df['prev_close_date'] = dates

df.to_csv(p, index=False, encoding='utf-8-sig')

print(df)