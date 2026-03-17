from __future__ import annotations

import os
from typing import Optional

import discord
from discord.ext import commands


class OpsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, *, get_knowledge, get_config, get_db, knowledge_dir: str):
        self.bot = bot
        self._get_knowledge = get_knowledge
        self._get_config = get_config
        self._get_db = get_db
        self.knowledge_dir = knowledge_dir
        # Permission gating is handled centrally in bot_core.py (E-board + owner).


    @commands.command(name="channels", aliases=["channelids", "chanids", "chans"])
    async def channels_cmd(self, ctx: commands.Context):
        """Show configured channel IDs from config.json (E-board only)."""
        cfg = self._get_config() or {}
        text_map = cfg.get("channels", {}) if isinstance(cfg.get("channels", {}), dict) else {}
        bot_map = cfg.get("bot_channels", {}) if isinstance(cfg.get("bot_channels", {}), dict) else {}
        voice_map = cfg.get("voice_channels", {}) if isinstance(cfg.get("voice_channels", {}), dict) else {}

        def _fmt(mapping: dict) -> list[str]:
            out: list[str] = []
            for name, cid in mapping.items():
                try:
                    cid_int = int(cid)
                    out.append(f"• **{name}** → <#{cid_int}> (`{cid_int}`)")
                except Exception:
                    out.append(f"• **{name}** → `{cid}`")
            return out

        embed = discord.Embed(
            title="📌 PowerBot – Configured Channel IDs",
            description="Pulled from `data/config.json`.",
            color=0x2A9D8F,
        )

        def _add_chunked_fields(title: str, lines: list[str]):
            if not lines:
                return
            # Discord embed field value limit is 1024 chars
            chunk: list[str] = []
            size = 0
            part = 1
            for line in lines:
                if size + len(line) + 1 > 1000 and chunk:
                    embed.add_field(name=f"{title} ({part})", value="\n".join(chunk), inline=False)
                    chunk, size = [], 0
                    part += 1
                chunk.append(line)
                size += len(line) + 1
            if chunk:
                embed.add_field(name=f"{title} ({part})" if part > 1 else title, value="\n".join(chunk), inline=False)

        _add_chunked_fields("📝 Text Channels", _fmt(text_map))
        _add_chunked_fields("🤖 Bot/Game Channels", _fmt(bot_map))
        _add_chunked_fields("🔊 Voice Channels", _fmt(voice_map))

        default_log = cfg.get("default_log_channel_id")
        if default_log is not None:
            try:
                default_log_int = int(default_log)
                embed.set_footer(text=f"default-log = {default_log_int}")
            except Exception:
                pass

        await ctx.send(embed=embed)

    @commands.command(name="antispam", aliases=["spam", "spamguard"])
    async def antispam_cmd(self, ctx: commands.Context, mode: Optional[str] = None):
        """View or toggle anti-spam settings. Usage: !antispam [on|off|here|status]"""
        cfg = self._get_config() or {}
        save_cfg = getattr(self.bot, "_pb_save_config", None)

        m = (mode or "status").lower().strip()
        if m in {"on", "enable", "enabled"}:
            cfg["antispam_enabled"] = True
            if callable(save_cfg):
                save_cfg(cfg)
            await ctx.send("✅ Anti-spam is now **ON**.")
            return
        if m in {"off", "disable", "disabled"}:
            cfg["antispam_enabled"] = False
            if callable(save_cfg):
                save_cfg(cfg)
            await ctx.send("🛑 Anti-spam is now **OFF**.")
            return
        if m in {"here", "notifyhere", "sethere"}:
            cfg["antispam_notify_channel_id"] = str(ctx.channel.id)
            if callable(save_cfg):
                save_cfg(cfg)
            await ctx.send(f"✅ Anti-spam alerts will post in {ctx.channel.mention}.")
            return

        # Status view
        enabled = bool(cfg.get("antispam_enabled", True))
        notify_id = cfg.get("antispam_notify_channel_id") or cfg.get("default_log_channel_id")
        try:
            notify_int = int(notify_id) if notify_id is not None else None
        except Exception:
            notify_int = None

        window_seconds = int(cfg.get("antispam_window_seconds", 10))
        max_msgs = int(cfg.get("antispam_max_msgs_in_window", 7))
        dup_thr = int(cfg.get("antispam_duplicate_threshold", 2))
        links_window = int(cfg.get("antispam_links_window_seconds", 30))
        max_links = int(cfg.get("antispam_max_links_in_window", 3))
        cooldown = int(cfg.get("antispam_alert_cooldown_seconds", 120))
        action = str(cfg.get("antispam_action", "notify")).lower()
        exempt = cfg.get("antispam_exempt_channel_ids", [])
        exempt_n = len(exempt) if isinstance(exempt, list) else 0

        embed = discord.Embed(title="🛡️ PowerBot Anti-Spam Status", color=0x2A9D8F)
        embed.add_field(name="Enabled", value="✅ ON" if enabled else "🛑 OFF", inline=True)
        embed.add_field(
            name="Notify Channel",
            value=(f"<#{notify_int}> (`{notify_int}`)" if notify_int else "(not set)"),
            inline=False,
        )
        embed.add_field(
            name="Thresholds",
            value=(
                f"• Rate: {max_msgs} msgs / {window_seconds}s\n"
                f"• Duplicate: {dup_thr} repeats (>=40 chars)\n"
                f"• Links: {max_links} links / {links_window}s\n"
                f"• Alert cooldown: {cooldown}s\n"
                f"• Action: `{action}`"
            ),
            inline=False,
        )
        embed.add_field(name="Exempt Channels", value=f"{exempt_n} configured", inline=True)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    # bot_core injects these attributes after creating the bot
    get_knowledge = getattr(bot, "_pb_get_knowledge")
    get_config = getattr(bot, "_pb_get_config")
    get_db = getattr(bot, "_pb_get_db")
    knowledge_dir = getattr(bot, "_pb_knowledge_dir")
    await bot.add_cog(OpsCog(bot, get_knowledge=get_knowledge, get_config=get_config, get_db=get_db, knowledge_dir=knowledge_dir))
