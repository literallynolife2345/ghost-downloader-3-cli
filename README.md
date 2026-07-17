# Ghost Downloader 3 CLI (`gd3`)
Entirely vibe-coded if you cant tell

Multi-protocol downloader CLI powered by the [Ghost Downloader 3](https://github.com/XiaoYouChR/Ghost-Downloader-3) engine, designed for headless/terminal use.

## Install

```bash
pip install ghost-downloader-3-cli
```

Or with BitTorrent support:

```bash
pip install "ghost-downloader-3-cli[bittorrent]"
```

Requires Python 3.11+. Works on Windows, macOS, and Linux.

## Quick start

```bash
# Download a file
gd3 download https://example.com/video.mp4

# Download to a specific folder and wait for completion
gd3 download https://youtube.com/watch?v=... -o ~/Videos --wait

# Batch download from a URL list
gd3 batch urls.txt

# See what's installed
gd3 info
gd3 list-packs
```

## Usage

```
gd3 download <url> [options]
gd3 batch <file> [options]
gd3 list-packs
gd3 info
gd3 config [key] [value]
```

### `download` / `dl`

Download a single URL.

| Option | Shorthand | Description |
|--------|-----------|-------------|
| `--output DIR` | `-o` | Output directory (default: config `downloadFolder`) |
| `--name NAME` | `-n` | Override filename |
| `--client-profile PROFILE` | `-p` | Browser fingerprint (auto, chrome, firefox, safari, raw) |
| `--wait` | | Wait for download to finish |
| `--timeout SEC` | | Max wait time (0 = unlimited, default: wait forever) |
| `--dry-run` | | Parse URL and show info, but don't download |

### `batch` / `b`

Download multiple URLs from a file (one per line, `#` for comments).

```
gd3 batch urls.txt -o ./downloads
```

### `config` / `c`

Show or set configuration:

```bash
gd3 config                    # list all settings
gd3 config downloadFolder     # show a single value
gd3 config downloadFolder ~/Downloads  # set a value
```

Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `downloadFolder` | `~/Downloads` | Default output directory |
| `maxTaskNum` | `3` | Concurrent downloads |
| `proxyServer` | `Auto` | Proxy (`http://...`, `socks5://...`, or `Auto`/`None`) |
| `isSpeedLimitEnabled` | `False` | Enable download speed limit |
| `speedLimitation` | `4194304` | Speed limit in bytes/sec (4 MB/s) |
| `clientProfile` | `auto` | Browser fingerprint |
| `shouldVerifySsl` | `False` | Verify SSL certificates |

### `info` / `i`

Show engine version, loaded feature packs, and registered runtimes.

### `list-packs` / `lp`

List all loaded feature packs and their URL parsers.

## Protocols

| Protocol | Pack | Notes |
|----------|------|-------|
| HTTP/HTTPS | `http_pack` | Full range-request support, multi-segment download |
| FTP/FTPS | `ftp_pack` | |
| BitTorrent / Magnet | `bittorrent_pack` | Requires `libtorrent` (`pip install .[bittorrent]`) |
| HLS / M3U8 | `m3u8_pack` | Stream download, live recording |
| MPEG-DASH | `m3u8_pack` | |
| eD2k / eMule | `ed2k_pack` | Requires `goed2kd` runtime |
| YouTube | `yt-dlp_pack` | Delegates to `yt-dlp` (auto-installs) |
| Bilibili | `bili_pack` | |
| GitHub Releases | `github_pack` | |
| HuggingFace | `huggingface_pack` | Model/dataset downloads |
| FFmpeg | `ffmpeg_pack` | Merge/transcode steps (uses system `ffmpeg`) |
| Disk copy | `disk_pack` | Local file copying |

Missing packs are skipped gracefully with a warning — you don't need every runtime installed.

## Configuration file

`gd3` stores config at:

- **Linux/macOS:** `~/.config/ghost-downloader-3/config.json`
- **Windows:** `%USERPROFILE%\.config\ghost-downloader-3\config.json`

It's a plain JSON file — edit it directly if you prefer.

## CLI vs GUI

Ghost Downloader 3 is also available as a [PySide6 Qt GUI application](https://github.com/XiaoYouChR/Ghost-Downloader-3). This CLI edition:

- Shares **the same download engine** — all `features/*/task.py` files are unchanged
- Replaces PySide6 with lightweight compatibility modules — no Qt runtime needed
- Replaces Qt services (`QObject`, `QTimer`, `QThread`) with pure asyncio
- Omits GUI-only files (`app/view/`, `app/assets/`, `app/startup.py`, etc.)
- Omits the Jack Yao OS catalog pack (depends on the removed `app.view` module)

## Development

```bash
git clone https://github.com/literallynolife2345/ghost-downloader-3-cli
cd ghost-downloader-3-cli
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate # Linux/macOS
pip install -e .
```

To include BitTorrent support:

```bash
pip install -e ".[bittorrent]"
```

## License

GNU General Public License v3.0 — same as the original project.
