import json
import discord
from discord.ext import commands
import asyncio
import random
import os
from datetime import datetime
import pytz
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="?", intents=intents, help_command=None)

OWNER_ID = 739048881651712010
ACTIVATION_FILE = "activated_servers.json"

try:
    with open(ACTIVATION_FILE, "r") as f:
        activated_servers = json.load(f)
except:
    activated_servers = []

user_ephemeral_messages = {}
giveaway_entries = {}
giveaway_messages = {}
giveaway_winners = {}
rerolled_history = {}
giveaway_ended_embeds = {}

def parse_duration(duration_str):
    units = {"d": 86400, "hr": 3600, "min": 60}
    total_seconds = 0
    for part in duration_str.lower().split():
        for key in units:
            if part.endswith(key):
                value = int(part[:-len(key)])
                total_seconds += value * units[key]
                break
    if total_seconds <= 0:
        raise commands.BadArgument("Duration must be greater than 0.")
    return total_seconds

def format_time(seconds):
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}hr {m}min" if d else f"{h}hr {m}min" if h else f"{m}min" if m else "Less than a minute"

@bot.check
def is_activated(ctx):
    return str(ctx.guild.id) in activated_servers or ctx.command.name in ["activate"]

@bot.command()
@commands.is_owner()
async def activate(ctx):
    if str(ctx.guild.id) in activated_servers:
        return await ctx.send(embed=discord.Embed(description="**I am already activated, Owner.**", color=discord.Color.green()))
    activated_servers.append(str(ctx.guild.id))
    with open(ACTIVATION_FILE, "w") as f:
        json.dump(activated_servers, f)
    await ctx.send(embed=discord.Embed(description="**I am activated, Owner.**", color=discord.Color.green()))

@bot.command()
@commands.is_owner()
async def deactivate(ctx):
    if str(ctx.guild.id) not in activated_servers:
        return await ctx.send(embed=discord.Embed(description="Bot is not activated.", color=discord.Color.orange()))
    activated_servers.remove(str(ctx.guild.id))
    with open(ACTIVATION_FILE, "w") as f:
        json.dump(activated_servers, f)
    await ctx.send(embed=discord.Embed(description="**Bot deactivated, Owner.**", color=discord.Color.red()))

@bot.command()
@commands.has_permissions(administrator=True)
async def help(ctx):
    embed = discord.Embed(title="GIVEAWAY BOT COMMANDS", color=discord.Color.blurple())
    embed.add_field(name="#1  **?giveaway**", value="- Trigger giveaway setup. Fields included : Channel, Prize, Winners-count, Duration,  Host.  ", inline=False)
    embed.add_field(name="#2  **?giveawaycancel [message_id]**", value="- Cancel a giveaway.", inline=False)
    embed.add_field(name="#3  **?reroll <message_id> @winners**", value="- Reroll selected winners.", inline=False)
    embed.add_field(name="#4  **?exit**", value="- Exit giveaway setup.", inline=False)
    embed.set_footer(text="Admin-only commands.")
    await ctx.send(embed=embed)

def cleanup_ephemerals(giveaway_id, user_id):
    if giveaway_id in user_ephemeral_messages and user_id in user_ephemeral_messages[giveaway_id]:
        old = user_ephemeral_messages[giveaway_id][user_id]
        try:
            asyncio.create_task(old.delete())
        except:
            pass

@bot.command()
@commands.has_permissions(administrator=True)
async def giveaway(ctx):
    def check(m): return m.author == ctx.author and m.channel == ctx.channel

    steps = [
        ("#1 Mention the channel to host the giveaway", "channel"),
        ("#2 Prize-pool of the giveaway ?", lambda m: m.content),
        ("#3 No of winners?", "int"),
        ("#4 Duration of the giveaway? (Eg., 1d 2hr 30min)", "duration"),
        ("#5 Host? (mention/name)", lambda m: m.content)
    ]
    answers = []
    user_replies = []

    for question, parser in steps:
        while True:
            q_msg = await ctx.send(embed=discord.Embed(description=f"**{question}**", color=discord.Color.blurple()))
            try:
                response = await bot.wait_for("message", timeout=120.0, check=check)
            except asyncio.TimeoutError:
                await q_msg.delete()
                for m in user_replies:
                    try: await m.delete()
                    except: pass
                return await ctx.send(embed=discord.Embed(description=" Timed out. Giveaway setup canceled.", color=discord.Color.red()))

            content = response.content.strip().lower()
            if content in ("?exit", "?giveawaycancel"):
                await q_msg.delete()
                try: await response.delete()
                except: pass
                for m in user_replies:
                    try: await m.delete()
                    except: pass
                return await ctx.send(embed=discord.Embed(description=" Giveaway setup canceled.", color=discord.Color.red()), delete_after=1)

            try:
                if parser == "int":
                    value = int(response.content)
                elif parser == "duration":
                    value = parse_duration(response.content)
                elif parser == "channel":
                    value = response.channel_mentions[0] if response.channel_mentions else None
                    if not value:
                        await q_msg.delete()
                        await response.delete()
                        await ctx.send(embed=discord.Embed(description=" Please mention a valid channel.", color=discord.Color.red()), delete_after=3)
                        continue
                elif callable(parser):
                    value = parser(response)

                answers.append(value)
                await q_msg.delete()
                await response.delete()
                break
            except:
                await q_msg.delete()
                await response.delete()
                await ctx.send(embed=discord.Embed(description=" Invalid input. Try again.", color=discord.Color.red()), delete_after=3)

    channel, prize, winners, duration, host_tag = answers
    time_display = format_time(duration)
    emoji = "<a:rdxm:1392170883057057802>"
    arrow = "<:Screenshot20250709102722:1392369398727049237>"
    centered_title = f"{emoji} {prize} {emoji}"

    embed = discord.Embed(
        title=centered_title,
        description=f"{arrow} **Ends in:** {time_display}\n{arrow} **Winners:** {winners}\n{arrow} **Hosted by:** {host_tag}",
        color=discord.Color.dark_blue()
    )
    embed.set_footer(text="Click the button below to enter!")

    class GiveawayView(discord.ui.View):
        def __init__(self, duration):
            super().__init__(timeout=duration)
            self.entries = []
            self.msg_id = None
            self.entry_button = discord.ui.Button(label="🟢 0 Entries", style=discord.ButtonStyle.secondary, disabled=True)
            self.add_item(self.entry_button)

        @discord.ui.button(label="Enter/Exit", style=discord.ButtonStyle.primary, emoji=discord.PartialEmoji(name="partychristmas", animated=True, id=1392184654349467719))
        async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
            user = interaction.user
            msg = giveaway_messages.get(self.msg_id)
            if not msg or user.bot:
                return

            cleanup_ephemerals(self.msg_id, user.id)

            if user.id in self.entries:
                self.entries.remove(user.id)
                self.entry_button.label = f"🟢 {len(self.entries)} Entries"
                await msg.edit(view=self)
                await interaction.response.send_message(embed=discord.Embed(description="**You have opted out.**", color=discord.Color.red()), ephemeral=True)
                user_ephemeral_messages.setdefault(self.msg_id, {})[user.id] = await interaction.original_response()
                return

            self.entries.append(user.id)
            self.entry_button.label = f"🟢 {len(self.entries)} Entries"
            await msg.edit(view=self)
            await interaction.response.send_message(embed=discord.Embed(description="**You have entered!**", color=discord.Color.green()), ephemeral=True)
            user_ephemeral_messages.setdefault(self.msg_id, {})[user.id] = await interaction.original_response()

    view = GiveawayView(duration)
    msg = await channel.send(embed=embed, view=view)
    view.msg_id = msg.id
    giveaway_entries[msg.id] = view.entries
    giveaway_messages[msg.id] = msg

    last_time = ""
    for remaining in range(duration, 0, -1):
        await asyncio.sleep(1)
        t = format_time(remaining)
        if t != last_time:
            last_time = t
            updated_embed = discord.Embed(
                title=centered_title,
                description=f"{arrow} **Ends in:** {t}\n{arrow} **Winners:** {winners}\n{arrow} **Hosted by:** {host_tag}",
                color=discord.Color.dark_blue()
            )
            updated_embed.set_footer(text="Click the button below to enter!")
            view.entry_button.label = f"🟢 {len(view.entries)} Entries"
            try:
                await msg.edit(embed=updated_embed, view=view)
            except:
                pass

    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    valid_entries = [ctx.guild.get_member(uid) for uid in view.entries if ctx.guild.get_member(uid)]

    for child in view.children:
        child.disabled = True

    if len(valid_entries) < winners:
        final_embed = discord.Embed(
            title=centered_title,
            description=f"{arrow} **Ended on:** {now.strftime('%d %b %Y, %I:%M %p IST')}\n{arrow} **Winners:** Not enough entries.\n{arrow} **Hosted by:** {host_tag}",
            color=discord.Color.dark_blue()
        )
        final_embed.set_footer(text="Click the button below to enter!")
        view.entry_button.label = f"🟢 {len(view.entries)} Entries"
        await msg.edit(embed=final_embed, view=view)
        return await channel.send(f"**Not enough entries to select winners. **", reference=msg)

    chosen = random.sample(valid_entries, winners)
    giveaway_winners[msg.id] = [m.id for m in chosen]
    mentions = ", ".join(m.mention for m in chosen)

    final_embed = discord.Embed(
        title=centered_title,
        description=f"{arrow} **Ended on:** {now.strftime('%d %b %Y, %I:%M %p IST')}\n{arrow} **Winners:** {mentions}\n{arrow} **Hosted by:** {host_tag}",
        color=discord.Color.dark_blue()
    )
    final_embed.set_footer(text="Click the button below to enter!")
    view.entry_button.label = f"🟢 {len(view.entries)} Entries"

    await msg.edit(embed=final_embed, view=view)
    await channel.send(f"**🎉  Congratulations {mentions}! You’ve won `{prize}`!**", reference=msg)

    giveaway_ended_embeds[msg.id] = final_embed  # Store final embed for reroll use

@bot.command()
@commands.has_permissions(administrator=True)
async def reroll(ctx, message_id: int):
    mentions = ctx.message.mentions
    msg = giveaway_messages.get(message_id)
    entries = giveaway_entries.get(message_id, [])
    prev_winner_ids = giveaway_winners.get(message_id, [])

    if not mentions or not msg or not prev_winner_ids:
        return await ctx.send("Invalid reroll request.")

    rerolled_ids = [m.id for m in mentions]

    if not all(uid in prev_winner_ids for uid in rerolled_ids):
        return await ctx.send("Only current winners can be rerolled.")

    history = rerolled_history.get(message_id, [])
    history.extend(rerolled_ids)
    rerolled_history[message_id] = list(set(history))

    eligible = [uid for uid in entries if uid not in prev_winner_ids and uid not in rerolled_history[message_id]]
    if len(eligible) < len(rerolled_ids):
        return await ctx.send("Not enough eligible participants to reroll.")

    new_winner_ids = random.sample(eligible, len(rerolled_ids))

    updated_winner_ids = []
    new_idx = 0
    for uid in prev_winner_ids:
        if uid in rerolled_ids:
            updated_winner_ids.append(new_winner_ids[new_idx])
            new_idx += 1
        else:
            updated_winner_ids.append(uid)

    giveaway_winners[message_id] = updated_winner_ids

    new_mentions = [ctx.guild.get_member(uid).mention for uid in updated_winner_ids]
    embed = giveaway_ended_embeds.get(message_id)
    if not embed:
        return await ctx.send(" Final giveaway state not found.")

    lines = embed.description.split("\n")
    arrow = "<:Screenshot20250709102722:1392369398727049237>"
    for i, line in enumerate(lines):
        if "**Winners:**" in line:
            lines[i] = f"{arrow} **Winners:** {', '.join(new_mentions)}"

    updated_embed = discord.Embed(title=embed.title, description="\n".join(lines), color=discord.Color.dark_blue())
    updated_embed.set_footer(text=embed.footer.text)
    await msg.edit(embed=updated_embed)
    await msg.channel.send(f"**🎉  Updated Final Winners: {', '.join(new_mentions)}**", reference=msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def giveawaycancel(ctx, message_id: int = None):
    if not message_id:
        return await ctx.send(embed=discord.Embed(
            description=" Please provide a valid giveaway message ID.",
            color=discord.Color.red()))

    msg = giveaway_messages.get(message_id)
    if not msg:
        try:
            # Try fetching from channel if not in active giveaways
            msg = await ctx.channel.fetch_message(message_id)
        except:
            return await ctx.send(embed=discord.Embed(
                description=" Giveaway not found.",
                color=discord.Color.red()))

    try:
        await msg.delete()
    except:
        pass  # message might already be deleted

    # Clean up all records
    giveaway_entries.pop(message_id, None)
    giveaway_messages.pop(message_id, None)
    giveaway_winners.pop(message_id, None)
    giveaway_ended_embeds.pop(message_id, None)
    rerolled_history.pop(message_id, None)

    await ctx.send(embed=discord.Embed(
        description=" Giveaway canceled successfully.",
        color=discord.Color.red()))

# Keep Alive Flask App
app = Flask('')

@app.route('/')
def home():
    return "Giveaway Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run).start()

keep_alive()
bot.run(os.getenv("TOKEN"))
