<div align="center">

# NOP — NikOmniPlayer

**A local audio/video player with built-in downloads, a system-wide equalizer, color correction and file conversion.**

[English](README.md) · [Русский](README.ru.md)

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6)
![Python](https://img.shields.io/badge/python-3.13-3776AB)
![GUI](https://img.shields.io/badge/GUI-PyQt6-41CD52)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)

[**⬇ Download the installer**](https://github.com/ChebNikit/NOP/releases/latest)

<img src="assets/screenshots/player.png" alt="NOP main window" width="760">

</div>

---

## Why NOP

One app instead of five: play your media, download new media, tune the sound, fix the picture and convert files — all in one small window.

## Features

- **Player** — audio and video, track list with search and filters, repeat one / shuffle / sequential, playback speed 0.5×–2×, remembers your position.
- **Downloads** — YouTube, TikTok, Instagram, Spotify and direct HTTP(S) links. Separate video resolution/profile and audio quality, `cookies.txt` support, a dedicated progress panel with speed, size and stage.
- **Equalizer** — two modes: *NOP only* (audio and video inside the player) or *Whole device* through [Equalizer APO](https://sourceforge.net/projects/equalizerapo/), so your browser and other apps get the same sound. Presets, custom bands, save/delete your own.
- **Video** — color correction, fullscreen with auto-hiding controls, and a compact **video-only mode** (256×144, always on top) toggled with a middle click on the video.
- **Video transcoding panel** (`Ctrl+Shift+T`) — re-encode videos to H.264, H.265/HEVC or VP9 in MP4, MOV, MKV, WebM or AVI at 720p, 1080p, 2K or 4K, with a choice of audio codec (AAC, Opus, MP3, FLAC, PCM or copy), hardware encoders (NVIDIA NVENC, Intel Quick Sync, AMD AMF), a preview, and pause/resume.
- **Converter** — convert audio and video with a live preview, plus documents, vector graphics, e-books and 3D models through bundled engines (FFmpeg, LibreOffice, Inkscape, calibre, Blender) in the installer build.
- **Customization** — Russian / English interface, five color themes (*Classic*, *Cosmic + Vanilla*, *Lavender + Violet*, *Jet Black / Orchid*, *Wine Ash / Turquoise*), independent panels you can show or hide.
- **Layout profiles** — "Listen", "Download" and "All" switch the set of panels in one click.

## Install (Windows 10 1809+ / Windows 11, x64)

1. Open the [**Releases**](https://github.com/ChebNikit/NOP/releases/latest) page.
2. Download the latest `NOP_Setup.exe`.
3. Run it and follow the installer.

> Windows 7 and 8 are not supported.

## Run from source

```bash
git clone https://github.com/ChebNikit/NOP.git
cd NOP
pip install -r requirements.txt
```

You also need **ffmpeg** and **deno** on your system:

```bash
winget install ffmpeg
winget install DenoLand.Deno
```

For the best video playback NOP uses **libmpv** (the mpv library); if it is not found, the player falls back to the built-in Qt/FFmpeg path.

Then start it:

```bash
python buildkit/source/NOP_1_1.py
```

## Build the Windows installer

The build kit lives in [`buildkit/`](buildkit). You need Windows 10 (1809+) or Windows 11 x64, an internet connection on the first run and about 25 GB of free disk space (about 8 GB without the conversion engines). Nothing has to be installed beforehand: the kit downloads a private Python, the libraries and the runtime components itself, checks every download against pinned SHA-256 hashes and changes nothing in your system.

```bat
cd buildkit
BUILD_NOP_SETUP.bat
```

The installer is written to `buildkit\dist\NOP_Setup.exe`, next to a `.sha256` file and `BUILD_REPORT.json`. The built application is self-tested before the installer is created; if the self-test fails, no installer is produced. Useful options: `--no-engines` (a lighter installer without the document, vector, e-book and 3D converters), `--offline`, `--clean`, `--from-step N`, `--verify-install` (on a test PC only). See [`buildkit/README.md`](buildkit/README.md) for details and troubleshooting, and [`buildkit/docs/VERIFICATION.md`](buildkit/docs/VERIFICATION.md) for what has and has not been tested.

The application source is `buildkit/source/NOP_1_1.py`. To build from your own modified copy: `BUILD_NOP_SETUP.bat --source "C:\path\to\NOP.py"`. The installer also includes [Equalizer APO](https://sourceforge.net/projects/equalizerapo/) 1.4.2 for the *Whole device* equalizer mode: the build downloads it, checks a pinned SHA-256 and embeds it, and `NOP_Setup.exe` runs it when APO is not already installed (Windows asks for administrator permission and the APO wizard asks you to choose your audio device). Publish the finished installer in **Releases**, not in the repository.

## Hotkeys

| Key | Action |
|---|---|
| `Space` | Pause / resume |
| `← / →` | Seek 5 seconds |
| `F11` | Fullscreen on / off |
| `Esc` | Exit video mode, or close the app |
| `Ctrl+T` | Track list |
| `Ctrl+E` | Equalizer |
| `Ctrl+D` | Download settings |
| `Ctrl+Shift+D` | Downloads progress panel |
| `Ctrl+Shift+V` | File converter |
| `Ctrl+Shift+T` | Video transcoding panel |
| `Ctrl+Shift+C` | Color correction |
| `Ctrl+S` | Seek bar |
| `Ctrl+H` | Button and volume panel |
| `Ctrl+R` | Window size panel |
| `Ctrl+P` | Always on top |
| `Ctrl+M` | Move window to screen center |
| `Ctrl+,` | App settings (language, theme) |
| `F1` | About |
| Right click | Context menu |
| Middle click on video | Compact video-only mode |

## Using the downloader

- Pick a service and link type, choose a folder and quality, then press the red **Download** button.
- Some sites require login: export your browser cookies to `cookies.txt` (for example with the *Get cookies.txt LOCALLY* extension) and select the file in the download settings.
- Spotify needs your own **Client ID** and an authorization step; the format and bitrate are set separately.
- Availability and quality depend on each service and can change over time. Downloads are handled by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [FFmpeg](https://github.com/FFmpeg/FFmpeg).

## Disclaimer

NOP is meant for personal use. You are responsible for what you download and for respecting the terms of the services and the rights of content owners in your country.

## Built with

[PyQt6](https://www.riverbankcomputing.com/software/pyqt/) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [FFmpeg](https://ffmpeg.org/) · [libmpv](https://mpv.io/) · [Equalizer APO](https://sourceforge.net/projects/equalizerapo/)

## License

Distributed under the **GNU GPL v3**. See [LICENSE](LICENSE).

## Support the project

NOP is free and open source. If it is useful to you, you can support its development:

<table>
<tr>
<td align="center"><img src="assets/donate_crypto_qr.jpg" width="200" alt="Ethereum QR code"><br><b>Ethereum</b></td>
<td align="center"><img src="assets/donate_ozon_qr.jpg" width="200" alt="Ozon Bank SBP QR code"><br><b>Ozon Bank (SBP, Russia)</b></td>
</tr>
</table>

- **Ethereum** (ETH and ERC-20 tokens on the Ethereum network): `0x5EDfAbe50567aD88b7bA3138E369a780Eb513A2C`
- **Ozon Bank** (SBP, for bank accounts in Russia): https://finance.ozon.ru/apps/sbp/ozonbankpay/01a162fe-be3f-7ff3-8cc6-7659ed88b12c

## Author

Made by **Nik**. If NOP is useful to you, star the repository and share it with a friend. ⭐
