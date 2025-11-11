import argparse
import yaml
import sys
import random
import datetime
import time
import threading
import queue
import json
import hashlib
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
DATA_PATH = os.environ.get('PSEUDOTV_DATA_PATH', '.')

# --- EPG Generation Logic (to be run in background) ---
def fetch_videos(channel_url, playlist_end, min_duration=None, max_duration=None, sort_order='newest', match_title=None, date_after=None, date_before=None, cache_enabled=False, cache_ttl_hours=0):
    """Fetches, filters, and sorts video information from a YouTube channel URL, with optional caching."""

    def _match_filter(info_dict):
        """yt-dlp filter function to exclude videos based on various criteria."""
        if info_dict.get('live_status') == 'is_upcoming':
            return False
        
        duration = info_dict.get('duration')
        if duration:
            if min_duration is not None and duration < min_duration:
                return False
            if max_duration is not None and duration > max_duration:
                return False
        
        return True

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

    cache_file_path = None
    if cache_enabled and cache_ttl_hours > 0:
        # Create a unique cache file name based on the URL and filters
        cache_key = f"{processed_url}-{playlist_end}-{min_duration}-{max_duration}-{sort_order}-{match_title}-{date_after}-{date_before}"
        cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()
        cache_file_path = os.path.join(DATA_PATH, f"cache_{cache_hash}.json")

        if os.path.exists(cache_file_path):
            try:
                with open(cache_file_path, 'r') as f:
                    cache_data = json.load(f)
                cache_timestamp = datetime.datetime.fromisoformat(cache_data['timestamp'])
                if (datetime.datetime.now() - cache_timestamp).total_seconds() < cache_ttl_hours * 3600:
                    print(f"[{datetime.datetime.now()}] Using cached data for {processed_url}")
                    return cache_data['videos']
                else:
                    print(f"[{datetime.datetime.now()}] Cache expired for {processed_url}")
            except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
                print(f"[{datetime.datetime.now()}] Error reading cache file {cache_file_path}: {e}. Re-fetching.", file=sys.stderr)

    ydl_opts = {
        'playlistend': playlist_end,
        'quiet': True,
        'no_warnings': True,
        'match_filter': _match_filter,
    }
    if match_title:
        ydl_opts['matchtitle'] = match_title
    if date_after:
        ydl_opts['dateafter'] = date_after
    if date_before:
        ydl_opts['datebefore'] = date_before

    try:
        print(f"[{datetime.datetime.now()}] Fetching from: {processed_url} (sort_order: {sort_order})")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(processed_url, download=False)
            if 'entries' in result:
                entries = result['entries']
                print(f"[{datetime.datetime.now()}] Fetched {len(entries)} raw videos from {processed_url}")

                # Save to cache if enabled
                if cache_enabled and cache_file_path:
                    cache_data = {
                        'timestamp': datetime.datetime.now().isoformat(),
                        'videos': entries
                    }
                    try:
                        with open(cache_file_path, 'w') as f:
                            json.dump(cache_data, f)
                        print(f"[{datetime.datetime.now()}] Saved data to cache: {cache_file_path}")
                    except IOError as e:
                        print(f"[{datetime.datetime.now()}] Error writing cache file {cache_file_path}: {e}", file=sys.stderr)

                return entries
    except Exception as e:
        print(f"[{datetime.datetime.now()}] Error fetching from {processed_url}: {e}", file=sys.stderr)
        if processed_url != channel_url:
            print(f"[{datetime.datetime.now()}] Attempting fallback to original URL: {channel_url}", file=sys.stderr)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(channel_url, download=False)
                    if 'entries' in result:
                        entries = result['entries']
                        print(f"[{datetime.datetime.now()}] Fetched {len(entries)} raw videos from fallback {channel_url}")

                        # Save to cache if enabled (for fallback URL too)
                        if cache_enabled and cache_file_path:
                            cache_data = {
                                'timestamp': datetime.datetime.now().isoformat(),
                                'videos': entries
                            }
                            try:
                                with open(cache_file_path, 'w') as f:
                                    json.dump(cache_data, f)
                                print(f"[{datetime.datetime.now()}] Saved data to cache (fallback): {cache_file_path}")
                            except IOError as e:
                                print(f"[{datetime.datetime.now()}] Error writing cache file {cache_file_path}: {e}", file=sys.stderr)
                        return entries
            except Exception as e_fallback:
                print(f"[{datetime.datetime.now()}] Error fetching from original URL {channel_url}: {e_fallback}", file=sys.stderr)
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
            
            if item.get('is_ad'):
                SubElement(programme_element, 'title').text = 'Commercial Break'
                SubElement(programme_element, 'desc').text = 'Commercials'
            else:
                SubElement(programme_element, 'title').text = item.get('title', 'Untitled')
                SubElement(programme_element, 'desc').text = item.get('description', 'No description available.')
            
            SubElement(programme_element, 'video').set('src', f"https://www.youtube.com/watch?v={item.get('id')}")
            current_time = end_time

def create_epg(config, target_channel_id=None):
    if target_channel_id:
        print(f"[{datetime.datetime.now()}] Starting EPG update for channel: {target_channel_id}...")
    else:
        print(f"[{datetime.datetime.now()}] Starting full EPG generation...")

        epg_config = config.get('epg', {})
        days_to_generate = epg_config.get('days', 2)
        output_file_name = epg_config.get('output_file', 'epg.xml')
        output_file = os.path.join(DATA_PATH, output_file_name)
        publicity_pools = config.get('publicity', {})
        all_channels = config.get('channels', [])
    
        # Get global cache settings
        global_cache_config = config.get('cache', {})
        global_cache_ttl_hours = global_cache_config.get('ttl_hours', 0) # Default to 0 (no caching)
    
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        new_tv_element = Element('tv')
    
        # --- Step 1: Parse existing EPG and preserve what's needed ---
        if os.path.exists(output_file):
            print(f"[{datetime.datetime.now()}] Found existing EPG file: {output_file}. Parsing...")
            try:
                tree = ET.parse(output_file)
                root = tree.getroot()
                # Always preserve all channel definitions
                for channel in root.findall('channel'):
                    new_tv_element.append(channel)
    
                # Preserve programs based on the operation mode
                for program in root.findall('programme'):
                    # If updating a single channel, keep all programs from OTHER channels
                    if target_channel_id and program.get('channel') != target_channel_id:
                        new_tv_element.append(program)
                    # If doing a full refresh, check the channel's refresh strategy
                    elif not target_channel_id:
                        channel_id_of_program = program.get('channel')
                        channel_config_of_program = next((c for c in all_channels if c.get('id') == channel_id_of_program), None)
                        
                        refresh_strategy = 'roll' # Default strategy
                        if channel_config_of_program:
                            refresh_strategy = channel_config_of_program.get('epg_refresh_strategy', 'roll')

                        # Only preserve future programs if the strategy is 'roll'
                        if refresh_strategy == 'roll':
                            stop_time = datetime.datetime.strptime(program.get('stop'), '%Y%m%d%H%M%S %z')
                            if stop_time > now_utc:
                                new_tv_element.append(program)    
            except ET.ParseError:
                print(f"[{datetime.datetime.now()}] Could not parse existing EPG file. A new one will be created.", file=sys.stderr)
    
        # --- Step 2: Determine which channels to process ---
        if target_channel_id:
            channels_to_process = [c for c in all_channels if c['id'] == target_channel_id]
            if not channels_to_process:
                print(f"Error: Channel ID '{target_channel_id}' not found in config.yaml", file=sys.stderr)
                # Still write out the preserved EPG data
                tree = ElementTree(new_tv_element)
                indent(tree, space="  ", level=0)
                tree.write(output_file, encoding='UTF-8', xml_declaration=True)
                return
        else:
            channels_to_process = all_channels
    
        # --- Step 3: Process channels and generate new programs ---
        for channel_config in channels_to_process:
            channel_id = channel_config['id']
            channel_name = channel_config['name']
    
            # Add channel definition if it's missing (for new channels)
            if new_tv_element.find(f'.//channel[@id="{channel_id}"]') is None:
                channel_element = SubElement(new_tv_element, 'channel', id=channel_id)
                SubElement(channel_element, 'display-name').text = channel_name
                if channel_config.get('icon_url'):
                    SubElement(channel_element, 'icon', src=channel_config.get('icon_url'))
                print(f"[{datetime.datetime.now()}] Added new channel definition for '{channel_name}'.")
    
            # Determine the start time for new programs
            last_program_end_time = now_utc
            if not target_channel_id: # Only look for last program time in full refresh mode
                for program in new_tv_element.findall(f'.//programme[@channel="{channel_id}"]'):
                    stop_time = datetime.datetime.strptime(program.get('stop'), '%Y%m%d%H%M%S %z')
                    if stop_time > last_program_end_time:
                        last_program_end_time = stop_time
    
            # Get the set of already scheduled video IDs for this channel (in full refresh mode)
            scheduled_video_ids = set()
            if not target_channel_id:
                for program in new_tv_element.findall(f'.//programme[@channel="{channel_id}"]'):
                    video_src_element = program.find('video')
                    if video_src_element is not None and 'v=' in video_src_element.get('src', ''):
                        scheduled_video_ids.add(video_src_element.get('src').split('v=')[-1])
    
            print(f"[{datetime.datetime.now()}] Processing '{channel_name}'. New programs will start from {last_program_end_time}.")
    
            # Fetching and filtering logic (mostly unchanged)
            all_available_videos = []
            min_duration = channel_config.get('min_duration')
            max_duration = channel_config.get('max_duration')
            sort_order = channel_config.get('sort_order', 'newest')
            match_title = channel_config.get('match_title')
            date_after = channel_config.get('date_after')
            date_before = channel_config.get('date_before')
            mixing_algorithm = channel_config.get('mixing_algorithm', 'concatenate')
            global_max_videos_per_source = epg_config.get('max_videos_per_source', 50)
            channel_max_videos = channel_config.get('max_videos_per_source', global_max_videos_per_source)
    
            # Determine effective cache settings for this channel
            cache_enabled = channel_config.get('cache', False)
            cache_ttl_hours = channel_config.get('cache_ttl_hours', global_cache_ttl_hours)
    
            source_channels_videos = []
            for yt_channel_url in channel_config.get('youtube_channels', []):
                source_channels_videos.append(fetch_videos(yt_channel_url, channel_max_videos, min_duration, max_duration, sort_order, match_title, date_after, date_before, cache_enabled, cache_ttl_hours))
    
            if mixing_algorithm == 'interleave':
                max_len = max(len(v) for v in source_channels_videos) if source_channels_videos else 0
                for i in range(max_len):
                    for videos in source_channels_videos:
                        if i < len(videos):
                            all_available_videos.append(videos[i])
            else:
                for videos in source_channels_videos:
                    all_available_videos.extend(videos)
    
            unscheduled_videos = [v for v in all_available_videos if v and v.get('id') not in scheduled_video_ids]
            print(f"[{datetime.datetime.now()}] Fetched {len(all_available_videos)} total videos, {len(unscheduled_videos)} are new.")
    
            if sort_order == 'oldest':
                unscheduled_videos.sort(key=lambda x: x.get('upload_date', ''))
            elif sort_order == 'random':
                random.shuffle(unscheduled_videos)
            else:  # newest
                unscheduled_videos.sort(key=lambda x: x.get('upload_date', ''), reverse=True)
    
            publicity_videos = []
            publicity_pool_name = channel_config.get('publicity_pool')
            if publicity_pool_name and publicity_pool_name in publicity_pools:
                publicity_pool_config = publicity_pools[publicity_pool_name]
                pub_min_duration = publicity_pool_config.get('min_duration')
                pub_max_duration = publicity_pool_config.get('max_duration')
                pub_max_videos = publicity_pool_config.get('max_videos_per_source', global_max_videos_per_source)
    
                # Determine effective cache settings for publicity pool
                pub_cache_enabled = publicity_pool_config.get('cache', False)
                pub_cache_ttl_hours = publicity_pool_config.get('cache_ttl_hours', global_cache_ttl_hours)
    
                for yt_channel_url in publicity_pool_config.get('youtube_channels', []):
                    fetched_ads = fetch_videos(yt_channel_url, pub_max_videos, pub_min_duration, pub_max_duration, 'random', None, None, None, pub_cache_enabled, pub_cache_ttl_hours)
                    for ad in fetched_ads:
                        ad['is_ad'] = True # Add the flag here
                    publicity_videos.extend(fetched_ads)
    
            new_playlist = interleave_playlist(unscheduled_videos, publicity_videos, channel_config.get('programs_per_publicity', 0))
            generate_programme_elements(new_tv_element, channel_id, new_playlist, days_to_generate, last_program_end_time)
    
        # --- Step 4: Write the final EPG to file ---
        tree = ElementTree(new_tv_element)
        indent(tree, space="  ", level=0)
        tree.write(output_file, encoding='UTF-8', xml_declaration=True)
        print(f"[{datetime.datetime.now()}] EPG generation complete.")
def background_epg_generator():
    # Initial delay to allow the server to start up before the first EPG generation
    time.sleep(10)
    interval_hours = CONFIG.get('epg', {}).get('refresh_interval_hours', 12)
    interval_seconds = interval_hours * 3600
    while True:
        create_epg(CONFIG)
        print(f"Next EPG refresh scheduled in {interval_hours} hours.")
        time.sleep(interval_seconds)

# --- Flask Web Server ---
@app.route('/epg.xml')
def serve_epg():
    epg_file_name = CONFIG.get('epg', {}).get('output_file', 'epg.xml')
    epg_file = os.path.join(DATA_PATH, epg_file_name)
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
        group_title = channel.get('group_title', 'Other')
        icon_url = channel.get('icon_url', '')
        stream_url = url_for('stream_channel', channel_id=channel_id, _external=True)
        m3u_content += f'#EXTINF:-1 tvg-id="{channel_id}" tvg-logo="{icon_url}" tvg-name="{channel_name}" group-title="{group_title}",{channel_name}\n'
        m3u_content += f'{stream_url}\n'
    return Response(m3u_content, mimetype='application/vnd.apple.mpegurl')

@app.route('/stream/<channel_id>')
def stream_channel(channel_id):

    def generate_stream(channel_id):
        # This generator is responsible for yielding a continuous stream of video data.
        
        # --- EPG Parsing and Schedule Setup ---
        try:
            epg_file_name = CONFIG.get('epg', {}).get('output_file', 'epg.xml')
            epg_file = os.path.join(DATA_PATH, epg_file_name)
            tree = ET.parse(epg_file)
            root = tree.getroot()
        except (FileNotFoundError, ET.ParseError):
            print(f"Could not find or parse EPG file {epg_file}. Aborting stream.", file=sys.stderr)
            return

        channel_programs = sorted([
            {
                'start': p.get('start'),
                'stop': p.get('stop'),
                'title': p.find('title').text if p.find('title') is not None else 'Untitled',
                'url': p.find('video').get('src')
            }
            for p in root.findall('programme') if p.get('channel') == channel_id and p.find('video') is not None
        ], key=lambda x: x['start'])

        channel_config = next((c for c in CONFIG['channels'] if c['id'] == channel_id), None)
        if not channel_config or not channel_programs:
            print(f"Channel '{channel_id}' not found or has no programs.", file=sys.stderr)
            return

        # --- Find Starting Program ---
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        start_index = -1
        seek_time = 0
        for i, program in enumerate(channel_programs):
            start_time = datetime.datetime.strptime(program['start'], '%Y%m%d%H%M%S %z')
            stop_time = datetime.datetime.strptime(program['stop'], '%Y%m%d%H%M%S %z')
            if start_time <= now_utc < stop_time:
                start_index = i
                seek_time = (now_utc - start_time).total_seconds()
                break
        
        if start_index == -1:
            # If no program is currently running, try to find the next scheduled program to start from its beginning.
            for i, program in enumerate(channel_programs):
                start_time = datetime.datetime.strptime(program['start'], '%Y%m%d%H%M%S %z')
                if start_time > now_utc:
                    print(f"No currently running program. Starting with next scheduled program: '{program['title']}'")
                    start_index = i
                    seek_time = 0
                    break

        if start_index == -1:
            print(f"No currently or future scheduled program found for channel '{channel_id}'.", file=sys.stderr)
            return

        # --- Main Streaming Loop ---
        quality_setting = channel_config.get('quality', 'best')
        output_config = channel_config.get('output', {})

        for i in range(start_index, len(channel_programs)):
            program = channel_programs[i]
            yt_dlp_process = None
            ffmpeg_process = None

            try:
                print(f"[{datetime.datetime.now()}] Starting stream for program: '{program['title']}'")

                yt_dlp_cmd = [
                    'yt-dlp',
                    program['url'],
                    '-f', quality_setting,
                    '-o', '-' # Pipe to stdout
                ]

                ffmpeg_cmd = [
                    'ffmpeg',
                    '-i', '-', # Read from stdin
                    '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
                    '-s', output_config.get('resolution', '1280x720'),
                    '-r', str(output_config.get('framerate', 30)),
                    '-b:v', output_config.get('video_bitrate', '4M'),
                    '-c:a', 'aac',
                    '-b:a', output_config.get('audio_bitrate', '192k'),
                    '-f', 'mpegts',
                    'pipe:1' # Pipe to stdout
                ]

                # Apply seek time only for the very first video of the stream
                current_seek_time = seek_time if i == start_index else 0
                if current_seek_time > 0:
                    # Insert -ss before -i for fast seeking
                    ffmpeg_cmd.insert(1, '-ss')
                    ffmpeg_cmd.insert(2, str(current_seek_time))

                # Start yt-dlp process
                yt_dlp_process = subprocess.Popen(yt_dlp_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

                # Start ffmpeg process, piping yt-dlp's output to its input
                ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=yt_dlp_process.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                
                # This allows yt-dlp to receive a SIGPIPE if ffmpeg exits.
                if yt_dlp_process.stdout:
                    yt_dlp_process.stdout.close()

                # Yield chunks from ffmpeg's output
                while True:
                    chunk = ffmpeg_process.stdout.read(4096)
                    if not chunk:
                        break
                    yield chunk
                
                print(f"[{datetime.datetime.now()}] Finished program: '{program['title']}'")

            except (GeneratorExit, BrokenPipeError):
                print(f"[{datetime.datetime.now()}] Client disconnected. Stopping stream for '{program['title']}'.", file=sys.stderr)
                break # Exit the loop
            except Exception as e:
                print(f"[{datetime.datetime.now()}] Error during stream for '{program['title']}': {e}. Skipping to next program.", file=sys.stderr)
                continue # Skip to the next video
            finally:
                # Clean up processes for the current video
                for p, name in [(yt_dlp_process, 'yt-dlp'), (ffmpeg_process, 'ffmpeg')]:
                    if p and p.poll() is None:
                        print(f"[{datetime.datetime.now()}] Terminating leftover {name} process (PID: {p.pid}).", file=sys.stderr)
                        p.terminate()
                        try:
                            p.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            p.kill()
                            p.wait()

    return Response(generate_stream(channel_id), mimetype='video/MP2T')

def main():
    parser = argparse.ArgumentParser(description='PseudoTV Server.')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind the server to.')
    parser.add_argument('--port', type=int, default=5004, help='Port to run the server on.')
    parser.add_argument('--create-epg', action='store_true', help='Generate the full EPG and exit.')
    parser.add_argument('--update-channel', type=str, help='Update the EPG for a specific channel ID and exit.')
    args = parser.parse_args()

    if args.create_epg:
        create_epg(CONFIG)
        sys.exit(0)

    if args.update_channel:
        create_epg(CONFIG, target_channel_id=args.update_channel)
        sys.exit(0)

    epg_file_name = CONFIG.get('epg', {}).get('output_file', 'epg.xml')
    epg_file = os.path.join(DATA_PATH, epg_file_name)
    if not os.path.exists(epg_file):
        print("No existing EPG found. Performing initial EPG generation synchronously...")
        create_epg(CONFIG)

    epg_thread = threading.Thread(target=background_epg_generator, daemon=True)
    epg_thread.start()
    print("Background EPG refresh thread started.")

    app.run(host=args.host, port=args.port)

if __name__ == '__main__':
    main()
