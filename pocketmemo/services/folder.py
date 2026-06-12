"""Folder service — flat folders for organizing files and notes.

Folders have a ``kind`` ("file" or "note"). They only affect browsing in /files;
semantic recall always searches across everything regardless of folder.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from pocketmemo.database import SessionLocal
from pocketmemo.i18n import t
from pocketmemo.models import Folder, Note, StoredFile, User

logger = logging.getLogger(__name__)


async def create_folder(user: User, name: str, kind: str = "file") -> str:
    name = (name or "").strip()[:255]
    if not name:
        return t("folder_name_empty", user.language)
    async with SessionLocal() as session:
        session.add(Folder(user_id=user.id, name=name, kind=kind))
        await session.commit()
    logger.info("Created %s folder %r for user %s", kind, name, user.id)
    return t("folder_created", user.language, name=name)


async def get_folders(user: User, kind: str = "file") -> list[Folder]:
    async with SessionLocal() as session:
        stmt = (
            select(Folder)
            .where(Folder.user_id == user.id, Folder.kind == kind)
            .order_by(Folder.name)
        )
        return list((await session.execute(stmt)).scalars().all())


async def get_folder(user: User, folder_id: int) -> Folder | None:
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
            )
        ).scalar_one_or_none()


async def _folders_with_counts(
    user: User, kind: str, model
) -> tuple[list[tuple[Folder, int]], int]:
    async with SessionLocal() as session:
        folders = list(
            (
                await session.execute(
                    select(Folder)
                    .where(Folder.user_id == user.id, Folder.kind == kind)
                    .order_by(Folder.name)
                )
            ).scalars().all()
        )
        rows = (
            await session.execute(
                select(model.folder_id, func.count())
                .where(model.user_id == user.id)
                .group_by(model.folder_id)
            )
        ).all()
    counts = {fid: c for fid, c in rows}
    folder_counts = [(f, counts.get(f.id, 0)) for f in folders]
    uncategorized = counts.get(None, 0)
    return folder_counts, uncategorized


async def get_file_folders_with_counts(user: User):
    return await _folders_with_counts(user, "file", StoredFile)


async def get_note_folders_with_counts(user: User):
    return await _folders_with_counts(user, "note", Note)


async def get_files_in_folder(user: User, folder_id: int | None) -> list[StoredFile]:
    async with SessionLocal() as session:
        cond = (
            StoredFile.folder_id.is_(None)
            if folder_id is None
            else StoredFile.folder_id == folder_id
        )
        stmt = (
            select(StoredFile)
            .where(StoredFile.user_id == user.id, cond)
            .order_by(StoredFile.id.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def get_notes_in_folder(user: User, folder_id: int | None) -> list[Note]:
    async with SessionLocal() as session:
        cond = (
            Note.folder_id.is_(None) if folder_id is None else Note.folder_id == folder_id
        )
        stmt = (
            select(Note)
            .where(Note.user_id == user.id, cond)
            .order_by(Note.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def delete_folder(user: User, folder_id: int) -> str:
    async with SessionLocal() as session:
        folder = (
            await session.execute(
                select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
            )
        ).scalar_one_or_none()
        if folder is None:
            return t("folder_not_found", user.language, id=folder_id)
        name = folder.name
        await session.delete(folder)  # files/notes folder_id set NULL by the DB
        await session.commit()
    logger.info("Deleted folder %s for user %s", folder_id, user.id)
    return t("folder_deleted", user.language, name=name)


async def _move(user: User, model, item_id: int, folder_id: int | None, kind: str) -> str:
    lang = user.language
    async with SessionLocal() as session:
        item = (
            await session.execute(
                select(model).where(model.id == item_id, model.user_id == user.id)
            )
        ).scalar_one_or_none()
        if item is None:
            return t("file_not_found", lang, id=item_id)
        if folder_id is None:
            item.folder_id = None
            await session.commit()
            return t("folder_moved_uncat", lang)
        folder = (
            await session.execute(
                select(Folder).where(
                    Folder.id == folder_id, Folder.user_id == user.id, Folder.kind == kind
                )
            )
        ).scalar_one_or_none()
        if folder is None:
            return t("folder_not_found", lang, id=folder_id)
        item.folder_id = folder_id
        name = folder.name
        await session.commit()
    logger.info("Moved %s %s to folder %s (user %s)", kind, item_id, folder_id, user.id)
    return t("folder_moved", lang, name=name)


async def move_file(user: User, file_id: int, folder_id: int | None) -> str:
    return await _move(user, StoredFile, file_id, folder_id, "file")


async def move_note(user: User, note_id: int, folder_id: int | None) -> str:
    return await _move(user, Note, note_id, folder_id, "note")
