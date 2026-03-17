from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands


def _as_entries(planning_notes: Any) -> List[Dict[str, Any]]:
    if not isinstance(planning_notes, dict):
        return []
    entries = planning_notes.get("entries", [])
    return entries if isinstance(entries, list) else []


def _score_entry(entry: Dict[str, Any], q: str) -> int:
    """Very simple relevance score; higher is better."""
    if not q:
        return 0
    ql = q.lower()
    score = 0
    title = str(entry.get("title", "")).lower()
    content = str(entry.get("content", "")).lower()
    tags = entry.get("tags", [])
    tags_txt = " ".join([str(t).lower() for t in tags]) if isinstance(tags, list) else ""

    if ql in title:
        score += 10
    if ql in tags_txt:
        score += 6
    if ql in content:
        score += 4

    # bonus for multiple keyword hits (split by space)
    parts = [p for p in ql.split() if p]
    for p in parts:
        if p in title:
            score += 3
        if p in tags_txt:
            score += 2
        if p in content:
            score += 1
    return score


def _find_by_id(entries: List[Dict[str, Any]], query_id: str) -> Optional[Dict[str, Any]]:
    q = (query_id or "").strip().lower()
    if not q:
        return None

    # exact match first
    for e in entries:
        if str(e.get("id", "")).lower() == q:
            return e

    # prefix match
    for e in entries:
        if str(e.get("id", "")).lower().startswith(q):
            return e

    # fuzzy contains
    for e in entries:
        if q in str(e.get("id", "")).lower():
            return e

    return None


class NotesCog(commands.Cog):
    """Searchable planning / meeting notes stored in data/knowledge/planning_notes.json"""

    def __init__(self, bot: commands.Bot, *, get_knowledge):
        self.bot = bot
        self._get_knowledge = get_knowledge
        # Permission gating is handled centrally in bot_core.py (E-board + owner).


    @commands.command(name="notes", aliases=["planning_notes", "minutes_search"])
    async def notes_cmd(self, ctx: commands.Context, *, keywords: str = ""):
        """Search planning notes by keywords. If no keywords, list latest entries."""
        knowledge = self._get_knowledge() or {}
        planning = knowledge.get("planning_notes", {})
        entries = _as_entries(planning)

        if not entries:
            await ctx.send("⚠️ No planning notes found. (data/knowledge/planning_notes.json is missing or empty.)")
            return

        q = (keywords or "").strip()
        if not q:
            # list latest (sorted by date desc if present)
            def d(e):
                return str(e.get("date", "")) + " " + str(e.get("id", ""))
            entries_sorted = sorted(entries, key=d, reverse=True)[:6]

            embed = discord.Embed(
                title="🗒️ Planning Notes (latest)",
                description="Use `!notes <keywords>` to search or `!note <id>` to open one.",
                color=0x5865F2,
            )
            for e in entries_sorted:
                embed.add_field(
                    name=f"{e.get('date','')} — {e.get('title','(untitled)')}",
                    value=f"ID: `{e.get('id','')}`",
                    inline=False,
                )
            await ctx.send(embed=embed)
            return

        # search
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for e in entries:
            s = _score_entry(e, q)
            if s > 0:
                scored.append((s, e))
        scored.sort(key=lambda t: (t[0], str(t[1].get("date",""))), reverse=True)

        if not scored:
            await ctx.send(f"Nothing found in planning notes for: **{q}**")
            return

        embed = discord.Embed(
            title="🔎 Planning Notes Search",
            description=f"Query: **{q}**\nOpen one with `!note <id>`.",
            color=0x5865F2,
        )

        for s, e in scored[:5]:
            content = str(e.get("content", "")).strip().replace("\n", " ")
            if len(content) > 160:
                content = content[:157] + "..."
            embed.add_field(
                name=f"{e.get('date','')} — {e.get('title','(untitled)')}",
                value=f"ID: `{e.get('id','')}` • score: {s}\n{content}",
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.command(name="note", aliases=["minutes", "planning_note"])
    async def note_cmd(self, ctx: commands.Context, note_id: str):
        """Open a specific planning note entry by id."""
        knowledge = self._get_knowledge() or {}
        planning = knowledge.get("planning_notes", {})
        entries = _as_entries(planning)

        e = _find_by_id(entries, note_id)
        if not e:
            await ctx.send(f"Couldn't find a planning note with id like: **{note_id}**\nTry `!notes {note_id}`.")
            return

        title = str(e.get("title", "(untitled)"))
        date = str(e.get("date", ""))
        eid = str(e.get("id", ""))

        embed = discord.Embed(
            title=f"🗒️ {title}",
            description=f"Date: **{date}**\nID: `{eid}`",
            color=0x5865F2,
        )

        tags = e.get("tags", [])
        if isinstance(tags, list) and tags:
            embed.add_field(name="Tags", value=", ".join(str(t) for t in tags)[:1000], inline=False)

        people = e.get("people", [])
        if isinstance(people, list) and people:
            embed.add_field(name="People", value=", ".join(str(p) for p in people)[:1000], inline=False)

        resources = e.get("resources", [])
        if isinstance(resources, list) and resources:
            lines = []
            for r in resources[:6]:
                if isinstance(r, dict):
                    label = r.get("label") or "Resource"
                    ref = r.get("ref") or ""
                    lines.append(f"- {label}: {ref}")
            if lines:
                embed.add_field(name="Resources", value="\n".join(lines)[:1000], inline=False)

        content = str(e.get("content", "")).strip()
        if not content:
            content = "(no content)"
        # Discord embed field value max ~1024; description 4096. We'll put first chunk in a field, rest as messages.
        first = content[:1000]
        embed.add_field(name="Notes", value=first, inline=False)
        await ctx.send(embed=embed)

        remaining = content[1000:]
        # Send remaining in chunks
        while remaining:
            chunk = remaining[:1800]
            remaining = remaining[1800:]
            await ctx.send(chunk)

    @commands.command(name="cosplay", aliases=["cosplay_info", "event_info"])
    async def cosplay_cmd(self, ctx: commands.Context):
        """Shortcut: open event planning note (customize note key for your club)."""
        await self.note_cmd(ctx, "event-planning")


async def setup(bot: commands.Bot):
    get_knowledge = getattr(bot, "_pb_get_knowledge")
    await bot.add_cog(NotesCog(bot, get_knowledge=get_knowledge))
