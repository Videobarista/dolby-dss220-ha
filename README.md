# Dolby DSS220 for Home Assistant

[![Release](https://img.shields.io/github/v/release/Videobarista/dolby-dss220-ha)](https://github.com/Videobarista/dolby-dss220-ha/releases)
[![Ruff](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/ruff.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/ruff.yml)
[![hassfest](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/hassfest.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/hassfest.yml)
[![HACS](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/hacs.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/hacs.yml)
[![CodeQL](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/codeql.yml)
[![Tests](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Videobarista/dolby-dss220-ha/actions/workflows/tests.yml)
[![Quality scale: Bronze (aligned)](https://img.shields.io/badge/quality%20scale-bronze%20(aligned)-cd7f32.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Videobarista&repository=dolby-dss220-ha&category=integration)

Home Assistant custom integration for the **Dolby DSS200 / DSS220 Show Store** cinema server, with
its media block (for example a CAT745 IMB). It uses the server's own **SMI web services** (Show
Management Interface): SOAP over HTTP on **TCP port 8080**, the documented interface theatre
management systems use. No cloud, no web interface scraping, no TMS in between.

Built from the WSDL and XSD schemas the server publishes itself (server software 4.9.5).

> This is an independent community project. It is **not affiliated with, endorsed by, sponsored by
> or supported by** Dolby Laboratories. See [Disclaimer](#disclaimer).

## What you get

| Entity | Type | What it does |
| --- | --- | --- |
| Server | `media_player` | Play, pause, stop, next/previous clip, seek, show selection (source), volume and mute |
| Input | `select` | Media block input: Server, HDMI 1, HDMI 2 (HD-SDI appears when the server reports it) |
| Schedule mode | `select` | Full automatic, select automatic or manual (configuration) |
| Douser closed | `switch` | Douser of the projector, as controlled by the server |
| Lamp | `switch` | Lamp (light) of the projector, as controlled by the server |
| Transport state | `sensor` | Ready, playing, paused, stopped, unavailable, ... |
| Current show | `sensor` | Name of the selected show (SPL) |
| Current clip | `sensor` | Name of the clip (CPL) that is playing |
| Clip timecode / Show timecode | `sensor` | `HH:MM:SS / HH:MM:SS` |
| Clip remaining / Show remaining | `sensor` | Remaining time in seconds |
| Active alarms | `sensor` | Number of alarms of the server and its components, with the list as attribute |
| Clock offset | `sensor` | Server clock minus Home Assistant clock, with the server time zone (diagnostic) |
| Response time | `sensor` | Duration of the playback state request (diagnostic) |
| Last seen | `sensor` | When the server last answered (diagnostic) |

The media player shows the **clip** as title, with its position and duration, and the **show** as
playlist and source. The source list contains the playable shows; a show that misses a KDM or
content is left out.

| Server transport state | Media player state |
| --- | --- |
| Playing | playing |
| Paused | paused |
| Selecting, seeking, recovering, late | buffering |
| Ready, stopped, unselected | idle |
| Unavailable (media block not ready) | idle (the transport state sensor shows `unavailable`) |
| Server does not answer | off |

### Control is opt-in

The integration starts **read-only**. Switch on **Allow control** while adding the server or later
in the integration options to use play, pause, show selection, input, volume, douser and lamp.
While it is off, every command is refused, also when it comes from an automation or script.

### Switched off is not an error

A cinema server is often switched off for the night. An unreachable server does not make the
setup fail: the media player shows **off**, the other entities become unavailable and everything
returns on its own once the server answers again.

## Requirements

- A Dolby DSS200 or DSS220 with server software 4.x and its SMI web services on port 8080.
- Home Assistant 2025.10 or newer.
- Network access from Home Assistant to **TCP 8080** of the server.

The web services listen on the server's **management network**. On a server without a theatre
network (only the auditorium port in use), set it to the auditorium network: log in on the
console as `config`, open the advanced options and set **Management network** to **Auditorium**,
then reboot. Without that, port 8080 does not answer on the auditorium address.

The auditorium network of a DSS is fixed by Dolby and often has no default gateway. If Home
Assistant is in another subnet, give the server a gateway in its own subnet (also in the
`config` console) or put Home Assistant in that subnet, for instance with a dedicated VLAN.

## Installation

1. Use the **Open in HACS** button above, or add this repository by hand:
   HACS → Custom repositories → paste the repository URL, category **Integration**.
2. Install, restart Home Assistant.
3. Settings → Devices & services → Add integration → **Dolby DSS220**.
4. Enter the IP address of the server. Port 8080 is the default of the SMI web services.
   Choose whether Home Assistant may control the server.

The server is identified by the UUID it reports, so it is not added twice. To change the address
later, choose **Reconfigure** on the integration entry.

### Manual

Copy `custom_components/dolby_dss220` to the `custom_components` folder of your Home Assistant
configuration, restart Home Assistant and continue with step 3 above.

## Removal

1. Go to **Settings → Devices & services** and open **Dolby DSS220**.
2. Open the menu (three dots) next to the server and choose **Delete**.
3. To remove the files as well: in HACS, open **Dolby DSS220** and choose **Remove**, or delete
   `custom_components/dolby_dss220` for a manual installation. Restart Home Assistant afterwards.

Nothing is changed on the server itself.

## Polling

| Every | What |
| --- | --- |
| 5 seconds | Transport state, positions, selected show and clip, input |
| 30 seconds | Schedule mode, volume, mute, douser, lamp |
| 5 minutes | Show list, clock and time zone, components and alarms |

A newly selected show that is not yet in the show list triggers one extra show list request.
Clip names are cached. After every command the state is read again at once.

## Known limitations

- **Volume, mute, douser and lamp** are passed on by the server to the cinema processor and the
  projector it is set up to control. When the server has no such device configured, it answers
  with a fault and the entity becomes unavailable (the media player then offers no volume
  controls).
- **Seeking** positions within the current clip. The server positions within the whole show, so
  the integration adds the start of the current clip in the show to the position you choose.
- Changing the input is only possible when the media block supports it; the server refuses it
  otherwise and Home Assistant shows the error.
- The show list is read every 5 minutes. A show ingested in the meantime shows up in the source
  list at the next read, or at once after a command.
- The clock offset sensor only shows the difference. Set the clock and time zone of the server
  itself, for instance with an NTP server set in the `config` console.

## Diagnostics

Settings → Devices & services → Dolby DSS220 → menu → **Download diagnostics** gives the state as
the integration sees it, the components the server reports and the requests the server answers
with a fault. The IP address and the identifiers of the server are left out, so the file can be
attached to an issue.

## Network security

The SMI web services (TCP 8080) have **no password and no encryption**. Anyone who can reach them
can start, stop and select shows, with or without Home Assistant. This integration cannot change
that; the network has to. A sensible setup:

- Put the server, its media block and the projector in a VLAN of their own.
- Allow only the Home Assistant host (with a fixed IP address) to reach the server on
  **TCP 8080**. Home Assistant needs nothing else from it.
- Allow an admin workstation to reach the web interface of the server only, preferably from a
  management VLAN.
- Block everything else towards the server from other networks. Besides port 8080 the server
  runs a web interface, SSH and SNMP, among others.
- Give the server no internet access and never forward any of its ports from the internet.
  Keep guest and office Wi-Fi out of this VLAN.

What the integration does on its side:

- It opens no ports, webhooks or listeners; it only connects out to the server.
- Control is off until you switch it on (see [Control is opt-in](#control-is-opt-in)).
- Every value sent to the server is validated against the server's own schema and XML-escaped.
- Every answer is size-limited (4 MB), parsed with `defusedxml` and has a time limit; redirects
  are not followed.
- It sends one request at a time, and an unreachable server is tried once per polling interval.
- Diagnostics leave out the IP address and the identifiers of the server and its components.
- Every Home Assistant user, admin or not, can operate the server once control is on. Limit who
  has an account.

See [SECURITY.md](SECURITY.md) for reporting a vulnerability.

## Quality scale

This integration is aligned with the **Bronze** tier of the
[Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
Home Assistant only grades integrations that ship with Home Assistant itself, so this is a
self-assessment, not an official rating. The status per rule is recorded in
[`quality_scale.yaml`](custom_components/dolby_dss220/quality_scale.yaml).

One rule is deliberately not followed: *test-before-setup* asks an integration to hold back its
setup while the device does not answer. A cinema server switched off for the night is a normal
state, so the integration sets it up anyway and shows it as off (see
[Switched off is not an error](#switched-off-is-not-an-error)).

## Development

The tests use [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
and run on every push. To run them locally (Python 3.14):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

`tests/fixtures/` holds SOAP answers in the format of the server. `get_input_select.xml` was
captured from a DSS220 with a CAT745; the others follow the server's published schemas.

## Brand images

`custom_components/dolby_dss220/brand/` holds a plain, self-drawn cinema server icon. It is
deliberately generic: the Dolby marks belong to Dolby Laboratories and are not redistributed here.
Replace those files with your own if you have the right to use a manufacturer's artwork; see
`Brand/README.md` for the sizes.

## Disclaimer

This integration is an independent, community-made project. It is not affiliated with, endorsed
by, sponsored by or supported by Dolby Laboratories, Inc. or any of its subsidiaries. "Dolby",
"Show Store" and model names such as DSS200, DSS220 and CAT745 are trademarks of their respective
owners. They are used here only to describe which equipment the integration works with.

The integration is built from the interface the server publishes and provided as is, without
warranty of any kind (see the [license](LICENSE)). It starts, stops and selects shows and switches
the douser, lamp and inputs of real cinema equipment: check how it behaves on your own
installation before you rely on it during a screening. For help with the server itself, contact
Dolby or your dealer. Problems with this integration belong in this repository's issues, not with
them.

## License

MIT © 2026 Videobarista
