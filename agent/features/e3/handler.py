import base64
import json
import re
from datetime import datetime, timedelta, timezone

from .client import check_status, fetch_courses, fetch_file_links, fetch_timeline_snapshot, login_and_sync, make_user_key
from .client import clear_runtime_data
from .db import (
    delete_user_data,
    ensure_reminder_prefs,
    get_e3_account_by_user_id,
    get_grade_items,
    get_reminder_prefs,
    get_timeline_event_details,
    get_timeline_events,
    get_upcoming_events,
    init_db,
    upsert_grade_item,
    update_reminder_enabled,
    update_login_state,
    upsert_e3_account,
    upsert_event,
    upsert_user,
)
from .events import extract_events_from_fetch_all


ASYNC_ACTIONS = {"login", "relogin", "重新登入"}
EVENT_TYPE_ALIASES = {
    "作業": "homework",
    "homework": "homework",
    "hw": "homework",
    "行事曆": "calendar",
    "calendar": "calendar",
    "考試": "exam",
    "exam": "exam",
}


def _encode_secret(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _decode_secret(token):
    return base64.b64decode(token.encode("ascii")).decode("utf-8")


def _format_e3_error(exc):
    message = str(exc).strip()
    lowered = message.lower()
    if "exceeded 30 redirects" in lowered:
        return (
            "⚠️ E3 登入失敗：登入流程發生過多重新導向。\n"
            "這通常不是單純帳密錯誤，比較像 E3/SSO 暫時異常、cookie 被拒絕，或登入頁流程已改變。"
        )
    if "timeout" in lowered:
        return "⏱️ E3 登入失敗：登入頁回應逾時，請稍後再試。"
    return "⚠️ E3 登入失敗，請確認帳密、ChromeDriver 或 Selenium 環境。"


def _parse_e3_action(text):
    command = text.strip()
    parts = command.split(maxsplit=1)
    raw_action = parts[1].strip() if len(parts) > 1 else ""
    tokens = raw_action.split()
    verb = tokens[0].lower() if tokens else ""
    return raw_action, verb, tokens


def handle_e3_command(text, logger, line_user_id=None):
    init_db()

    action, verb, tokens = _parse_e3_action(text)
    action_head = tokens[0] if tokens else ""

    if not action or action.lower() in {"help", "幫助", "功能"}:
        return (
            "📘 E3 指令：\n"
            "1) e3 login <帳號> <密碼>\n"
            "2) e3 relogin\n"
            "3) e3 logout\n"
            "4) e3 課程 / e3 course\n"
            "5) e3 近期 [作業/行事曆/考試]\n"
            "6) e3 timeline / e3 行事曆 [作業/行事曆/考試]\n"
            "7) e3 詳情 <編號>\n"
            "8) e3 狀態\n"
            "9) e3 grades / e3 成績\n"
            "10) e3 files <課名關鍵字>\n"
            "11) e3 remind show/on/off\n"
            "說明：課程指令會顯示目前學期（例如 114上 / 114下）"
        )

    if action_head == "狀態" or verb == "status":
        return _check_e3_status(line_user_id)

    if action_head == "課程" or verb in {"course", "courses"}:
        return _list_courses(logger, line_user_id)

    if action_head == "成績" or verb in {"grade", "grades"}:
        return _list_grades(logger, line_user_id)

    if action_head == "檔案" or verb in {"file", "files", "materials"}:
        return _list_files(tokens, logger, line_user_id)

    if verb == "login":
        return _queue_async(action, line_user_id)

    if action in ASYNC_ACTIONS - {"login"} or verb == "relogin":
        return _queue_async(action, line_user_id)

    if action_head == "登出" or verb == "logout":
        return _logout(line_user_id)

    if verb == "remind" or action_head == "提醒":
        return _handle_remind(tokens, line_user_id)

    if action_head == "近期" or verb == "upcoming":
        return _upcoming(tokens, line_user_id)

    if action_head == "行事曆" or verb in {"timeline", "calendar"}:
        return _timeline(tokens, line_user_id, logger)

    if action.startswith("詳情") or verb in {"detail", "details"}:
        return _event_detail(action, tokens, line_user_id)

    return "❓ 不支援的 E3 指令，請輸入：e3 幫助"


def run_e3_async_command(text, logger, line_user_id=None):
    init_db()

    action, verb, tokens = _parse_e3_action(text)

    if verb == "login":
        return _login(action, logger, line_user_id)

    if action in {"重新登入"} or verb == "relogin":
        return _relogin(logger, line_user_id)

    return "沒有可執行的背景 E3 任務。"


def _queue_async(action, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    if action.startswith("login"):
        tokens = action.split()
        if len(tokens) < 3:
            return "用法：e3 login <帳號> <密碼>"
        return "⏳ E3 登入已開始，正在驗證帳號並讀取首頁內容。完成後會再推播結果給你。"

    row = get_e3_account_by_user_id(user_id)
    if not row:
        return "找不到已綁定帳號，請先 `e3 login <帳號> <密碼>`。"
    return "⏳ E3 重新登入已開始，完成後會再推播結果給你。"


def _check_e3_status(line_user_id):
    user_key = make_user_key(line_user_id) if line_user_id else None
    runtime_status = check_status(user_key=user_key)
    if not runtime_status["available"]:
        return f"⚠️ E3 狀態：不可用\n找不到 E3 專案：{runtime_status['e3_root']}"

    if not line_user_id:
        return "⚠️ E3 狀態：需要 LINE 使用者身分"

    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    account_row = get_e3_account_by_user_id(user_id)
    if not account_row:
        return "⚠️ E3 狀態：未綁定帳號\n請先輸入 `e3 login <帳號> <密碼>`。"

    login_status = account_row["login_status"] or "unknown"
    has_password = bool(account_row["encrypted_password"])
    has_cookie = bool(runtime_status.get("has_cookie"))
    has_courses = bool(runtime_status.get("has_courses"))
    has_home_html = bool(runtime_status.get("has_home_html"))
    user_name = runtime_status.get("user_name") or ""
    user_email = runtime_status.get("user_email") or ""
    last_error = account_row["last_error"] or ""
    reminder_prefs = get_reminder_prefs(user_id)
    reminder_enabled = bool(reminder_prefs["enabled"]) if reminder_prefs else False
    reminder_schedule = _default_reminder_schedule()

    if login_status == "ok" and has_password and (has_cookie or has_home_html or has_courses):
        headline = "🟢 E3 狀態：已登入"
    elif login_status == "error":
        headline = "⚠️ E3 狀態：登入異常"
    else:
        headline = "🟡 E3 狀態：已綁定，尚未就緒"

    lines = [headline]
    lines.append(f"帳號：{account_row['e3_account']}")
    lines.append(f"姓名：{user_name or '尚未取得'}")
    lines.append(f"Email：{user_email or '尚未取得'}")
    lines.append(f"密碼：{'已儲存' if has_password else '未儲存'}")
    lines.append(f"Cookie：{'可用' if has_cookie else '未找到'}")
    lines.append(f"課程快取：{'可用' if has_courses else '未找到'}")
    lines.append(f"提醒：{'開啟' if reminder_enabled else '關閉'}")
    lines.append(f"提醒時段：{', '.join(reminder_schedule) if reminder_schedule else '未設定'}")
    if last_error:
        lines.append(f"最近錯誤：{last_error}")
    if not (has_password and (has_cookie or has_home_html or has_courses)):
        lines.append("建議：輸入 `e3 relogin` 或重新 `e3 login <帳號> <密碼>`。")
    return "\n".join(lines)


def _list_courses(logger, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    try:
        data = fetch_courses(make_user_key(line_user_id))
    except Exception as exc:
        logger.error("e3_list_courses_failed error=%s", exc)
        return "E3 本地資料讀取失敗，請先 `e3 login <帳號> <密碼>` 或 `e3 relogin`。"

    if not isinstance(data, dict) or not data:
        return "目前沒有可用課程資料，請先 `e3 login <帳號> <密碼>`。"

    semester_tag = _current_semester_tag()
    current_courses = []
    for display_name, payload in data.items():
        if _extract_semester_tag(display_name) == semester_tag:
            current_courses.append((display_name, payload))

    if not current_courses:
        return f"目前找不到 {semester_tag} 學期課程，請先 `e3 relogin` 重新同步。"

    lines = [f"📚 你的 {semester_tag} 學期 E3 課程（前 10 筆）："]
    for idx, (display_name, payload) in enumerate(current_courses, start=1):
        course_id = ""
        if isinstance(payload, dict):
            course_id = payload.get("_course_id") or ""
        cleaned_name = _strip_semester_prefix(display_name)
        course_label = f"{course_id} {cleaned_name}".strip()
        lines.append(f"{idx}. {course_label}")
        if idx >= 10:
            break
    return "\n".join(lines)


def _is_meaningful_grade(score):
    text = str(score or "").strip()
    return bool(text) and text != "-"


def extract_grade_items(courses):
    items = []
    if not isinstance(courses, dict):
        return items

    for display_name, payload in courses.items():
        if not isinstance(payload, dict):
            continue
        grades = payload.get("grades") or {}
        if not isinstance(grades, dict):
            continue
        course_id = str(payload.get("_course_id") or "").strip()
        course_name = _course_name_for_display(display_name)
        for item_name, score in grades.items():
            if not _is_meaningful_grade(score):
                continue
            item_text = re.sub(r"\s+", " ", str(item_name or "").replace("\u000b", " ")).strip()
            score_text = re.sub(r"\s+", " ", str(score or "")).strip()
            if not item_text or not score_text:
                continue
            items.append(
                {
                    "course_id": course_id,
                    "course_name": course_name,
                    "item_name": item_text,
                    "score": score_text,
                }
            )
    return items


def sync_grade_items(user_id, courses):
    existing = {
        (row["course_id"], row["item_name"]): row["score"]
        for row in get_grade_items(user_id)
    }
    changes = []
    for item in extract_grade_items(courses):
        key = (item["course_id"], item["item_name"])
        old_score = existing.get(key)
        if old_score != item["score"]:
            change = dict(item)
            change["old_score"] = old_score
            changes.append(change)
        upsert_grade_item(
            user_id,
            item["course_id"],
            item["course_name"],
            item["item_name"],
            item["score"],
        )
    return changes


def _format_grade_change_summary(changes):
    if not changes:
        return ""
    lines = ["📊 新成績："]
    for idx, item in enumerate(changes[:5], start=1):
        course_name = _shorten_course_name(item["course_name"], max_len=24)
        if item.get("old_score"):
            lines.append(f"{idx}. {course_name}｜{item['item_name']}：{item['old_score']} -> {item['score']}")
        else:
            lines.append(f"{idx}. {course_name}｜{item['item_name']}：{item['score']}")
    if len(changes) > 5:
        lines.append(f"另有 {len(changes) - 5} 筆更新。")
    return "\n".join(lines)


def _list_grades(logger, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    try:
        data = fetch_courses(make_user_key(line_user_id))
    except Exception as exc:
        logger.error("e3_list_grades_failed error=%s", exc)
        return "E3 成績資料讀取失敗，請先 `e3 relogin`。"

    grade_items = extract_grade_items(data)
    if not grade_items:
        return "目前沒有可用成績資料。"

    lines = ["📊 E3 成績（前 12 筆）："]
    for idx, item in enumerate(grade_items[:12], start=1):
        lines.append(f"{idx}. {_shorten_course_name(item['course_name'], max_len=22)}")
        lines.append(f"   {item['item_name']}：{item['score']}")
    return "\n".join(lines)


def _matches_course_keyword(course_label, keyword):
    if not keyword:
        return True
    left = re.sub(r"\s+", "", str(course_label or "")).lower()
    right = re.sub(r"\s+", "", str(keyword or "")).lower()
    return right in left


def _filter_active_homework_rows(rows, courses):
    active_pairs = set()
    if isinstance(courses, dict):
        for display_name, payload in courses.items():
            if not isinstance(payload, dict):
                continue
            course_id = str(payload.get("_course_id") or "").strip()
            assignments = (payload.get("assignments") or {}).get("assignments") or []
            for item in assignments:
                if not isinstance(item, dict):
                    continue
                category = str(item.get("category") or "").strip().lower()
                submitted_files = item.get("submitted_files") or []
                if category not in {"in_progress", "upcoming"}:
                    continue
                if submitted_files:
                    continue
                title = re.sub(r"\s+", " ", str(item.get("title") or "").strip())
                if course_id and title:
                    active_pairs.add((course_id, title))

    if not active_pairs:
        return [row for row in rows if row["event_type"] != "homework"]

    filtered = []
    for row in rows:
        if row["event_type"] != "homework":
            filtered.append(row)
            continue
        title = re.sub(r"\s+", " ", str(row["title"] or "").strip())
        course_id = str(row["course_id"] or "").strip()
        if (course_id, title) in active_pairs:
            filtered.append(row)
    return filtered


def _list_files(tokens, logger, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    keyword = " ".join(tokens[1:]).strip() if len(tokens) >= 2 else ""
    if not keyword:
        return "用法：e3 files <課名關鍵字>"

    try:
        snapshot = fetch_file_links(make_user_key(line_user_id))
    except Exception as exc:
        logger.error("e3_list_files_failed error=%s", exc)
        return "E3 檔案資料讀取失敗，請先 `e3 relogin`。"

    courses = snapshot.get("courses") or {}
    file_links = snapshot.get("file_links") or {}
    semester_tag = _current_semester_tag()
    matches = []

    for display_name, payload in courses.items():
        if _extract_semester_tag(display_name) != semester_tag:
            continue
        course_id = str((payload or {}).get("_course_id") or "").strip()
        course_name = _course_name_for_display(display_name)
        searchable = f"{course_id} {course_name}"
        if not _matches_course_keyword(searchable, keyword):
            continue
        links = file_links.get(course_id) or {}
        handouts = list((links.get("handouts") or []))[:5]
        assignment_files = []
        for assignment_title, entry in (links.get("assignments") or {}).items():
            web_files = (entry or {}).get("web_files") or []
            if web_files:
                assignment_files.append((assignment_title, web_files[0]))
            if len(assignment_files) >= 3:
                break
        matches.append((course_id, course_name, handouts, assignment_files))

    if not matches:
        return f"找不到包含「{keyword}」的課程檔案，請先 `e3 relogin` 更新資料。"

    lines = ["📎 E3 課程檔案（前 2 門）："]
    for course_idx, (course_id, course_name, handouts, assignment_files) in enumerate(matches[:2], start=1):
        lines.append(f"{course_idx}. {course_id} {course_name}".strip())
        if handouts:
            lines.append("   講義：")
            for item in handouts[:3]:
                lines.append(f"   - {item.get('name')}")
                lines.append(f"     {item.get('url')}")
        if assignment_files:
            lines.append("   作業附件：")
            for assignment_title, item in assignment_files[:2]:
                lines.append(f"   - {assignment_title} / {item.get('name')}")
                lines.append(f"     {item.get('url')}")
        if not handouts and not assignment_files:
            lines.append("   目前沒有可用檔案連結。")
    return "\n".join(lines)


def _require_line_user(line_user_id):
    if not line_user_id:
        return None, "這個 E3 指令需要 LINE 使用者身分（請在 1:1 聊天中使用）。"
    user_id = upsert_user(line_user_id)
    return user_id, None


def _sync_events_for_user(user_id, courses, calendar_events=None):
    events = extract_events_from_fetch_all(courses, calendar_events=calendar_events)
    for event in events:
        upsert_event(
            user_id=user_id,
            event_uid=event["event_uid"],
            event_type=event["event_type"],
            course_id=event.get("course_id"),
            course_name=event.get("course_name"),
            title=event["title"],
            due_at=event["due_at"],
            payload_json=event["payload_json"],
        )
    return events


def _format_home_preview(preview):
    lines = []
    user_name = preview.get("user_name") or ""
    user_email = preview.get("user_email") or ""
    if user_name:
        lines.append(f"👤 姓名：{user_name}")
    if user_email:
        lines.append(f"📧 Email：{user_email}")
    if not lines:
        lines.append("👤 姓名：未取得")
        lines.append("📧 Email：未取得")
    return "\n".join(lines)


def _current_semester_tag(now=None):
    taipei_tz = timezone(timedelta(hours=8))
    now = now or datetime.now(taipei_tz)
    year = now.year
    month = now.month

    if month >= 9:
        roc_year = year - 1911
        term = "上"
    elif month == 1:
        roc_year = year - 1912
        term = "上"
    elif 2 <= month <= 6:
        roc_year = year - 1912
        term = "下"
    else:
        roc_year = year - 1911
        term = "上"

    return f"{roc_year}{term}"


def _extract_semester_tag(display_name):
    match = re.match(r"^(\d{2,3}[上下])", (display_name or "").strip())
    return match.group(1) if match else None


def _strip_semester_prefix(display_name):
    cleaned = re.sub(r"^\d{2,3}[上下]", "", (display_name or "").strip())
    cleaned = cleaned.replace("_", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _course_name_for_display(course_name):
    text = _strip_semester_prefix(course_name) if course_name else "-"
    matches = list(re.finditer(r"[\u4e00-\u9fff]", text))
    if matches:
        end = matches[-1].end()
        while end < len(text) and text[end] in ")）】] ":
            end += 1
        text = text[:end]
    text = re.sub(r"\s+", " ", text).strip(" -_|,")
    return text or "-"


def _shorten_course_name(course_name, max_len=28):
    text = _course_name_for_display(course_name)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _shorten_title(title, max_len=32):
    text = re.sub(r"\s+", " ", (title or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _format_due_at_for_display(value):
    if not value:
        return "N/A"

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)

    taipei_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=taipei_tz)
    else:
        dt = dt.astimezone(taipei_tz)
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return dt.strftime("%m/%d") + f" ({weekdays[dt.weekday()]}) " + dt.strftime("%H:%M")


def _format_event_type_label(event_type):
    mapping = {
        "calendar": "行事曆",
        "homework": "作業",
        "exam": "考試",
    }
    return mapping.get(event_type, event_type)


def _parse_event_type_filter(tokens):
    if len(tokens) < 2:
        return None, None

    raw_filter = tokens[1].strip().lower()
    event_type = EVENT_TYPE_ALIASES.get(raw_filter)
    if event_type:
        return event_type, None
    return None, "類型只支援：作業 / 行事曆 / 考試"


def _default_reminder_schedule():
    return ["09:00", "21:00"]


def _timeline_heading(event_type):
    section_emoji = {
        "exam": "🧪",
        "homework": "📝",
        "calendar": "🗓️",
    }.get(event_type, "📌")
    return f"{section_emoji} 【{_format_event_type_label(event_type)}】"


def _line_response(text, messages=None):
    payload = {"text": text}
    if messages:
        payload["messages"] = messages
    return payload


def _format_reminder_summary(enabled, schedule, timezone_name="Asia/Taipei"):
    return (
        "⏰ E3 提醒設定\n"
        f"狀態：{'開啟' if enabled else '關閉'}\n"
        f"時區：{timezone_name}\n"
        f"時段：{', '.join(schedule) if schedule else '未設定'}\n"
        "提醒時間固定為每天 09:00 與 21:00，可直接點按按鈕開關。"
    )


def _build_reminder_settings_flex(enabled, schedule, alt_text):
    status_text = "已開啟" if enabled else "已關閉"
    status_color = "#15803D" if enabled else "#B91C1C"
    bg_color = "#F0FDF4" if enabled else "#FEF2F2"
    schedule_text = " / ".join(schedule) if schedule else "尚未設定"

    def _button(label, text, style="secondary", color="#2563EB"):
        button = {
            "type": "button",
            "height": "sm",
            "style": style,
            "action": {
                "type": "message",
                "label": label,
                "text": text,
            },
        }
        if style == "primary":
            button["color"] = color
        return button

    return {
        "type": "flex",
        "altText": alt_text,
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#0F766E",
                "paddingAll": "14px",
                "contents": [
                    {
                        "type": "text",
                        "text": "提醒設定",
                        "color": "#FFFFFF",
                        "weight": "bold",
                        "size": "lg",
                    },
                    {
                        "type": "text",
                        "text": "每天固定時段自動推送近期事件",
                        "color": "#CCFBF1",
                        "size": "xs",
                        "margin": "sm",
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "backgroundColor": bg_color,
                        "cornerRadius": "12px",
                        "paddingAll": "12px",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"狀態｜{status_text}",
                                "weight": "bold",
                                "color": status_color,
                                "size": "sm",
                            },
                            {
                                "type": "text",
                                "text": "時區｜Asia/Taipei",
                                "size": "xs",
                                "color": "#475569",
                            },
                            {
                                "type": "text",
                                "text": f"時段｜{schedule_text}",
                                "size": "sm",
                                "wrap": True,
                                "color": "#0F172A",
                            },
                        ],
                    },
                    {
                        "type": "text",
                        "text": "快速切換",
                        "weight": "bold",
                        "size": "sm",
                        "color": "#334155",
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "contents": [
                            _button("開啟", "e3 remind on", style="primary", color="#15803D"),
                            _button("關閉", "e3 remind off", style="primary", color="#B91C1C"),
                        ],
                    },
                    {
                        "type": "text",
                        "text": "提醒時間",
                        "weight": "bold",
                        "size": "sm",
                        "color": "#334155",
                    },
                    {
                        "type": "text",
                        "text": "每天固定推送兩次：09:00、21:00",
                        "size": "sm",
                        "wrap": True,
                        "color": "#334155",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    _button("重新整理設定", "e3 remind show"),
                ],
            },
        },
    }


def _build_timeline_flex(rows, alt_text, hero_title, event_type=None):
    bubbles = []
    accent = {
        "exam": "#B22222",
        "homework": "#D97706",
        "calendar": "#2563EB",
    }.get(event_type, "#4B5563")
    for idx, row in rows[:10]:
        due_at = _format_due_at_for_display(row["due_at"])
        course_name = _course_name_for_display(row["course_name"] or row["course_id"] or "-")
        title = _shorten_title(row["title"], max_len=44)
        bubbles.append(
            {
                "type": "bubble",
                "size": "kilo",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": accent,
                    "paddingAll": "12px",
                    "contents": [
                        {
                            "type": "text",
                            "text": hero_title,
                            "color": "#FFFFFF",
                            "weight": "bold",
                            "size": "sm",
                        },
                        {
                            "type": "text",
                            "text": due_at,
                            "color": "#FFFFFF",
                            "size": "xs",
                            "margin": "sm",
                        },
                    ],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "text",
                            "text": course_name,
                            "weight": "bold",
                            "size": "md",
                            "wrap": True,
                        },
                        {
                            "type": "text",
                            "text": title,
                            "size": "sm",
                            "wrap": True,
                            "color": "#374151",
                        },
                        {
                            "type": "text",
                            "text": f"編號 #{idx}",
                            "size": "xs",
                            "color": "#6B7280",
                        },
                    ],
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "height": "sm",
                            "color": accent,
                            "action": {
                                "type": "message",
                                "label": "查看詳情",
                                "text": f"e3 詳情 {idx}",
                            },
                        }
                    ],
                },
            }
        )

    if not bubbles:
        return None

    return {
        "type": "flex",
        "altText": alt_text,
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


def _build_detail_flex(row, index, alt_text):
    payload = {}
    payload_json = row["payload_json"] or ""
    if payload_json:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            payload = {}

    action_buttons = [
        {
            "type": "button",
            "style": "primary",
            "height": "sm",
            "color": "#2563EB",
            "action": {
                "type": "message",
                "label": "回到時間軸",
                "text": "e3 timeline",
            },
        }
    ]
    if payload.get("url"):
        action_buttons.append(
            {
                "type": "button",
                "style": "link",
                "height": "sm",
                "action": {
                    "type": "uri",
                    "label": "開啟 E3",
                    "uri": payload["url"],
                },
            }
        )

    return {
        "type": "flex",
        "altText": alt_text,
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#2563EB",
                "paddingAll": "12px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"事件詳情 #{index}",
                        "color": "#FFFFFF",
                        "weight": "bold",
                        "size": "md",
                    }
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": _format_event_type_label(row["event_type"]), "size": "sm", "color": "#6B7280"},
                    {"type": "text", "text": _course_name_for_display(row["course_name"] or row["course_id"] or "-"), "weight": "bold", "wrap": True},
                    {"type": "text", "text": row["title"], "wrap": True, "size": "sm"},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": f"截止：{_format_due_at_full(row['due_at'])}", "size": "sm", "wrap": True},
                    {"type": "text", "text": f"顯示日期：{payload.get('date_label') or '-'}", "size": "sm", "wrap": True},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": action_buttons,
            },
        },
    }


def _format_due_at_full(value):
    if not value:
        return "N/A"

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)

    taipei_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=taipei_tz)
    else:
        dt = dt.astimezone(taipei_tz)
    return dt.strftime("%Y/%m/%d %H:%M")


def _extract_detail_index(action, tokens):
    if len(tokens) >= 2 and tokens[1].isdigit():
        return int(tokens[1])

    match = re.match(r"^詳情\s*(\d+)$", action.strip())
    if match:
        return int(match.group(1))
    return None


def _format_event_detail(row, index):
    payload = {}
    payload_json = row["payload_json"] or ""
    if payload_json:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            payload = {}

    lines = [f"🔎 事件詳情 #{index}"]
    lines.append(f"類型：{_format_event_type_label(row['event_type'])}")
    lines.append(f"課程：{_course_name_for_display(row['course_name'] or row['course_id'] or '-')}")
    lines.append(f"標題：{row['title']}")
    lines.append(f"截止：{_format_due_at_full(row['due_at'])}")

    date_label = payload.get("date_label")
    if date_label:
        lines.append(f"顯示日期：{date_label}")

    url = payload.get("url")
    if url:
        lines.append(f"連結：{url}")

    event_id = payload.get("event_id")
    if event_id:
        lines.append(f"事件 ID：{event_id}")

    return "\n".join(lines)


def _format_timeline(rows, header):
    lines = [header]
    ordered_groups = _build_timeline_display_groups(rows)
    for event_type, items in ordered_groups:
        if not items:
            continue
        lines.append(_timeline_heading(event_type))
        for idx, row in items:
            due_at = _format_due_at_for_display(row["due_at"])
            course_name = _shorten_course_name(row["course_name"] or row["course_id"] or "-")
            title = _shorten_title(row["title"])
            icon = "👉" if event_type == "homework" else "📍"
            lines.append(f"{idx}. {due_at} ｜{course_name}")
            lines.append(f"   {icon} {title}")
            lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _build_timeline_display_groups(rows):
    grouped_rows = {"exam": [], "homework": [], "calendar": []}
    for row in rows:
        grouped_rows.setdefault(row["event_type"], []).append(row)

    section_order = ["exam", "homework", "calendar"]
    ordered = []
    display_index = 1
    for event_type in section_order:
        items = grouped_rows.get(event_type) or []
        section_items = []
        for row in items:
            section_items.append((display_index, row))
            display_index += 1
        ordered.append((event_type, section_items))
    return ordered


def _filter_rows_by_event_type(rows, event_type):
    if not event_type:
        return rows
    return [row for row in rows if row["event_type"] == event_type]


def _build_timeline_messages(rows, header, event_type=None):
    filtered_rows = _filter_rows_by_event_type(rows, event_type)
    if not filtered_rows:
        return None, []

    ordered_groups = _build_timeline_display_groups(filtered_rows)
    text_sections = []
    messages = []
    for group_event_type, items in ordered_groups:
        if not items:
            continue
        if not text_sections:
            section_lines = [header, _timeline_heading(group_event_type)]
        else:
            section_lines = [_timeline_heading(group_event_type)]
        for idx, row in items:
            due_at = _format_due_at_for_display(row["due_at"])
            course_name = _shorten_course_name(row["course_name"] or row["course_id"] or "-")
            title = _shorten_title(row["title"])
            icon = "👉" if group_event_type == "homework" else "📍"
            section_lines.append(f"{idx}. {due_at} ｜{course_name}")
            section_lines.append(f"   {icon} {title}")
            section_lines.append("")
        if section_lines[-1] == "":
            section_lines.pop()
        section_text = "\n".join(section_lines)
        text_sections.append(section_text)
        flex = _build_timeline_flex(items, section_text, _timeline_heading(group_event_type), event_type=group_event_type)
        if flex:
            messages.append(flex)

    return "\n\n".join(text_sections), messages


def _event_detail(action, tokens, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    index = _extract_detail_index(action, tokens)
    if index is None or index <= 0:
        return "用法：e3 詳情 <編號>"

    rows = get_timeline_event_details(user_id, limit=50)
    display_rows = []
    for _, items in _build_timeline_display_groups(rows):
        display_rows.extend(items)

    row = None
    for display_index, candidate in display_rows:
        if display_index == index:
            row = candidate
            break

    if row is None:
        return f"找不到第 {index} 筆事件，請先輸入 `e3 近期` 或 `e3 timeline` 確認編號。"

    text = _format_event_detail(row, index)
    flex = _build_detail_flex(row, index, text)
    return _line_response(text, messages=[flex] if flex else None)


def _handle_remind(tokens, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    prefs = ensure_reminder_prefs(user_id)
    subcommand = tokens[1].lower() if len(tokens) >= 2 else "show"

    if subcommand in {"show", "狀態"}:
        schedule = _default_reminder_schedule()
        text = _format_reminder_summary(bool(prefs["enabled"]), schedule, prefs["timezone"])
        flex = _build_reminder_settings_flex(bool(prefs["enabled"]), schedule, text)
        return _line_response(text, messages=[flex] if flex else None)

    if subcommand in {"on", "開啟"}:
        update_reminder_enabled(user_id, True)
        prefs = get_reminder_prefs(user_id)
        schedule = _default_reminder_schedule()
        text = "✅ 已開啟 E3 自動提醒。\n\n" + _format_reminder_summary(True, schedule, prefs["timezone"])
        flex = _build_reminder_settings_flex(True, schedule, text)
        return _line_response(text, messages=[flex] if flex else None)

    if subcommand in {"off", "關閉"}:
        update_reminder_enabled(user_id, False)
        prefs = get_reminder_prefs(user_id)
        schedule = _default_reminder_schedule()
        text = "🛑 已關閉 E3 自動提醒。\n\n" + _format_reminder_summary(False, schedule, prefs["timezone"])
        flex = _build_reminder_settings_flex(False, schedule, text)
        return _line_response(text, messages=[flex] if flex else None)

    return "⚠️ 用法：`e3 remind show`、`e3 remind on`、`e3 remind off`"


def _login(action, logger, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    tokens = action.split()
    if len(tokens) < 3:
        return "用法：e3 login <帳號> <密碼>"

    account = tokens[1].strip()
    password = tokens[2].strip()

    try:
        result = login_and_sync(account, password, make_user_key(line_user_id), update_data=True, update_links=True)
        courses = result["courses"]
        calendar_events = result.get("calendar_events") or []
        preview = result["home_preview"]
        events = _sync_events_for_user(user_id, courses, calendar_events=calendar_events)
        grade_changes = sync_grade_items(user_id, courses)
        upsert_e3_account(user_id, account, _encode_secret(password), status="ok", error=None)
        reply = (
            "✅ E3 登入成功。\n"
            f"已同步課程：{len(courses)} 門，時間軸事件：{len(events)} 筆。\n"
            f"{_format_home_preview(preview)}"
        )
        grade_summary = _format_grade_change_summary(grade_changes)
        if grade_summary:
            reply += "\n" + grade_summary
        return reply
    except Exception as exc:
        logger.error("e3_login_failed error=%s", exc)
        upsert_e3_account(user_id, account, _encode_secret(password), status="error", error=str(exc))
        return _format_e3_error(exc)


def _relogin(logger, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    row = get_e3_account_by_user_id(user_id)
    if not row:
        return "找不到已綁定帳號，請先 `e3 login <帳號> <密碼>`。"

    account = row["e3_account"]
    encrypted_password = row["encrypted_password"]
    if not encrypted_password:
        return "找不到已儲存密碼，請重新執行 `e3 login <帳號> <密碼>`。"

    try:
        password = _decode_secret(encrypted_password)
        result = login_and_sync(account, password, make_user_key(line_user_id), update_data=True, update_links=True)
        courses = result["courses"]
        calendar_events = result.get("calendar_events") or []
        preview = result["home_preview"]
        events = _sync_events_for_user(user_id, courses, calendar_events=calendar_events)
        grade_changes = sync_grade_items(user_id, courses)
        update_login_state(user_id, "ok", None)
        reply = (
            "✅ E3 重新登入成功。\n"
            f"已同步課程：{len(courses)} 門，時間軸事件：{len(events)} 筆。\n"
            f"{_format_home_preview(preview)}"
        )
        grade_summary = _format_grade_change_summary(grade_changes)
        if grade_summary:
            reply += "\n" + grade_summary
        return reply
    except Exception as exc:
        logger.error("e3_relogin_failed error=%s", exc)
        update_login_state(user_id, "error", str(exc))
        if "Exceeded 30 redirects" in str(exc):
            return _format_e3_error(exc)
        return "E3 重新登入失敗，請重新輸入 `e3 login <帳號> <密碼>`。"


def _logout(line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    delete_user_data(user_id)
    clear_runtime_data(make_user_key(line_user_id))
    return "🧹 E3 已登出，並清除本地綁定、事件快取與登入工作目錄。"


def _upcoming(tokens, line_user_id):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    event_type, filter_error = _parse_event_type_filter(tokens)
    if filter_error:
        return f"⚠️ {filter_error}"

    rows = get_upcoming_events(user_id, limit=10)
    if not rows:
        return "目前沒有近期事件，請先 `e3 login` 或 `e3 relogin` 進行同步。"
    if event_type == "homework":
        try:
            courses = fetch_courses(make_user_key(line_user_id))
        except Exception:
            courses = {}
        rows = _filter_active_homework_rows(rows, courses)
        if not rows:
            return "目前沒有未繳且尚未過期的作業。"
    text, messages = _build_timeline_messages(rows, "⏰ 近期提醒（前 10 筆）：", event_type=event_type)
    if not text:
        return "目前沒有符合條件的近期事件。"
    return _line_response(text, messages=messages or None)


def _timeline(tokens, line_user_id, logger):
    user_id, err = _require_line_user(line_user_id)
    if err:
        return err

    event_type, filter_error = _parse_event_type_filter(tokens)
    if filter_error:
        return f"⚠️ {filter_error}"

    try:
        snapshot = fetch_timeline_snapshot(make_user_key(line_user_id))
    except Exception as exc:
        logger.error("e3_timeline_fetch_failed error=%s", exc)
        snapshot = None

    if snapshot:
        _sync_events_for_user(
            user_id,
            snapshot.get("courses") or {},
            calendar_events=snapshot.get("calendar_events") or [],
        )

    rows = get_timeline_events(user_id, limit=20)
    if not rows:
        return "目前沒有可用時間軸事件，請先 `e3 login` 或 `e3 relogin`。"
    text, messages = _build_timeline_messages(rows, "🗓️ E3 時間軸（前 20 筆）：", event_type=event_type)
    if not text:
        return "目前沒有符合條件的時間軸事件。"
    return _line_response(text, messages=messages or None)
