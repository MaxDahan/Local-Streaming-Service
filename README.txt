Local broadcasting service to local network. Great for running on a raspberry pi.

Directions:

1. Make sure to have a media/ folder with media/raw and media/converted. Throw all your
folders of content into the raw folder (ex: media/Adventure Time) then run 
"encode_to_720p.sh". This will convert all the videos to the same format into the 
converted folder.

2. From here define your channels in "channels.json" with the folder names for each channel.
This will pull from the converted folder so make sure the folder names match.

3. From here run "start_http_server.sh" then "start_all_streams.sh" and you're good to go!
