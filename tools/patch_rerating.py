"""patch_rerating.py — sfd_rerating_watch.py ticker 타입 패치"""
import re, os

target = os.path.join(os.path.dirname(__file__), "sfd_rerating_watch.py")
content = open(target, encoding="utf-8").read()

old = 'news_aux = news_df[["ticker", "article_count", "top_tags"]].copy()'
new = ('news_aux = news_df[["ticker", "article_count", "top_tags"]].copy()\n'
       '        news_aux["ticker"] = news_aux["ticker"].astype(str).str.zfill(6)')

if old in content:
    content = content.replace(old, new)
    open(target, "w", encoding="utf-8").write(content)
    print("[OK] patch DONE — ticker type unified")
else:
    print("[SKIP] already patched or target not found")
