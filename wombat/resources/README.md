# wombat/resources

Runtime resource files bundled with Wombat (and included in standalone builds).

## `config.event_definitions.yml` (not present yet)

The Events panel loads a default event library from
`config.event_definitions.yml` in this directory on startup, if the file exists.

It is intentionally **absent** for now. The natural default is
funscript-tools' `config.event_definitions.yml`
(<https://github.com/edger477/funscript-tools>), but that project currently
ships **no license**, so redistributing the file would be unlicensed. Until it
carries an OSI license (in which case we can bundle it here with attribution),
or until a Wombat-authored default is written, Wombat starts with no default
library — users load their own via **Load event definitions…**.
