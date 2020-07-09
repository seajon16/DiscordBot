import asyncio
import os
import discord
from discord import VoiceChannel
from discord.ext import commands
import random
from gtts import gTTS
from gtts.lang import tts_langs
from youtube_dl import YoutubeDL
from datetime import datetime, timedelta
from functools import wraps, partial
import logging

from exceptions import BananaCrime
from settings import get_settings


SOUND_DIR = 'sounds'
GTTS_DEFAULT_LANG = 'en-uk'
GTTS_TEMP_FILE = f'{SOUND_DIR}/temp_voice.mp3'
FFMPEG_OPTS = {
    'before_options': \
        '-reconnect 1 ' \
        '-reconnect_streamed 1 ' \
        '-reconnect_delay_max 5',
    'options': '-vn'
}
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'default_search': 'auto',
    'quiet': True,
    'source_address': '0.0.0.0'
}
YTDL = YoutubeDL(YTDL_OPTS)

LOGGER = logging.getLogger(__name__)

settings_dict = get_settings()
# Number of minutes of inactivity before leaving a voice channel
VC_TIMEOUT = settings_dict['vc_timeout_mins']
# Number of seconds between each time the bot checks for inactivity
VC_CHECK_INTERVAL = settings_dict['vc_timeout_check_interval_secs']


def ffmpeg_error_catcher(loop, channel, err):
    """Passed into `VoiceContoller.play` to handle and report FFmpeg errors.

    Inspired by:
        https://discordpy.readthedocs.io/en/latest/faq.html#id13
    """
    if not err:
        return
    LOGGER.error(
        f'FFmpeg failed while streaming: {type(err).__name__}, {err.args!r}'
    )
    reporter_coro = channel.send('Had an issue while streaming; try again.')
    fut = asyncio.run_coroutine_threadsafe(reporter_coro, loop)
    try:
        fut.result()
    except Exception as ex:
        LOGGER.error(
            "Not only did FFmpeg fail to stream, "
            "I couldn't alert the guild that made the request: "
            f"{type(ex).__name__}, {ex.args!r}"
        )


class YTDLSource(discord.PCMVolumeTransformer):
    """Wrapper for YoutubeDL streaing functionality.

    Shouldn't directly call the constructor; use `create_from_search` instead.
    Inspired by:
        https://github.com/Rapptz/discord.py/blob/master/examples/basic_voice.py
    """

    def __init__(self, source, info, volume=0.5):
        super().__init__(source, volume)
        self.title = info['title']
        self.uploader = info['uploader']
        self.duration_m, self.duration_s = divmod(info['duration'], 60)

    def __str__(self):
        return (
            f"{self.title}\n"
            f"uploaded by {self.uploader}\n"
            f"[{self.duration_m}m {self.duration_s}s]"
        )

    @classmethod
    async def create_from_search(cls, search, loop=None):
        """Create a YTDLSource object using a search term.

        Args:
            search (str): The URL or search term to use to find audio.
            loop (async Event Loop, optional): The loop to run the search on.
        """
        loop = loop or asyncio.get_event_loop()
        info = await loop.run_in_executor(
            None, lambda: YTDL.extract_info(search, download=False)
        )
        # If it found multiple possibilities, just grab the 1st one
        if 'entries' in info:
            info = info['entries'][0]

        return cls(discord.FFmpegPCMAudio(info['url'], **FFMPEG_OPTS), info)


class GuildVoiceRecord:
    """Represents additional data needed on a per-guild basis when using Voice.

    Specifically:
        1. The last channel a voice-related command was executed & when
        2. The Lock used by that guild to prevent spam-based issues

    Args:
        last_channel (Channel): The text channel where the most recent voice-
            related command was executed. If None, the `send` method will not
            do anything.
        dt (Datetime, optional): Datetime object to use for time comparisons;
            defaults to `now()`.
    """

    def __init__(self, last_channel=None, dt=None):
        self.last_channel = last_channel
        self.dt = dt or datetime.now()
        self.lock = asyncio.Lock()

    @property
    def should_timeout(self):
        """Return if the GVA should be timed out using VC_TIMEOUT."""
        return self.dt + timedelta(minutes=VC_TIMEOUT) < datetime.now()

    def update(self, last_channel):
        """Update the object by recording the new most recent voice command."""
        self.last_channel = last_channel
        self.dt = datetime.now()

    async def send(self, msg):
        """Send a message to my last channel if I have one, else do nothing."""
        if self.last_channel:
            await self.last_channel.send(msg)


class VoiceController(commands.Cog, name='Voice'):
    """Handles all voice-related functionality.

    Will read soundboard files from SOUND_DIR.
    NOTE: There cannot be sounds with duplicate filenames.
    """

    def __init__(self, bot):
        self.bot = bot
        # Grab valid TTS languages from `gtts.lang` to give language options
        self.valid_tts_langs = tts_langs()
        self.load_sounds()
        # Perform VC timeout setup
        bot.loop.run_until_complete(self.init_guild_voice_records())
        bot.loop.create_task(self.inactivity_checker())

    def load_sounds(self):
        """Build the dictionaries relating categories and lists of sounds."""
        self.category_to_sounds = {}  # used for easy listing
        self.sound_to_category = {}   # used to quickly check for membership
        # For each subdirectory (category) of sounds
        for category in next(os.walk('sounds'))[1]:
            # Associate the category with its list of sounds
            sounds = [
                sound[:-4] for sound in os.listdir(f'{SOUND_DIR}/{category}')
            ]
            for sound in sounds:
                if sound in self.sound_to_category:
                    raise ValueError(
                        'Detected duplicate sound name: '
                        f'{self.sound_to_category[sound]}/{sound} '
                        f'vs {category}/{sound}'
                    )
                self.sound_to_category[sound] = category
            self.category_to_sounds[category] = sorted(sounds)

    async def init_guild_voice_records(self):
        """Populate the guild voice records with known guilds.

        NOTE: By default, only grabs 100.
        """
        self.guild_voice_records = {}
        async for guild in self.bot.fetch_guilds():
            self.guild_voice_records[guild.id] = None

    def requires_guild_update(f):
        """Decorator that records a voice action was performed in a guild.

        Used to manage inactivity timeouts.
        """
        @wraps(f)
        async def wrapper(self, ctx, *args, **kwargs):
            gvr_obj = self.guild_voice_records.get(ctx.guild.id)
            if gvr_obj:
                gvr_obj.update(ctx.channel)
            else:
                self.guild_voice_records[ctx.guild.id] = \
                    GuildVoiceRecord(ctx.channel)
            await f(self, ctx, *args, **kwargs)

        return wrapper

    async def inactivity_checker(self):
        """Periodic task that removes inactive voice connections."""
        await self.bot.wait_until_ready()

        try:
            while True:
                for guild_id, vrecord in self.guild_voice_records.items():
                    guild = self.bot.get_guild(guild_id)
                    # Edge case where the API couldn't find the guild
                    # This'll get picked up next cylce, so ignore it for now
                    if not guild:
                        continue

                    vclient = guild.voice_client
                    if vrecord and vrecord.should_timeout:
                        self.guild_voice_records[guild.id] = None
                        if vclient and vclient.is_connected():
                            await vclient.disconnect()
                            await vrecord.send(
                                'Disconnected from voice due to inactivity.'
                            )
                            LOGGER.info(f'VC timed out in {guild}#{guild_id}')

                    # Disconnects might silently fail when someone runs a leave
                    #   right after the bot creates a new voice client, so
                    #   guild_voice_records might be missing a GVR
                    # If we just put a retry wrapper around disconnect calls,
                    #   it still can't detect it without introducing unnecessary
                    #   delays for all disconnects, since voice clients don't
                    #   reflect the issue until after the bot re-syncs w discord
                    elif not vrecord and vclient and vclient.is_connected():
                        # Since this is so rare and can only happen when someone
                        #   already tried executing leave, don't even give a
                        #   channel to send a timeout message to
                        self.guild_voice_records[guild_id] = GuildVoiceRecord()
                        LOGGER.info(
                            f'Handled missing GVR in {guild}#{guild_id}'
                        )

                await asyncio.sleep(VC_CHECK_INTERVAL)

        except asyncio.CancelledError:
            LOGGER.debug('Inactivity checking task was cancelled')
        except Exception:
            # NOTE: This exception isn't re-raised since it gets logged
            #   and already stopped/"finished" the task; if we raised it again,
            #   discord.py's main handler would report it again unless we made a
            #   custom canceller/reaper
            LOGGER.critical('Inactivity checking task failed:', exc_info=True)

    async def _summon(self, ctx):
        """Helper that attempts to join the VC of the caller.

        NOTE: Does not perform any locking.
        """
        if not ctx.author.voice:
            raise BananaCrime('You are not in a voice channel')
        target_channel = ctx.author.voice.channel
        vclient = ctx.voice_client
        if vclient and vclient.is_connected():
            if vclient.channel == target_channel:
                raise BananaCrime("I'm already in this channel")
            await vclient.move_to(target_channel)
        else:
            await target_channel.connect()

    async def prepare_to_play(self, ctx):
        """Prepare to play an AudioSource.

        Specifically, ensure I am not already playing something, and
            if I'm not in a VC, attempt to join that of the caller.
        NOTE: Does not perform any locking.
        """
        vclient = ctx.voice_client
        if not vclient or not vclient.is_connected():
            await self._summon(ctx)
            return ctx.voice_client

        if vclient.is_playing():
            raise BananaCrime("I'm already playing something")

        if vclient.is_paused():
            vclient.stop()

        return vclient

    @commands.is_owner()
    @commands.command(pass_context=True, aliases=('reload',))
    async def reloadsb(self, ctx):
        """Reload soundboard listing; must be my owner."""
        self.load_sounds()
        await ctx.send('Done.')

    @commands.command(pass_context=True)
    @requires_guild_update
    async def join(self, ctx, channel: VoiceChannel=None):
        """Join the given voice channel."""
        if not channel:
            raise BananaCrime('I need a channel to join')
        vclient = ctx.voice_client
        async with self.guild_voice_records[ctx.guild.id].lock:
            if vclient and vclient.is_connected():
                if vclient.channel == channel:
                    raise BananaCrime("I'm already in this channel")
                await vclient.move_to(channel)
            else:
                await channel.connect()

    @commands.command(pass_context=True)
    @requires_guild_update
    async def summon(self, ctx):
        """Join the voice channel of the caller."""
        async with self.guild_voice_records[ctx.guild.id].lock:
            await self._summon(ctx)

    @commands.command(pass_context=True)
    @requires_guild_update
    async def stop(self, ctx):
        """Stop all playback but stays in channel."""
        vclient = ctx.voice_client
        if not vclient:
            raise BananaCrime("I'm not in a voice channel")

        if vclient.is_playing() or vclient.is_paused():
            vclient.stop()
        else:
            raise BananaCrime("I'm not playing anything")

    @commands.command(pass_context=True)
    async def leave(self, ctx):
        """Leave the current voice channel."""
        vclient = ctx.voice_client
        if not vclient:
            raise BananaCrime("I'm not in a voice channel")

        self.guild_voice_records[ctx.guild.id] = None
        await ctx.voice_client.disconnect()

    @commands.command(pass_context=True)
    @requires_guild_update
    async def sb(self, ctx, desire: str=None):
        """Play a given sound from the soundboard.

        Call this command with no argument to see available sounds.
        """
        if not desire:
            await ctx.send(
                'Available categories: '
                f'{", ".join(self.category_to_sounds)}, all'
            )

        elif desire == 'all':
            await ctx.send(
                'All available sounds:\n'
                + '\n'.join([
                    '\n'.join(sounds)
                    for sounds in self.category_to_sounds.values()
                ])
            )

        # If they searched a category
        elif desire in self.category_to_sounds:
            await ctx.send(
                f'Category {desire}: '
                f'{", ".join(self.category_to_sounds[desire])}'
            )

        elif desire == 'random':
            category, sounds = random.choice(
                list(self.category_to_sounds.items())
            )
            guild_lock = self.guild_voice_records[ctx.guild.id].lock
            if guild_lock.locked():
                raise BananaCrime("I'm already trying to process a VC command")
            async with guild_lock:
                vclient = await self.prepare_to_play(ctx)
            path = f'{SOUND_DIR}/{category}/{random.choice(sounds)}.mp3'
            vclient.play(
                discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(path), 0.5)
            )

        # Ensure the sound exists
        elif desire in self.sound_to_category:
            category = self.sound_to_category[desire]
            guild_lock = self.guild_voice_records[ctx.guild.id].lock
            if guild_lock.locked():
                raise BananaCrime("I'm already trying to process a VC command")
            async with guild_lock:
                vclient = await self.prepare_to_play(ctx)
            path = f'{SOUND_DIR}/{category}/{desire}.mp3'
            vclient.play(
                discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(path), 0.5)
            )

        else:
            raise BananaCrime(
                'Invalid category/sound name; try `q.sb` with no arguments'
            )

    @commands.command(pass_context=True)
    @requires_guild_update
    async def say(self, ctx, *, desire=None):
        """Use gTTS to play a text-to-speech message."""
        await ctx.invoke(self.saylang, GTTS_DEFAULT_LANG, desire=desire)

    @commands.command(pass_context=True)
    @requires_guild_update
    async def saylang(self, ctx, lang=None, *, desire=None):
        """Use gTTS to play a text-to-speech message using a given language."""
        if not lang:
            await ctx.send(
                'Available languages:\n'
                + '\n'.join([
                    f'{v}: `{k}`' for k, v in self.valid_tts_langs.items()
                ])
            )
            return
        if not desire:
            raise BananaCrime('Give me text to speak')

        async with self.guild_voice_records[ctx.guild.id].lock:
            vclient = await self.prepare_to_play(ctx)
        try:
            tts = gTTS(desire, lang=lang)
        except ValueError:
            raise BananaCrime('Invalid language')
        tts.save(GTTS_TEMP_FILE)

        vclient.play(
            discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    # Suppress bitrate estimation warning
                    GTTS_TEMP_FILE, options='-loglevel error'
                ),
                1
            )
        )

    @commands.command(pass_context=True)
    @requires_guild_update
    async def play(self, ctx, *, desire: str=None):
        """Play a song. Give me a URL or a search term."""
        if not desire:
            raise BananaCrime('Give me a search term')

        async with self.guild_voice_records[ctx.guild.id].lock:
            async with ctx.typing():
                vclient = await self.prepare_to_play(ctx)
                ytdl_src = await YTDLSource.create_from_search(
                    desire, self.bot.loop
                )
                vclient.play(
                    ytdl_src,
                    after=partial(
                        ffmpeg_error_catcher, self.bot.loop, ctx.channel
                    )
                )
            await ctx.send(f"*Now playing:*\n{ytdl_src}")

    @commands.command(pass_context=True)
    @requires_guild_update
    async def pause(self, ctx):
        """Pause song playback."""
        vclient = ctx.voice_client
        if not vclient or not vclient.is_playing():
            raise BananaCrime("I'm not playing anything")
        if type(vclient.source) != YTDLSource:
            raise BananaCrime("You can't pause the soundboard")

        vclient.pause()

    @commands.command(pass_context=True)
    @requires_guild_update
    async def resume(self, ctx):
        """Resume playing a song."""
        vclient = ctx.voice_client
        if not vclient or not vclient.is_connected():
            raise BananaCrime("I'm not in a voice channel")
        if type(vclient.source) != YTDLSource:
            raise BananaCrime("You can't pause/unpause the soundboard")
        if not vclient.is_paused():
            raise BananaCrime("I'm not paused")

        vclient.resume()

    @commands.command(pass_context=True)
    @requires_guild_update
    async def playing(self, ctx):
        """Get the information of the currently playing song, if any."""
        vclient = ctx.voice_client
        if not vclient or not vclient.is_connected():
            raise BananaCrime("I'm not even in a voice channel")

        if (vclient.is_playing() or vclient.is_paused()) \
            and type(vclient.source) == YTDLSource:
            await ctx.send(f"*Currently playing:*\n{vclient.source}")
        else:
            raise BananaCrime("I'm not playing any songs at the moment")

    @commands.command(pass_context=True)
    @requires_guild_update
    async def volume(self, ctx, vol: int=None):
        """Get or set the volume of whatever is currently playing.

        Takes a percentage as an integer, if any.
        """
        vclient = ctx.voice_client
        if not vclient or not vclient.is_connected():
            raise BananaCrime("I'm not even in a voice channel")
        if not vclient.is_playing():
            raise BananaCrime("I'm not playing anything")
        if vol is None:
            await ctx.send(
                f'Volume is currently at {int(vclient.source.volume * 100)}%.')
            return
        if not vol >= 0 or not vol <= 100:
            raise BananaCrime("That's not a valid integer percentage (0-100)")

        vclient.source.volume = vol / 100
        await ctx.send(f"Volume set to {vol}%.")
