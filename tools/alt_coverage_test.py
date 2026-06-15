# alt_coverage_test.py — pykrx / FinanceDataReader 대안 테스트
# Layer 2.6 데이터소스 검증용

from datetime import date, timedelta

today = date.today().strftime("%Y%m%d")
yesterday = (date.today() - timedelta(days=3)).strftime("%Y%m%d")  # 주말 대비 3일 전

samples = ["005930", "000660", "035720", "051910", "068270"]
names   = ["Samsung", "SKHynix", "Kakao", "LGChem", "Celltrion"]

print("=" * 50)
print("[TEST 1] pykrx - get_market_fundamental")
print("=" * 50)
try:
    from pykrx import stock
    for ticker, nm in zip(samples, names):
        try:
            df = stock.get_market_fundamental(yesterday, ticker)
            if df is not None and not df.empty:
                row = df.iloc[0]
                print(f"  OK {ticker} {nm} | PER={row.get('PER')} PBR={row.get('PBR')} EPS={row.get('EPS')}")
            else:
                print(f"  EMPTY {ticker} {nm}")
        except Exception as e:
            print(f"  ERROR {ticker} {nm}: {e}")
except ImportError:
    print("  pykrx not installed -> pip install pykrx")

print()
print("=" * 50)
print("[TEST 2] FinanceDataReader")
print("=" * 50)
try:
    import FinanceDataReader as fdr
    for ticker, nm in zip(samples, names):
        try:
            df = fdr.DataReader(ticker, yesterday, today)
            print(f"  OK {ticker} {nm} | rows={len(df)} last_close={df['Close'].iloc[-1] if not df.empty else 'N/A'}")
        except Exception as e:
            print(f"  ERROR {ticker} {nm}: {e}")
except ImportError:
    print("  FinanceDataReader not installed -> pip install finance-datareader")

print()
print("Done.")
