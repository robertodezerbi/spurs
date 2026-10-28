`astronaut.png` is the NASA public-domain portrait of Eileen Collins, distributed
as a scikit-image sample image. Retrieved from the pinned scikit-image v0.19.3
repository path `skimage/data/astronaut.png` on raw.githubusercontent.com.
SHA-256: 88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5.
Used only to exercise the real bundled OpenCV face detector; it is not a
speaker-recognition or active-speaker ground-truth dataset.

`jfk.flac` is the public speech fixture from OpenAI Whisper's pinned v20240930
`tests/jfk.flac`; the source is the US presidential inaugural address.
SHA-256: 63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715.
`jfk.txt` contains the spoken reference used by `tools/verify_transcription.py`.
Having the fixture available does not mean transcription has passed: model-host
access is required and the real inference gate currently reports blocked.
