    import discord
    from discord.ext import commands
    import os
    import re
    import asyncio
    import aiohttp
    import json
    import struct
    import zlib
    
    
    # ─── PNG ICON GENERATOR ────────────────────────────────────────────────────────
    def _make_icon_png(width=420, height=420, r=88, g=101, b=242):
        """Generate a solid-colour PNG in memory — no Pillow needed."""
    
        def chunk(tag, data):
            c = tag + data
            return (
                struct.pack(">I", len(data))
                + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            )
    
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        raw = b"".join(b"\x00" + bytes([r, g, b] * width) for _ in range(height))
        idat = chunk(b"IDAT", zlib.compress(raw))
        iend = chunk(b"IEND", b"")
        return sig + ihdr + idat + iend
    
    
    # ─── BOT SETUP ─────────────────────────────────────────────────────────────────
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    # ─── CONFIG ────────────────────────────────────────────────────────────────────
    AUTO_ROLE_ID = 1448272224007098539
    TICKET_CATEGORY_ID = 1486016109860622468
    SUPPORT_ROLE_ID = 1449143018534863042
    SHOP_CHANNEL_ID = None  # set with !setshop
    
    # Roblox config (set via Secrets)
    ROBLOX_UNIVERSE_ID = os.getenv("ROBLOX_UNIVERSE_ID", "11260731543")
    ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE", "")
    ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY", "")
    
    
    # ─── GLOBAL ERROR HANDLER ──────────────────────────────────────────────────────
    @bot.event
    async def on_command_error(ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Wait **{error.retry_after:.1f}s** before using that command again.",
                delete_after=6,
            )
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(
                "❌ You don't have permission to use that command.", delete_after=6
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"❌ Missing argument: `{error.param.name}`. Use `!bothelp` for usage.",
                delete_after=10,
            )
        elif isinstance(error, commands.BadArgument):
            await ctx.send(
                "❌ Invalid argument. Use `!bothelp` for correct usage.", delete_after=10
            )
        elif isinstance(error, commands.CommandNotFound):
            pass
        else:
            raise error
    
    
    # ─── AUTO-ROLE ─────────────────────────────────────────────────────────────────
    @bot.event
    async def on_member_join(member: discord.Member):
        if AUTO_ROLE_ID is None:
            return
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="Auto-role on join")
                print(f"[Auto-Role] Assigned {role.name} to {member.name}")
            except discord.Forbidden:
                print(f"[Auto-Role] Missing permissions to assign role to {member.name}")
    
    
    async def _sync_auto_role():
        """Assign the auto-role to every existing member who is missing it."""
        if AUTO_ROLE_ID is None:
            return
        await bot.wait_until_ready()
        for guild in bot.guilds:
            role = guild.get_role(AUTO_ROLE_ID)
            if not role:
                continue
            count = 0
            for member in guild.members:
                if member.bot:
                    continue
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Startup role sync")
                        count += 1
                        await asyncio.sleep(0.5)  # avoid hitting rate limits
                    except discord.Forbidden:
                        print(f"[Role Sync] No permission for {member.name}")
            print(f"[Role Sync] Assigned {role.name} to {count} member(s) in {guild.name}")
    
    
    # ─── TICKET SYSTEM ─────────────────────────────────────────────────────────────
    def _ticket_channel_name(member: discord.Member) -> str:
        safe = re.sub(
            r"[^a-z0-9-]", "", member.name.lower().replace(" ", "-").replace("_", "-")
        )
        return f"ticket-{safe}" if safe else f"ticket-{member.id}"
    
    
    class TicketView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
    
        @discord.ui.button(
            label="🎫 Open Ticket",
            style=discord.ButtonStyle.primary,
            custom_id="open_ticket",
        )
        async def open_ticket(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            guild = interaction.guild
            member = interaction.user
            ch_name = _ticket_channel_name(member)
    
            existing = discord.utils.get(guild.text_channels, name=ch_name)
            if existing:
                await interaction.response.send_message(
                    f"You already have an open ticket: {existing.mention}", ephemeral=True
                )
                return
    
            category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            if SUPPORT_ROLE_ID:
                support_role = guild.get_role(SUPPORT_ROLE_ID)
                if support_role:
                    overwrites[support_role] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True
                    )
    
            try:
                ticket_channel = await guild.create_text_channel(
                    name=ch_name,
                    category=category,
                    overwrites=overwrites,
                    reason=f"Ticket opened by {member.name}",
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I don't have permission to create channels.", ephemeral=True
                )
                return
    
            embed = discord.Embed(
                title="Create a Ticket",
                description=(
                    f"Hello {member.mention}! Please describe your intent and a staff member "
                    f"will be with you shortly.\n\nClick **Close Ticket** once your needs are satisfied."
                ),
                color=discord.Color.green(),
            )
            await ticket_channel.send(embed=embed, view=CloseTicketView())
            await interaction.response.send_message(
                f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True
            )
    
    
    class CloseTicketView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
    
        @discord.ui.button(
            label="🔒 Close Ticket",
            style=discord.ButtonStyle.danger,
            custom_id="close_ticket",
        )
        async def close_ticket(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            await interaction.response.send_message(
                "Closing ticket in 5 seconds...", ephemeral=True
            )
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(
                    reason=f"Ticket closed by {interaction.user.name}"
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ I don't have permission to delete this channel.", ephemeral=True
                )
    
    
    @bot.command(name="ticketpanel")
    @commands.has_permissions(administrator=True)
    async def ticket_panel(ctx: commands.Context):
        embed = discord.Embed(
            title="📩 Tickets",
            description="Click the button below to open a ticket. A private channel will be created just for you.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=TicketView())
        await ctx.message.delete()
    
    
    # ─── SHOP ──────────────────────────────────────────────────────────────────────
    async def _fetch_gamepasses() -> list[dict]:
        """Fetch all gamepasses for the configured universe from Roblox using the Catalog API."""
        passes = []
    
        async with aiohttp.ClientSession() as session:
            try:
                # Step 1: Get the root place ID from the universe
                print(f"[Shop] Fetching universe info for ID: {ROBLOX_UNIVERSE_ID}")
                universe_resp = await session.get(
                    f"https://games.roblox.com/v1/games?universeIds={ROBLOX_UNIVERSE_ID}"
                )
                universe_data = await universe_resp.json(content_type=None)
                places = universe_data.get("data", [])
    
                if not places:
                    print(f"[Shop] ❌ Universe {ROBLOX_UNIVERSE_ID} not found")
                    return []
    
                place_id = places[0].get("rootPlaceId")
                print(f"[Shop] Found place ID: {place_id}")
    
                # Step 2: Fetch gamepasses using the Catalog API
                cursor = ""
                while True:
                    url = (
                        f"https://catalog.roblox.com/v1/search/items/details"
                        f"?category=Gamepass&creatorId={place_id}&creatorType=Place"
                        f"&sortType=Relevance&limit=100"
                        + (f"&cursor={cursor}" if cursor else "")
                    )
    
                    print(f"[Shop] Fetching from: {url}")
                    resp = await session.get(url)
    
                    if resp.status != 200:
                        print(f"[Shop] ❌ API returned status {resp.status}")
                        break
    
                    data = await resp.json(content_type=None)
                    gp_list = data.get("data", [])
    
                    if not gp_list:
                        print(f"[Shop] No gamepasses found in this batch")
                        break
    
                    print(f"[Shop] Found {len(gp_list)} gamepasses in this batch")
                    passes.extend(gp_list)
    
                    cursor = data.get("nextPageCursor")
                    if not cursor:
                        break
    
                    await asyncio.sleep(0.5)  # Rate limiting
    
                print(f"[Shop] ✅ Successfully fetched {len(passes)} total gamepasses")
                return passes
    
            except Exception as e:
                print(f"[Shop] ❌ Error fetching gamepasses: {e}")
                import traceback
    
                traceback.print_exc()
                return []
    
    
    def _build_shop_embed(passes: list[dict]) -> discord.Embed:
        embed = discord.Embed(
            title="🛒 Gamepass Shop",
            description="Browse our available gamepasses below!",
            color=discord.Color.gold(),
        )
        if not passes:
            embed.description = "No gamepasses are currently available."
            return embed
    
        for gp in passes:
            gp_id = gp.get("id")
            gp_name = gp.get("name") or gp.get("displayName", "Unknown")
            price = gp.get("price")
            price_str = f"{price:,} Robux" if price else "Free"
            link = f"https://www.roblox.com/game-pass/{gp_id}/" if gp_id else ""
            embed.add_field(
                name=f"🎟️ {gp_name}",
                value=f"**Price:** {price_str}\n[View on Roblox]({link})"
                if link
                else f"**Price:** {price_str}",
                inline=True,
            )
        embed.set_footer(text="Use !updateshop to refresh this list")
        return embed
    
    
    async def _post_or_update_shop():
        """Clear the shop channel and post a fresh shop embed."""
        if not SHOP_CHANNEL_ID:
            return
        for guild in bot.guilds:
            channel = guild.get_channel(SHOP_CHANNEL_ID)
            if not channel:
                continue
            try:
                passes = await _fetch_gamepasses()
                embed = _build_shop_embed(passes)
                # Delete previous bot messages in the channel
                async for msg in channel.history(limit=50):
                    if msg.author == bot.user:
                        await msg.delete()
                await channel.send(embed=embed)
            except Exception as e:
                print(f"[Shop] Failed to update shop: {e}")
    
    
    @bot.command(name="setshop")
    @commands.has_permissions(administrator=True)
    async def set_shop(ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where the gamepass shop is displayed. Usage: !setshop #channel"""
        global SHOP_CHANNEL_ID
        SHOP_CHANNEL_ID = channel.id
        await ctx.send(
            f"✅ Shop channel set to {channel.mention}. Use `!updateshop` to post the shop."
        )
    
    
    @bot.command(name="updateshop")
    @commands.has_permissions(administrator=True)
    async def update_shop(ctx: commands.Context):
        """Refresh the gamepass shop embed. Usage: !updateshop"""
        if not SHOP_CHANNEL_ID:
            await ctx.send("❌ No shop channel set. Use `!setshop #channel` first.")
            return
        msg = await ctx.send("⏳ Fetching gamepasses...")
        await _post_or_update_shop()
        await msg.edit(content="✅ Shop updated!")
    
    
    @bot.command(name="testgamepasses")
    @commands.has_permissions(administrator=True)
    async def test_gamepasses(ctx: commands.Context):
        """Debug: fetch and display raw gamepass data"""
        msg = await ctx.send("⏳ Fetching gamepasses for testing...")
        passes = await _fetch_gamepasses()
    
        if not passes:
            await msg.edit(content="❌ No gamepasses found. Check the console for errors.")
            return
    
        summary = f"Found **{len(passes)}** gamepasses!\n\n"
        summary += "**First 3 gamepasses:**\n"
        for i, gp in enumerate(passes[:3], 1):
            summary += f"{i}. **{gp.get('name', 'Unknown')}** - {gp.get('price', 'Free')} Robux (ID: {gp.get('id')})\n"
    
        await msg.edit(content=summary)
    
    
    # ─── CONFIG COMMANDS ────────────────────────────────────────────────────────────
    @bot.command(name="setautorole")
    @commands.has_permissions(administrator=True)
    async def set_auto_role(ctx: commands.Context, role: discord.Role):
        global AUTO_ROLE_ID
        AUTO_ROLE_ID = role.id
        await ctx.send(
            f"✅ Auto-role set to **{role.name}**. New members will automatically receive this role."
        )
    
    
    @bot.command(name="setticketcategory")
    @commands.has_permissions(administrator=True)
    async def set_ticket_category(ctx: commands.Context, category: discord.CategoryChannel):
        global TICKET_CATEGORY_ID
        TICKET_CATEGORY_ID = category.id
        await ctx.send(f"✅ Ticket category set to **{category.name}**.")
    
    
    @bot.command(name="setsupportrole")
    @commands.has_permissions(administrator=True)
    async def set_support_role(ctx: commands.Context, role: discord.Role):
        global SUPPORT_ROLE_ID
        SUPPORT_ROLE_ID = role.id
        await ctx.send(f"✅ Support role set to **{role.name}**.")
    
    
    # ─── ROBLOX GAMEPASS CREATOR ───────────────────────────────────────────────────
    @bot.command(name="creategamepass")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def create_gamepass(ctx: commands.Context, price: int, *, name: str):
        """Create a Roblox gamepass. Usage: !creategamepass <price> <name>"""
        if not ROBLOX_COOKIE:
            await ctx.send("❌ `ROBLOX_COOKIE` secret is not set.")
            return
    
        status_msg = await ctx.send(
            f"⏳ Creating gamepass **{name}** (Price: {price} Robux)..."
        )
        cookie_str = f".ROBLOSECURITY={ROBLOX_COOKIE}"
        CREATE_URL = "https://apis.roblox.com/game-passes/v1/game-passes"
    
        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: Probe to get XSRF token
                probe_resp = await session.post(
                    CREATE_URL,
                    headers={"Cookie": cookie_str},
                    data=aiohttp.FormData(),
                )
                xsrf_token = probe_resp.headers.get("x-csrf-token")
                if not xsrf_token:
                    probe_body = await probe_resp.text()
                    await status_msg.edit(
                        content=f"❌ Could not get XSRF token (HTTP {probe_resp.status}). "
                        f"Your `.ROBLOSECURITY` cookie may be expired.\n```{probe_body[:300]}```"
                    )
                    return
    
                # Step 2: Resolve root place ID
                universe_resp = await session.get(
                    f"https://games.roblox.com/v1/games?universeIds={ROBLOX_UNIVERSE_ID}",
                    headers={"Cookie": cookie_str},
                )
                universe_data = await universe_resp.json(content_type=None)
                places = universe_data.get("data", [])
                if not places:
                    await status_msg.edit(
                        content=f"❌ Universe `{ROBLOX_UNIVERSE_ID}` not found."
                    )
                    return
                place_id = places[0].get("rootPlaceId")
    
                # Step 3: Create gamepass
                form = aiohttp.FormData()
                form.add_field("Name", name)
                form.add_field("Description", f"Gamepass: {name}")
                form.add_field("UniverseId", str(ROBLOX_UNIVERSE_ID))
                form.add_field("IsForSale", "true")
                form.add_field("Price", str(price))
                form.add_field(
                    "IconImageFile",
                    _make_icon_png(),
                    filename="icon.png",
                    content_type="image/png",
                )
    
                create_resp = await session.post(
                    CREATE_URL,
                    headers={"Cookie": cookie_str, "X-CSRF-TOKEN": xsrf_token},
                    data=form,
                )
                raw_text = await create_resp.text()
    
                try:
                    result = json.loads(raw_text)
                except json.JSONDecodeError:
                    await status_msg.edit(
                        content=f"❌ Unexpected response (HTTP {create_resp.status}):\n```{raw_text[:400]}```"
                    )
                    return
    
                if create_resp.status in (200, 201):
                    gp_id = (
                        result.get("gamePassId")
                        or result.get("id")
                        or result.get("Id")
                        or result.get("gamepassId")
                    )
    
                    embed = discord.Embed(
                        title="✅ Gamepass Created!", color=discord.Color.green()
                    )
                    embed.add_field(name="Name", value=name, inline=True)
                    embed.add_field(name="Price", value=f"{price} Robux", inline=True)
                    if gp_id:
                        embed.add_field(name="Gamepass ID", value=str(gp_id), inline=False)
                        embed.add_field(
                            name="Link",
                            value=f"https://www.roblox.com/game-pass/{gp_id}/",
                            inline=False,
                        )
                    await status_msg.edit(content=None, embed=embed)
    
                    # Auto-refresh shop if one is configured
                    if SHOP_CHANNEL_ID:
                        await asyncio.sleep(
                            2
                        )  # give Roblox a moment to register the new pass
                        await _post_or_update_shop()
    
                else:
                    errors = result.get("errors", result.get("title", raw_text[:300]))
                    if isinstance(errors, list) and errors:
                        error_msg = errors[0].get("message", str(errors[0]))
                    elif isinstance(errors, dict):
                        first_key = next(iter(errors))
                        vals = errors[first_key]
                        error_msg = vals[0] if isinstance(vals, list) else str(vals)
                    else:
                        error_msg = str(errors)[:300]
                    await status_msg.edit(
                        content=f"❌ Roblox error (HTTP {create_resp.status}): {error_msg}"
                    )
    
        except Exception as e:
            import traceback
    
            print(f"[Roblox] Exception:\n{traceback.format_exc()}")
            await status_msg.edit(content=f"❌ Unexpected error: {repr(e)}")
    
    
    # ─── HELP ──────────────────────────────────────────────────────────────────────
    @bot.command(name="bothelp")
    async def bot_help(ctx: commands.Context):
        embed = discord.Embed(title="Bot Commands", color=discord.Color.blurple())
        embed.add_field(
            name="⚙️ Setup (Admin only)",
            value=(
                "`!setautorole @Role` — Set the role auto-assigned to new members\n"
                "`!setticketcategory <CategoryName>` — Set category for ticket channels\n"
                "`!setsupportrole @Role` — Set the staff role that can see tickets\n"
                "`!ticketpanel` — Post the ticket panel in this channel\n"
                "`!setshop #channel` — Set the gamepass shop channel\n"
                "`!updateshop` — Refresh the shop with latest gamepasses\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎮 Roblox (Admin only)",
            value=(
                "`!creategamepass <price> <name>` — Create a Roblox gamepass\n"
                "Example: `!creategamepass 100 VIP Access`\n"
                "`!testgamepasses` — Test gamepass fetching (debug)\n"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)
    
    
    # ─── STARTUP ───────────────────────────────────────────────────────────────────
    @bot.event
    async def on_ready():
        bot.add_view(TicketView())
        bot.add_view(CloseTicketView())
        print(f"✅ Bot is online as {bot.user} (ID: {bot.user.id})")
        print(f"   Universe ID : {ROBLOX_UNIVERSE_ID}")
        print(f"   Auto-Role   : {AUTO_ROLE_ID}")
        print(f"   Ticket Cat  : {TICKET_CATEGORY_ID}")
        print(f"   Support Role: {SUPPORT_ROLE_ID}")
        # Run role sync in the background so startup isn't blocked
        asyncio.create_task(_sync_auto_role())
    
    
    if __name__ == "__main__":
        token = os.getenv("DISCORD_BOT_TOKEN")
        if not token:
            raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set.")
        bot.run(token)
    
