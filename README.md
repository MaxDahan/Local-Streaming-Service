Local broadcasting service to local network and file/folder streamer. Great for running on a raspberry pi.

**Directions**

1. Make sure to have a media/ folder with media/raw and media/converted. Throw all your
folders of content into the raw folder (ex: media/raw/Adventure Time) then run 
"encode_to_720p.sh". This will convert all the videos to the same format into the 
converted folder.

2. From here define your channels in "channels.json" with the folder names for each channel.
This will pull from the converted folder so make sure the folder names match.

3. Run "sudo ./start_server.sh" to boot up the channel servers and website!

Access the stream from maxistreams.local
*you can also access m3u8 links for debugging at "<ipaddress>/channels/<channel-name>/output/<channel-name>.m3u8"

4. run "sudo ./stop_server.sh" to end the streaming and website processes.

**Features**

Channels: like tv channels for livestreaming as they run all the time. Configurable through channels.json.

Browser: file browser where you can shuffle play all media in a folder or play a specific file. Up to 5 sessions allowed at a time. Additional sessions will boot the oldest session (sessions are based on ip address).

**Information**

Make sure to use an SSD and not Hard Drive as things will lag with a Hard Drive!!

Logrotate: to stop logs from becoming super big after running this for a long time they are contained to two files that 
get cleaned periodically. Additionally, the .ts files also get cleaned and the number in the file name eventually loops back to 0.
