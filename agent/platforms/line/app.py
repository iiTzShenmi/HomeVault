import logging
import time

from flask import Flask, request

from agent.config import auto_reload_enabled, port
from agent.features.e3.reminders import start_reminder_worker
from agent.features.weather import handle_city_weather, handle_location_weather
from agent.features.e3 import handle_e3_command
from agent.platforms.line.background import (
    build_processing_ack,
    is_background_e3_command,
    register_background_command,
    start_e3_background_task,
)
from agent.platforms.line.messaging import (
    e3_quick_reply_items,
    push_to_line,
    send_line_response,
    verify_signature,
)


app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _handle_weather_text(text, reply_token, line_user_id):
    parts = text[2:].strip()
    if parts:
        reply = handle_city_weather(parts, logger)
    else:
        reply = handle_location_weather(None, logger)
    if reply_token:
        send_line_response(reply_token, line_user_id, reply, logger)
    else:
        logger.warning("skip_reply reason=missing_reply_token message_type=text")


def _handle_e3_text(text, reply_token, line_user_id):
    if is_background_e3_command(text):
        accepted, existing = register_background_command(line_user_id, text)
        if not accepted:
            logger.info(
                "e3_background_duplicate user=%s text=%s age_ms=%s",
                line_user_id,
                text,
                int((time.time() - existing["started_at"]) * 1000),
            )
            ack = "⏳ 這個 E3 指令已在處理中，請稍等一下，我完成後會直接推播結果。"
        else:
            logger.info("e3_background_queued user=%s text=%s", line_user_id, text)
            ack = build_processing_ack(text)
        if reply_token:
            send_line_response(
                reply_token,
                line_user_id,
                ack,
                logger,
                quick_reply_items=e3_quick_reply_items(),
            )
        else:
            logger.warning("skip_reply reason=missing_reply_token message_type=text")
        if accepted:
            start_e3_background_task(
                text,
                line_user_id,
                logger,
                lambda user_id, payload: push_to_line(user_id, payload, logger),
            )
        return

    result = handle_e3_command(text, logger, line_user_id)
    if reply_token:
        send_line_response(
            reply_token,
            line_user_id,
            result,
            logger,
            quick_reply_items=e3_quick_reply_items(),
        )
    else:
        logger.warning("skip_reply reason=missing_reply_token message_type=text")


def _handle_homevault(reply_token, line_user_id):
    reply = (
        "支援指令：\n"
        "1) 天氣 台北\n"
        "2) 天氣\n"
        "3) e3 login <帳號> <密碼>\n"
        "4) e3 relogin\n"
        "5) e3 課程 / e3 course\n"
        "6) e3 近期 [作業/行事曆/考試]\n"
        "7) e3 timeline / e3 行事曆 [作業/行事曆/考試]\n"
        "8) e3 詳情 <編號>\n"
        "9) e3 grades / e3 成績\n"
        "10) e3 files <課名關鍵字>\n"
        "11) e3 remind show/on/off\n"
        "12) e3 幫助"
    )
    if reply_token:
        send_line_response(
            reply_token,
            line_user_id,
            reply,
            logger,
            quick_reply_items=e3_quick_reply_items(),
        )
    else:
        logger.warning("skip_reply reason=missing_reply_token message_type=text")


@app.route("/callback", methods=["POST"])
def callback():
    if not verify_signature(request, logger):
        return "Unauthorized", 401

    data = request.get_json(silent=True) or {}
    events = data.get("events")
    if not isinstance(events, list):
        logger.warning("invalid_callback_payload reason=missing_events_field")
        return "Bad Request", 400

    for event in events:
        if not isinstance(event, dict):
            logger.warning("invalid_event_payload reason=event_not_dict")
            continue

        if event.get("type") != "message":
            continue

        reply_token = event.get("replyToken")
        source = event.get("source", {})
        line_user_id = source.get("userId") if isinstance(source, dict) else None
        message = event.get("message", {})
        if not isinstance(message, dict):
            logger.warning("invalid_message_payload reason=message_not_dict")
            continue

        message_type = message.get("type")
        if message_type == "text":
            text = (message.get("text") or "").strip()
            logger.info("line_text_received user=%s text=%s", line_user_id, text)

            if text.startswith("天氣"):
                _handle_weather_text(text, reply_token, line_user_id)
            elif text.lower().startswith("e3"):
                _handle_e3_text(text, reply_token, line_user_id)
            elif text.lower() == "homevault":
                _handle_homevault(reply_token, line_user_id)
            else:
                logger.info("ignore_message reason=unknown_text text=%s", text)
            continue

        if message_type == "location":
            latitude = message.get("latitude")
            longitude = message.get("longitude")
            if latitude is None or longitude is None:
                logger.warning("invalid_location_payload reason=missing_coordinates")
                continue
            reply = handle_location_weather((latitude, longitude), logger)
            if reply_token:
                send_line_response(reply_token, line_user_id, reply, logger)
            else:
                logger.warning("skip_reply reason=missing_reply_token message_type=location")

    return "OK"


def _should_start_background_worker():
    if not auto_reload_enabled():
        return True
    import os

    return os.getenv("WERKZEUG_RUN_MAIN") == "true"


if _should_start_background_worker():
    start_reminder_worker(lambda user_id, payload: push_to_line(user_id, payload, logger), logger)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port(), threaded=True, use_reloader=auto_reload_enabled())
