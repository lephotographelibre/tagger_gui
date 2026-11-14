test with False MP3 reencoded Issue #3

I used a reencoded MP3 in order to test spectogram génération on suspect MP3 (Inital 320k -> to 128k -> reencoded as 320k)

```bash
ffmpeg -i 02initial.mp3 -b:a 128k sortie.mp3
ffmpeg -i sortie.mp3 -b:a 320k 02reencodé.mp3
```
The program  has detected this suspect MP3 and generated a spectogram for this file only 

<img width="3433" height="1129" alt="tagger_gui_mp3_réencodé_spectrogramme" src="https://github.com/user-attachments/assets/025c325b-f1ac-40e5-91b0-618d39cde9d5" />

<img width="1650" height="701" alt="02reencodé_suspect" src="https://github.com/user-attachments/assets/ba4485ad-6322-4cce-a558-01e177d1a024" />
