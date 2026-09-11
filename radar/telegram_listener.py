"""cry4scan — Telegram remote control for RADAR.

Run this once on your machine (it keeps running, polling Telegram):
    python telegram_listener.py

From Telegram:
    /run     lance un cycle maintenant (résumé court : ce qui vaut le coup)
    /auto    active le scan automatique (toutes les 30 min, silencieux sinon)
    /stop    coupe le scan automatique
    /top     liste actionnable actuelle (tape un bouton pour approfondir)
    /status  en cours ? auto actif ? prochain scan quand ?
    /help    liste des commandes

Each opportunity comes with [Approfondir] [Faire maintenant] [Ignorer]
buttons. Approfondir shows the full breakdown for THAT one opportunity —
not the whole list again. Faire maintenant / Ignorer are remembered
(store.py's `decisions` table) so the same thing doesn't get pushed at you
again unless its score moves enough to mean the situation changed.

RADAR filters before it notifies (see radar/signals/decision.py): only
opportunities worth acting on now are pushed automatically. Everything
else stays reachable via /top instead of arriving as noise.

Hackathon-tagged do_now opportunities also get a VERIFY pass (see
radar/signals/verify_hackathon.py): RADAR tries to open the official page
and read deadline/prize/your-own-GitHub-match info directly. If that page
is behind an anti-bot check, RADAR does not try to get past it — it sends
you a separate "can you check this one yourself" message instead.

Only replies to the chat_id in .env.local — anyone else messaging the bot
is ignored, so a stranger who finds the bot username can't trigger runs on
your machine. Uses plain long-polling on Telegram's getUpdates via
`requests` (already a project dependency) — no new library needed.
"""
from __future__ import annotations

import datetime as _dt
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests

from radar.signals.decision import DO_NOW, WATCH, Decision, decide
from radar.signals.store import RadarStore
from radar.signals.verify_hackathon import HackathonVerification, verify_hackathon
from run import ALERT_THRESHOLD, DEFAULT_QUERIES, build_dispatcher, load_env_local, run_once

POLL_TIMEOUT = 30  # seconds, Telegram long-poll
AUTO_INTERVAL_MINUTES = 30

# A decided (ignored/done) opportunity is only re-surfaced if its score has
# moved by at least this much since the decision — otherwise "ignore" would
# mean nothing.
DECISION_RESURFACE_DELTA = 0.15

_API = "https://api.telegram.org/bot{token}/{method}"


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------

def _post(token: str, method: str, payload: dict) -> dict:
    try:
        resp = requests.post(_API.format(token=token, method=method), json=payload, timeout=15)
        return resp.json()
    except requests.RequestException as e:
        print(f"[telegram] {method} failed: {e}")
        return {}


def send_message(token: str, chat_id: str, text: str, keyboard: list[list[dict]] | None = None) -> int | None:
    payload = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    result = _post(token, "sendMessage", payload)
    return (result.get("result") or {}).get("message_id")


def edit_message(token: str, chat_id: str, message_id: int, text: str) -> None:
    _post(token, "editMessageText", {
        "chat_id": chat_id, "message_id": message_id, "text": text[:4000],
        "reply_markup": {"inline_keyboard": []},
    })


def answer_callback(token: str, callback_id: str, text: str = "") -> None:
    _post(token, "answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})


# ---------------------------------------------------------------------------
# Formatting — short by default, full detail only on request
# ---------------------------------------------------------------------------

_TIER_MARK = {DO_NOW: "🔥", WATCH: "🟡"}
_TIER_LABEL = {DO_NOW: "Faisable maintenant", WATCH: "À surveiller"}


def _snippet(score, width: int = 90) -> str:
    text = (score.representative_text or "").strip().replace("\n", " ")
    if len(text) > width:
        text = text[: width - 1].rstrip() + "…"
    return text


def _effort_label(score) -> str:
    if score.effort_score < 0.35:
        return "effort faible"
    if score.effort_score < 0.55:
        return "effort moyen"
    return "effort élevé"


_RISK_LEVEL_FR = {"LOW": "faible", "MEDIUM": "moyen", "HIGH": "élevé"}
_TREND_FR = {
    "accelerating": "en accélération",
    "steady": "stable",
    "saturating": "en train de saturer",
    "insufficient_data": "pas assez de recul",
}


def _risk_label(score) -> str:
    return _RISK_LEVEL_FR.get(score.risk_level, score.risk_level.lower())


def _trend_label(score) -> str:
    return _TREND_FR.get(score.trend, score.trend)


def _meta_line(score) -> str:
    bits = []
    if score.money_mention:
        bits.append(score.money_mention)
    bits.append(_effort_label(score))
    bits.append("/".join(sorted(score.platforms)))
    return " · ".join(bits)


def _card_keyboard(opp_id: str, include_detail: bool = True) -> list[list[dict]]:
    row = []
    if include_detail:
        row.append({"text": "🔎 Approfondir", "callback_data": f"detail:{opp_id}"})
    row.append({"text": "✅ Faire maintenant", "callback_data": f"done:{opp_id}"})
    row.append({"text": "🚫 Ignorer", "callback_data": f"ignore:{opp_id}"})
    return [row]


def _verification_lines(verification: HackathonVerification | None) -> list[str]:
    """Only ever called with a non-blocked verification — a blocked one is
    reported through its own heads-up message instead (see
    format_blocked_notice), not folded into the card silently."""
    if not verification or not verification.checked or verification.blocked:
        return []
    facts = []
    if verification.deadline_text:
        facts.append(verification.deadline_text)
    if verification.prize_text:
        facts.append(verification.prize_text)
    if verification.github_matches:
        top = verification.github_matches[0]
        facts.append(f"ton repo \"{top['name']}\" correspond peut-être ({top['match_score']:.0f}%)")
    if not facts:
        return []
    return ["", "Vérifié sur la page officielle:"] + [f"• {f}" for f in facts]


def format_card(score, decision: Decision, is_new: bool, verification: HackathonVerification | None = None) -> str:
    """The rich notification: one opportunity, the essentials, nothing
    else. Used for auto-scan pushes and the #1 pick in a /run summary."""
    header = f"{_TIER_MARK[decision.tier]} {_TIER_LABEL[decision.tier]}"
    if is_new:
        header += " · nouveau"
    lines = [header, f"\"{_snippet(score, 110)}\"", _meta_line(score)]
    if decision.why:
        lines.append("")
        lines.append("Pourquoi:")
        for w in decision.why[:3]:
            lines.append(f"• {w}")
    lines += _verification_lines(verification)
    return "\n".join(lines)


def format_detail(
    score, decision: Decision, first_seen: str | None, verification: HackathonVerification | None = None
) -> str:
    """Full breakdown for ONE opportunity — the actual "approfondir"."""
    lines = [
        f"{_TIER_MARK.get(decision.tier, '⚪')} {_TIER_LABEL.get(decision.tier, 'Ignorée')}",
        f"\"{_snippet(score, 220)}\"",
        "",
        f"Score global : {score.opportunity_score:.2f}  ·  valeur estimée : {decision.value_score:.2f}",
        f"Récompense mentionnée : {score.money_mention or 'non précisée dans le texte'}",
        f"Effort estimé : {_effort_label(score)}",
        f"Risque : {_risk_label(score)}",
        f"Pertinence : {score.relevance_score:.0%}",
        f"Sources : {score.signal_count} signal(aux) · {'/'.join(sorted(score.platforms))}",
        f"Tendance : {_trend_label(score)}",
    ]
    if first_seen:
        lines.append(f"Détecté depuis : {first_seen[:10]}")
    if decision.why:
        lines.append("")
        lines.append("Pourquoi ça vaut le coup :")
        lines += [f"• {w}" for w in decision.why]
    if decision.concerns:
        lines.append("")
        lines.append("Points de vigilance :")
        lines += [f"• {c}" for c in decision.concerns]
    lines += _verification_lines(verification)
    if verification and verification.blocked:
        lines.append("")
        lines.append("🔒 Page officielle protégée (anti-bot) — vérifie toi-même :")
        lines.append(verification.official_url or "")
    if score.representative_url:
        lines.append("")
        lines.append(score.representative_url)
    return "\n".join(lines)


def format_blocked_notice(score, verification: HackathonVerification) -> str:
    """Sent as its own message the moment a hackathon page turns out to be
    behind an anti-bot/login check — this project never tries to get past
    one, it hands the check back to the user instead."""
    return (
        f"🔒 Vérification bloquée\n"
        f"\"{_snippet(score, 90)}\"\n\n"
        f"La page officielle est protégée (anti-bot ou connexion requise) — "
        f"je ne peux pas la lire automatiquement. Tu veux bien checker toi-même ?\n"
        f"{verification.official_url or ''}"
    )


def _teaser_button(score, decision: Decision) -> dict:
    text = f"{_TIER_MARK[decision.tier]} "
    if score.money_mention:
        text += f"{score.money_mention} · "
    text += _snippet(score, 40)
    if len(text) > 60:
        text = text[:59] + "…"
    return {"text": text, "callback_data": f"detail:{score.opportunity_id}"}


def actionable_opportunities(
    result, store: RadarStore
) -> tuple[list[tuple[object, Decision]], list[tuple[object, Decision]]]:
    """(do_now, watch) — decided (ignored/done) ones filtered out unless
    their score moved enough since the decision to mean something changed."""
    decisions_db = store.get_decisions()
    do_now, watch = [], []
    for score in result.scores:
        prior = decisions_db.get(score.opportunity_id)
        if prior and abs(score.opportunity_score - prior[1]) < DECISION_RESURFACE_DELTA:
            continue
        d = decide(score)
        if d.tier == DO_NOW:
            do_now.append((score, d))
        elif d.tier == WATCH:
            watch.append((score, d))
    do_now.sort(key=lambda t: t[1].value_score, reverse=True)
    watch.sort(key=lambda t: t[1].value_score, reverse=True)
    return do_now, watch


def format_run_summary(
    result, elapsed: float, do_now, watch, verification_by_id: dict | None = None
) -> tuple[str, list[list[dict]]]:
    """Header text + keyboard for /run's response: the best pick gets the
    full card inline, up to 2 more get one-line buttons, watch-tier stays
    a single count — never a dump of everything found."""
    header = f"🔎 Scan terminé ({elapsed:.0f}s) — {result.signal_count} signaux analysés"

    if not do_now:
        note = f"\n\nRien d'actionnable maintenant."
        if watch:
            note += f" {len(watch)} à surveiller — /top pour les voir."
        return header + note, []

    best_score, best_decision = do_now[0]
    verification = (verification_by_id or {}).get(best_score.opportunity_id)
    body = format_card(best_score, best_decision, best_score.is_new, verification)
    keyboard = _card_keyboard(best_score.opportunity_id)

    for score, decision in do_now[1:3]:
        keyboard.append([_teaser_button(score, decision)])

    text = f"{header}\n\n{body}"
    return text, keyboard


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ListenerState:
    def __init__(self, store: RadarStore):
        self.store = store
        self.running = False
        self.running_mode = None  # "manuel" | "auto"
        self.running_since = None
        self.auto_on = False
        self.last_result = None
        self.last_mode = None
        self.scheduler = None
        self.lock = threading.Lock()  # serializes /run against the auto-scan job — both hit the same SQLite file
        self.score_by_id: dict[str, object] = {}  # refreshed on every scan/list — resolves button taps
        self.verification_by_id: dict[str, HackathonVerification] = {}  # memoized — never re-fetch the same page

    def cache_scores(self, result) -> None:
        self.score_by_id = {s.opportunity_id: s for s in result.scores}


def _verify_do_now(state: ListenerState, token: str, chat_id: str, do_now) -> None:
    """Runs VERIFY only for do_now-tier, hackathon-tagged opportunities —
    a real network fetch, so it must never run over the full batch, only
    the handful that already passed DECIDE. Memoized so a repeat /top or a
    later scan doesn't re-fetch the same page."""
    for score, _decision in do_now:
        if "hackathon_or_competition" not in score.relevance_reasons:
            continue
        if score.opportunity_id in state.verification_by_id:
            continue
        result = verify_hackathon(score)
        state.verification_by_id[score.opportunity_id] = result
        if result.blocked:
            send_message(token, chat_id, format_blocked_notice(score, result))


def _busy_message(state: ListenerState) -> str:
    since = ""
    if state.running_since:
        since = f" (démarré il y a {time.time() - state.running_since:.0f}s)"
    who = "Le scan automatique" if state.running_mode == "auto" else "Un scan manuel"
    return f"⏳ {who} est en cours{since} — un seul scan à la fois. Réessaie dans quelques minutes."


# ---------------------------------------------------------------------------
# Scan execution
# ---------------------------------------------------------------------------

def run_and_report(state: ListenerState, dispatcher, token: str, chat_id: str) -> None:
    if not state.lock.acquire(blocking=False):
        send_message(token, chat_id, _busy_message(state))
        return
    state.running = True
    state.running_mode = "manuel"
    state.running_since = time.time()
    send_message(token, chat_id, "🔎 Scan manuel lancé — ça prend généralement 4 à 7 minutes...")
    try:
        result, elapsed = run_once(dispatcher=dispatcher)
        state.last_result, state.last_mode = result, "manuel"
        state.cache_scores(result)
        do_now, watch = actionable_opportunities(result, state.store)
        _verify_do_now(state, token, chat_id, do_now)
        text, keyboard = format_run_summary(result, elapsed, do_now, watch, state.verification_by_id)
        send_message(token, chat_id, text, keyboard)
    except Exception:
        send_message(token, chat_id, f"⚠️ Erreur pendant le scan manuel:\n{traceback.format_exc()[-1500:]}")
    finally:
        state.running = False
        state.running_mode = None
        state.running_since = None
        state.lock.release()


def start_auto(state: ListenerState, dispatcher, token: str, chat_id: str) -> None:
    if state.auto_on:
        send_message(token, chat_id, f"🛰️ Scan auto déjà actif (toutes les {AUTO_INTERVAL_MINUTES} min).")
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    from radar.signals.orchestrator import run_cycle

    def job():
        # Same lock as /run — both touch the same SQLite file, never overlap.
        # Silent by design: no start message, no end message, unless a new
        # do_now-tier opportunity actually clears the bar.
        if not state.lock.acquire(blocking=False):
            print("[telegram] auto-scan skipped this round: a scan is already running")
            return
        state.running = True
        state.running_mode = "auto"
        state.running_since = time.time()
        try:
            result = run_cycle(DEFAULT_QUERIES, state.store, dispatcher, alert_threshold=ALERT_THRESHOLD)
            state.last_result, state.last_mode = result, "auto"
            state.cache_scores(result)
            do_now, _watch = actionable_opportunities(result, state.store)
            new_do_now = [(s, d) for s, d in do_now if s.is_new]
            if not new_do_now:
                print("[telegram] auto-scan done, nothing new to push — staying quiet")
                return
            _verify_do_now(state, token, chat_id, new_do_now)
            for score, decision in new_do_now:
                verification = state.verification_by_id.get(score.opportunity_id)
                send_message(
                    token, chat_id,
                    format_card(score, decision, is_new=True, verification=verification),
                    _card_keyboard(score.opportunity_id),
                )
        except Exception:
            send_message(token, chat_id, f"⚠️ Erreur pendant le scan auto:\n{traceback.format_exc()[-1500:]}")
        finally:
            state.running = False
            state.running_mode = None
            state.running_since = None
            state.lock.release()

    scheduler = BackgroundScheduler()
    scheduler.add_job(job, trigger=IntervalTrigger(minutes=AUTO_INTERVAL_MINUTES))
    scheduler.start()
    state.scheduler = scheduler
    state.auto_on = True
    next_run = (_dt.datetime.now() + _dt.timedelta(minutes=AUTO_INTERVAL_MINUTES)).strftime("%H:%M")
    send_message(
        token, chat_id,
        f"🛰️ Scan auto activé — toutes les {AUTO_INTERVAL_MINUTES} min (prochain vers {next_run}).\n"
        f"Silencieux sauf si quelque chose vaut vraiment le coup. /status pour vérifier, /stop pour couper.",
    )


def stop_auto(state: ListenerState, token: str, chat_id: str) -> None:
    if not state.auto_on or not state.scheduler:
        send_message(token, chat_id, "Le scan auto n'est pas actif.")
        return
    state.scheduler.shutdown(wait=False)
    state.scheduler = None
    state.auto_on = False
    send_message(token, chat_id, "🛑 Scan auto coupé.")


# ---------------------------------------------------------------------------
# /top and button callbacks
# ---------------------------------------------------------------------------

def send_top(state: ListenerState, token: str, chat_id: str) -> None:
    if state.last_result is None:
        send_message(token, chat_id, "Pas encore de résultat. /run pour lancer un scan.")
        return
    do_now, watch = actionable_opportunities(state.last_result, state.store)
    if not do_now and not watch:
        send_message(token, chat_id, "Rien d'actionnable en ce moment. /run pour rescanner.")
        return
    _verify_do_now(state, token, chat_id, do_now)

    lines = []
    keyboard = []
    if do_now:
        lines.append(f"🔥 {len(do_now)} à faire maintenant")
    if watch:
        lines.append(f"🟡 {len(watch)} à surveiller")
    lines.append("")
    lines.append("Tape un bouton pour le détail complet de cette opportunité.")

    for score, decision in (do_now + watch)[:8]:
        keyboard.append([_teaser_button(score, decision)])

    send_message(token, chat_id, "\n".join(lines), keyboard)


def handle_callback(state: ListenerState, token: str, chat_id: str, callback_query: dict) -> None:
    cq_id = callback_query.get("id", "")
    data = callback_query.get("data") or ""
    message = callback_query.get("message") or {}
    message_id = message.get("message_id")
    action, _, opp_id = data.partition(":")

    score = state.score_by_id.get(opp_id)
    if score is None:
        answer_callback(token, cq_id, "Donnée expirée — relance /top")
        return

    if action == "detail":
        decision = decide(score)
        first_seen = state.store.get_first_seen(opp_id)
        verification = state.verification_by_id.get(opp_id)
        answer_callback(token, cq_id)
        send_message(
            token, chat_id, format_detail(score, decision, first_seen, verification),
            _card_keyboard(opp_id, include_detail=False),
        )
    elif action in ("ignore", "done"):
        state.store.record_decision(opp_id, action, score.opportunity_score)
        if action == "ignore":
            answer_callback(token, cq_id, "Ignorée")
            text = f"🚫 Ignorée ✅\n\"{_snippet(score, 90)}\""
        else:
            # Deliberately not "Prise en charge" — that read as if RADAR had
            # done something. It hasn't: no automation exists here by
            # design, this is a bookmark, not a status. Say that plainly.
            answer_callback(token, cq_id, "Noté")
            text = (
                f"📌 Noté — tu t'en occupes\n\"{_snippet(score, 90)}\"\n\n"
                f"RADAR n'a rien fait d'automatique, c'est juste un marque-page : "
                f"plus de notification pour celle-ci sauf changement important."
            )
            if score.representative_url:
                text += f"\n{score.representative_url}"
        if message_id:
            edit_message(token, chat_id, message_id, text)


HELP_TEXT = (
    "🛰️ cry4scan\n\n"
    "/run — scan maintenant, résumé court\n"
    "/auto — scan automatique toutes les 30 min, silencieux sauf découverte\n"
    "/stop — coupe le scan automatique\n"
    "/top — liste actionnable actuelle, boutons pour approfondir\n"
    "/status — en cours ? auto actif ? prochain scan ?\n"
    "/help — cette liste\n\n"
    "Chaque opportunité a 3 boutons : Approfondir (détail complet), "
    "Faire maintenant (marque-page — RADAR ne fait rien pour toi), "
    "Ignorer — les deux derniers sont mémorisés, RADAR ne re-notifie pas "
    "dessus sans changement significatif."
)


def _dispatch_update(state: ListenerState, dispatcher, token: str, chat_id: str, update: dict) -> None:
    callback_query = update.get("callback_query")
    if callback_query:
        from_chat = str((callback_query.get("message") or {}).get("chat", {}).get("id", ""))
        if from_chat == str(chat_id):
            handle_callback(state, token, chat_id, callback_query)
        return

    message = update.get("message") or {}
    from_chat = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()

    if from_chat != str(chat_id):
        return  # ignore anyone but the configured owner

    if text == "/run":
        threading.Thread(
            target=run_and_report, args=(state, dispatcher, token, chat_id), daemon=True
        ).start()
    elif text == "/auto":
        start_auto(state, dispatcher, token, chat_id)
    elif text == "/stop":
        stop_auto(state, token, chat_id)
    elif text == "/top":
        send_top(state, token, chat_id)
    elif text == "/status":
        bits = [_busy_message(state) if state.running else "💤 inactif"]
        if state.auto_on and state.scheduler:
            jobs = state.scheduler.get_jobs()
            if jobs and jobs[0].next_run_time:
                bits.append(f"🛰️ auto ON — prochain scan vers {jobs[0].next_run_time.strftime('%H:%M')}")
            else:
                bits.append("🛰️ auto ON")
        else:
            bits.append("🛰️ auto OFF")
        send_message(token, chat_id, "\n".join(bits))
    elif text in ("/help", "/start"):
        send_message(token, chat_id, HELP_TEXT)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    env = load_env_local()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing from .env.local — nothing to do.")
        return

    dispatcher = build_dispatcher()
    state = ListenerState(store=RadarStore())
    print(f"[telegram] cry4scan listening from chat {chat_id}... (Ctrl+C to stop)")
    send_message(token, chat_id, "🛰️ cry4scan en ligne. /help pour les commandes.")

    offset = 0

    try:
        while True:
            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"offset": offset, "timeout": POLL_TIMEOUT},
                    timeout=POLL_TIMEOUT + 10,
                )
                resp.raise_for_status()
                updates = resp.json().get("result", [])
            except requests.RequestException as e:
                print(f"[telegram] poll error: {e} — retrying in 5s")
                time.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                # A crash handling ONE update must never take the whole bot
                # down — found the hard way: a callback hit "database is
                # locked" and the unguarded exception killed the process,
                # silently, with no restart. Every update is now isolated.
                try:
                    _dispatch_update(state, dispatcher, token, chat_id, update)
                except Exception:
                    tb = traceback.format_exc()
                    print(f"[telegram] unhandled error processing an update:\n{tb}")
                    try:
                        send_message(token, chat_id, f"⚠️ Erreur interne (ignorée, le bot continue de tourner):\n{tb[-800:]}")
                    except Exception:
                        pass
    finally:
        if state.scheduler:
            state.scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
