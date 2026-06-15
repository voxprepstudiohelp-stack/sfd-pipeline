"""patch_backtest2.py — sfd_backtest_d1 signal_label 호환성 패치"""
import re

path = 'tools/sfd_backtest_d1.py'
c = open(path, encoding='utf-8').read()

MARKER = '# [compat_load_signal]'
if MARKER in c:
    print('[SKIP] already patched')
else:
    old = '    required = {"ticker", "total_score", "signal_label"}'
    new = (
        '    ' + MARKER + '\n'
        "    if 'signal_label' not in df.columns and 'signal' in df.columns:\n"
        "        df['signal_label'] = df['signal']\n"
        '    required = {"ticker", "total_score", "signal_label"}'
    )
    if old not in c:
        print('[ERROR] pattern not found — manual check required')
        print('current column check lines:')
        for i, line in enumerate(c.splitlines(), 1):
            if 'signal_label' in line and 'required' in line:
                print(f'  {i}: {line}')
    else:
        patched = c.replace(old, new, 1)
        open(path, 'w', encoding='utf-8').write(patched)
        print('[OK] load_signal() compatibility patch DONE')
        print('patch content:')
        print(new)
