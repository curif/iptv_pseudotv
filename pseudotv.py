
import argparse
import yaml
import sys
import random
import datetime
import time
import threading
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent
import yt_dlp
import subprocess
import xml.etree.ElementTree as ET
import os
from flask import Flask, Response, request, url_for

app = Flask(__name__)

# --- Configuration Loading ---
def load_config():
    config_path = os.environ.get('PSEUDOTV_CONFIG_PATH', 'config.yaml')
    print(f"Loading configuration from: {config_path}")
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {config_path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML configuration: {e}", file=sys.stderr)
        sys.exit(1)

CONFIG = load_config()

# --- EPG Generation Logic (to be run in background) ---
def fetch_videos(channel_url, playlist_end, min_duration=None, max_duration=None, sort_order='newest'):
    """Fetches, filters, and sorts video information from a YouTube channel URL."""
    processed_url = channel_url
    if "youtube.com/c/" in channel_url or "youtube.com/user/" in channel_url or "youtube.com/@" in channel_url:
        if "youtube.com/@" in channel_url:
            channel_handle = channel_url.split('@')[-1].split('/')[0]
            processed_url = f"https://www.youtube.com/@{channel_handle}/videos"
        elif "youtube.com/c/" in channel_url:
            channel_handle = channel_url.split('/c/')[-1].split('/')[0]
            processed_url = f"https://www.youtube.com/c/{channel_handle}/videos"
        elif "youtube.com/user/" in channel_url:
            channel_handle = channel_url.split('/user/')[-1].split('/')[0]
            processed_url = f"https://www.youtube.com/user/{channel_handle}/videos"

    ydl_opts = {
        'playlistend': playlist_end,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(processed_url, download=False)
            if 'entries' in result:
                entries = result['entries']
                if min_duration is not None:
                    entries = [e for e in entries if e.get('duration', 0) >= min_duration]
                if max_duration is not None:
                    entries = [e for e in entries if e.get('duration', 0) <= max_duration]
                if sort_order == 'oldest':
                    entries.reverse()
                elif sort_order == 'random':
                    random.shuffle(entries)
                return entries
    except Exception as e:
        print(f"Error fetching from {processed_url}: {e}", file=sys.stderr)
        if processed_url != channel_url:
            print(f"Attempting fallback to original URL: {channel_url}", file=sys.stderr)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(channel_url, download=False)
                    if 'entries' in result:
                        return result['entries']
            except Exception as e_fallback:
                print(f"Error fetching from original URL {channel_url}: {e_fallback}", file=sys.stderr)
    return []

def interleave_playlist(programs, publicity, programs_per_publicity):
    if not publicity or programs_per_publicity <= 0:
        return programs
    playlist = []
    for i, program in enumerate(programs):
        playlist.append(program)
        if (i + 1) % programs_per_publicity == 0:
            if publicity:
                playlist.append(random.choice(publicity))
    return playlist

def generate_programme_elements(root_element, channel_id, playlist, days, start_offset_time):
    if not playlist:
        return
    
    total_duration_seconds = sum(item.get('duration', 0) for item in playlist)
    if total_duration_seconds == 0: return

    # Calculate how many times the playlist needs to repeat to fill the EPG duration
    schedule_end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    remaining_time_to_fill = (schedule_end_time - start_offset_time).total_seconds()
    if remaining_time_to_fill <= 0: return

    repeat_count = int(remaining_time_to_fill / total_duration_seconds) + 1

    current_time = start_offset_time
    for _ in range(repeat_count):
        for item in playlist:
            duration = item.get('duration', 0)
            if duration == 0: continue
            end_time = current_time + datetime.timedelta(seconds=duration)
            programme_element = SubElement(root_element, 'programme', 
                                           start=current_time.strftime('%Y%m%d%H%M%S %z'),
                                           stop=end_time.strftime('%Y%m%d%H%M%S %z'),
                                           channel=channel_id)
            SubElement(programme_element, 'title').text = item.get('title', 'Untitled')
            SubElement(programme_element, 'desc').text = item.get('description', 'No description available.')
            SubElement(programme_element, 'video').set('src', f"https://www.youtube.com/watch?v={item.get('id')}")
            current_time = end_time

def create_epg(config):
    print(f"[{datetime.datetime.now()}] Starting EPG generation...")
    epg_config = config.get('epg', {})
    days_to_generate = epg_config.get('days', 2)
    output_file = epg_config.get('output_file', 'epg.xml')
    publicity_pools = config.get('publicity', {})
    all_channels = config.get('channels', [])

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    new_tv_element = Element('tv')

    # Preserve future programs and channel definitions from existing EPG
    existing_programs = {}
    if os.path.exists(output_file):
        try:
            tree = ET.parse(output_file)
            root = tree.getroot()
            for channel in root.findall('channel'):
                new_tv_element.append(channel)
                channel_id = channel.get('id')
                existing_programs[channel_id] = []
                for program in root.findall(f'.//programme[@channel="{channel_id}"]'):
                    stop_time = datetime.datetime.strptime(program.get('stop'), '%Y%m%d%H%M%S %z')
                    if stop_time > now_utc:
                        existing_programs[channel_id].append(program)
        except ET.ParseError:
            print(f"Could not parse existing EPG file: {output_file}. A new one will be created.", file=sys.stderr)
            existing_programs = {}

    for channel_config in all_channels:
        channel_id = channel_config['id']
        channel_name = channel_config['name']

        # If channel is new, add it to the EPG
        if new_tv_element.find(f'.//channel[@id="{channel_id}"]') is None:
            channel_element = SubElement(new_tv_element, 'channel', id=channel_id)
            SubElement(channel_element, 'display-name').text = channel_name

        # Add preserved future programs to the new EPG and find the last end time
        last_program_end_time = now_utc
        scheduled_video_ids = set()
        if channel_id in existing_programs:
            for program in existing_programs[channel_id]:
                new_tv_element.append(program)
                video_src_element = program.find('video')
                if video_src_element is not None:
                    video_src = video_src_element.get('src')
                    if 'v=' in video_src:
                        video_id = video_src.split('v=')[-1]
                        scheduled_video_ids.add(video_id)
                stop_time = datetime.datetime.strptime(program.get('stop'), '%Y%m%d%H%M%S %z')
                if stop_time > last_program_end_time:
                    last_program_end_time = stop_time

        print(f"Processing channel: {channel_name}. Preserved {len(scheduled_video_ids)} future programs. Generating new programs starting from {last_program_end_time}")
        
        # Fetch all available videos
        all_available_videos = []
        min_duration = channel_config.get('min_duration')
        max_duration = channel_config.get('max_duration')
        # Always fetch newest first to have a consistent base for sorting
        sort_order = channel_config.get('sort_order', 'newest')
        mixing_algorithm = channel_config.get('mixing_algorithm', 'concatenate')
        source_channels_videos = []
        for yt_channel_url in channel_config.get('youtube_channels', []):
            source_channels_videos.append(fetch_videos(yt_channel_url, 50, min_duration, max_duration, 'newest'))
        
        # Mix available videos before filtering
        if mixing_algorithm == 'interleave':
            max_len = max(len(v) for v in source_channels_videos) if source_channels_videos else 0
            for i in range(max_len):
                for videos in source_channels_videos:
                    if i < len(videos):
                        all_available_videos.append(videos[i])
        else: # Default to 'concatenate'
            for videos in source_channels_videos:
                all_available_videos.extend(videos)

        # Filter out already scheduled videos
        unscheduled_videos = [v for v in all_available_videos if v.get('id') not in scheduled_video_ids]

        # Sort the new, unscheduled videos
        if sort_order == 'oldest':
            unscheduled_videos.reverse() # Assumes fetch_videos returns newest first
        elif sort_order == 'random':
            random.shuffle(unscheduled_videos)

        # Fetch publicity videos
        publicity_videos = []
        publicity_pool_name = channel_config.get('publicity_pool')
        if publicity_pool_name and publicity_pool_name in publicity_pools:
            publicity_pool_config = publicity_pools[publicity_pool_name]
            pub_min_duration = publicity_pool_config.get('min_duration')
            pub_max_duration = publicity_pool_config.get('max_duration')
            for yt_channel_url in publicity_pool_config.get('youtube_channels', []):
                publicity_videos.extend(fetch_videos(yt_channel_url, 50, pub_min_duration, pub_max_duration, 'random'))
        
        # Create new playlist from unscheduled videos and generate programme elements
        new_playlist = interleave_playlist(unscheduled_videos, publicity_videos, channel_config.get('programs_per_publicity', 0))
        generate_programme_elements(new_tv_element, channel_id, new_playlist, days_to_generate, last_program_end_time)

    # Write the new EPG file
    tree = ElementTree(new_tv_element)
    indent(tree, space="  ", level=0)
    tree.write(output_file, encoding='UTF-8', xml_declaration=True)
    print(f"[{datetime.datetime.now()}] EPG generation complete.")

def background_epg_generator():
    """A background thread function to periodically generate the EPG."""
    interval_hours = CONFIG.get('epg', {}).get('refresh_interval_hours', 12)
    interval_seconds = interval_hours * 3600
    while True:
        create_epg(CONFIG)
        print(f"Next EPG refresh scheduled in {interval_hours} hours.")
        time.sleep(interval_seconds)

# --- Flask Web Server ---
@app.route('/epg.xml')
def serve_epg():
    epg_file = CONFIG.get('epg', {}).get('output_file', 'epg.xml')
    try:
        with open(epg_file, 'r') as f:
            return Response(f.read(), mimetype='application/xml')
    except FileNotFoundError:
        return "EPG not found. It may be generating. Please try again in a moment.", 404

@app.route('/m3u')
def serve_m3u():
    m3u_content = "#EXTM3U\n\n"
    for channel in CONFIG.get('channels', []):
        channel_id = channel['id']
        channel_name = channel['name']
        group_title = channel.get('group_title', 'Other') # Default to 'Other' if not specified
        stream_url = url_for('stream_channel', channel_id=channel_id, _external=True)
        m3u_content += f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{channel_name}" group-title="{group_title}",{channel_name}\n'
        m3u_content += f'{stream_url}\n'
    return Response(m3u_content, mimetype='application/vnd.apple.mpegurl')

@app.route('/stream/<channel_id>')
def stream_channel(channel_id):
    def generate_stream(channel_id):
        epg_file = CONFIG.get('epg', {}).get('output_file', 'epg.xml')
        try:
            tree = ET.parse(epg_file)
            root = tree.getroot()
        except (FileNotFoundError, ET.ParseError):
            # EPG should be available due to initial generation, but handle error gracefully
            print(f"Could not find or parse EPG file {epg_file}. Aborting stream.", file=sys.stderr)
            return

        channel_programs = []
        for program_element in root.findall('programme'):
            if program_element.get('channel') == channel_id:
                video_element = program_element.find('video')
                if video_element is not None:
                    channel_programs.append({
                        'start': program_element.get('start'),
                        'stop': program_element.get('stop'),
                        'title': program_element.find('title').text if program_element.find('title') is not None else 'Untitled',
                        'url': video_element.get('src')
                    })
        channel_programs.sort(key=lambda x: x['start'])
        channel_config = next((c for c in CONFIG['channels'] if c['id'] == channel_id), None)
        if not channel_config:
            print(f"Channel ID '{channel_id}' not found in configuration.", file=sys.stderr)
            return

        quality_setting = channel_config.get('quality', 'best')
        output_config = channel_config.get('output', {})
        resolution = output_config.get('resolution', '1280x720')
        framerate = output_config.get('framerate', 30)
        video_bitrate = output_config.get('video_bitrate', '4M')
        audio_bitrate = output_config.get('audio_bitrate', '192k')

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        start_index = 0
        seek_time = 0
        for i, program in enumerate(channel_programs):
            start_time = datetime.datetime.strptime(program['start'], '%Y%m%d%H%M%S %z')
            stop_time = datetime.datetime.strptime(program['stop'], '%Y%m%d%H%M%S %z')
            if start_time <= now_utc < stop_time:
                start_index = i
                seek_time = (now_utc - start_time).total_seconds()
                break

        for i in range(start_index, len(channel_programs)):
            program = channel_programs[i]
            video_url = program['url']
            try:
                ydl_opts = {'format': quality_setting, 'quiet': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    stream_url = info['url']

                ffmpeg_cmd = [
                    'ffmpeg',
                    '-i', stream_url,
                    '-c:v', 'libx264',
                    '-s', resolution,
                    '-r', str(framerate),
                    '-b:v', video_bitrate,
                    '-c:a', 'aac',
                    '-b:a', audio_bitrate,
                    '-f', 'mpegts',
                    'pipe:1'
                ]
                if i == start_index and seek_time > 0:
                    ffmpeg_cmd.insert(1, '-ss')
                    ffmpeg_cmd.insert(2, str(seek_time))
                process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                while True:
                    chunk = process.stdout.read(1024)
                    if not chunk:
                        break
                    yield chunk
                process.wait()
            except Exception as e:
                print(f"Error streaming '{program['title']}': {e}", file=sys.stderr)
                continue

    return Response(generate_stream(channel_id), mimetype='video/MP2T')

def main():
    parser = argparse.ArgumentParser(description='PseudoTV Server.')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind the server to.')
    parser.add_argument('--port', type=int, default=5004, help='Port to run the server on.')
    parser.add_argument('--create_epg_only', action='store_true', help='Generate the EPG and exit.')
    args = parser.parse_args()

    if args.create_epg_only:
        create_epg(CONFIG)
        sys.exit(0)

    # Check for existing EPG file on startup
    epg_file = CONFIG.get('epg', {}).get('output_file', 'epg.xml')
    if not os.path.exists(epg_file):
        print("No existing EPG found. Performing initial EPG generation synchronously...")
        create_epg(CONFIG)
    else:
        print(f"Using existing EPG file: {epg_file}. Background refresh will update it.")

    # Start the background thread for periodic EPG refreshes
    epg_thread = threading.Thread(target=background_epg_generator, daemon=True)
    epg_thread.start()
    print("Background EPG refresh thread started.")

    # Start the Flask server
    app.run(host=args.host, port=args.port)

if __name__ == '__main__':
    main()
