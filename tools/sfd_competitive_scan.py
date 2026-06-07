#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfd_competitive_scan.py -- Competitive Intelligence Scanner v1.0

기능:
  1. SCAN_TARGETS: 국내/해외/오픈소스 14개 경쟁 플랫폼 정의
  2. CURRENT_SFD: 현재 SFD 스펙과의 기능 비교
  3. 강점/약점 테이블 + New BM candidates 자동 추출
  4. 출력: outputs/latest/sfd_competitive_scan_latest.json
  5. --report 터미널 리포트 / --mock 네트워크 없이 정적 데이터

Usage:
  py tools/sfd_competitive_scan.py
  py tools/sfd_competitive_scan.py --report
  py tools/sfd_competitive_scan.py --mock --report

Version: v1.0
Author:  Claude Sonnet 4.6 (2026-06-07)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── 경로 설정 ─────────────────────────────────────────────────────────────
_HERE   = Path(__file__).resolve().parent
_BASE   = Path(os.environ.get("SFD_BASE_DIR", str(_HERE.parent)))
_LATEST = _BASE / "outputs" / "latest"
OUTPUT_JSON = _LATEST / "sfd_competitive_scan_latest.json"

# ═══════════════════════════════════════════════════════════════════════════
# SFD 현재 스펙
# ═══════════════════════════════════════════════════════════════════════════
CURRENT_SFD = {
    "version": "V10.4",
    "score_components": [
        "tech(93pt)", "news", "investor_flow", "fund(PER/PBR/EPS)",
        "theme", "macro", "sector(BM-6)", "dart(BM-7)",
        "hoga(BM-8)", "us_boost(BM-9)",
    ],
    "signal_tiers": {
        "RESERVE_BUY": "total_score >= 90",
        "WATCH_ONLY":  "total_score >= 70",
        "HOLD":        "below 70",
        "NO_TRADE":    "BM-5 override",
        "SIGNAL_EXPIRED": "BM-13 5-bar timeout",
    },
    "backtest":   "D+1 feedback loop (archive pairing)",
    "coverage":   "483 tickers (KIS API, KOSPI/KOSDAQ)",
    "layers":     "Layer -2 ~ 5.5 (13+ layers)",
    "automation": "GitHub Actions daily 08:35 KST",
    "output":     "Google Drive (OAuth2 refresh token)",
    # 기능 태그 집합 -- 비교 기준
    "feature_tags": {
        "daily_automation",        # 매일 자동 실행
        "multi_layer_pipeline",    # 다층 레이어 파이프라인
        "technical_score",         # 기술적 분석
        "fundamental_score",       # 펀더멘털 (PER/PBR/EPS)
        "news_score",              # 뉴스 감성
        "investor_flow",           # 기관/외국인 수급
        "sector_score",            # 섹터 분석
        "macro_indicators",        # 매크로 지표
        "dart_events",             # 공시 이벤트
        "hoga_analysis",           # 호가창 분석
        "us_market_link",          # 미국 시장 연동
        "d1_backtest",             # D+1 백테스트
        "signal_expiry",           # 신호 만료 (BM-13)
        "portfolio_monitor",       # 포트폴리오 모니터링
        "threshold_optimizer",     # 임계값 자동 최적화
        "ci_cd_pipeline",          # CI/CD 자동화
        "cloud_output",            # 클라우드 저장
        "korean_market_focus",     # 한국 시장 특화
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# 경쟁 플랫폼 정의
# ═══════════════════════════════════════════════════════════════════════════
# feature_tags: 해당 플랫폼이 보유한 기능
# unique_features: SFD에 없는 차별화 기능 (→ BM candidates 원천)
# gaps_vs_sfd: SFD 대비 없는 기능
SCAN_TARGETS = [
    # ── 국내 ────────────────────────────────────────────────────────────
    {
        "name":     "키움 영웅문AI",
        "category": "domestic",
        "url":      "https://www.kiwoom.com",
        "signal_approach": "ML + 조건검색식 하이브리드, 실시간",
        "coverage":        "전 코스피/코스닥 (~2,500종목)",
        "automation":      "HTS 연동 실시간",
        "backtest":        "조건검색 백테스트 (HTS 내 제한적)",
        "feature_tags": {
            "technical_score", "news_score", "daily_automation",
            "korean_market_focus",
        },
        "unique_features": [
            {"tag": "realtime_signal",     "desc": "실시간 시그널 (장중 연속 업데이트)"},
            {"tag": "hts_order_link",      "desc": "HTS 직결 주문 자동화"},
            {"tag": "condition_search_ui", "desc": "조건검색식 GUI 빌더"},
            {"tag": "candlestick_pattern", "desc": "AI 캔들 패턴 인식"},
        ],
        "gaps_vs_sfd": [
            "fundamental_score", "investor_flow", "dart_events",
            "hoga_analysis", "us_market_link", "d1_backtest",
            "signal_expiry", "threshold_optimizer", "ci_cd_pipeline",
        ],
        "notes": "HTS 생태계 최강. 실시간/주문 연동이 SFD 대비 핵심 차별점.",
    },
    {
        "name":     "신한 알파",
        "category": "domestic",
        "url":      "https://www.shinhansec.com",
        "signal_approach": "AI 포트폴리오 추천, 로보어드바이저",
        "coverage":        "코스피/코스닥 + 해외 일부",
        "automation":      "MTS 푸시 알림",
        "backtest":        "포트폴리오 레벨 시뮬레이션",
        "feature_tags": {
            "technical_score", "fundamental_score", "korean_market_focus",
            "portfolio_monitor",
        },
        "unique_features": [
            {"tag": "portfolio_optimization", "desc": "AI 포트폴리오 최적화 (비중 자동 계산)"},
            {"tag": "rebalancing_alert",      "desc": "리밸런싱 알림 자동화"},
            {"tag": "risk_score",             "desc": "종목별 리스크 스코어 (VaR 기반)"},
        ],
        "gaps_vs_sfd": [
            "investor_flow", "dart_events", "hoga_analysis",
            "us_market_link", "d1_backtest", "signal_expiry",
            "threshold_optimizer", "ci_cd_pipeline",
        ],
        "notes": "포트폴리오 최적화 기능이 SFD 대비 강점. 개별 종목 스코어 정밀도는 낮음.",
    },
    {
        "name":     "미래에셋 TIGER AI",
        "category": "domestic",
        "url":      "https://securities.miraeasset.com",
        "signal_approach": "AI ETF 추천 + 자산배분",
        "coverage":        "ETF 특화, 글로벌 자산군",
        "automation":      "앱 알림",
        "backtest":        "ETF 과거 수익률 비교",
        "feature_tags": {
            "macro_indicators", "sector_score", "korean_market_focus",
            "cloud_output",
        },
        "unique_features": [
            {"tag": "etf_analysis",      "desc": "ETF 성과 분석 및 추천"},
            {"tag": "asset_allocation",  "desc": "AI 자산배분 (주식/채권/현금 비중)"},
            {"tag": "global_coverage",   "desc": "미국/중국/유럽 ETF 커버리지"},
        ],
        "gaps_vs_sfd": [
            "technical_score", "fundamental_score", "investor_flow",
            "dart_events", "hoga_analysis", "d1_backtest",
            "signal_expiry", "threshold_optimizer", "ci_cd_pipeline",
        ],
        "notes": "ETF/자산배분 특화. 개별 종목 시그널과는 다른 방향.",
    },
    {
        "name":     "한투 AI",
        "category": "domestic",
        "url":      "https://www.truefriend.com",
        "signal_approach": "AI 목표주가 + 스크리닝",
        "coverage":        "코스피/코스닥 전체",
        "automation":      "앱 알림, WTS",
        "backtest":        "제한적 (기간별 수익률)",
        "feature_tags": {
            "technical_score", "fundamental_score", "news_score",
            "korean_market_focus", "sector_score",
        },
        "unique_features": [
            {"tag": "ai_target_price",  "desc": "AI 목표가 자동 산출 (12개월)"},
            {"tag": "analyst_consensus","desc": "애널리스트 컨센서스 통합"},
            {"tag": "earnings_calendar","desc": "실적 발표 캘린더 + 서프라이즈 감지"},
        ],
        "gaps_vs_sfd": [
            "investor_flow", "dart_events", "hoga_analysis",
            "us_market_link", "d1_backtest", "signal_expiry",
            "threshold_optimizer", "ci_cd_pipeline",
        ],
        "notes": "AI 목표가 자동 산출이 독보적. 실적 서프라이즈 감지는 SFD의 DART와 상보적.",
    },
    # ── 해외 ────────────────────────────────────────────────────────────
    {
        "name":     "Alpaca",
        "category": "global",
        "url":      "https://alpaca.markets",
        "signal_approach": "브로커 API + 알고 트레이딩 프레임워크",
        "coverage":        "미국 주식/ETF, 암호화폐",
        "automation":      "API 기반 완전 자동화, paper trading",
        "backtest":        "Alpaca Data API + 사용자 정의 로직",
        "feature_tags": {
            "technical_score", "daily_automation", "ci_cd_pipeline",
            "portfolio_monitor", "cloud_output",
        },
        "unique_features": [
            {"tag": "paper_trading",    "desc": "Paper trading (모의투자 API 완전 통합)"},
            {"tag": "fractional_shares","desc": "소수점 매수"},
            {"tag": "live_execution",   "desc": "실시간 주문 실행 API"},
            {"tag": "webhook_trigger",  "desc": "Webhook 기반 외부 시그널 실행"},
        ],
        "gaps_vs_sfd": [
            "fundamental_score", "news_score", "investor_flow",
            "dart_events", "hoga_analysis", "korean_market_focus",
            "signal_expiry",
        ],
        "notes": "주문 실행 API가 핵심. SFD는 시그널 생성에 집중 -- 실행 레이어로 Alpaca 연동 검토 가능.",
    },
    {
        "name":     "Composer",
        "category": "global",
        "url":      "https://www.composer.trade",
        "signal_approach": "No-code 전략 빌더 + 자동 리밸런싱",
        "coverage":        "미국 ETF/주식",
        "automation":      "조건부 자동 리밸런싱",
        "backtest":        "클릭 기반 백테스트 (사용자 전략)",
        "feature_tags": {
            "daily_automation", "portfolio_monitor", "threshold_optimizer",
        },
        "unique_features": [
            {"tag": "nocode_strategy_builder", "desc": "No-code 시그널 전략 빌더 (if-then 로직)"},
            {"tag": "auto_rebalancing",        "desc": "조건부 자동 리밸런싱 실행"},
            {"tag": "strategy_marketplace",    "desc": "전략 공유 마켓플레이스"},
        ],
        "gaps_vs_sfd": [
            "fundamental_score", "news_score", "investor_flow",
            "dart_events", "hoga_analysis", "korean_market_focus",
            "macro_indicators", "sector_score",
        ],
        "notes": "No-code 전략 빌더 UX가 강점. SFD는 코드 기반이나 정밀도가 훨씬 높음.",
    },
    {
        "name":     "Tickeron",
        "category": "global",
        "url":      "https://tickeron.com",
        "signal_approach": "AI 패턴 인식 + 확률적 예측",
        "coverage":        "미국 주식/ETF/암호화폐",
        "automation":      "AI 트레이딩 봇",
        "backtest":        "패턴별 과거 성공률 통계",
        "feature_tags": {
            "technical_score", "daily_automation", "d1_backtest",
            "portfolio_monitor",
        },
        "unique_features": [
            {"tag": "ai_pattern_recognition", "desc": "AI 캔들/차트 패턴 자동 인식 + 예측확률"},
            {"tag": "confidence_score",        "desc": "시그널 신뢰도 % 표시"},
            {"tag": "pattern_backtest",        "desc": "패턴별 과거 성공률 통계"},
            {"tag": "ai_trading_bot",          "desc": "AI 자동 매매 봇 (backtested strategy)"},
        ],
        "gaps_vs_sfd": [
            "fundamental_score", "investor_flow", "dart_events",
            "hoga_analysis", "korean_market_focus", "macro_indicators",
            "signal_expiry",
        ],
        "notes": "패턴 인식 + 확률 표시가 SFD의 기준봉(BM-F) 로직과 유사하나 ML 기반.",
    },
    {
        "name":     "Trade Ideas",
        "category": "global",
        "url":      "https://www.trade-ideas.com",
        "signal_approach": "실시간 AI 스캐너 + Holly AI 봇",
        "coverage":        "미국 전체 상장 종목 (실시간)",
        "automation":      "실시간 Holly AI 자율 매매",
        "backtest":        "Odds Maker (조건별 과거 통계)",
        "feature_tags": {
            "technical_score", "daily_automation", "d1_backtest",
            "news_score",
        },
        "unique_features": [
            {"tag": "realtime_scanner",   "desc": "실시간 AI 스캐너 (초 단위 업데이트)"},
            {"tag": "holly_ai_bot",       "desc": "Holly AI 자율 매매 봇"},
            {"tag": "odds_maker",         "desc": "Odds Maker: 조건별 과거 확률 통계"},
            {"tag": "multi_strategy",     "desc": "다중 전략 동시 스캔"},
        ],
        "gaps_vs_sfd": [
            "fundamental_score", "investor_flow", "dart_events",
            "hoga_analysis", "korean_market_focus", "macro_indicators",
            "sector_score", "signal_expiry",
        ],
        "notes": "실시간 스캐닝이 SFD의 가장 큰 차이. Holly AI 봇 개념은 SFD 자동화와 유사한 방향.",
    },
    {
        "name":     "Kavout",
        "category": "global",
        "url":      "https://www.kavout.com",
        "signal_approach": "ML 기반 K Score (0-9) 정량 스코어",
        "coverage":        "미국 주식 (~5,000종목)",
        "automation":      "일 1회 스코어 업데이트",
        "backtest":        "K Score 과거 수익률 검증 제공",
        "feature_tags": {
            "technical_score", "fundamental_score", "daily_automation",
            "d1_backtest", "sector_score",
        },
        "unique_features": [
            {"tag": "ml_composite_score", "desc": "ML 앙상블 단일 합성 스코어 (K Score 0-9)"},
            {"tag": "factor_analysis",    "desc": "150+ 팩터 자동 분석"},
            {"tag": "alpha_decay_monitor","desc": "알파 감쇠 모니터 (시그널 유효기간 추적)"},
        ],
        "gaps_vs_sfd": [
            "news_score", "investor_flow", "dart_events",
            "hoga_analysis", "korean_market_focus", "macro_indicators",
            "signal_expiry", "ci_cd_pipeline",
        ],
        "notes": "K Score 아키텍처가 SFD total_score와 가장 유사. ML 앙상블 vs 규칙 기반의 차이.",
    },
    # ── 오픈소스 ────────────────────────────────────────────────────────
    {
        "name":     "FinRL",
        "category": "opensource",
        "url":      "https://github.com/AI4Finance-Foundation/FinRL",
        "signal_approach": "딥 강화학습 (DRL) 트레이딩 에이전트",
        "coverage":        "미국/중국 주식, 암호화폐, 다중 자산",
        "automation":      "DRL 에이전트 자율 실행",
        "backtest":        "gym 환경 기반 시뮬레이션",
        "feature_tags": {
            "technical_score", "daily_automation", "d1_backtest",
            "portfolio_monitor", "macro_indicators",
        },
        "unique_features": [
            {"tag": "deep_rl_agent",      "desc": "Deep RL 에이전트 (PPO/A2C/DDPG 등)"},
            {"tag": "custom_gym_env",     "desc": "커스텀 gym 환경으로 전략 학습"},
            {"tag": "multi_asset_rl",     "desc": "다중 자산 동시 포트폴리오 최적화 RL"},
        ],
        "gaps_vs_sfd": [
            "fundamental_score", "news_score", "investor_flow",
            "dart_events", "hoga_analysis", "korean_market_focus",
            "signal_expiry", "cloud_output",
        ],
        "notes": "RL 기반 임계값/전략 최적화 아이디어 참고 가능. sfd_threshold_optimizer와 결합 검토.",
    },
    {
        "name":     "OpenBB",
        "category": "opensource",
        "url":      "https://openbb.co",
        "signal_approach": "데이터 터미널 + 분석 프레임워크 (블룸버그 대체)",
        "coverage":        "글로벌 (주식/채권/암호화폐/매크로)",
        "automation":      "라우팅 API, 커스텀 스크린 가능",
        "backtest":        "플러그인 방식",
        "feature_tags": {
            "technical_score", "fundamental_score", "macro_indicators",
            "news_score", "sector_score", "cloud_output",
        },
        "unique_features": [
            {"tag": "data_aggregation_hub", "desc": "20+ 데이터 소스 통합 허브"},
            {"tag": "options_data",         "desc": "옵션 체인/그릭 데이터 통합"},
            {"tag": "dark_pool_data",       "desc": "다크풀/기관 블록 거래 데이터"},
            {"tag": "earnings_surprise",    "desc": "실적 서프라이즈 점수 (EPS 예상 대비)"},
        ],
        "gaps_vs_sfd": [
            "investor_flow", "dart_events", "hoga_analysis",
            "korean_market_focus", "signal_expiry", "ci_cd_pipeline",
            "d1_backtest",
        ],
        "notes": "데이터 레이어 강화에 참고. 옵션/다크풀/EPS서프라이즈는 SFD 확장 후보.",
    },
    {
        "name":     "Qlib",
        "category": "opensource",
        "url":      "https://github.com/microsoft/qlib",
        "signal_approach": "Microsoft 퀀트 프레임워크 -- 알파 마이닝, 팩터 분석",
        "coverage":        "중국/미국 주식 (A-share 특화)",
        "automation":      "파이프라인 자동화 지원",
        "backtest":        "이벤트 기반 백테스트 엔진 내장",
        "feature_tags": {
            "technical_score", "fundamental_score", "daily_automation",
            "d1_backtest", "sector_score", "ci_cd_pipeline",
        },
        "unique_features": [
            {"tag": "alpha_mining",        "desc": "자동 알파 팩터 마이닝 (Genetic Programming)"},
            {"tag": "factor_library",      "desc": "내장 팩터 라이브러리 (300+ 팩터)"},
            {"tag": "online_learning",     "desc": "온라인 학습 (신규 데이터 연속 학습)"},
            {"tag": "ensemble_models",     "desc": "LightGBM/LSTM/TFT 앙상블"},
        ],
        "gaps_vs_sfd": [
            "news_score", "investor_flow", "dart_events",
            "hoga_analysis", "korean_market_focus", "signal_expiry",
            "cloud_output",
        ],
        "notes": "팩터 마이닝 자동화는 SFD BM 발굴 로직에 직접 참고 가능. 중국 시장 특화라 KR 적용은 추가 작업 필요.",
    },
    {
        "name":     "QuantConnect",
        "category": "opensource",
        "url":      "https://www.quantconnect.com",
        "signal_approach": "클라우드 백테스트 + 라이브 트레이딩 엔진 (LEAN)",
        "coverage":        "글로벌 (주식/옵션/선물/FX/암호화폐)",
        "automation":      "완전 자동화, 클라우드 실행",
        "backtest":        "틱 단위 정밀 백테스트 (20년+)",
        "feature_tags": {
            "technical_score", "fundamental_score", "daily_automation",
            "d1_backtest", "macro_indicators", "portfolio_monitor",
            "ci_cd_pipeline", "cloud_output", "threshold_optimizer",
        },
        "unique_features": [
            {"tag": "tick_backtest",      "desc": "틱 단위 정밀 백테스트 (슬리피지/수수료 정밀 반영)"},
            {"tag": "options_strategy",   "desc": "옵션 전략 백테스트/실행"},
            {"tag": "research_notebook",  "desc": "클라우드 Research Notebook 통합"},
            {"tag": "multi_asset_live",   "desc": "다중 자산 라이브 트레이딩 동시 실행"},
        ],
        "gaps_vs_sfd": [
            "news_score", "investor_flow", "dart_events",
            "hoga_analysis", "korean_market_focus", "signal_expiry",
        ],
        "notes": "백테스트 정밀도가 SFD의 D+1 방식 대비 월등. 장기적으로 LEAN 엔진 연동 검토 가능.",
    },
    {
        "name":     "zipline-reloaded",
        "category": "opensource",
        "url":      "https://github.com/stefan-jansen/zipline-reloaded",
        "signal_approach": "이벤트 기반 백테스트 (Quantopian 후계)",
        "coverage":        "미국 주식 (커스텀 번들로 확장 가능)",
        "automation":      "스케줄러 내장",
        "backtest":        "이벤트 기반, 파이프라인 API",
        "feature_tags": {
            "technical_score", "fundamental_score", "daily_automation",
            "d1_backtest", "ci_cd_pipeline",
        },
        "unique_features": [
            {"tag": "pipeline_api",         "desc": "Pipeline API: 팩터 기반 스크리닝 파이프라인"},
            {"tag": "event_driven_bt",      "desc": "이벤트 기반 백테스트 (look-ahead bias 방지)"},
            {"tag": "custom_data_bundle",   "desc": "커스텀 데이터 번들 (KR 데이터 연동 가능)"},
        ],
        "gaps_vs_sfd": [
            "news_score", "investor_flow", "dart_events",
            "hoga_analysis", "korean_market_focus", "signal_expiry",
            "cloud_output", "macro_indicators",
        ],
        "notes": "KR 커스텀 번들 구성 시 SFD 신호를 zipline 팩터로 변환해 정밀 백테스트 가능.",
    },
]

# ═══════════════════════════════════════════════════════════════════════════
# New BM Candidates 정의 (경쟁사 unique_features 분석 기반)
# BM-1 ~ BM-13: 기존 구현 완료
# BM-14+: 신규 후보
# ═══════════════════════════════════════════════════════════════════════════
BM_CANDIDATES = [
    {
        "bm_id":    "BM-14",
        "tag":      "ai_pattern_recognition",
        "feature":  "AI 캔들 패턴 인식 스코어",
        "source":   "Tickeron, 키움 영웅문AI",
        "priority": "HIGH",
        "rationale": ("sfd_technical_analyzer.py의 기준봉(F)/눌림목(G) 로직을 ML 패턴 인식으로 "
                      "보강. 200개+ 패턴 자동 감지 후 과거 성공률 기반 스코어 산출."),
    },
    {
        "bm_id":    "BM-15",
        "tag":      "ai_target_price",
        "feature":  "AI 목표주가 자동 산출",
        "source":   "한투 AI",
        "priority": "MED",
        "rationale": ("PER/PBR/EPS 데이터(sfd_fundamental_watch) + 기술적 저항선(sfd_technical) "
                      "조합으로 단기(1-2주) 목표주가 자동 계산. RESERVE_BUY 시그널에 목표가 제공."),
    },
    {
        "bm_id":    "BM-16",
        "tag":      "earnings_surprise",
        "feature":  "실적 서프라이즈 감지 스코어",
        "source":   "한투 AI, OpenBB",
        "priority": "HIGH",
        "rationale": ("DART EPS 발표 vs 컨센서스 비교. 서프라이즈 +15% 이상 시 펀더멘털 "
                      "부스트 +5pt. sfd_event_calendar_builder + sfd_fundamental_watch 연동."),
    },
    {
        "bm_id":    "BM-17",
        "tag":      "options_data",
        "feature":  "옵션 시장 시그널 통합",
        "source":   "OpenBB, QuantConnect",
        "priority": "LOW",
        "rationale": ("KOSPI200 옵션 P/C ratio, 내재변동성(IV) 급등 → 변동성 경고. "
                      "VIX 역할을 KR 로컬 옵션 데이터로 대체 가능. KRX 옵션 API 필요."),
    },
    {
        "bm_id":    "BM-18",
        "tag":      "alpha_decay_monitor",
        "feature":  "알파 감쇠 모니터 (시그널 신선도 추적)",
        "source":   "Kavout",
        "priority": "MED",
        "rationale": ("RESERVE_BUY 발령 후 N일 경과 시 스코어 감쇠 곡선 적용. BM-13의 "
                      "5-bar timeout을 감쇠 함수로 대체 검토. sfd_signal_quality.py 확장."),
    },
    {
        "bm_id":    "BM-19",
        "tag":      "dark_pool_data",
        "feature":  "기관 블록거래/다크풀 감지",
        "source":   "OpenBB",
        "priority": "LOW",
        "rationale": ("KRX 대량매매 시스템(블록딜) 공시 분석. 기존 investor_flow(BM-2.6c)와 "
                      "결합 시 대형 기관 포지셔닝 조기 감지 가능."),
    },
    {
        "bm_id":    "BM-20",
        "tag":      "portfolio_optimization",
        "feature":  "AI 포트폴리오 비중 최적화",
        "source":   "신한 알파, FinRL",
        "priority": "MED",
        "rationale": ("RESERVE_BUY 복수 종목 시 Mean-Variance 또는 RL 기반 비중 배분. "
                      "sfd_portfolio_monitor.py 확장. Grade A/B/C 체계와 통합."),
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# 비교 / 분석 로직
# ═══════════════════════════════════════════════════════════════════════════

def _check_url(url: str, timeout: int = 5) -> str:
    """HTTP HEAD 요청으로 URL 활성 상태 확인. 'active'/'inactive'/'unknown'"""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "SFD-Scanner/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "active" if resp.status < 400 else "inactive"
    except Exception:
        return "unknown"


def compare_target(target: dict, sfd_tags: set) -> dict:
    """경쟁사 vs SFD 비교 결과 생성."""
    t_tags = target.get("feature_tags", set())

    shared     = sorted(t_tags & sfd_tags)           # 공통 보유 기능
    sfd_ahead  = sorted(sfd_tags - t_tags)            # SFD만 보유 (SFD 강점)
    comp_ahead = sorted(t_tags - sfd_tags)            # 경쟁사만 보유 (SFD 약점)

    return {
        "name":           target["name"],
        "category":       target["category"],
        "url":            target["url"],
        "signal_approach": target["signal_approach"],
        "shared_features":      shared,
        "sfd_advantages":       sfd_ahead,
        "competitor_advantages": comp_ahead,
        "unique_features":      target.get("unique_features", []),
        "gaps_vs_sfd":          target.get("gaps_vs_sfd", []),
        "notes":                target.get("notes", ""),
    }


def generate_report(mock: bool = False) -> dict:
    sfd_tags = CURRENT_SFD["feature_tags"]
    comparisons   = []
    url_statuses  = {}

    for target in SCAN_TARGETS:
        comp = compare_target(target, sfd_tags)

        if not mock:
            status = _check_url(target["url"])
            url_statuses[target["name"]] = status
            comp["url_status"] = status
        else:
            comp["url_status"] = "mock"

        comparisons.append(comp)

    # BM candidates: unique_features에서 SFD 미보유 항목 추출
    # (사전 정의된 BM_CANDIDATES 전체 포함)
    seen_tags = set()
    auto_candidates = []
    for target in SCAN_TARGETS:
        for uf in target.get("unique_features", []):
            tag = uf["tag"]
            if tag not in seen_tags:
                # BM_CANDIDATES에 이미 있는지 확인
                in_bm = any(b["tag"] == tag for b in BM_CANDIDATES)
                if not in_bm:
                    auto_candidates.append({
                        "bm_id":    "BM-?",
                        "tag":      tag,
                        "feature":  uf["desc"],
                        "source":   target["name"],
                        "priority": "MED",
                        "rationale": f"자동 추출: {target['name']}의 unique feature",
                    })
                seen_tags.add(tag)

    all_candidates = BM_CANDIDATES + auto_candidates

    # SFD 전체 강점 요약
    sfd_advantages_summary = sorted(sfd_tags - set().union(
        *[t.get("feature_tags", set()) for t in SCAN_TARGETS]
    ))

    # 카테고리별 통계
    cats = {"domestic": 0, "global": 0, "opensource": 0}
    for t in SCAN_TARGETS:
        cats[t["category"]] = cats.get(t["category"], 0) + 1

    return {
        "generated_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mock_mode":       mock,
        "sfd_version":     CURRENT_SFD["version"],
        "scan_summary": {
            "total_targets":   len(SCAN_TARGETS),
            "by_category":     cats,
            "bm_candidates":   len(all_candidates),
        },
        "current_sfd":     {k: v for k, v in CURRENT_SFD.items()
                            if k != "feature_tags"},
        "comparisons":     comparisons,
        "new_bm_candidates": all_candidates,
        "sfd_exclusive_features": sfd_advantages_summary,
        "url_statuses":    url_statuses,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 터미널 리포트
# ═══════════════════════════════════════════════════════════════════════════

def print_report(result: dict) -> None:
    comparisons = result["comparisons"]
    candidates  = result["new_bm_candidates"]
    summ        = result["scan_summary"]

    print()
    print("=" * 72)
    print("  SFD COMPETITIVE INTELLIGENCE REPORT v1.0")
    print(f"  생성: {result['generated_at']}  |  SFD {result['sfd_version']}"
          f"  |  {'MOCK' if result['mock_mode'] else 'LIVE'}")
    print(f"  대상: {summ['total_targets']}개 플랫폼  "
          f"(국내 {summ['by_category'].get('domestic',0)}  "
          f"해외 {summ['by_category'].get('global',0)}  "
          f"오픈소스 {summ['by_category'].get('opensource',0)})")
    print("=" * 72)

    # 경쟁사 비교 테이블
    for cat_key, cat_label in [("domestic","[ 국내 ]"), ("global","[ 해외 ]"),
                                 ("opensource","[ 오픈소스 ]")]:
        cat_comps = [c for c in comparisons if c["category"] == cat_key]
        if not cat_comps:
            continue
        print(f"\n{cat_label}")
        for c in cat_comps:
            status_str = f"[{c.get('url_status','?')}]" if c.get("url_status") != "mock" else ""
            print(f"  {'─'*66}")
            print(f"  {c['name']:<28} {status_str}")
            print(f"  접근법: {c['signal_approach']}")
            if c["competitor_advantages"]:
                print(f"  경쟁사 강점(SFD 부재): {', '.join(c['competitor_advantages'][:4])}")
            if c["unique_features"]:
                uf_strs = [uf["desc"][:35] for uf in c["unique_features"][:3]]
                print(f"  독보적 기능: {' / '.join(uf_strs)}")
            if c["notes"]:
                print(f"  메모: {c['notes'][:68]}")

    # New BM Candidates
    print(f"\n{'='*72}")
    print(f"  NEW BM CANDIDATES ({len(candidates)}개)")
    print(f"{'='*72}")
    priority_order = {"HIGH": 0, "MED": 1, "LOW": 2}
    sorted_cands = sorted(candidates,
                          key=lambda x: (priority_order.get(x["priority"], 9), x["bm_id"]))
    for bm in sorted_cands:
        pri_mark = {"HIGH": "★★★", "MED": "★★ ", "LOW": "★  "}.get(bm["priority"], "   ")
        print(f"  {bm['bm_id']:<8} {pri_mark}  {bm['feature']}")
        print(f"           출처: {bm['source']}")
        print(f"           {bm['rationale'][:70]}")
        print()

    # SFD 독보적 강점
    excl = result.get("sfd_exclusive_features", [])
    if excl:
        print(f"{'='*72}")
        print(f"  SFD 독보적 기능 (경쟁사 전부 미보유): {', '.join(excl)}")

    print(f"\n{'='*72}")
    print(f"  저장: {OUTPUT_JSON}")
    print(f"{'='*72}\n")


# ═══════════════════════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════════════════════

def run(mock: bool = False, report: bool = False) -> None:
    print(f"[CS] Competitive Scan v1.0 | mock={mock} | report={report}")
    _LATEST.mkdir(parents=True, exist_ok=True)

    result = generate_report(mock=mock)

    OUTPUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[CS] 저장 완료: {OUTPUT_JSON}")
    print(f"[CS] 대상 {result['scan_summary']['total_targets']}개 | "
          f"BM candidates {result['scan_summary']['bm_candidates']}개")

    if report:
        print_report(result)
    else:
        # 간단 요약
        for cat in ("domestic", "global", "opensource"):
            n = result["scan_summary"]["by_category"].get(cat, 0)
            print(f"[CS] {cat:<12} {n}개 플랫폼 스캔 완료")
        high_bms = [b for b in result["new_bm_candidates"] if b["priority"] == "HIGH"]
        print(f"[CS] HIGH priority BM candidates: {len(high_bms)}개 -> {OUTPUT_JSON}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SFD Competitive Intelligence Scanner v1.0")
    parser.add_argument("--mock",   action="store_true", help="네트워크 없이 정적 데이터로 실행")
    parser.add_argument("--report", action="store_true", help="터미널 리포트 출력")
    args = parser.parse_args()
    run(mock=args.mock, report=args.report)
