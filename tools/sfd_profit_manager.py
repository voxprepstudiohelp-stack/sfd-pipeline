# -*- coding: utf-8 -*-
# sfd_profit_manager.py | v1.1 | Claude (Anthropic) 2026-06-15
# Deploy to: sfd-pipeline/tools/sfd_profit_manager.py
#
# [v1.0 -> v1.1 changes]
# - [NOTIFIER] sfd_notifier.py 이메일 연동
#   -> PARTIAL_SELL / TRAIL_STOP_CRITICAL 이벤트 → 이메일 발송
#   -> notifier import 실패 시 graceful skip (파이프라인 비중단)
# 저장 위치: Drive 04_AI_Handover