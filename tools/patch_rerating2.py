"""patch_rerating2.py — numeric 컬럼 타입 변환 패치"""
import os

target = os.path.join(os.path.dirname(__file__), "sfd_rerating_watch.py")
content = open(target, encoding="utf-8").read()

# 패치: base DataFrame 생성 직후 숫자 컬럼 강제 변환 삽입
old = '    if price_df is not None:'
new = '''    # ── 숫자 컬럼 타입 강제 변환 (str → float, 오류는 NaN)
    numeric_cols = ["total_score", "news_score", "vol_ratio", "rsi",
                    "ma_align", "investor_score", "tech_score"]
    for col in numeric_cols:
        if col in base.columns:
            base[col] = pd.to_numeric(base[col], errors="coerce")

    if price_df is not None:'''

if old in content and "숫자 컬럼 타입 강제 변환" not in content:
    content = content.replace(old, new)
    open(target, "w", encoding="utf-8").write(content)
    print("[OK] patch2 DONE — numeric column type conversion")
else:
    print("[SKIP] already patched or target not found")
