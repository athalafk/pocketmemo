"""File service — store & retrieve user files via Telegram + pgvector search.

Files are saved to /app/storage/files/{telegram_id}/ (a persistent Docker
volume) along with their telegram_file_id for instant re-sending. Photos and
PDFs are described with vision so they can be found by their contents later.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from pocketmemo.database import SessionLocal
from pocketmemo.i18n import t
from pocketmemo.llm import llm
from pocketmemo.models import StoredFile, User

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path("/app/storage/files")

# Nearest candidates handed to the LLM matcher when recalling a file.
RECALL_CANDIDATES = 5
# Coarse pre-filter: drop candidates farther than this before asking the LLM.
RECALL_PREFILTER_MAX_DISTANCE = 0.9

FILE_MATCH_SYSTEM_PROMPT = (
    "You are a file matcher. Pick the ONE file from the list that best matches the "
    "user's request, or say none. Answer with ONLY a single number: the matching "
    "file's number, or 0 if none is truly relevant. No other text."
)

# Phrases (EN + ID) that mean "list all my files" rather than fetch one.
_LIST_QUERY_HINTS = (
    "what file", "what files", "which file", "all file", "all files", "my files",
    "list file", "list files", "show files", "files do i", "files i have",
    "apa saja", "apa aja", "semua file", "semua foto", "semua gambar", "daftar",
    "punya apa", "ada apa", "file apa", "gambar apa",
)


def _sanitize(name: str) -> str:
    """Strip unsafe characters from a filename for on-disk storage."""
    name = name.strip().replace("/", "_").replace("\\", "_")
    name = re.sub(r"[^\w.\- ]", "", name, flags=re.UNICODE)
    return name[:200] or "file"


def _parse_choice(raw: str, n: int) -> int | None:
    """Extract the chosen number from the LLM answer. Returns 1..n or None."""
    match = re.search(r"\d+", raw or "")
    if not match:
        return None
    idx = int(match.group())
    return idx if 1 <= idx <= n else None


def _is_list_query(query: str) -> bool:
    """Detect a "show all my files" request (vs. fetching one specific file)."""
    ql = query.lower()
    return any(hint in ql for hint in _LIST_QUERY_HINTS)


async def save_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User
) -> tuple[str, int]:
    """Download the message attachment, store it on disk + DB.

    Returns (reply_text, stored_file_id).
    """
    message = update.message
    caption = (message.caption or "").strip()

    if message.photo:
        tg_obj = message.photo[-1]
        file_id = tg_obj.file_id
        file_type = "photo"
        mime_type = "image/jpeg"
        original_name = f"photo_{tg_obj.file_unique_id}.jpg"
        file_size = getattr(tg_obj, "file_size", None)
    elif message.document:
        tg_obj = message.document
        file_id = tg_obj.file_id
        file_type = "document"
        mime_type = tg_obj.mime_type
        original_name = tg_obj.file_name or f"doc_{tg_obj.file_unique_id}"
        file_size = tg_obj.file_size
    else:
        return t("file_unsupported_media", user.language), 0

    user_dir = STORAGE_ROOT / str(user.telegram_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / f"{tg_obj.file_unique_id}_{_sanitize(original_name)}"

    tg_file = await context.bot.get_file(file_id)
    await tg_file.download_to_drive(custom_path=str(dest))

    if file_size is None:
        try:
            file_size = dest.stat().st_size
        except OSError:
            file_size = None

    # Vision: describe photos/PDFs for smarter naming & search.
    vision_desc = ""
    if file_type == "photo" or mime_type == "application/pdf":
        try:
            vision_desc = await llm.describe_media(dest.read_bytes(), mime_type or "image/jpeg")
        except Exception:
            logger.exception("Vision failed for %s", dest)

    if caption:
        display_name = caption
    elif vision_desc:
        display_name = vision_desc[:200]
    else:
        display_name = Path(original_name).stem or original_name

    description = vision_desc or caption or None
    embed_text = (
        " ".join(p for p in (caption, vision_desc, Path(original_name).stem) if p).strip()
        or display_name
    )
    embedding = await llm.embed(embed_text)

    async with SessionLocal() as session:
        stored = StoredFile(
            user_id=user.id,
            original_name=original_name,
            display_name=display_name,
            file_path=str(dest),
            telegram_file_id=file_id,
            file_type=file_type,
            mime_type=mime_type,
            file_size=file_size,
            description=description,
            embedding=embedding,
        )
        session.add(stored)
        await session.commit()
        await session.refresh(stored)
        file_id_db = stored.id

    logger.info("Saved file %r for user %s -> %s", display_name, user.id, dest)
    return t("file_saved", user.language, name=display_name), file_id_db


async def recall_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, query: str
) -> str | None:
    """Find the best-matching file and send it. Returns text if a reply is needed."""
    query = (query or "").strip()
    if not query:
        return t("file_recall_what", user.language)

    if _is_list_query(query):
        return await list_files_text(user)

    query_embedding = await llm.embed_query(query)
    async with SessionLocal() as session:
        dist = StoredFile.embedding.cosine_distance(query_embedding).label("dist")
        stmt = (
            select(StoredFile, dist)
            .where(StoredFile.user_id == user.id, StoredFile.embedding.is_not(None))
            .order_by(dist)
            .limit(RECALL_CANDIDATES)
        )
        rows = (await session.execute(stmt)).all()

    if not rows:
        return t("file_none", user.language)

    filtered = [
        stored
        for stored, distance in rows
        if distance is None or distance <= RECALL_PREFILTER_MAX_DISTANCE
    ]
    if not filtered:
        return t("file_recall_none", user.language, query=query)

    listing = "\n".join(f"{i}. {f.display_name}" for i, f in enumerate(filtered, start=1))
    prompt = (
        f"The user wants this file: \"{query}\".\n\n"
        f"Stored files:\n{listing}\n\n"
        "Which number matches best? Answer 0 if none is relevant."
    )
    raw = await llm.chat(prompt, system_prompt=FILE_MATCH_SYSTEM_PROMPT)
    choice = _parse_choice(raw, len(filtered))
    if choice is None:
        return t("file_recall_none", user.language, query=query)

    stored = filtered[choice - 1]
    chat_id = update.effective_chat.id
    caption = stored.display_name
    try:
        if stored.file_type == "photo":
            await context.bot.send_photo(chat_id, photo=stored.telegram_file_id, caption=caption)
        else:
            await context.bot.send_document(chat_id, document=stored.telegram_file_id, caption=caption)
    except Exception:
        logger.warning("Send via file_id failed, falling back to disk for file %s", stored.id)
        path = Path(stored.file_path)
        if not path.exists():
            return t("file_physical_missing", user.language)
        with path.open("rb") as fh:
            if stored.file_type == "photo":
                await context.bot.send_photo(chat_id, photo=fh, caption=caption)
            else:
                await context.bot.send_document(chat_id, document=fh, caption=caption)

    logger.info("Recalled file %s (%r) for user %s", stored.id, stored.display_name, user.id)
    return None


async def get_all_files(user: User) -> list[StoredFile]:
    """All of the user's files, newest first."""
    async with SessionLocal() as session:
        stmt = (
            select(StoredFile)
            .where(StoredFile.user_id == user.id)
            .order_by(StoredFile.id.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


def format_file_line(f: StoredFile) -> str:
    """One compact line for the file list."""
    icon = "🖼️" if f.file_type == "photo" else "📄"
    return f"#{f.id} {icon} {f.display_name}"


async def list_files_text(user: User) -> str:
    """All files as plain text."""
    files = await get_all_files(user)
    if not files:
        return t("file_none", user.language)
    lines = [t("file_list_header", user.language)]
    lines.extend(format_file_line(f) for f in files)
    lines.append("\n" + t("file_list_footer", user.language))
    return "\n".join(lines)


async def send_file_by_id(context, user: User, chat_id: int, file_id: int) -> str | None:
    """Send a stored file by id (used by the 👁️ View button). Returns text on failure."""
    async with SessionLocal() as session:
        f = (
            await session.execute(
                select(StoredFile).where(
                    StoredFile.id == file_id, StoredFile.user_id == user.id
                )
            )
        ).scalar_one_or_none()
    if f is None:
        return t("file_not_found", user.language, id=file_id)
    try:
        if f.file_type == "photo":
            await context.bot.send_photo(chat_id, photo=f.telegram_file_id, caption=f.display_name)
        else:
            await context.bot.send_document(chat_id, document=f.telegram_file_id, caption=f.display_name)
    except Exception:
        logger.warning("send_file_by_id via file_id failed, falling back to disk for %s", f.id)
        path = Path(f.file_path)
        if not path.exists():
            return t("file_physical_missing", user.language)
        with path.open("rb") as fh:
            if f.file_type == "photo":
                await context.bot.send_photo(chat_id, photo=fh, caption=f.display_name)
            else:
                await context.bot.send_document(chat_id, document=fh, caption=f.display_name)
    return None


async def delete_file(user: User, file_id: int) -> str:
    """Delete a file (DB row + the file on disk)."""
    async with SessionLocal() as session:
        f = (
            await session.execute(
                select(StoredFile).where(
                    StoredFile.id == file_id, StoredFile.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if f is None:
            return t("file_not_found", user.language, id=file_id)
        path = f.file_path
        name = f.display_name
        await session.delete(f)
        await session.commit()
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove physical file %s", path)
    logger.info("Deleted file %s for user %s", file_id, user.id)
    return t("file_deleted", user.language, name=name)
