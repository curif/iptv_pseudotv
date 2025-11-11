# PseudoTV - Your Personal IPTV Server

PseudoTV is a Python-based IPTV server that creates live TV channels from YouTube content. It generates a standard M3U playlist and an XMLTV EPG, allowing you to create your own custom channels and watch them in any compatible IPTV player.

## Features

- **Dynamic Channel Creation:** Create custom channels from multiple YouTube sources.
- **EPG Generation:** Automatically generates a multi-day XMLTV-compatible Electronic Program Guide.
- **Publicity/Ad Interleaving:** Interleave publicity or ad videos between regular programs.
- **Configurable Video Mixing:** Choose between different algorithms for mixing videos from source channels (`concatenate` or `interleave`).
- **Configurable Sorting:** Sort videos by newest, oldest, or random order.
- **Duration Filtering:** Filter out videos that are too short or too long.
- **Per-Channel Output Format:** Define the output resolution, framerate, and bitrate for each channel individually.
- **Stable Streaming:** Re-encodes all videos to a consistent format for maximum compatibility with IPTV clients.
- **Background EPG Refresh:** Automatically refreshes the EPG at a configurable interval.
- **Web-Based API:** Provides standard M3U and EPG endpoints for easy integration.
- **Docker Support:** Includes a Dockerfile for easy deployment.

## Configuration

The entire system is configured through the `config.yaml` file. Below is a detailed explanation of each section and its parameters.

### `epg` Section

This section controls the Electronic Program Guide generation.

-   `days` (integer, default: `2`): The number of days for which the EPG schedule will be generated.
-   `output_file` (string, default: `"epg.xml"`): The name of the XMLTV file where the EPG data will be saved.
-   `refresh_interval_hours` (integer, default: `12`): How often (in hours) the EPG will be regenerated in the background.
-   `max_videos_per_source` (integer, optional, default: `50`): The maximum number of videos to fetch from each YouTube channel source during EPG generation. Lowering this value can significantly speed up EPG generation.

### `cache` Section

This section configures the caching behavior for YouTube video metadata, significantly speeding up EPG generation by reducing repeated calls to YouTube.

-   `ttl_hours` (integer, default: `0`): The default Time To Live (TTL) in hours for cached video metadata. If set to `0` or omitted, caching is effectively disabled globally.

### `publicity` Section

This section defines pools of YouTube channels that will be used for publicity/ad videos.

-   `[pool_name]` (object): A custom name for your publicity pool (e.g., `general_ads`).
    -   `min_duration` (integer, optional): Minimum duration (in seconds) for publicity videos to be considered.
    -   `max_duration` (integer, optional): Maximum duration (in seconds) for publicity videos to be considered.
    -   `youtube_channels` (list of strings): A list of YouTube channel URLs or handles (e.g., `https://www.youtube.com/@YourAdChannel`) from which to fetch publicity videos.
    -   `max_videos_per_source` (integer, optional): Overrides the global `epg.max_videos_per_source` for this specific publicity pool.
    -   `cache` (boolean, optional, default: `false`): Set to `true` to enable caching for this publicity pool.
    -   `cache_ttl_hours` (integer, optional): Overrides the global `cache.ttl_hours` for this specific publicity pool.

### `channels` Section

This is a list of your custom TV channels. Each item in the list represents one channel.

-   `id` (string, **required**): A unique identifier for the channel (e.g., `"news-channel"`). This ID is used in the M3U playlist and stream URLs.
-   `name` (string, **required**): The display name of the channel (e.g., `"Global News"`).
-   `group_title` (string, optional, default: `"Other"`): A category name for the channel (e.g., `"News"`, `"Technology"`). Used by IPTV clients to group channels in the M3U playlist.
-   `quality` (string, optional, default: `"best"`): A `yt-dlp` format selector string to specify the desired quality of the source YouTube videos (e.g., `"best[height<=720]"` for 720p, `"bestaudio"` for audio-only).
-   `mixing_algorithm` (string, optional, default: `"concatenate"`): How videos from multiple `youtube_channels` for this program channel are combined.
    -   `"concatenate"`: Appends videos from each source channel in the order they are listed.
    -   `"interleave"`: Takes one video from each source channel in a round-robin fashion for a more dynamic mix.
-   `sort_order` (string, optional, default: `"newest"`): How the fetched videos are sorted.
    -   `"newest"`: Sorts videos from newest to oldest.
    -   `"oldest"`: Sorts videos from oldest to newest.
    -   `"random"`: Randomizes the order of videos.
-   `programs_per_publicity` (integer, optional, default: `0`): After how many regular programs a random publicity video should be inserted. Set to `0` or omit for no publicity.
-   `publicity_pool` (string, optional): The name of the publicity pool (defined in the `publicity` section) to use for this channel.
-   `epg_refresh_strategy` (string, optional, default: `'roll'`): Determines how the channel's EPG is handled during a scheduled background refresh.
    -   `'roll'`: Preserves future programs from the previous EPG, only adding new programs after the last scheduled event.
    -   `'rebuild'`: Completely erases all existing programs for the channel and rebuilds the schedule from scratch. This is ideal for channels where content freshness is critical, like news.
-   `min_duration` (integer, optional): Minimum duration (in seconds) for program videos to be considered.
-   `max_duration` (integer, optional): Maximum duration (in seconds) for program videos to be considered.
-   `max_videos_per_source` (integer, optional): Overrides the global `epg.max_videos_per_source` for this specific channel.
-   `cache` (boolean, optional, default: `false`): Set to `true` to enable caching for this channel.
-   `cache_ttl_hours` (integer, optional): Overrides the global `cache.ttl_hours` for this specific channel.
-   `match_title` (string, optional): A case-insensitive regular expression to filter videos by their title. Only videos whose titles match this pattern will be included. For example, `impro` will match any video with "impro" in the title.
-   `date_after` (string, optional): Filters videos to include only those uploaded after a specific date. The date can be in two formats:
    -   **Absolute:** `YYYYMMDD` (e.g., `20230101` for January 1st, 2023).
    -   **Relative:** A duration from the current time, such as `now-1y` (one year), `now-6m` (six months), or `now-3d` (three days).
-   `date_before` (string, optional): Filters videos to include only those uploaded before a specific date. It follows the same formats as `date_after` (e.g., `20231231` or `now-1w`). Use `date_after` and `date_before` together to create a specific time window.
-   `output` (object, **required**): Defines the stable output format for this channel's stream. All videos will be re-encoded to these specifications for consistent playback across IPTV clients.
    -   `resolution` (string, default: `"1280x720"`): The output video resolution (e.g., `"1920x1080"`, `"640x360"`).
    -   `framerate` (integer, default: `30`): The output video frame rate (e.g., `25`, `30`).
    -   `video_bitrate` (string, default: `"4M"`): The output video bitrate (e.g., `"2M"`, `"6M"`).
    -   `audio_bitrate` (string, default: `"192k"`): The output audio bitrate (e.g., `"128k"`, `"256k"`).
-   `youtube_channels` (list of strings, **required**): A list of YouTube channel URLs or handles from which to fetch program videos for this channel.

## Installation and Usage

### Prerequisites

- Python 3.x
- `ffmpeg`

### Manual Installation

1.  **Create a virtual environment:**
    ```bash
    python3 -m venv venv
    ```

2.  **Install dependencies:**
    ```bash
    venv/bin/pip install -r requirements.txt
    ```

3.  **Run the server:**
    ```bash
    venv/bin/python pseudotv.py
    ```

### Command-line Arguments

The application accepts the following arguments for managing the EPG manually:

-   `--create-epg`: Generates a completely new EPG for all channels based on your `config.yaml` and then exits.
    ```bash
    python pseudotv.py --create-epg
    ```

-   `--update-channel <channel_id>`: Recreates the schedule for a single, specific channel without affecting any other channels in the EPG. This is useful for refreshing one channel quickly. The existing schedule for the target channel will be cleared and replaced.
    ```bash
    python pseudotv.py --update-channel news-channel
    ```

### Docker Installation (with docker-compose)

This is the recommended method for running the server with Docker, as it makes managing configuration and data persistence easier.

1.  **Create a data directory:**
    ```bash
    mkdir data
    ```

2.  **Edit `config.yaml`:** Modify the `config.yaml` file on your host machine to your liking.

3.  **Run with docker-compose:**
    ```bash
    docker-compose up -d
    ```

    The `docker-compose.yml` file is configured to:
    -   Mount your local `config.yaml` into the container.
    -   Mount the `./data` directory to persist the generated EPG file.
    -   Set the `PSEUDOTV_DATA_PATH` environment variable so the application knows where to store the EPG.

### Docker Installation (manual)

1.  **Build the Docker image:**
    ```bash
    docker build -t pseudotv .
    ```

2.  **Run the Docker container:**
    ```bash
    docker run -d -p 5004:5004 --name pseudotv pseudotv
    ```

### Manual EPG Generation

You can generate or update the EPG once without starting the full web server, which is useful for initial setup or debugging.

**Using `docker-compose` (recommended):**

-   **Create the full EPG:**
    ```bash
    docker-compose run --rm pseudotv python pseudotv.py --create-epg
    ```

-   **Update a single channel:**
    ```bash
    docker-compose run --rm pseudotv python pseudotv.py --update-channel news-channel
    ```

**Using `docker run` (if not using docker-compose):**

-   **Create the full EPG:**
    ```bash
    docker run --rm -v $(pwd)/config.yaml:/app/config.yaml -v $(pwd):/app -e PSEUDOTV_CONFIG_PATH=/app/config.yaml pseudotv python pseudotv.py --create-epg
    ```

-   **Update a single channel:**
    ```bash
    docker run --rm -v $(pwd)/config.yaml:/app/config.yaml -v $(pwd):/app -e PSEUDOTV_CONFIG_PATH=/app/config.yaml pseudotv python pseudotv.py --update-channel news-channel
    ```

## Accessing Your Channels

Once the server is running, you can use the following URLs in your IPTV player or management software:

-   **M3U Playlist:** `http://<your-server-ip>:5004/m3u`
-   **EPG:** `http://<your-server-ip>:5004/epg.xml`

Replace `<your-server-ip>` with the IP address of the machine running the server.
