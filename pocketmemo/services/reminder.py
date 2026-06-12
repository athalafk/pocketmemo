"""Reminder service — create, list, cancel, update, and deliver reminders.

Two kinds:
- one_time : fires once at a specific time ("meeting at 3pm tomorrow").
- routine  : repeats weekly (e.g. a class schedule), reminding ``lead_minutes``
             before the event time. Default lead is 30 minutes, configurable.

Times are stored timezone-aware (UTC). Natural-language parsing uses the LLM
with the user's local time as context.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone

import pytz
from sqlalchemy import or_, select

from pocketmemo.database import SessionLocal
from pocketmemo.i18n import t
from pocketmemo.llm import llm
from pocketmemo.models import Reminder, User

logger = logging.getLogger(__name__)

# Weekday names per language; index follows datetime.weekday() (Monday == 0).
WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "id": ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"],
}

DEFAULT_LEAD_MINUTES = 30

PARSE_SYSTEM_PROMPT = (
    "You are a reminder schedule parser. Convert the user's request into valid JSON:\n"
    "- kind: \"one_time\" or \"routine\"\n"
    "- message: short summary of what to be reminded (no time info, no URL)\n"
    "- datetime: ONE_TIME only, 'YYYY-MM-DD HH:MM' (24h, user local time)\n"
    "- days: ROUTINE only, array of weekday numbers (0=Monday,1=Tuesday,...,6=Sunday)\n"
    "- time: ROUTINE only, 'HH:MM' (event time, 24h)\n"
    "- lead_minutes: minutes before the event to remind. Default 30 for routine, "
    "0 for one_time. Convert phrases like '1 hour before' to minutes.\n"
    "- link: a URL the user mentions (e.g. a meeting link), otherwise null.\n"
    "- location: a place the user mentions (e.g. \"A's house\", \"room 301\"), otherwise null.\n"
    "Use the provided current time to resolve words like 'tomorrow' or 'next Monday'. "
    "IMPORTANT: for one_time, if the user gives NO specific time of day, set datetime "
    "to null (we will ask the user for the time). "
    "Output ONLY JSON."
)

UPDATE_SYSTEM_PROMPT = (
    "You help update a reminder. Given the active reminders and the user's change "
    "request, output JSON:\n"
    "- reminder_id: the id the user means (number), or 0 if none matches.\n"
    "- changes: an object with ONLY the fields to change:\n"
    "  - message: new description (string)\n"
    "  - link: new URL (string)\n"
    "  - location: new place (string)\n"
    "  - days: new weekday array (0=Monday..6=Sunday) for routine reminders\n"
    "  - time: new 'HH:MM' event time (routine)\n"
    "  - lead_minutes: minutes before the event\n"
    "  - datetime: 'YYYY-MM-DD HH:MM' for one-time reminders\n"
    "Include only fields the user actually wants changed. Output ONLY JSON."
)


def _user_tz(user: User) -> pytz.BaseTzInfo:
    try:
        return pytz.timezone(user.timezone or "Asia/Jakarta")
    except Exception:
        return pytz.timezone("Asia/Jakarta")


def _fmt_local(dt_utc: datetime, tz: pytz.BaseTzInfo) -> str:
    return dt_utc.astimezone(tz).strftime("%a, %d %b %Y %H:%M")


def _weekday_names(days: list[int], lang: str) -> str:
    names = WEEKDAYS.get(lang, WEEKDAYS["en"])
    return ", ".join(names[d] for d in days)


def _clean_link(link: str | None) -> str:
    link = (link or "").strip()
    return link if link.lower().startswith(("http://", "https://")) else ""


def _extra_lines(location: str | None, link: str) -> str:
    """Build the optional 📍 location / 🔗 link lines for a confirmation message."""
    out = ""
    if location:
        out += f"📍 {location}\n"
    if link:
        out += f"🔗 {link}\n"
    return out


def compute_next_occurrence(
    days: list[int],
    time_str: str,
    lead_minutes: int,
    tz: pytz.BaseTzInfo,
    after: datetime | None = None,
) -> datetime | None:
    """Next notification time (UTC) for a recurring schedule, or None if invalid."""
    after = after or datetime.now(timezone.utc)
    after_local = after.astimezone(tz)
    try:
        hh, mm = (int(x) for x in time_str.replace(".", ":").split(":")[:2])
    except (ValueError, AttributeError):
        return None

    for offset in range(0, 8):
        cand_date = (after_local + timedelta(days=offset)).date()
        if cand_date.weekday() not in days:
            continue
        event_local = tz.localize(datetime.combine(cand_date, time(hh, mm)))
        remind_local = event_local - timedelta(minutes=lead_minutes)
        if remind_local > after_local:
            return remind_local.astimezone(timezone.utc)
    return None


async def _parse_schedule(text: str, user: User) -> dict:
    tz = _user_tz(user)
    now_local = datetime.now(tz)
    weekday = WEEKDAYS["en"][now_local.weekday()]
    prompt = (
        f"Current time: {weekday}, {now_local:%Y-%m-%d %H:%M} (zone {user.timezone}).\n"
        f"User request: \"{text}\"\n"
        "Output the schedule JSON as instructed."
    )
    return await llm.complete_json(prompt, system_prompt=PARSE_SYSTEM_PROMPT)


async def create_reminder(user: User, text: str) -> tuple[str, int | None, bool]:
    """Parse the request and store a reminder.

    Returns (reply_text, reminder_id_or_None, needs_time). ``needs_time`` is True
    when a one-time reminder has no time of day yet and we should ask the user.
    """
    lang = user.language
    schedule = await _parse_schedule(text, user)
    if not schedule:
        return t("reminder_parse_fail", lang), None, False

    kind = schedule.get("kind")
    message = (schedule.get("message") or "").strip() or text.strip()
    link = _clean_link(schedule.get("link"))
    location = (schedule.get("location") or "").strip() or None
    extra = _extra_lines(location, link)
    tz = _user_tz(user)

    if kind == "routine":
        raw_days = schedule.get("days") or []
        days = sorted({int(d) for d in raw_days if str(d).isdigit() and 0 <= int(d) <= 6})
        time_str = schedule.get("time")
        lead = int(schedule.get("lead_minutes") or DEFAULT_LEAD_MINUTES)
        if not days or not time_str:
            return t("reminder_routine_incomplete", lang), None, False
        next_at = compute_next_occurrence(days, time_str, lead, tz)
        if next_at is None:
            return t("reminder_invalid", lang), None, False

        rule = json.dumps({"days": days, "time": time_str})
        async with SessionLocal() as session:
            rem = Reminder(
                user_id=user.id, message=message, remind_at=next_at,
                is_recurring=True, recurrence_rule=rule, lead_minutes=lead,
                link=link or None, location=location, is_sent=False,
            )
            session.add(rem)
            await session.commit()
            await session.refresh(rem)

        logger.info("Created routine reminder %s for user %s", rem.id, user.id)
        reply = t(
            "reminder_routine_created", lang, id=rem.id, message=message, extra=extra,
            days=_weekday_names(days, lang), time=time_str, lead=lead,
            next=_fmt_local(next_at, tz),
        )
        return reply, rem.id, False

    # one_time
    dt_str = schedule.get("datetime")
    lead = int(schedule.get("lead_minutes") or 0)
    if not dt_str:
        return t("reminder_ask_time", lang), None, True
    try:
        naive = datetime.strptime(str(dt_str).strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return t("reminder_ask_time", lang), None, True

    event_local = tz.localize(naive)
    remind_utc = (event_local - timedelta(minutes=lead)).astimezone(timezone.utc)
    if remind_utc <= datetime.now(timezone.utc):
        return t("reminder_onetime_past", lang, time=f"{event_local:%d %b %H:%M}"), None, False

    async with SessionLocal() as session:
        rem = Reminder(
            user_id=user.id, message=message, remind_at=remind_utc,
            is_recurring=False, recurrence_rule=None, lead_minutes=lead,
            link=link or None, location=location, is_sent=False,
        )
        session.add(rem)
        await session.commit()
        await session.refresh(rem)

    logger.info("Created one-time reminder %s for user %s", rem.id, user.id)
    lead_note = t("reminder_lead_note", lang, lead=lead) if lead else ""
    reply = t(
        "reminder_onetime_created", lang, id=rem.id, message=message, extra=extra,
        when=_fmt_local(remind_utc, tz), lead_note=lead_note,
    )
    return reply, rem.id, False


async def set_reminder_field(user: User, reminder_id: int, field: str, value: str) -> str:
    """Set the location or link on a reminder (used by the optional follow-up buttons)."""
    lang = user.language
    value = (value or "").strip()
    async with SessionLocal() as session:
        rem = (
            await session.execute(
                select(Reminder).where(
                    Reminder.id == reminder_id, Reminder.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if rem is None:
            return t("reminder_not_found", lang, id=reminder_id)
        if field == "location":
            rem.location = value
            label = t("change_location", lang)
        elif field == "link":
            if not value.lower().startswith(("http://", "https://")):
                return t("reminder_link_invalid", lang)
            rem.link = value
            label = t("change_link", lang)
        else:
            return t("action_unknown", lang)
        await session.commit()
    return t("reminder_field_set", lang, field=label)


async def get_active_reminders(user: User) -> list[Reminder]:
    """Active reminders (recurring + unsent one-time)."""
    async with SessionLocal() as session:
        stmt = (
            select(Reminder)
            .where(
                Reminder.user_id == user.id,
                or_(Reminder.is_recurring.is_(True), Reminder.is_sent.is_(False)),
            )
            .order_by(Reminder.remind_at)
        )
        return list((await session.execute(stmt)).scalars().all())


def format_reminder_line(rem: Reminder, user: User) -> str:
    """One compact line for /list."""
    lang = user.language
    tz = _user_tz(user)
    when = _fmt_local(rem.remind_at, tz)
    link = ""
    if rem.location:
        link += f" 📍 {rem.location}"
    if rem.link:
        link += f" 🔗 {rem.link}"
    if rem.is_recurring and rem.recurrence_rule:
        rule = json.loads(rem.recurrence_rule)
        return t(
            "reminder_line_routine",
            lang,
            id=rem.id,
            message=rem.message,
            days=_weekday_names(rule.get("days", []), lang),
            time=rule.get("time"),
            when=when,
            link=link,
        )
    return t(
        "reminder_line_onetime",
        lang,
        id=rem.id,
        message=rem.message,
        when=when,
        link=link,
    )


async def list_reminders(user: User) -> str:
    """Active reminders as plain text (fallback without inline keyboard)."""
    rows = await get_active_reminders(user)
    if not rows:
        return t("reminder_none", user.language)
    lines = [t("reminder_list_header", user.language)]
    lines.extend(format_reminder_line(r, user) for r in rows)
    lines.append("\n" + t("reminder_list_footer", user.language))
    return "\n".join(lines)


async def cancel_reminder(user: User, reminder_id: int) -> str:
    async with SessionLocal() as session:
        rem = (
            await session.execute(
                select(Reminder).where(
                    Reminder.id == reminder_id, Reminder.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if rem is None:
            return t("reminder_not_found", user.language, id=reminder_id)
        await session.delete(rem)
        await session.commit()
    logger.info("Cancelled reminder %s for user %s", reminder_id, user.id)
    return t("reminder_cancelled", user.language, id=reminder_id)


def _strip_link_lines(msg: str) -> str:
    return "\n".join(
        ln for ln in (msg or "").splitlines() if not ln.strip().startswith("🔗")
    ).strip()


def _describe_for_update(rem: Reminder) -> str:
    parts = [f"#{rem.id}", "routine" if rem.is_recurring else "one-time", f"message: {rem.message}"]
    if rem.is_recurring and rem.recurrence_rule:
        rule = json.loads(rem.recurrence_rule)
        days_txt = ",".join(WEEKDAYS["en"][d] for d in rule.get("days", []))
        parts.append(f"schedule: {days_txt} {rule.get('time')} lead {rem.lead_minutes}m")
    if rem.link:
        parts.append(f"link: {rem.link}")
    return " | ".join(parts)


async def _parse_update(text: str, user: User, reminders: list[Reminder]) -> dict:
    listing = "\n".join(_describe_for_update(r) for r in reminders)
    now_local = datetime.now(_user_tz(user))
    prompt = (
        f"Current time: {now_local:%Y-%m-%d %H:%M} (zone {user.timezone}).\n"
        f"Active reminders:\n{listing}\n\n"
        f"User request: \"{text}\"\n"
        "Output JSON {reminder_id, changes} as instructed."
    )
    return await llm.complete_json(prompt, system_prompt=UPDATE_SYSTEM_PROMPT)


def _apply_changes(rem: Reminder, changes: dict, user: User) -> list[str]:
    """Apply changes in-place. Returns translated labels of what changed."""
    lang = user.language
    applied: list[str] = []
    tz = _user_tz(user)

    new_msg = changes.get("message")
    if isinstance(new_msg, str) and new_msg.strip():
        rem.message = _strip_link_lines(new_msg) or new_msg.strip()
        applied.append(t("change_description", lang))

    if "link" in changes:
        link = (changes.get("link") or "").strip()
        if link.lower().startswith(("http://", "https://")):
            rem.link = link
            rem.message = _strip_link_lines(rem.message) or rem.message
            applied.append(t("change_link", lang))

    new_loc = changes.get("location")
    if isinstance(new_loc, str) and new_loc.strip():
        rem.location = new_loc.strip()
        applied.append(t("change_location", lang))

    if rem.is_recurring:
        rule = json.loads(rem.recurrence_rule or "{}")
        sched_changed = False
        if changes.get("days"):
            days = sorted({int(d) for d in changes["days"] if str(d).isdigit() and 0 <= int(d) <= 6})
            if days:
                rule["days"] = days
                sched_changed = True
                applied.append(t("change_days", lang))
        if changes.get("time"):
            rule["time"] = str(changes["time"]).replace(".", ":")
            sched_changed = True
            applied.append(t("change_time", lang))
        if changes.get("lead_minutes") is not None:
            rem.lead_minutes = int(changes["lead_minutes"])
            sched_changed = True
            applied.append(t("change_lead", lang))
        if sched_changed:
            rem.recurrence_rule = json.dumps({"days": rule.get("days", []), "time": rule.get("time")})
            nxt = compute_next_occurrence(rule.get("days", []), rule.get("time", ""), rem.lead_minutes, tz)
            if nxt is not None:
                rem.remind_at = nxt
                rem.is_sent = False
    else:
        if changes.get("datetime"):
            try:
                naive = datetime.strptime(str(changes["datetime"]).strip()[:16], "%Y-%m-%d %H:%M")
                if changes.get("lead_minutes") is not None:
                    rem.lead_minutes = int(changes["lead_minutes"])
                rem.remind_at = (
                    tz.localize(naive) - timedelta(minutes=rem.lead_minutes)
                ).astimezone(timezone.utc)
                rem.is_sent = False
                applied.append(t("change_time", lang))
            except ValueError:
                pass
        elif changes.get("lead_minutes") is not None:
            old_lead = rem.lead_minutes
            event = rem.remind_at + timedelta(minutes=old_lead)
            rem.lead_minutes = int(changes["lead_minutes"])
            rem.remind_at = event - timedelta(minutes=rem.lead_minutes)
            applied.append(t("change_lead", lang))

    return applied


async def _update_and_reply(user: User, reminder_id: int, changes: dict) -> str:
    async with SessionLocal() as session:
        rem = (
            await session.execute(
                select(Reminder).where(
                    Reminder.id == reminder_id, Reminder.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if rem is None:
            return t("reminder_not_found", user.language, id=reminder_id)
        applied = _apply_changes(rem, changes, user)
        if not applied:
            return t("reminder_update_nothing", user.language)
        await session.commit()
        await session.refresh(rem)

    logger.info("Updated reminder %s for user %s: %s", reminder_id, user.id, applied)
    return t(
        "reminder_updated",
        user.language,
        id=reminder_id,
        changes=", ".join(applied),
        line=format_reminder_line(rem, user),
    )


async def update_reminder_nl(user: User, text: str) -> str:
    reminders = await get_active_reminders(user)
    if not reminders:
        return t("reminder_update_none", user.language)
    parsed = await _parse_update(text, user, reminders)
    try:
        reminder_id = int(parsed.get("reminder_id") or 0)
    except (TypeError, ValueError):
        reminder_id = 0
    if reminder_id <= 0:
        return t("reminder_update_no_target", user.language)
    return await _update_and_reply(user, reminder_id, parsed.get("changes") or {})


async def update_reminder_by_id(user: User, reminder_id: int, text: str) -> str:
    async with SessionLocal() as session:
        rem = (
            await session.execute(
                select(Reminder).where(
                    Reminder.id == reminder_id, Reminder.user_id == user.id
                )
            )
        ).scalar_one_or_none()
    if rem is None:
        return t("reminder_not_found", user.language, id=reminder_id)
    parsed = await _parse_update(text, user, [rem])
    return await _update_and_reply(user, reminder_id, parsed.get("changes") or {})


async def send_due_reminders(bot) -> None:
    """Send all due reminders. Called by the poller every minute."""
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        stmt = (
            select(Reminder, User)
            .join(User, Reminder.user_id == User.id)
            .where(Reminder.is_sent.is_(False), Reminder.remind_at <= now)
        )
        rows = (await session.execute(stmt)).all()

        for rem, user in rows:
            lang = user.language
            tz = _user_tz(user)
            event_local = rem.remind_at + timedelta(minutes=rem.lead_minutes)
            body = t("reminder_notification", lang, message=rem.message)
            body += "\n" + t("reminder_notif_time", lang, time=_fmt_local(event_local, tz))
            if rem.location:
                body += f"\n📍 {rem.location}"
            if rem.link:
                body += f"\n🔗 {rem.link}"
            try:
                await bot.send_message(chat_id=user.telegram_id, text=body)
            except Exception:
                logger.exception("Failed to send reminder %s", rem.id)
                continue

            if rem.is_recurring and rem.recurrence_rule:
                rule = json.loads(rem.recurrence_rule)
                nxt = compute_next_occurrence(
                    rule.get("days", []), rule.get("time", ""), rem.lead_minutes, _user_tz(user), after=now
                )
                if nxt is not None:
                    rem.remind_at = nxt
                else:
                    rem.is_sent = True
            else:
                rem.is_sent = True

        if rows:
            await session.commit()
            logger.info("Dispatched %d due reminder(s)", len(rows))
