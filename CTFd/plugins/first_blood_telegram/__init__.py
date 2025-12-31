import logging
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy import asc
from sqlalchemy import event

from CTFd.models import Challenges, Solves, db
from CTFd.plugins import bypass_csrf_protection
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only
from CTFd.utils.modes import get_model

log = logging.getLogger(__name__)

# --- Config keys ---
CFG_ENABLED = "FB_TG_ENABLED"          # "1" / "0"
CFG_TOKEN = "FB_TG_TOKEN"              # bot token
CFG_CHAT_ID = "FB_TG_CHAT_ID"          # telegram chat id
CFG_TEMPLATE = "FB_TG_TEMPLATE"        # message template
CFG_PARSE_MODE = "FB_TG_PARSE_MODE"    # "", "HTML", "MarkdownV2"


def _cfg(key: str, default: str = "") -> str:
    value = get_config(key)
    if value is None:
        return default
    return str(value)


def _is_enabled() -> bool:
    return _cfg(CFG_ENABLED, "0") == "1"


def _mask_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:6]}...{token[-4:]}"


def _telegram_send_message(token: str, chat_id: str, text: str, parse_mode: str = "") -> None:
    """
    Minimal Telegram sendMessage without extra deps.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            _ = resp.read()
    except Exception:
        log.exception("FirstBloodTelegram: failed to send telegram message")


def _render_template_text(template: str, vars_: Dict[str, str]) -> str:
    """
    Simple template rendering: {key} -> value
    """
    rendered = template
    for key, value in vars_.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _first_visible_solve_for_challenge(challenge_id: int) -> Optional[Solves]:
    """
    First solve per challenge among visible/non-banned accounts.
    """
    model = get_model()  # Users or Teams depending on mode
    query = (
        Solves.query.join(model, Solves.account_id == model.id)
        .filter(Solves.challenge_id == challenge_id, model.hidden == False, model.banned == False)
        .order_by(asc(Solves.date), asc(Solves.id))
    )
    return query.first()


def _announce_first_blood_if_needed(solve_id: int) -> None:
    if not _is_enabled():
        return

    token = _cfg(CFG_TOKEN, "").strip()
    chat_id = _cfg(CFG_CHAT_ID, "").strip()
    if not token or not chat_id:
        return

    solve = Solves.query.get(solve_id)
    if not solve:
        return

    model = get_model()
    account = model.query.get(solve.account_id)
    if not account or getattr(account, "hidden", False) or getattr(account, "banned", False):
        return

    challenge_id = getattr(solve, "challenge_id", None)
    if not challenge_id:
        return

    first = _first_visible_solve_for_challenge(int(challenge_id))
    if not first or int(first.id) != int(solve.id):
        return

    challenge = Challenges.query.get(int(challenge_id))
    challenge_name = str(getattr(challenge, "name", "") or f"challenge:{challenge_id}")
    challenge_category = str(getattr(challenge, "category", "") or "")
    challenge_points = str(getattr(challenge, "value", "") or "")

    solver_name = str(getattr(account, "name", "") or f"account:{solve.account_id}")
    solver_type = "team" if model.__name__.lower().startswith("team") else "user"

    vars_ = {
        "solver": solver_name,
        "solver_type": solver_type,
        "challenge": challenge_name,
        "category": challenge_category,
        "points": challenge_points,
        "solve_id": str(solve.id),
        "challenge_id": str(challenge_id),
        "date_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }

    template = _cfg(CFG_TEMPLATE, "🩸 FIRST BLOOD! {solver} solved {challenge}")
    parse_mode = _cfg(CFG_PARSE_MODE, "").strip()
    message = _render_template_text(template, vars_)

    _telegram_send_message(token=token, chat_id=chat_id, text=message, parse_mode=parse_mode)


def load(app):
    """
    Entry point for CTFd plugin.
    """

    bp = Blueprint(
        "first_blood_telegram",
        __name__,
        url_prefix="/admin/first_blood_telegram",
    )

    @bp.route("/", methods=["GET"])
    @admins_only
    def get_settings():
        """
        Return plugin settings as JSON.
        """
        return jsonify(
            {
                "success": True,
                "settings": {
                    "enabled": _cfg(CFG_ENABLED, "0") == "1",
                    "token_masked": _mask_token(_cfg(CFG_TOKEN, "")),
                    "token_is_set": bool(_cfg(CFG_TOKEN, "").strip()),
                    "chat_id": _cfg(CFG_CHAT_ID, ""),
                    "template": _cfg(CFG_TEMPLATE, "🩸 FIRST BLOOD! {solver} solved {challenge}"),
                    "parse_mode": _cfg(CFG_PARSE_MODE, ""),
                },
                "placeholders": [
                    "{solver}",
                    "{solver_type}",
                    "{challenge}",
                    "{category}",
                    "{points}",
                    "{solve_id}",
                    "{challenge_id}",
                    "{date_utc}",
                ],
                "how_to_update": {
                    "method": "POST",
                    "content_type": "application/json",
                    "body_example": {
                        "enabled": True,
                        "token": "123456:ABCDEF...",
                        "chat_id": "-1001234567890",
                        "template": "🏁 FB! {solver} первым закрыл «{challenge}»",
                        "parse_mode": "",
                    },
                },
            }
        )

    @bp.route("/", methods=["POST"])
    @admins_only
    @bypass_csrf_protection
    def set_settings():
        """
        Update plugin settings.
        """
        payload: Dict[str, Any] = {}
        if request.is_json:
            payload = request.get_json(silent=True) or {}
        else:
            payload = dict(request.form)

        if "enabled" in payload:
            enabled = payload["enabled"]
            if isinstance(enabled, str):
                enabled = enabled.lower() in ("1", "true", "yes", "on")
            set_config(CFG_ENABLED, "1" if bool(enabled) else "0")

        if "token" in payload:
            set_config(CFG_TOKEN, str(payload["token"]).strip())

        if "chat_id" in payload:
            set_config(CFG_CHAT_ID, str(payload["chat_id"]).strip())

        if "template" in payload:
            template = str(payload["template"]).strip()
            set_config(CFG_TEMPLATE, template or "🩸 FIRST BLOOD! {solver} solved {challenge}")

        if "parse_mode" in payload:
            set_config(CFG_PARSE_MODE, str(payload["parse_mode"]).strip())

        return jsonify({"success": True})

    @bp.route("/test", methods=["POST"])
    @admins_only
    @bypass_csrf_protection
    def test_message():
        """
        Send a test message to current chat_id.
        """
        token = _cfg(CFG_TOKEN, "").strip()
        chat_id = _cfg(CFG_CHAT_ID, "").strip()
        if not token or not chat_id:
            return jsonify({"success": False, "error": "token/chat_id not set"}), 400

        message = "✅ FirstBloodTelegram test message"
        _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=message,
            parse_mode=_cfg(CFG_PARSE_MODE, "").strip(),
        )
        return jsonify({"success": True})

    app.register_blueprint(bp)

    @event.listens_for(db.session, "after_flush")
    def _after_flush(session, flush_context):
        pending = session.info.setdefault("fb_tg_pending_solves", [])
        for obj in session.new:
            if isinstance(obj, Solves):
                solve_id = getattr(obj, "id", None)
                if solve_id is not None:
                    pending.append(int(solve_id))

    @event.listens_for(db.session, "after_rollback")
    def _after_rollback(session):
        session.info.pop("fb_tg_pending_solves", None)

    @event.listens_for(db.session, "after_commit")
    def _after_commit(session):
        solve_ids = session.info.pop("fb_tg_pending_solves", [])
        if not solve_ids:
            return
        with app.app_context():
            for solve_id in solve_ids:
                _announce_first_blood_if_needed(solve_id)
