# -*- coding: utf-8 -*-
# sfd_signal_aggregator.py | v4.0 | Claude (Anthropic) 2026-06-15
# Deploy to: sfd-pipeline/tools/sfd_signal_aggregator.py
#
# [v3.9 -> v4.0 changes]
# - [L2.9-TF] trend_filter 연동: sfd_trend_filter_latest.csv 후처리 필터
#   -> FAIL 종목: signal을 TREND_FAIL로 다운그레이드 (DROP 아님 — 기록 보존)
#   -> trend_filter CSV 없으면 graceful skip (파이프라인 비중단)
#   -> 출력 컬럼 추가: trend_filter_pass (True/False/None), trend_filter_reason
# 저장 위치: Drive 04_AI_Handover