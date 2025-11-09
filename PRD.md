
# Product Requirements Document: PseudoTV IPTV System

**Author:** Gemini

**Date:** 2025-11-08

## 1. Introduction

PseudoTV is a Python-based IPTV system designed to create and stream television-like channels from YouTube content. The system will function as a single, parametrized script capable of generating an Electronic Program Guide (EPG) and streaming the content of a specified channel. The core idea is to simulate a CCTV broadcast, where channels are curated playlists of YouTube videos from various sources.

## 2. Goals and Objectives

*   To create a lightweight, command-line-driven IPTV system.
*   To provide a flexible way to create custom TV channels from existing YouTube content.
*   To generate a standard EPG that can be consumed by IPTV players.
*   To offer a continuous, uninterrupted stream for each channel, seamlessly transitioning between videos.

## 3. Target Audience

*   **Hobbyists and Media Enthusiasts:** Individuals interested in creating their own custom TV channels for personal use.
*   **Developers:** Programmers looking for a simple, scriptable IPTV solution to integrate into other projects.

## 4. Features

### 4.1. EPG Generation

*   The system generates an EPG in XMLTV format.
*   EPG generation runs as a background task at a configurable interval (e.g., every 12 hours).
*   An initial EPG generation is performed synchronously on server startup to ensure immediate availability.

### 4.2. Content Streaming

*   The system will be able to stream a single channel at a time.
*   Streaming will be initiated by the `--stream <channel_id>` command-line parameter.
*   The stream will be a continuous pipe of video data, allowing external programs (like FFmpeg or a media player) to consume it.
*   The system will handle the transition between videos in the schedule internally, ensuring a seamless viewing experience.

### 4.3. Publicity Interleaving

*   The system can be configured to interleave publicity videos (like commercials or propaganda) between regular program videos.
*   Publicity videos are sourced from dedicated YouTube channels, defined in configurable pools.
*   The frequency of publicity breaks (e.g., one publicity video after every 3 regular programs) is configurable per channel.

### 4.4. Program Duration Filtering

*   Each channel can be configured with an optional minimum and maximum duration (in seconds) to filter out videos that are too short or too long.

### 4.5. Configurable Program Mixing

*   Each channel can be configured with a `mixing_algorithm` to control how videos from different source YouTube channels are ordered.
    *   `concatenate`: Appends the list of videos from each source channel one after the other (default).
    *   `interleave`: Creates a more dynamic mix by taking one video from each source channel in a round-robin fashion.

### 4.6. Configurable Video Sorting

*   Each channel can be configured with a `sort_order` parameter to control the order of videos fetched from YouTube.
    *   `newest`: Sorts videos from newest to oldest (default).
    *   `oldest`: Sorts videos from oldest to newest.
    *   `random`: Randomizes the order of the videos.

### 4.8. Channel Grouping

*   Channels can be organized into groups (e.g., "News", "Adults") within the M3U playlist using the `group-title` attribute, allowing for better organization in IPTV clients.

### 4.9. Configuration

*   All system and channel configuration will be managed through a single YAML file (e.g., `config.yaml`).
*   The configuration will support defining multiple channels.
*   For each channel, users can specify a list of YouTube channel URLs or IDs, an optional `quality` parameter to control the stream resolution (e.g., `best[height<=720]`), and optional `min_duration` and `max_duration` parameters.

## 6. Configuration (`config.yaml`)

The `config.yaml` file will have a structure similar to this:

```yaml
epg:
  # Number of days to generate the EPG for
  days: 2
  # Path to save the EPG file
  output_file: "epg.xml"

publicity:
  # Define pools of publicity videos
  news_ads:
    youtube_channels:
      - "https://www.youtube.com/c/PublicityChannel1"
      - "https://www.youtube.com/c/PublicityChannel2"
  music_ads:
    youtube_channels:
      - "https://www.youtube.com/c/PublicityChannel3"

channels:
  - id: "news-channel"
    name: "News Channel"
    quality: "best[height<=720]"
    # Play one publicity video after every 3 regular programs
    programs_per_publicity: 3
    # Use the 'news_ads' publicity pool for this channel
    publicity_pool: "news_ads"
    youtube_channels:
      - "https://www.youtube.com/c/NewsChannel1"
      - "https://www.youtube.com/c/NewsChannel2"

  - id: "music-channel"
    name: "Music Channel"
    quality: "best[height<=1080]"
    # Play one publicity video after every 5 regular programs
    programs_per_publicity: 5
    # Use the 'music_ads' publicity pool for this channel
    publicity_pool: "music_ads"
    youtube_channels:
      - "https://www.youtube.com/user/MusicUser1"
      - "https://www.youtube.com/user/MusicUser2"

  - id: "no-ads-channel"
    name: "No-Ads Channel"
    # This channel will have no publicity as the parameters are omitted
    youtube_channels:
      - "https://www.youtube.com/user/NoAdsUser"
```

## 7. API Specification

While the primary trigger for EPG generation is a command-line argument, the system will expose a simple HTTP endpoint to generate and serve the EPG on demand.

*   **Endpoint:** `/epg.xml`
*   **Method:** `GET`
*   **Response:** The EPG in XMLTV format.

This allows IPTV players to fetch the EPG over the network.

## 8. Streaming Mechanism

The streaming will be achieved by:

1.  When a stream is initiated, the system will check the EPG to find the currently scheduled program. It will then calculate the time offset and start the stream from the correct point in the video, simulating a live broadcast.
2.  Fetching the direct streamable URL for a YouTube video using the configured quality settings.
3.  Using `ffmpeg` to re-encode the video to a standard, consistent format (e.g., 720p, 30fps) defined in each channel's configuration. This ensures a stable stream for all IPTV clients, regardless of the source video's properties.
4.  Piping the re-encoded video as an MPEG Transport Stream to standard output.

## 9. Out of Scope

*   **User Interface:** This is a command-line-only tool. No graphical user interface will be developed.
*   **Content Re-encoding:** The system will avoid computationally intensive re-encoding of video and audio streams. However, it will perform intelligent format selection and lightweight remuxing (changing container format without re-encoding) to ensure a standardized output stream (e.g., MP4 container with H.264 video and AAC audio) for external consumption.
*   **Authentication:** The system will only work with public YouTube channels and videos. No support for private content or user authentication will be included in the initial version.
*   **Real-time EPG Updates:** The EPG is generated on demand and is static until the next generation. It will not update in real-time.

## 10. Future Enhancements

*   **Support for other video platforms:** (e.g., Vimeo, Dailymotion).
*   **Live-streaming support:** Ability to include live streams in the channel lineup.
*   **EPG Caching:** Caching the EPG to reduce generation time.
*   **Dockerization:** Providing a Docker image for easy deployment.
