"""cry4scan — Telegram remote control for RADAR.

Run this once on your machine (it keeps running, polling Telegram):
    python telegram_listener.py

From Telegram:
    /run     lance un cycle maintenant, répond avec les résultats
    /auto    active le scan automatique (toutes les 30 min)
    /stop    coupe le scan automatique
    /top     renvoie le dernier résultat en cache (instantané, pas de nouveau scan)
    /status  état actuel (en cours / auto actif ou non)
    /help    liste des commandes

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

from run import ALERT_THRESHOLD, DEFAULT_QUERIES, build_dispatcher, load_env_local, run_once

POLL_TIMEOUT = 30  # seconds, Telegram long-poll
AUTO_INTERVAL_MINUTES = 30

# Opportunities at/above this bar (LOW risk, decent relevance) are shown as
# "validated" — worth a look now. Everything else is shown as "à vérifier"
# so the two aren't visually confused in a wall of scores.
VALIDATED_RISK_LEVELS = {"LOW"}
VALIDATED_MIN_RELEVANCE = 0.5


def send_message(token: str, chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"[telegram] failed to send message: {e}")


def _is_validated(s) -> bool:
    return s.risk_level in VALIDATED_RISK_LEVELS and s.relevance_score >= VALIDATED_MIN_RELEVANCE


def _snippet(s, width: int = 90) -> str:
    text = (s.representative_text or "").strip().replace("\n", " ")
    if len(text) > width:
        text = text[: width - 1].rstrip() + "…"
    return text


def _new_scores(result):
    return sorted((s for s in result.scores if s.is_new), key=lambda s: s.opportunity_score, reverse=True)


def format_summary(result, elapsed: float, mode: str = "manuel") -> str:
    """Short push: title + the essential, nothing else. Full breakdown lives
    behind /top — this is the "headline", /top is "approfondir"."""
    icon = "🛰️" if mode == "auto" else "🔎"
    label = "scan auto" if mode == "auto" else "scan manuel"
    new_ones = _new_scores(result)

    if not new_ones:
        return f"{icon} {label} terminé ({elapsed:.0f}s) — rien de nouveau. /top pour le classement actuel."

    validated_new = [s for s in new_ones if _is_validated(s)]
    best = new_ones[0]
    mark = "✅" if _is_validated(best) else "❔"
    lines = [
        f"{icon} {len(new_ones)} 🆕 nouvelle(s) ({len(validated_new)} validée(s))",
        f"{mark} {best.opportunity_score:.2f} · {'/'.join(sorted(best.platforms))} · \"{_snippet(best, 70)}\"",
    ]
    if len(new_ones) > 1:
        lines.append(f"+ {len(new_ones) - 1} autre(s) nouvelle(s)")
    lines.append("/top pour le détail complet")
    return "\n".join(lines)


def format_result(result, elapsed: float, mode: str = "manuel", top_n: int = 5) -> str:
    header_icon = "🛰️" if mode == "auto" else "🔎"
    mode_label = "scan auto" if mode == "auto" else "scan manuel"

    top = sorted(result.scores, key=lambda s: s.opportunity_score, reverse=True)[:top_n]
    validated = [s for s in top if _is_validated(s)]
    new_count = sum(1 for s in top if s.is_new)

    lines = [
        f"{header_icon} cry4scan — {mode_label} terminé ({elapsed:.0f}s)",
        f"{result.raw_count} bruts → {result.signal_count} signaux → {result.cluster_count} clusters",
        f"{new_count} 🆕 nouvelles · {len(top) - new_count} déjà connues · {len(validated)}/{len(top)} validées",
        "",
    ]

    if not top:
        lines.append("Rien de significatif ce cycle-ci.")
        return "\n".join(lines)

    for i, s in enumerate(top, 1):
        mark = "✅" if _is_validated(s) else "❔"
        new_badge = " 🆕" if s.is_new else ""
        platforms = "/".join(sorted(s.platforms))
        snippet = _snippet(s)
        line = f"{mark} {i}. {s.opportunity_score:.2f} · {platforms} · {s.signal_count} sig · risque {s.risk_level}{new_badge}"
        lines.append(line)
        if snippet:
            lines.append(f"    “{snippet}”")
        if s.representative_url:
            lines.append(f"    {s.representative_url}")

    lines.append("")
    lines.append("✅ validé  ❔ à vérifier  🆕 jamais vu avant")
    return "\n".join(lines)


class ListenerState:
    def __init__(self):
        self.running = False
        self.running_mode = None  # "manuel" | "auto" — which kind of scan currently holds the lock
        self.running_since = None  # datetime — for ETA context on "already running" messages
        self.auto_on = False
        self.last_result = None
        self.last_elapsed = None
        self.last_mode = None
        self.scheduler = None
        self.lock = threading.Lock()  # serializes /run against the auto-scan job — both hit the same SQLite file


def _busy_message(state: ListenerState) -> str:
    since = ""
    if state.running_since:
        elapsed_s = (time.time() - state.running_since)
        since = f" (démarré il y a {elapsed_s:.0f}s)"
    who = "Le scan automatique" if state.running_mode == "auto" else "Un scan manuel"
    return f"⏳ {who} est en cours{since} — un seul scan à la fois pour ne pas surcharger la base. Réessaie dans quelques minutes."


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
        state.last_result, state.last_elapsed, state.last_mode = result, elapsed, "manuel"
        send_message(token, chat_id, format_summary(result, elapsed, mode="manuel"))
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
    from radar.signals.store import RadarStore

    store = RadarStore()

    def job():
        # Same lock as /run — both touch the same SQLite file, never let them overlap.
        # Auto-scan stays silent by design: no start announcement, and no end
        # message unless it actually found something new — a scan that finds
        # nothing new is not worth a notification.
        if not state.lock.acquire(blocking=False):
            print("[telegram] auto-scan skipped this round: a scan is already running")
            return
        state.running = True
        state.running_mode = "auto"
        state.running_since = time.time()
        try:
            t0 = time.perf_counter()
            result = run_cycle(DEFAULT_QUERIES, store, dispatcher, alert_threshold=ALERT_THRESHOLD)
            elapsed = time.perf_counter() - t0
            state.last_result, state.last_elapsed, state.last_mode = result, elapsed, "auto"
            if _new_scores(result):
                send_message(token, chat_id, format_summary(result, elapsed, mode="auto"))
            else:
                print(f"[telegram] auto-scan done, nothing new ({elapsed:.0f}s) — staying quiet")
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
    send_message(
        token, chat_id,
        f"🛰️ Scan auto activé — un cycle toutes les {AUTO_INTERVAL_MINUTES} min "
        f"(prochain vers {(_dt.datetime.now() + _dt.timedelta(minutes=AUTO_INTERVAL_MINUTES)).strftime('%H:%M')}). "
        f"Silencieux si rien de nouveau — tu ne reçois un message que quand un scan trouve du neuf. /status pour vérifier que ça tourne, /stop pour couper.",
    )


def stop_auto(state: ListenerState, token: str, chat_id: str) -> None:
    if not state.auto_on or not state.scheduler:
        send_message(token, chat_id, "Le scan auto n'est pas actif.")
        return
    state.scheduler.shutdown(wait=False)
    state.scheduler = None
    state.auto_on = False
    send_message(token, chat_id, "🛑 Scan auto coupé.")


HELP_TEXT = (
    "🛰️ cry4scan — commandes\n\n"
    "/run — lance un cycle maintenant (résumé court à la fin)\n"
    "/auto — active le scan automatique (toutes les 30 min, silencieux si rien de nouveau)\n"
    "/stop — coupe le scan automatique\n"
    "/top — le détail complet du dernier résultat (le \"approfondir\")\n"
    "/status — en cours ? auto actif ? prochain scan quand ?\n"
    "/help — cette liste"
)


def main() -> None:
    env = load_env_local()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing from .env.local — nothing to do.")
        return

    dispatcher = build_dispatcher()
    state = ListenerState()
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
                message = update.get("message") or {}
                from_chat = str(message.get("chat", {}).get("id", ""))
                text = (message.get("text") or "").strip()

                if from_chat != str(chat_id):
                    continue  # ignore anyone but the configured owner

                if text == "/run":
                    threading.Thread(
                        target=run_and_report, args=(state, dispatcher, token, chat_id), daemon=True
                    ).start()
                elif text == "/auto":
                    start_auto(state, dispatcher, token, chat_id)
                elif text == "/stop":
                    stop_auto(state, token, chat_id)
                elif text == "/top":
                    if state.last_result is None:
                        send_message(token, chat_id, "Pas encore de résultat en cache. /run pour en lancer un.")
                    else:
                        send_message(
                            token, chat_id,
                            format_result(state.last_result, state.last_elapsed or 0.0, mode=state.last_mode or "manuel"),
                        )
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
    finally:
        if state.scheduler:
            state.scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
