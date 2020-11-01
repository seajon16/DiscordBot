# Description
A discord bot with nifty commands and a personality. \
A number of utility commands like `roll` and `choose`. \
Voice support, namely TTS message parsing and customizable soundboard playing with intelligent sound resolution using substring membership and edit distance. \
Inactivity timeouts for hanging voice sessions.

**Commands:**
* **General Utility**
  * `choose`: Pick a random option from a given list of choices
  * `code`: Provide a link to this repo
  * `fact`: Give a random fact using [uselessfacts.jsph.pl](https://uselessfacts.jsph.pl)
  * `help`: List all commands
  * `ping`/`howyoudoin`: Healthcheck
  * `roll`: Handle a dice roll in the form (A)dB(+C-D...)
* **Voice**
  * `join`/`leave`/`summon`: Join & leave voice channels
  * `pause`/`resume`: Pause/resume an audio stream
  * `playing`: Display information about what's currently playing
  * `refresh`: Refresh a voice connection to avoid voice connection timeout
  * `say`: Use gTTS to interpret and play text-to-speech (defaults to `en-uk`)
  * `saylang`: Use gTTS to interpret and play text-to-speech in a given language
  * `sb`: Soundboard interface with guess-maker using substring membership and edit distance
  * `sbcount`: Display how many sounds are currently in the soundboard
  * `sbreload`: Reload soundboard by re-scanning the `sounds/` directory*
  * `sbrequest`: Put in a request to add a sound to the soundboard
  * `stop`: Stop playing audio
  * `volume`: Get or set the volume of whatever is currently playing
\* must be my owner


# Requirements
* Python 3.7+
* The following `pip`-able packages:
  * `discord.py[voice]`
  * `gTTS`
  * `editdistance`


# Installation
* Install the requirements [listed above](#Requirements)
* Clone this repo
* Replace `[INSERT TOKEN HERE]` in [`settings.json`](./settings.json) with your bot's token
  * If you need a bot token and/or need to add the bot to a server, follow [these instructions](https://www.writebots.com/discord-bot-token/)


# Use & Customization
* Run `python main.py` to start the bot
* `q.help` lists all commands
* Sounds placed in the [`sounds`](./sounds) directory must be contained in additional subfolders, used as categories
  * For example, if one wanted to insert the sound `bell.mp3` in the `noises` category, one would place it in `sounds/noises/bell.mp3`
    * Note: there cannot be two sounds with the same file name
  * If the sound file is placed directly into the `sounds` folder, it will be ignored
* [`settings.json`](./settings.json) contains additional settings other than the bot `token`:
  * `logging`: The bot using the standard `logging` Python module; these are the settings used to configure the logger
    * If you'd like to change them, consult [the documentation](https://docs.python.org/3/library/logging.config.html)
  * `sb_num_new`: When listing newest sounds on soundboard, list the most recent `sb_num_new` sounds
  * `sb_request_file`: Name of the file to write soundboard requests to
  * `sb_request_file_max_size`: Loose maximum allowed size of the soundboard request file in bytes
    * Specifically, a soundboard request can only be a certain number of bytes long; once the file grows over `sb_request_file_max_size` bytes, requests will be denied
  * `vc_timeout_check_interval_secs`: The number of seconds between each time the bot checks for inactive voice clients
  * `vc_timeout_mins`: The number of minutes of inactivity before leaving a voice channel
* If you want to have this bot join over 100 discord servers, you'll have to edit the `fetch_guilds` call in `VoiceController.init_guild_voice_records` of [`voicecontroller.py`](./voicecontroller.py); consult [the documentation](https://discordpy.readthedocs.io/en/latest/api.html#discord.Client.fetch_guilds) if this applies to you


# About
I started this project wanting to gain experience working with asynchronous programming while producing code that I could use for goofy interactions during gaming sessions. It ended up revealing a number of nifty programming tricks like the Command pattern, partial functions, and how asynchronous programming lends itself to avoiding race conditions.


# Additional Resources
* [discord.py documentation](https://discordpy.readthedocs.io/en/latest/api.html)
* [General discord.py FAQ](https://discordpy.readthedocs.io/en/latest/faq.html)
