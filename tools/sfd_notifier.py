"""
sfd_notifier.py v1.2
=====================
목적: SFD 레포트 요약을 이메일 / 카카오톡으로 자동 발송
스케줄: 08:00 (토큰 체크) / 08:10 (장전) / 09:05 (개장) / 15:35 (장마감) / 필요시 수동

발송 내용:
  - 시장 온도 (KOSPI/KOSDAQ/환율)
  - SFD TOP5 신호
  - 계좌 요약 (수익률/추가매수 트리거)
  - 레포트 링크 (Google Drive 공개 URL)

설정 (.env):
  NOTIFY_EMAIL_TO               = your@email.com
  NOTIFY_EMAIL_FROM             = sender@gmail.com
  NOTIFY_EMAIL_PW               = gmail_app_password     # 앱 비밀번호 (2단계인증 필요)
  NOTIFY_KAKAO_TOKEN            = kakao_access_token     # 카카오 나에게 보내기
  KAKAO_REST_API_KEY            = kakao_rest_api_key     # client_credentials 재발급용
  GOOGLE_DRIVE_CREDENTIALS_JSON = /path/to/service_account.json

카카오 토큰 갱신 전략:
  1차) reissue_kakao_token(): client_credentials grant → 새 access_token 발급
  폴백) check_kakao_token(): 토큰 만료 임박/불가 시 이메일 경고 + 로그
"""

import os, json, csv, smtplib, logging, requests
from datetime import datetime, date
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── 경로 ──────────────────────────────────────────────────────
_DIR = Path(__file__).resolve().parent
def _find_root():
    for c in [_DIR, _DIR.parent]:
        if (c / ".env").exists(): return c
    return _DIR

BASE_DIR      = _find_root()
PIPELINE_ROOT = BASE_DIR
OUTPUT_DIR    = BASE_DIR / "outputs" / "latest"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [NOTIFIER] %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

def load_env():
    ep = BASE_DIR / ".env"
    if ep.exists():
        for line in ep.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
load_env()


# ══════════════════════════════════════════════════════════════
# Google Drive 업로드
# ══════════════════════════════════════════════════════════════
DRIVE_FOLDER_ID = "1p2ZTMfjW7HJx49GDXiL5loQjQp22SHkN"

def upload_report_to_drive():
    """Drive 동기화 폴더로 레포트 복사 (Google Drive 자동 동기화 활용)"""
    import shutil
    from datetime import datetime

    DRIVE_SYNC_FOLDER = r"H:\내 드라이브\AI_WorkSpace\I_SFC\04_AI_Handover"
    today = datetime.now().strftime("%Y%m%d_%H%M")

    copied = []  # (label, dst_name, drive_folder_url) 튜플 리스트
    targets = [
        (PIPELINE_ROOT / "outputs" / "latest" / "sfd_report_latest.html",
         f"SFD_Report_{today}.html", "📊 시황 레포트"),
        (PIPELINE_ROOT / "outputs" / "latest" / "sfd_account_latest.html",
         f"SFD_Account_{today}.html", "💼 계좌 분석"),
    ]

    DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/1p2ZTMfjW7HJx49GDXiL5loQjQp22SHkN"

    for src, dst_name, label in targets:
        if src.exists():
            dst = Path(DRIVE_SYNC_FOLDER) / dst_name
            try:
                shutil.copy2(str(src), str(dst))
                copied.append((label, dst_name, DRIVE_FOLDER_URL))
                print(f"  [DRIVE] {dst_name} → Drive 동기화 폴더 복사 완료")
            except Exception as e:
                print(f"  [DRIVE] 복사 실패: {e}")
        else:
            print(f"  [DRIVE] 파일 없음: {src}")

    return copied


# ══════════════════════════════════════════════════════════════
# 데이터 수집
# ══════════════════════════════════════════════════════════════
def load_summary() -> dict:
    """레포트 핵심 데이터 수집"""
    result = {
        "date":         date.today().strftime("%Y.%m.%d"),
        "time":         datetime.now().strftime("%H:%M"),
        "kospi":        "",  "kospi_chg": "",
        "nasdaq":       "",  "nasdaq_chg": "",
        "usd_krw":      "",
        "gold": "", "gold_chg": "", "oil": "", "oil_chg": "",
        "top5":         [],
        "account_ret":  "",
        "add_buy":      [],
        "cutloss":      [],
        "dart_hits":    [],
    }

    # 글로벌 시장 (KOSPI/NASDAQ/USD_KRW) — sfd_global_radar_latest.json
    # 실제 구조: market.indices.KOSPI/NASDAQ.{price, chg_pct}
    #            market.fx_rates.USD_KRW.{price, chg_pct}
    fp = OUTPUT_DIR / "sfd_global_radar_latest.json"
    if fp.exists():
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            mkt     = d.get("market", {})
            indices = mkt.get("indices", {})
            fx      = mkt.get("fx_rates", {})
            kospi   = indices.get("KOSPI", {})
            nasdaq  = indices.get("NASDAQ", {})
            usdkrw  = fx.get("USD_KRW", {})
            if kospi:
                result["kospi"]     = kospi.get("price", "")
                result["kospi_chg"] = kospi.get("chg_pct", "")
            if nasdaq:
                result["nasdaq"]     = nasdaq.get("price", "")
                result["nasdaq_chg"] = nasdaq.get("chg_pct", "")
            if usdkrw:
                result["usd_krw"] = usdkrw.get("price", "")
        except Exception as e:
            log.warning(f"sfd_global_radar_latest.json 파싱 실패: {e}")

    # 원자재 — macro_radar (실제구조: macros 키에 DXY/GOLD/OIL)
    for fname in ["sfd_macro_radar_latest.json", "sfd_macro_radar.json"]:
        fp = OUTPUT_DIR / fname
        if fp.exists():
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
                macros = d.get("macros", {})
                gold = macros.get("GOLD", {})
                oil  = macros.get("OIL",  {})
                result["gold"]     = str(gold.get("price", ""))
                result["gold_chg"] = str(gold.get("change_%", ""))
                result["oil"]      = str(oil.get("price", ""))
                result["oil_chg"]  = str(oil.get("change_%", ""))
            except Exception:
                pass
            break

    # TOP5 신호
    for fname in ["sfd_master_signal_latest.csv", "sfd_master_signal.csv"]:
        fp = OUTPUT_DIR / fname
        if fp.exists():
            try:
                rows = []
                with open(fp, encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        score = float(row.get("total_score", row.get("score", 0)) or 0)
                        sig   = row.get("signal", "")
                        if sig in ("RESERVE_BUY", "WATCH_ONLY") and score > 0:
                            rows.append({"name": row.get("name",""), "score": score, "signal": sig})
                rows.sort(key=lambda x: x["score"], reverse=True)
                result["top5"] = rows[:5]
            except Exception:
                pass
            break

    # 계좌 분석
    pf_path = BASE_DIR / "portfolio.json"
    if pf_path.exists():
        try:
            pf = json.loads(pf_path.read_text(encoding="utf-8"))
            holdings = pf.get("holdings", [])
            total_cost, total_profit = 0, 0
            for h in holdings:
                avg = float(h.get("avg_price", 0) or 0)
                qty = int(h.get("qty", 0) or 0)
                cur = float(h.get("current_price", avg) or avg)
                grade = h.get("grade", "C")
                total_cost   += avg * qty
                total_profit += (cur - avg) * qty
                trig = {"A": -15, "B": -25, "C": -20}.get(grade, -20)
                ret  = ((cur - avg) / avg * 100) if avg > 0 else 0
                if ret <= trig:
                    result["add_buy"].append(f"{h.get('name','')} ({ret:.1f}%)")
                if ret <= {"A":-30,"B":-40,"C":-30}.get(grade,-30):
                    result["cutloss"].append(f"{h.get('name','')} ({ret:.1f}%)")
            if total_cost > 0:
                result["account_ret"] = f"{total_profit/total_cost*100:+.2f}%"
        except Exception:
            pass

    # DART 이벤트 (보유종목)
    fp = OUTPUT_DIR / "sfd_dart_event_latest.csv"
    if fp.exists():
        try:
            with open(fp, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("in_sfd") == "Y":
                        score = int(float(row.get("impact_score", 0) or 0))
                        result["dart_hits"].append(
                            f"{row.get('corp_name','')} [{row.get('event_type','')}] {score:+d}pt")
        except Exception:
            pass

    return result


# ══════════════════════════════════════════════════════════════
# 메시지 포맷
# ══════════════════════════════════════════════════════════════
def build_text_summary(d: dict, report_url: str | None = None) -> str:
    """카카오/SMS용 텍스트 요약. report_url이 있으면 말미에 링크 추가."""
    lines = [
        f"📊 SFD 시황 요약 {d['date']} {d['time']}",
        "─" * 30,
    ]
    if d.get("kospi") != "":
        try:
            lines.append(f"KOSPI  {float(d['kospi']):,.2f} ({float(d['kospi_chg']):+.2f}%)")
        except (ValueError, TypeError):
            pass
    if d.get("nasdaq") != "":
        try:
            lines.append(f"NASDAQ {float(d['nasdaq']):,.2f} ({float(d['nasdaq_chg']):+.2f}%)")
        except (ValueError, TypeError):
            pass
    if d.get("usd_krw") != "":
        try:
            lines.append(f"달러/원 {float(d['usd_krw']):,.2f}")
        except (ValueError, TypeError):
            pass
    if d.get("gold"):
        lines.append(f"금($/oz) {d['gold']} ({d['gold_chg']}%)")
    if d.get("oil"):
        lines.append(f"WTI유가 {d['oil']} ({d['oil_chg']}%)")
    lines.append("")

    if d["top5"]:
        lines.append("🚀 SFD TOP5")
        for i, t in enumerate(d["top5"], 1):
            lines.append(f"  {i}. {t['name']} {t['score']:.0f}pt")
    lines.append("")

    if d["account_ret"]:
        lines.append(f"💼 계좌 수익률: {d['account_ret']}")
    if d["add_buy"]:
        lines.append(f"📥 추가매수 트리거: {', '.join(d['add_buy'])}")
    if d["cutloss"]:
        lines.append(f"🚨 손절 검토: {', '.join(d['cutloss'])}")
    if d["dart_hits"]:
        lines.append(f"📢 DART: {' / '.join(d['dart_hits'][:3])}")

    if report_url:
        lines.append(f"\n\n📊 전체 레포트:\n{report_url}")

    return "\n".join(lines)


def _build_drive_buttons_html(report_urls: list = None) -> str:
    """Drive 링크 버튼 HTML 생성"""
    if not report_urls:
        return (
            '<div style="background:#1a1a1a;padding:12px;border-radius:8px;'
            'font-size:11px;color:#aaa;word-break:break-all">'
            '📁 레포트가 첨부파일로 포함되어 있습니다.</div>'
        )
    buttons = ""
    for label, dst_name, folder_url in report_urls:
        buttons += (
            f'<a href="{folder_url}" target="_blank" '
            f'style="display:inline-block;background:#1565c0;color:#fff;'
            f'padding:10px 18px;border-radius:6px;text-decoration:none;'
            f'font-weight:600;margin:4px 4px 4px 0;font-size:13px">'
            f'{label} 열기 →</a>'
        )
    return (
        f'<div style="background:#1a1a1a;padding:12px;border-radius:8px">'
        f'<div style="color:#888;font-size:11px;margin-bottom:8px">'
        f'📂 Google Drive 레포트 (동기화 폴더)</div>'
        f'{buttons}</div>'
    )


def build_html_email(d: dict, report_urls: list = None, freshness_warn: str = "") -> str:
    """이메일용 HTML. report_urls: [(label, dst_name, folder_url), ...]"""
    top5_rows = "".join(
        f'<tr><td style="padding:4px 8px;color:#888">{i}</td>'
        f'<td style="padding:4px 8px;font-weight:600">{t["name"]}</td>'
        f'<td style="padding:4px 8px;color:#ff9800">{t["score"]:.0f}pt</td></tr>'
        for i, t in enumerate(d["top5"], 1)
    ) if d["top5"] else '<tr><td colspan="3" style="color:#888;padding:8px">신호 없음</td></tr>'

    add_buy_html = (
        f'<div style="background:#e65100;color:#fff;padding:8px 12px;border-radius:6px;margin:8px 0">'
        f'📥 추가매수 트리거: {", ".join(d["add_buy"])}</div>'
    ) if d["add_buy"] else ""

    cutloss_html = (
        f'<div style="background:#b71c1c;color:#fff;padding:8px 12px;border-radius:6px;margin:8px 0">'
        f'🚨 손절 검토: {", ".join(d["cutloss"])}</div>'
    ) if d["cutloss"] else ""

    dart_html = (
        f'<div style="background:#1a237e;color:#90caf9;padding:8px 12px;border-radius:6px;margin:8px 0">'
        f'📢 공시: {" / ".join(d["dart_hits"][:3])}</div>'
    ) if d["dart_hits"] else ""

    return f"""
<html><body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e0e0e0;padding:20px;max-width:600px;margin:0 auto">
<div style="background:#111;border-radius:10px;padding:20px;border:1px solid #222">
  <h2 style="color:#fff;margin-bottom:4px">📊 SFD 시황 요약</h2>
  <div style="color:#888;font-size:12px;margin-bottom:16px">{d['date']} {d['time']}</div>

  {f'<div style="background:#e65100;color:#fff;padding:8px 12px;border-radius:6px;margin-bottom:12px;font-size:12px">{freshness_warn}</div>' if freshness_warn else ""}

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:16px">
    <div style="background:#1a1a1a;padding:10px;border-radius:8px">
      <div style="color:#888;font-size:11px">KOSPI</div>
      <div style="font-size:16px;font-weight:700">{d['kospi']}</div>
      <div style="color:{'#e53935' if '+' in str(d['kospi_chg']) else '#1565c0'}">{d['kospi_chg']}%</div>
    </div>
    <div style="background:#1a1a1a;padding:10px;border-radius:8px">
      <div style="color:#888;font-size:11px">NASDAQ</div>
      <div style="font-size:16px;font-weight:700">{d['nasdaq']}</div>
      <div style="color:{'#e53935' if '+' in str(d['nasdaq_chg']) else '#1565c0'}">{d['nasdaq_chg']}%</div>
    </div>
    <div style="background:#1a1a1a;padding:10px;border-radius:8px">
      <div style="color:#888;font-size:11px">달러/원</div>
      <div style="font-size:16px;font-weight:700">{d['usd_krw']}</div>
    </div>
  </div>

  <div style="background:#1a1a1a;border-radius:8px;padding:12px;margin-bottom:12px">
    <div style="font-weight:700;margin-bottom:8px">🚀 SFD TOP5</div>
    <table style="width:100%;border-collapse:collapse">{top5_rows}</table>
  </div>

  {"<div style='background:#1a1a1a;padding:10px;border-radius:8px;margin-bottom:12px'><span style='color:#888;font-size:12px'>계좌 수익률</span><span style='font-size:18px;font-weight:700;margin-left:12px'>" + d['account_ret'] + "</span></div>" if d['account_ret'] else ""}

  {add_buy_html}{cutloss_html}{dart_html}

  <div style="margin-top:16px">
    {_build_drive_buttons_html(report_urls)}
  </div>
</div>
</body></html>"""


# ══════════════════════════════════════════════════════════════
# 발송 채널
# ══════════════════════════════════════════════════════════════
def send_email(subject: str, html_body: str, text_body: str,
               attach_files: list = None) -> bool:
    """Gmail SMTP 발송. attach_files: [Path, ...] HTML 파일 첨부 리스트"""
    from email.mime.base import MIMEBase
    from email import encoders

    to_addr   = os.environ.get("NOTIFY_EMAIL_TO", "")
    from_addr = os.environ.get("NOTIFY_EMAIL_FROM", "")
    password  = os.environ.get("NOTIFY_EMAIL_PW", "")

    if not all([to_addr, from_addr, password]):
        log.warning("이메일 설정 없음 (.env: NOTIFY_EMAIL_TO / FROM / PW)")
        return False

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"]    = from_addr
        msg["To"]      = to_addr

        # 본문 파트 (alternative: plain + html)
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text_body, "plain", "utf-8"))
        alt.attach(MIMEText(html_body, "html",  "utf-8"))
        msg.attach(alt)

        # HTML 레포트 파일 첨부
        for fpath in (attach_files or []):
            fpath = Path(fpath)
            if fpath.exists():
                with open(fpath, "rb") as f:
                    part = MIMEBase("text", "html")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{fpath.name}"'
                )
                msg.attach(part)
                log.info(f"  [MAIL] 첨부: {fpath.name}")
            else:
                log.warning(f"  [MAIL] 첨부 파일 없음: {fpath}")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(from_addr, password)
            s.sendmail(from_addr, to_addr, msg.as_string())
        log.info(f"✅ 이메일 발송 완료 → {to_addr}")
        return True
    except Exception as e:
        log.error(f"이메일 발송 실패: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 카카오 토큰 관리
# ══════════════════════════════════════════════════════════════
def _update_env_token(new_token: str) -> None:
    """.env 파일의 NOTIFY_KAKAO_TOKEN 값만 교체하고 os.environ 즉시 반영."""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("NOTIFY_KAKAO_TOKEN"):
                new_lines.append(f"NOTIFY_KAKAO_TOKEN={new_token}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"NOTIFY_KAKAO_TOKEN={new_token}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ["NOTIFY_KAKAO_TOKEN"] = new_token


def reissue_kakao_token() -> str | None:
    """
    client_credentials grant로 새 access_token 발급.
    카카오가 해당 grant를 허용하지 않으면 None 반환.
    성공 시 .env 업데이트 후 새 토큰 반환.
    """
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "")
    if not rest_api_key:
        log.warning("KAKAO_REST_API_KEY 미설정 — 토큰 재발급 불가")
        return None

    try:
        r = requests.post(
            "https://kauth.kakao.com/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id":  rest_api_key,
            },
            timeout=10,
        )
        body = r.json()
        new_token = body.get("access_token")
        if not new_token:
            log.warning(f"client_credentials 발급 실패 (카카오 미지원 가능): {body}")
            return None

        _update_env_token(new_token)
        log.info("✅ 카카오 토큰 재발급 완료 (client_credentials)")
        return new_token

    except Exception as e:
        log.error(f"카카오 토큰 재발급 예외: {e}")
        return None


def check_kakao_token() -> bool:
    """
    매일 08:00 호출용 토큰 유효성 점검.
    만료 임박(잔여 < 3600초) 또는 401 시:
      - 로그에 KAKAO_TOKEN_EXPIRED 출력
      - 이메일로 수동 갱신 요청 발송
    반환값: True(정상) / False(만료 임박 또는 오류)
    """
    token = os.environ.get("NOTIFY_KAKAO_TOKEN", "")
    if not token:
        log.warning("KAKAO_TOKEN_EXPIRED: NOTIFY_KAKAO_TOKEN 미설정 — 수동 갱신 필요")
        _send_token_expired_email("NOTIFY_KAKAO_TOKEN 미설정")
        return False

    try:
        r = requests.get(
            "https://kapi.kakao.com/v1/user/access_token_info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )

        if r.status_code == 401:
            log.error("KAKAO_TOKEN_EXPIRED: 토큰 만료(401) — 수동 갱신 필요")
            _send_token_expired_email("토큰이 만료되었습니다 (401 응답)")
            return False

        body = r.json()
        expires_in = body.get("expires_in", 0)  # 잔여 유효시간(초)

        if expires_in < 3600:
            log.warning(
                f"KAKAO_TOKEN_EXPIRED: 만료 임박 (잔여 {expires_in}초) — 수동 갱신 필요"
            )
            _send_token_expired_email(f"토큰 만료 임박 (잔여 {expires_in}초)")
            return False

        log.info(f"✅ 카카오 토큰 유효 (잔여 {expires_in}초 / {expires_in//3600}시간)")
        return True

    except Exception as e:
        log.error(f"카카오 토큰 점검 실패: {e}")
        return False


def _send_token_expired_email(reason: str) -> None:
    """카카오 토큰 만료 이메일 경고 발송."""
    subject   = "[SFD 긴급] 카카오 토큰 만료 임박 — 수동 갱신 필요"
    text_body = (
        f"[SFD 자동 알림]\n\n"
        f"카카오 토큰 갱신이 필요합니다.\n"
        f"사유: {reason}\n\n"
        f"카카오 개발자 콘솔(https://developers.kakao.com)에서\n"
        f"새 access_token을 발급받아 .env의 NOTIFY_KAKAO_TOKEN을 갱신해주세요."
    )
    html_body = f"""
<html><body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e0e0e0;padding:20px">
<div style="background:#b71c1c;border-radius:8px;padding:16px;max-width:520px">
  <h3 style="color:#fff;margin-top:0">🚨 카카오 토큰 만료 임박</h3>
  <p style="margin:4px 0">사유: <strong>{reason}</strong></p>
  <p style="margin:8px 0;font-size:13px;color:#ffcdd2">
    카카오 개발자 콘솔에서 새 access_token을 발급받아<br>
    <code>.env</code>의 <code>NOTIFY_KAKAO_TOKEN</code>을 갱신해주세요.
  </p>
</div>
</body></html>"""
    send_email(subject, html_body, text_body)


def _kakao_send_request(token: str, text: str) -> requests.Response:
    """카카오 나에게 보내기 단일 요청."""
    payload = {
        "template_object": json.dumps({
            "object_type": "text",
            "text": text[:1000],  # 카카오 텍스트 최대 1000자
            "link": {"web_url": "", "mobile_web_url": ""},
            "button_title": "SFD 레포트"
        })
    }
    return requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {token}"},
        data=payload,
        timeout=10,
    )


def send_kakao(text: str) -> bool:
    """
    카카오 나에게 보내기 API.
    401 응답 시 reissue_kakao_token() 시도 후 1회 재전송.
    재발급도 실패하면 check_kakao_token() 폴백(이메일 경고).
    """
    token = os.environ.get("NOTIFY_KAKAO_TOKEN", "")
    if not token:
        log.warning("카카오 토큰 없음 (.env: NOTIFY_KAKAO_TOKEN)")
        return False

    try:
        r = _kakao_send_request(token, text)
        log.info(f"카카오 응답 [{r.status_code}]: {r.text[:300]}")

        if r.status_code == 401:
            log.warning("카카오 401 — client_credentials 재발급 시도")
            new_token = reissue_kakao_token()

            if new_token:
                r = _kakao_send_request(new_token, text)
                log.info(f"카카오 재시도 응답 [{r.status_code}]: {r.text[:300]}")
            else:
                # client_credentials 불가 → 토큰 점검 + 이메일 경고 폴백
                log.error("KAKAO_TOKEN_EXPIRED: 자동 재발급 불가 — 수동 갱신 필요")
                check_kakao_token()
                return False

        if r.json().get("result_code") == 0:
            log.info("✅ 카카오 발송 완료")
            return True
        else:
            log.error(f"카카오 발송 실패 [{r.status_code}]: {r.text}")
            return False

    except Exception as e:
        log.error(f"카카오 발송 실패: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 신선도 체크
# ══════════════════════════════════════════════════════════════
def _check_report_freshness() -> str:
    """레포트 파일 신선도 확인 — 2시간 초과 시 경고 반환"""
    from datetime import timedelta
    report = PIPELINE_ROOT / "outputs" / "latest" / "sfd_report_latest.html"
    if not report.exists():
        return "⚠️ sfd_report_latest.html 없음"
    age = datetime.now() - datetime.fromtimestamp(report.stat().st_mtime)
    if age > timedelta(hours=2):
        total_sec = int(age.total_seconds())
        h, rem = divmod(total_sec, 3600)
        m = rem // 60
        return f"⚠️ 레포트 {h}시간 {m}분 전 데이터 (파이프라인 미실행 가능성)"
    return ""


# ══════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════
def run():
    ts = datetime.now().strftime("%H:%M")
    log.info(f"=== sfd_notifier.py v1.2 시작 ({ts}) ===")

    freshness_warn = _check_report_freshness()
    if freshness_warn:
        log.warning(freshness_warn)

    data = load_summary()

    report_urls = upload_report_to_drive()
    report_url  = report_urls[0][2] if report_urls else None

    text_msg = build_text_summary(data, report_url=report_url)
    html_msg = build_html_email(data, report_urls=report_urls, freshness_warn=freshness_warn)
    subject  = f"[SFD] {data['date']} {ts} 시황요약"

    if data["cutloss"]:
        subject = f"🚨 [SFD 긴급] 손절 검토 {len(data['cutloss'])}종목 — " + subject
    elif data["add_buy"]:
        subject = f"📥 [SFD] 추가매수 트리거 — " + subject

    log.info(f"제목: {subject}")
    log.info(f"TOP5: {[t['name'] for t in data['top5']]}")

    email_ok = send_email(subject, html_msg, text_msg, attach_files=[
        PIPELINE_ROOT / "outputs" / "latest" / "sfd_report_latest.html",
        PIPELINE_ROOT / "outputs" / "latest" / "sfd_account_latest.html",
    ])
    kakao_ok = send_kakao(text_msg)

    if not email_ok and not kakao_ok:
        log.warning("발송 채널 없음 — .env 설정 확인")
        log.info("=" * 40)
        log.info("텍스트 미리보기:")
        print(text_msg)

if __name__ == "__main__":
    run()
