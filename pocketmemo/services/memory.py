"""Memory service — save and recall quick facts via pgvector semantic search."""

from __future__ import annotations

import logging

from sqlalchemy import select

from pocketmemo.database import SessionLocal
from pocketmemo.i18n import language_directive, t
from pocketmemo.llm import llm
from pocketmemo.models import Memory, User

logger = logging.getLogger(__name__)

# How many nearest facts to feed the LLM as context.
RECALL_TOP_K = 5

# Only consider superseding an existing fact if it is at least this similar.
SUPERSEDE_MAX_DISTANCE = 0.45

RECALL_SYSTEM_PROMPT = (
    "You are a personal assistant. Below are facts the user previously saved. "
    "Answer the user's question using ONLY those facts, concisely. If the facts "
    "do not contain the answer, say so honestly — do not make things up."
)

SUPERSEDE_SYSTEM_PROMPT = (
    "Decide whether a NEW fact UPDATES/REPLACES an OLD fact about the same subject "
    "(e.g. an updated parking spot, address, or status). Answer ONLY 'yes' or 'no'."
)


async def save_memory(user: User, content: str) -> str:
    """Embed and persist a quick fact, replacing an outdated one if it supersedes it."""
    lang = user.language
    content = (content or "").strip()
    if not content:
        return t("memory_empty", lang)

    embedding = await llm.embed(content)

    # Look at the single nearest existing fact; if it's very similar, ask the LLM
    # whether the new fact replaces it (so "parked at A28" updates "parked at B17").
    async with SessionLocal() as session:
        dist = Memory.embedding.cosine_distance(embedding).label("dist")
        row = (
            await session.execute(
                select(Memory, dist)
                .where(Memory.user_id == user.id, Memory.embedding.is_not(None))
                .order_by(dist)
                .limit(1)
            )
        ).first()

    if row is not None:
        nearest, distance = row
        if distance is not None and distance <= SUPERSEDE_MAX_DISTANCE:
            verdict = await llm.chat(
                f"OLD fact: {nearest.content}\nNEW fact: {content}\n"
                "Does the NEW fact replace the OLD one?",
                system_prompt=SUPERSEDE_SYSTEM_PROMPT,
            )
            if verdict.strip().lower().startswith("y"):
                async with SessionLocal() as session:
                    m = await session.get(Memory, nearest.id)
                    if m is not None:
                        old = m.content
                        m.content = content
                        m.embedding = embedding
                        await session.commit()
                        logger.info("Superseded memory %s for user %s", nearest.id, user.id)
                        return t("memory_updated", lang, old=old)

    async with SessionLocal() as session:
        session.add(
            Memory(user_id=user.id, content=content, embedding=embedding, source_type="text")
        )
        await session.commit()
    logger.info("Saved memory for user %s (%d chars)", user.id, len(content))
    return t("memory_saved", lang)


async def get_all_memories(user: User) -> list[Memory]:
    async with SessionLocal() as session:
        stmt = (
            select(Memory)
            .where(Memory.user_id == user.id)
            .order_by(Memory.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


def format_memory_line(m: Memory) -> str:
    text = m.content if len(m.content) <= 80 else m.content[:77] + "…"
    return f"#{m.id} {text}"


async def delete_memory(user: User, memory_id: int) -> str:
    async with SessionLocal() as session:
        m = (
            await session.execute(
                select(Memory).where(Memory.id == memory_id, Memory.user_id == user.id)
            )
        ).scalar_one_or_none()
        if m is None:
            return t("memory_not_found", user.language, id=memory_id)
        await session.delete(m)
        await session.commit()
    logger.info("Deleted memory %s for user %s", memory_id, user.id)
    return t("memory_deleted", user.language, id=memory_id)


async def recall_memory(user: User, query: str) -> str:
    """Semantically search the user's facts and answer naturally."""
    query = (query or "").strip()
    if not query:
        return t("memory_recall_what", user.language)

    query_embedding = await llm.embed_query(query)
    async with SessionLocal() as session:
        stmt = (
            select(Memory)
            .where(Memory.user_id == user.id, Memory.embedding.is_not(None))
            .order_by(Memory.embedding.cosine_distance(query_embedding))
            .limit(RECALL_TOP_K)
        )
        memories = (await session.execute(stmt)).scalars().all()

    if not memories:
        return t("memory_recall_none", user.language)

    context_block = "\n".join(f"- {m.content}" for m in memories)
    prompt = f"Saved facts:\n{context_block}\n\nUser question: {query}"
    system = f"{RECALL_SYSTEM_PROMPT} {language_directive(user.language)}"
    answer = await llm.chat(prompt, system_prompt=system)
    logger.info("Recalled %d memories for user %s", len(memories), user.id)
    return answer
