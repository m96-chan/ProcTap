from processaudiotap import ProcessAudioTap
import wave

pid = 12345
wav = wave.open("output.wav", "wb")
wav.setnchannels(2)
wav.setsampwidth(2)  # 16bit
wav.setframerate(48000)

def on_data(pcm, frames):
    wav.writeframes(pcm)

with ProcessAudioTap(pid, on_data=on_data):
    input("Recording VRChat audio. Enter to stop.\n")

wav.close()