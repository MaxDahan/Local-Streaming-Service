Broadcasting service to local network.

Download your favorite video content and organize it into its own channel folders. The service will stream your channels for you to be opened in a browser. A rudamentary shuffling algorithm was implemented for further improvement.

side note: anything under 1 minute might have synching issues with the audio and video

run make_playlists.sh to populate all the channels with initial playlists

run python3 -m http.server 8080 to start the http server locally
python3 -m http.server 8080 --bind 0.0.0.0 for starting server on network

run start_looping_stream.sh to start a looping stream for a specific channel. This will make a shuffled playlist of everything in the channel folder that will reshuffle once every episode has played.

login to the stream on safari using http://localhost:8080/channels/<channel_name>/output/<channel_name>.m3u8
