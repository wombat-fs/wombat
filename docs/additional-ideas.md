## Integration with beat_this_cpp

I have an installation of this app available (and the repo is available at Guthub: https://github.com/mosynthkey/beat_this_cpp.git).

This is an AI based tool to detect a beat pattern in an audio file and generates
a list of timestamps. These could be used as a starting point for an audio based
funscript.

Idea: Add an integration for this. Use beat_this to generate the at: markers in
a funscript from the audio track of the loaded video and fill pos: in a user selectable way with an existing snippet. Best solution might even be to import the beat file as constant ActionList with pos:50. These can then be edited or overlaid with a layer/snippet controlling the pos.

Implementation details: Include as a git module or something else?


## Splash screen on startup

See assets folder for Claude design work on a logo. These should also be used for app icons and similar.

## Documentation

Set of md files describing how to work with Wombat: Installation instruction, Getting started guide, as well as more in-depth technical docs, including instructions on how to write a plugin.
