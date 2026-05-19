


struct Song {
    title: String,
    length: u32,
}


struct Playlist {
    songs: Vec<Song>,
}

impl Playlist {
    pub fn add_song(&mut self, title: String, length: u32) {
        self.songs.push(
            Song{title: title, length: length}
        )
    }

    pub fn print_songs(&self) {
        for (i,song) in self.songs.iter().enumerate() {
            println!(" song [{num}]: {title}, length: {length}", num=i+1, title=song.title, length=song.length);
        }
    }


}







fn main() {
    let mut list = Playlist{songs: Vec::new()};
    list.add_song(String::from("3 nights"), 3);
    list.add_song(String::from("Iyaz Replay"), 3);
    list.print_songs();
}