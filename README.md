Local broadcasting service to local network. Great for running on a raspberry pi.

**Directions**

1. Make sure to have a media/ folder with media/raw and media/converted. Throw all your
folders of content into the raw folder (ex: media/Adventure Time) then run 
"encode_to_720p.sh". This will convert all the videos to the same format into the 
converted folder.

2. From here define your channels in "channels.json" with the folder names for each channel.
This will pull from the converted folder so make sure the folder names match.

3. Run "./start_all_streams.sh" to boot up the channel servers!

3. From here run "sudo python3 start_server.py" and you're good to go!

Access the stream from maxistreams.local
*you can also access m3u8 links for debugging at "<ipaddress>/channels/<channel-name>/output/<channel-name>.m3u8"

**Information**

Channels: like tv channels for livestreaming as they run all the time. Configurable through channels.json.

Browser: file browser where you can shuffle play all media in a folder or play a specific file. Up to 5 sessions allowed at a time. Additional sessions will boot the oldest session (sessions are based on ip address).
