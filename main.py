from discord import Game
from discord.ext import commands
from random import choice
import logging
import logging.config
import asyncio
from websockets.exceptions import ConnectionClosedOK

from settings import get_settings
from exceptions import BananaCrime
from voicecontroller import VoiceController


settings_dict = get_settings()
logging.config.dictConfig(settings_dict["logging"])
LOGGER = logging.getLogger(__name__)

bot = commands.Bot(
    command_prefix='q.',
    description='Nifty bot that does things'
)

# Used to give error messages more personality
err_count = {}
banana_names = [
    'banana',
    'bafoon',
    'dingus',
    'horse',
    'fool',
    'crook',
    'fiend',
    'doofus',
    'goose',
    'oaf',
    "big stinky banana that evidently is the big banana and cannot type beep " \
        "boop bop on his/her keyboard like omg what's up with this guy lol xD"
]


async def check_err_count(ctx):
    author = ctx.author
    if author in err_count:
        err_count[author] += 1
        newval = err_count[author]
        if newval == 3:
            await ctx.send("That's the third command in a row you messed up.")
        elif newval == 6:
            await ctx.send("You really aren't good at this.")
        elif newval >= 9 and not newval % 3:
            await ctx.send(
                f'Are you doing this on purpose, {author.mention}? '
                'What are you tring to gain, huh?'
            )
    else:
        err_count[author] = 1


@bot.event
async def on_command_error(ctx, ex):
    await check_err_count(ctx)
    ex_type = type(ex)

    if ex_type == commands.errors.CommandNotFound:
        await ctx.send('Invalid command.')

    elif ex_type == commands.errors.MissingRequiredArgument:
        await ctx.send(
            'You did not specify the correct number of arguments. '
            'Try using `q.help {name of command}`.'
        )

    elif ex_type == commands.errors.CommandInvokeError \
        and type(ex.original) == BananaCrime:
        await ctx.send(f'{ex.original.crime}, you {choice(banana_names)}.')

    elif ex_type == commands.errors.NotOwner:
        await ctx.send("You aren't my owner, you banana.")

    elif ex_type == commands.errors.BadArgument:
        await ctx.send(ex.args[0])

    else:
        await ctx.send('what are you doing')
        LOGGER.error('Unexpected exception thrown while handling a command:')
        raise ex


@bot.event
async def on_command_completion(ctx):
    author = ctx.author
    if author in err_count:
        if err_count[author] >= 9:
            await ctx.send(
                f'Attention Server: {author.mention} FINALLY knows how to act '
                'like a normal human being!'
            )
        del err_count[author]


@bot.event
async def on_command(ctx):
    LOGGER.info(
        f'{ctx.message.author} in {ctx.guild}#{ctx.guild.id} '
        f'ran {ctx.message.content}'
    )


@bot.event
async def on_ready():
    LOGGER.info(f'Logged in as {bot.user}')
    await bot.change_presence(activity=Game('q.help'))


@bot.command()
@commands.is_owner()
async def shutdown(ctx):
    """Gracefully shut down the bot; must be my owner."""
    await ctx.send('okey dokey')
    await bot.logout()


async def stop_and_cleanup():
    """Stop the bot and perform loop cleanup."""
    LOGGER.info('Stopping bot...')
    await bot.logout()

    tasks = [
        task for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
    ]
    LOGGER.debug('Cancelling all tasks...')
    for task in tasks:
        LOGGER.debug(f'Cancelling {task}')
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    LOGGER.debug('All tasks cancelled')

    for task in tasks:
        if task.cancelled():
            continue
        task_ex = task.exception()
        # Ignore normal socket closures and uncaught cancels
        if task_ex is not None \
            and not isinstance(task_ex, ConnectionClosedOK) \
            and not isinstance(task_ex, asyncio.CancelledError):
            LOGGER.error('Unexpected exception found during shutdown:')
            bot.loop.call_exception_handler({
                'message': 'Unexpected exception found during shutdown',
                'exception': task_ex,
                'task': task
            })

    LOGGER.debug('Shutting down async generators...')
    await bot.loop.shutdown_asyncgens()
    LOGGER.debug('Async generators shut down')

    bot.loop.stop()


try:
    LOGGER.info('Starting bot...')
    bot.loop.run_until_complete(bot.login(settings_dict['token']))

    bot.load_extension('utilities')
    vccog = VoiceController(bot)
    bot.add_cog(vccog)

    bot.loop.run_until_complete(bot.connect())

except KeyboardInterrupt:
    LOGGER.info('Caught a keyboard interrupt; triggering shutdown...')
except Exception:
    # NOTE: This exception isn't re-raised since it's logged
    #   and will trigger the bot's shutdown procedure
    LOGGER.critical(
        'Encountered the following unrecoverable top-level exception; '
        'stopping bot...',
        exc_info=True
    )
finally:
    bot.loop.run_until_complete(stop_and_cleanup())
    bot.loop.close()
    LOGGER.info("Bot stopped")
