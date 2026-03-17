from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Dict, List, Optional, Tuple

import discord
from discord.ext import commands


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _normalize_day(day: str) -> Optional[str]:
    if not day:
        return None
    d = day.strip().lower()
    for canonical in DAYS:
        if canonical.lower().startswith(d):
            return canonical
    return None


def _normalize_name(name: str) -> str:
    return (name or "").strip().title()


def _parse_time(s: str) -> Optional[time]:
    """Parse times like '3:40 PM' or '3:40' safely."""
    if not isinstance(s, str) or not s.strip():
        return None
    txt = s.strip()

    # Accept '3:40' as 3:40 PM? Only if AM/PM missing, treat as 24h or assume PM? We'll default to 24h if >= 13.
    # Safer: if no AM/PM, treat as 24h if contains ':' and first part >= 0.
    m = re.match(r"^(\d{1,2}):(\d{2})(?:\s*([AaPp][Mm]))?$", txt)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    ap = m.group(3)
    if ap:
        ap = ap.upper()
        if hh == 12:
            hh = 0
        if ap == "PM":
            hh += 12
    return time(hour=hh % 24, minute=mm)


def _fmt_block(b: dict) -> str:
    return f"{b.get('start')}–{b.get('end')} • {b.get('kind')} • {b.get('title')}"


def _busy_blocks_for_day(person: dict, day: str) -> List[dict]:
    blocks = person.get("busy_blocks", []) if isinstance(person, dict) else []
    if not isinstance(blocks, list):
        return []
    out = [b for b in blocks if isinstance(b, dict) and (b.get("day") == day)]

    # Sort by start time if possible
    def _key(b: dict):
        t = _parse_time(str(b.get("start", "")))
        return (t.hour * 60 + t.minute) if t else 10**9

    out.sort(key=_key)
    return out


def _compute_free_windows(blocks: List[dict], *, day_start: time, day_end: time) -> List[Tuple[time, time]]:
    """Return free windows within [day_start, day_end)"""
    busy: List[Tuple[time, time]] = []
    for b in blocks:
        st = _parse_time(str(b.get("start", "")))
        en = _parse_time(str(b.get("end", "")))
        if not st or not en:
            continue
        busy.append((st, en))

    busy.sort(key=lambda x: (x[0].hour * 60 + x[0].minute))

    # Merge overlaps
    merged: List[Tuple[time, time]] = []
    for st, en in busy:
        if not merged:
            merged.append((st, en))
            continue
        last_st, last_en = merged[-1]
        if (st.hour, st.minute) <= (last_en.hour, last_en.minute):
            # overlap/contiguous
            if (en.hour, en.minute) > (last_en.hour, last_en.minute):
                merged[-1] = (last_st, en)
        else:
            merged.append((st, en))

    free: List[Tuple[time, time]] = []
    cur = day_start
    for st, en in merged:
        if (st.hour, st.minute) > (cur.hour, cur.minute):
            free.append((cur, st))
        if (en.hour, en.minute) > (cur.hour, cur.minute):
            cur = en
    if (day_end.hour, day_end.minute) > (cur.hour, cur.minute):
        free.append((cur, day_end))

    # Filter tiny windows (< 20 min)
    out: List[Tuple[time, time]] = []
    for st, en in free:
        mins = (en.hour * 60 + en.minute) - (st.hour * 60 + st.minute)
        if mins >= 20:
            out.append((st, en))
    return out


def _t12(t: time) -> str:
    # Windows-safe 12-hour formatting
    return datetime.combine(date.today(), t).strftime("%I:%M %p").lstrip("0")


class SchedulesCog(commands.Cog):
    def __init__(self, bot: commands.Bot, *, get_knowledge):
        self.bot = bot
        self._get_knowledge = get_knowledge
        # Permission gating is handled centrally in bot_core.py (E-board + owner).


    def _get_people(self) -> Dict[str, dict]:
        knowledge = self._get_knowledge() or {}
        sched = knowledge.get("schedules", {}) if isinstance(knowledge, dict) else {}
        people = sched.get("people", {}) if isinstance(sched, dict) else {}
        return people if isinstance(people, dict) else {}

    @commands.command(name="schedule", aliases=["sched", "times"])
    async def schedule_cmd(self, ctx: commands.Context, name: str, day: Optional[str] = None):
        """Show a person's schedule. Usage: !schedule <name> [day]"""
        people = self._get_people()
        person_name = _normalize_name(name)
        person = people.get(person_name)
        if not person:
            await ctx.send(f"I don't have a schedule saved for **{person_name}** yet.")
            return

        d = _normalize_day(day) if day else None

        embed = discord.Embed(
            title=f"🗓️ {person_name} – Schedule",
            description="Times are local (ET). Busy blocks include class, work, and other commitments.",
            color=0x2A9D8F,
        )

        if d:
            blocks = _busy_blocks_for_day(person, d)
            if not blocks:
                embed.add_field(name=d, value="No blocks saved.", inline=False)
            else:
                embed.add_field(name=d, value="\n".join(f"• {_fmt_block(b)}" for b in blocks)[:1000], inline=False)
        else:
            # Week summary
            for dd in DAYS:
                blocks = _busy_blocks_for_day(person, dd)
                if not blocks:
                    continue
                lines = [f"• {_fmt_block(b)}" for b in blocks]
                embed.add_field(name=dd, value="\n".join(lines)[:1000], inline=False)

            if len(embed.fields) == 0:
                embed.description = "No blocks saved."

        await ctx.send(embed=embed)

    @commands.command(name="free", aliases=["availability", "avail"])
    async def free_cmd(self, ctx: commands.Context, name: str, day: str):
        """Show free windows for a person on a day. Usage: !free <name> <day>"""
        people = self._get_people()
        person_name = _normalize_name(name)
        person = people.get(person_name)
        if not person:
            await ctx.send(f"I don't have a schedule saved for **{person_name}** yet.")
            return

        d = _normalize_day(day)
        if not d:
            await ctx.send("Pick a valid day: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.")
            return

        blocks = _busy_blocks_for_day(person, d)
        # Default "planning day" window: 9 AM to 9 PM
        free = _compute_free_windows(blocks, day_start=time(9, 0), day_end=time(21, 0))

        embed = discord.Embed(
            title=f"✅ {person_name} – Free windows ({d})",
            description="Computed from saved busy blocks. Window shown: 9:00 AM–9:00 PM (ET).",
            color=0x2A9D8F,
        )

        if not free:
            embed.add_field(name="Free", value="No 20+ minute free windows found in the 9–9 range.", inline=False)
        else:
            lines = [f"• {_t12(st)} – {_t12(en)}" for st, en in free]
            embed.add_field(name="Free", value="\n".join(lines)[:1000], inline=False)

        if blocks:
            lines = [f"• {_fmt_block(b)}" for b in blocks]
            embed.add_field(name="Busy blocks", value="\n".join(lines)[:1000], inline=False)

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    get_knowledge = getattr(bot, "_pb_get_knowledge")
    await bot.add_cog(SchedulesCog(bot, get_knowledge=get_knowledge))
