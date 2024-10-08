from . import config
from . import transcript
from . import ctfnote

import asyncio
import functools
import hashlib
import io
import logging
import typing
import os
import json

import discord                                                                  # type: ignore
import discord_slash                                                            # type: ignore
from discord_slash.utils.manage_commands import create_option, create_choice    # type: ignore
from discord_slash.model import SlashCommandOptionType                          # type: ignore
from discord.ext import tasks                                                   # type: ignore

import traceback

def require_role(minreq=None):
    if minreq is None:
        minreq = config.mgmt.player_role

    def decorator(f):
        @functools.wraps(f)
        async def wrapper(ctx: discord_slash.SlashContext, *args, **kw):
            if minreq not in [r.id for r in ctx.author.roles]:
                await ctx.send("Get lost!")
            else:
                return await f(ctx, *args, **kw)
        return wrapper
    return decorator

def setup():
    assert config.is_loaded

    # the warning about using commands.Bot instead of discord.Client is explained here:
    # https://stackoverflow.com/a/51235308/2550406
    # It is mostly about convenience: commands.Bot subclasses discord.Client and offers some features.
    # I am not changing this now, since I see no urgent reason to do so.
    bot = discord.Client(intents=discord.Intents.default())
    slash = discord_slash.SlashCommand(bot, sync_commands=True)
    log = logging.getLogger("bot")
    trans_mgr = transcript.TranscriptManager(bot)

    @bot.event
    async def on_ready():
        guild = bot.get_guild(config.bot.guild)

        log.info(discord.utils.oauth_url(
            config.bot.client_id,
            guild=guild,
            scopes=["bot", "applications.commands"]
            ))
        
    status_dict = {"type": "jeopardy", "challs": {cat: {} for cat in config.mgmt.categories}}

    @tasks.loop(seconds=15)
    async def display_status():
        transcript_channel: discord.TextChannel = bot.get_channel(config.mgmt.transcript_channel)
        status_msg = "```ansi\n"
        for cat in config.mgmt.categories:
            status_msg += "-"*30+"-+"+"-"*50 + f"\n\u001b[1;37m{cat.upper(): <30} \u001b[0;37m|\n"
            for name, chall in status_dict["challs"][cat].items():
                if chall["solved"]:
                    status_msg += (f"{name: <{30}} | ✅\n")
                elif chall["assigned"]:
                    status_msg += (f"{name: <{30}} | {', '.join(chall['assigned']) or ''}\n")
                else:
                    status_msg += (f"{name: <{30}} | ❌\n")
                if status_dict["type"] == "AD":
                    for vuln_name, vuln in chall["vulns"].items():
                        status_msg += " "*10 + f"{vuln_name: <20} | patch: {'✅' if vuln['patch'] else '❌'} | exploit: {'✅' if vuln['exploit'] else '❌'}\n"
        status_msg += "-"*30+"-+"+"-"*50 + "\n```"
        try:
            message = await transcript_channel.fetch_message(transcript_channel.last_message_id)
            await message.edit(content=status_msg)
        except:
            await transcript_channel.send(status_msg)

    @slash.slash(name="start",
                description="Start ctf",
                guild_ids=[config.bot.guild],
                options=[
                    create_option(name="ctf_type",
                                    description="What kind of ctf",
                                    option_type=SlashCommandOptionType.STRING,
                                    required=True,
                                    choices={"Jeopardy": "Jeopardy", "AD": "AD"}
                                    )])
    @require_role(config.mgmt.player_role)
    async def start_ctf(ctx: discord_slash.SlashContext, ctf_type: str):
        status_dict["type"] = ctf_type
        status_dict["challs"] = {cat: {} for cat in config.mgmt.categories}
        try:
            transcript_channel: discord.TextChannel = bot.get_channel(config.mgmt.transcript_channel)
            message = await transcript_channel.fetch_message(transcript_channel.last_message_id)
            curr_cat = None
            curr_chal = None
            chal = None
            for line in message.content.split("\n"):
                if line.startswith("-") or line.startswith("`"): continue
                elif line.startswith("\u001b[1;37m"):
                    curr_cat = line.split()[0].lstrip("\u001b[1;37m").rstrip("\u001b[0;37m").lower()
                    curr_chal = None
                elif line.startswith(" "):
                    if status_dict["type"] == "AD":
                        vuln_name, patch, exploit = line.split("|")
                        chal["vulns"][vuln_name.strip()] = {"patch": "✅" in patch, "exploit": "✅" in exploit}
                else:
                    curr_chal, assigned = line.split("|")
                    curr_chal = curr_chal.strip()
                    chal = {"solved": False, "assigned": set(), "vulns": {}}
                    if "✅" in assigned: chal["solved"] = True
                    elif "❌" not in assigned:
                        chal["assigned"] = set(map(lambda x: x.strip(), assigned.strip().split(",")))
                    
                if curr_cat is not None and curr_chal is not None:
                    status_dict["challs"][curr_cat][curr_chal] = chal
        except Exception as e:
            log.error(f"Failed to load status from channel: {e}", exc_info=True)

        display_status.start()
        await ctx.send(f"CTF started, type: {ctf_type}")

    @slash.slash(name="vuln",
                description="Start ctf",
                guild_ids=[config.bot.guild],
                options=[
                    create_option(name="vuln_name",
                                    description="Name of the vuln",
                                    option_type=SlashCommandOptionType.STRING,
                                    required=True
                                    )])
    @require_role(config.mgmt.player_role)
    async def add_vuln(ctx: discord_slash.SlashContext, vuln_name: str):
        status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["vulns"][vuln_name] = {"patch": False, "exploit": False}
        await ctx.send(f"Added vuln: {vuln_name}")

    @slash.slash(name="patch",
                description="Mark a vuln as patched",
                guild_ids=[config.bot.guild],
                options=[
                    create_option(name="vuln_name",
                                    description="Name of the vuln",
                                    option_type=SlashCommandOptionType.STRING,
                                    required=True
                                    )])
    @require_role(config.mgmt.player_role)
    async def mark_patched(ctx: discord_slash.SlashContext, vuln_name: str):
        if vuln_name in status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["vulns"]:
            status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["vulns"][vuln_name]["patch"] = True
            await ctx.send(f"Marked vuln {vuln_name} as patched")
        else:
            await ctx.send(f"Vuln {vuln_name} not found. Currently marked vulns: {', '.join(status_dict['challs'][ctx.channel.category.name][ctx.channel.name]['vulns'].keys())}")
    
    @slash.slash(name="exploit",
                description="Mark a vuln as exploited",
                guild_ids=[config.bot.guild],
                options=[
                    create_option(name="vuln_name",
                                    description="Name of the vuln",
                                    option_type=SlashCommandOptionType.STRING,
                                    required=True
                                    )])
    @require_role(config.mgmt.player_role)
    async def mark_exploited(ctx: discord_slash.SlashContext, vuln_name: str):
        if vuln_name in status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["vulns"]:
            status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["vulns"][vuln_name]["exploit"] = True
            await ctx.send(f"Marked vuln {vuln_name} as exploited")
        else:
            await ctx.send(f"Vuln {vuln_name} not found. Currently marked vulns: {', '.join(status_dict['challs'][ctx.channel.category.name][ctx.channel.name]['vulns'].keys())}")

    @slash.slash(name="ping", description="Just a test, sleeps for 5 seconds then replies with 'pong'", guild_ids=[config.bot.guild])
    async def ping(ctx: discord_slash.SlashContext):
        await ctx.defer()
        await asyncio.sleep(5)
        await ctx.send("Pong!")

    @slash.slash(name="chal",
                 description="Create a new challenge channel",
                 guild_ids=[config.bot.guild],
                 options=[
                        create_option(name="category",
                                      description="Which category does the channel belong to",
                                      option_type=SlashCommandOptionType.STRING,
                                      required=True,
                                      choices=dict(zip(*[config.mgmt.categories]*2))
                                      ),
                        create_option(name="challenge",
                                      description="Challenge name",
                                      option_type=SlashCommandOptionType.STRING,
                                      required=True),
                        create_option(name="ctfid",
                                      description="The int id of the ctf in ctfnote. Can be found in the URL.",
                                      option_type=SlashCommandOptionType.INTEGER,
                                      required=False)
                     ])
    @require_role(config.mgmt.player_role)
    async def create_challenge_channel(ctx: discord_slash.SlashContext, 
            category: str, challenge: str, ctfid = None):
        cat = discord.utils.find(lambda c: c.name == category, ctx.guild.categories)
        created = await ctx.guild.create_text_channel(challenge, position=0, category=cat)
        status_dict["challs"][category][created.name] = {"solved": False, "assigned": set(), "vulns": {}}
        await ctx.send(f"The channel for <#{created.id}> ({category}) was created")
        await ctfnote.add_task(ctx, created, challenge, category, solved_prefix = "✓-", ctfid = ctfid)


    @slash.slash(name="ctfnote_fixup_channel",
                 description="Use this if you need to set/change the ctfnote id of the current channel after the channel creation.",
                 guild_ids=[config.bot.guild],
                 options=[
                        create_option(name="ctfid",
                                      description="The int id of the ctf in ctfnote. Can be found in the URL.",
                                      option_type=SlashCommandOptionType.INTEGER,
                                      required=False)
                     ])
    @require_role(config.mgmt.player_role)
    async def ctfnote_fixup_channel(ctx: discord_slash.SlashContext, ctfid = None):
        await ctfnote.fixup_task(ctx, solved_prefix = "✓-", ctfid = ctfid)

    @slash.slash(name="solved",
                 description="The challenge was solved",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="flag",
                                   description="The flag that was obtained",
                                   option_type=SlashCommandOptionType.STRING,
                                   required=True)
                     ]
                 )
    @require_role(config.mgmt.player_role)
    async def mark_solved(ctx: discord_slash.SlashContext, flag: typing.Optional[str] = None):
        await ctx.defer()
        if not ctx.channel.name.startswith("✓"):
            status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["solved"] = True
            await ctx.channel.edit(name=f"✓-{ctx.channel.name}", position=999)

        ctfnote_res = await ctfnote.update_flag(ctx, flag)

        if flag is not None:
            msg = await ctx.send(f"The flag: `{flag}`")
            await msg.pin()
        else:
            await ctx.send("removed flag.")

    @slash.slash(name="archive",
                 description="Move all current challenges to a new archive",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="name",
                                   description="The name for the archive",
                                   option_type=SlashCommandOptionType.STRING,
                                   required=True)
                     ]
                 )
    @require_role(config.mgmt.player_role)
    async def archive(ctx: discord_slash.SlashContext, name: str):
        if ctx.guild is None:
            return
        await ctx.defer()
        new_cat = await ctx.guild.create_category(f"Archive-{name}", position=999)
        for cat in ctx.guild.categories:
            if cat.name not in config.mgmt.categories:
                continue
            for chan in cat.text_channels:
                await chan.edit(category=new_cat)
        status_dict["challs"] = {cat: {} for cat in config.mgmt.categories}
        await display_status()
        display_status.cancel()
        await ctx.send(f"Archived {name}")

    @slash.slash(name="export",
                 description="Move the specified category to a nice new upstate farm.",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="category",
                                   description="Which category to move.",
                                   option_type=SlashCommandOptionType.CHANNEL,
                                   required=True)
                 ])
    @require_role(config.mgmt.player_role)
    async def export(ctx: discord_slash.SlashContext, category: discord.abc.GuildChannel):
        # hacky but idc
        # lucid: It seems this can be fixed by updating discordpy and discord_slash.
        if ctx.deferred or ctx.responded:
            log.info("not sure why but handler called twice, ignoring")
            return
        if not isinstance(category, discord.CategoryChannel):
            log.info("Tried exporting non category channel %s", category.name)
            await ctx.send("Can only export categories, not normal channels!")
            return
        log.info("Exporting %s", category.name, exc_info=True)
        await ctx.defer()
        await trans_mgr.create(category, ctx)
        # # TODO: Support specifying timezone?
        # if ctx.guild is None:
        #     return
        # log.info("Exporting %s", ctx.channel.name)
        # transcript = await chat_exporter.export(ctx.channel, limit)

        # if transcript is None:
        #     log.error("Failed to create transcript!")
        #     await ctx.send("Failed to export channel!")
        #     return
        # filename = f"transcript_{ctx.channel.name}.html"
        # transcript_file = discord.File(io.BytesIO(transcript.encode()),
        #                                 filename=filename)
        # transcript_channel: discord.TextChannel = bot.get_channel(config.mgmt.transcript_channel)
        # msg = await transcript_channel.send(f"Transcript for {ctx.channel.name}", file=transcript_file)
        # await ctx.send(f"Transcript created [here]({msg.jump_url})")

    @slash.slash(name="nuke",
                 description="Remove all channels in a given category, destructive. Use /export first!",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="category",
                                   description="Which category to nuke.",
                                   option_type=SlashCommandOptionType.CHANNEL,
                                   required=True),
                     create_option(name="confirm",
                                   description="Are you really sure? Did you /export it?",
                                   option_type=SlashCommandOptionType.STRING,
                                   required=False)
                     ])
    @require_role(config.mgmt.admin_role)
    async def nuke(ctx: discord_slash.SlashContext, category: discord.abc.GuildChannel, confirm: str = None):
        if not isinstance(category, discord.CategoryChannel):
            await ctx.send("That's not a category, buddy...", hidden=True)
            return
        reference = hashlib.sha256((category.name + str(category.position)).encode()).hexdigest()
        if reference != confirm:
            await ctx.send(f"Are you ***REALLY*** sure you performed the /export for {category.name}?? If so, use this as confirmation code: {reference}", hidden=True)
            return
        await ctx.defer()
        for chan in category.channels:
            await chan.delete(reason=f"Nuked by {ctx.author.name} with #{category.name}")
        await category.delete(reason=f"Nuked by {ctx.author.name}")
        await ctx.send(f"Category {category.name} was nuked on request of {ctx.author.name}", hidden=False)



    @slash.slash(name="ctfnote_update_auth",
                 description="Update url and auth login info for the ctfnote integration",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="url",
                                   description="The url ctfnote is hosted at",
                                   option_type=SlashCommandOptionType.STRING,
                                   required=True),
                     create_option(name="adminlogin",
                                   description="Admin login password",
                                   option_type=SlashCommandOptionType.STRING,
                                   required=True),
                     create_option(name="adminpass",
                                   description="Admin login password",
                                   option_type=SlashCommandOptionType.STRING,
                                   required=True)
                     ])
    @require_role(config.mgmt.player_role)
    async def ctfnote_update_auth(ctx: discord_slash.SlashContext, url:str, adminlogin:str, adminpass:str):
        await ctfnote.update_login_info(ctx, url, adminlogin, adminpass)

    @slash.slash(name="ctfnote_assign_lead",
                 description="Assign given player as challenge lead for this channel",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="playername",
                                   description="The player that becomes leader",
                                   option_type=SlashCommandOptionType.USER,
                                   required=True),
                 ])
    @require_role(config.mgmt.player_role)
    async def ctfnote_update_assigned_player(ctx: discord_slash.SlashContext, playername: discord.member.Member):
        await ctfnote.assign_player(ctx, playername)

    @slash.slash(name="assign",
                 description="Assign player as working on this challenge",
                 guild_ids=[config.bot.guild],
                 options=[
                    create_option(name="playername",
                        description="The player that is working on this challenge",
                        option_type=SlashCommandOptionType.USER,
                        required=True),
                 ])
    @require_role(config.mgmt.player_role)
    async def update_assigned_player(ctx: discord_slash.SlashContext, playername: discord.member.Member):
        status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["assigned"].add(playername.name)
        await ctx.send(f"{playername.name} is now working on this challenge")


    @slash.slash(name="unassign",
                 description="Unassign player as no longer working on this challenge",
                 guild_ids=[config.bot.guild],
                 options=[
                    create_option(name="playername",
                        description="The player that is no longer working on this challenge",
                        option_type=SlashCommandOptionType.USER,
                        required=True),
                 ])
    @require_role(config.mgmt.player_role)
    async def update_unassigned_player(ctx: discord_slash.SlashContext, playername: discord.member.Member):
        status_dict["challs"][ctx.channel.category.name][ctx.channel.name]["assigned"].discard(playername.name)
        await ctx.send(f"{playername.name} is no longer working on this challenge")

    @slash.slash(name="ctfnote_register_myself",
                 description="Register yourself a ctfnote account",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="password",
                                   description="Autogenerated if unspecified",
                                   option_type=SlashCommandOptionType.STRING,
                                   required=False),
                 ])
    @require_role(config.mgmt.player_role)
    async def ctfnote_register_myself(ctx: discord_slash.SlashContext, password: str = None):
        await ctfnote.register_themselves(ctx, password or None)

    @slash.slash(name="ctfnote_who_leads",
                 description="Ping who's the current leader of this challenge",
                 guild_ids=[config.bot.guild])
    @require_role(config.mgmt.player_role)
    async def ctfnote_leader(ctx: discord_slash.SlashContext):
        await ctfnote.whos_leader_of_this_shit(ctx)

    @slash.slash(name="ctfnote_import",
                 description="Create a new CTF in ctfnote by providing a ctftime event link or id.",
                 guild_ids=[config.bot.guild],
                 options=[
                     create_option(name="link",
                         description="Link or event id on ctftime",
                         option_type=SlashCommandOptionType.STRING,
                         required=True),
                     ])
    @require_role(config.mgmt.player_role)
    async def ctfnote_import_from_ctftime(ctx: discord_slash.SlashContext, link: str):
        await ctfnote.import_ctf_from_ctftime(ctx, link)

    @slash.slash(name="stats",
                 description="Display some useful stats about the server, such as number of channels",
                 guild_ids=[config.bot.guild])
    async def stats(ctx: discord_slash.SlashContext):
        log.info("Running Stats command")
        num_channels = len(ctx.guild.channels)
        num_cats = 0
        for chan in ctx.guild.channels:
            log.debug("Channel: %s", chan.name)
            chan: discord.abc.GuildChannel
            if isinstance(chan, discord.CategoryChannel):
                num_cats += 1
        
        await ctx.send(f"Channels: {num_channels}/500, {500 - num_channels} left\nCategories: {num_cats}")

    ## Keep this last :)
    return bot

def run(loop: asyncio.AbstractEventLoop):
    bot = setup()
    bot.loop = loop
    loop.create_task(bot.start(config.bot.token))
