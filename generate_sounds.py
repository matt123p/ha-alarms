"""Script to generate default WAV sound files for the Alarms integration."""
import os
import math
import struct
import wave

# Target directory
SOUND_DIR = os.path.join(
    os.path.dirname(__file__),
    "custom_components",
    "alarms",
    "frontend",
    "sounds"
)
os.makedirs(SOUND_DIR, exist_ok=True)

SAMPLE_RATE = 22050  # Hz
VOLUME_MAX = 32767   # 16-bit signed max


def save_wav(filename: str, samples: list[int]) -> None:
    """Save raw sample list to 16-bit mono WAV file."""
    filepath = os.path.join(SOUND_DIR, filename)
    with wave.open(filepath, "wb") as w:
        w.setnchannels(1)  # Mono
        w.setsampwidth(2)  # 16-bit
        w.setframerate(SAMPLE_RATE)
        # Pack to 16-bit little-endian binary format
        binary_data = struct.pack(f"<{len(samples)}h", *samples)
        w.writeframes(binary_data)
    print(f"Generated: {filepath}")


def generate_digital() -> None:
    """Generate a rapid dual-beep digital alarm sound."""
    samples = []
    # 5 seconds duration
    duration = 5.0
    num_samples = int(SAMPLE_RATE * duration)
    
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        # Repeat pattern: 0.1s beep, 0.1s pause, 0.1s beep, 0.4s pause
        cycle = t % 0.7
        if cycle < 0.1 or (0.15 <= cycle < 0.25):
            # 2000Hz tone
            val = int(VOLUME_MAX * 0.5 * math.sin(2 * math.pi * 2000 * t))
        else:
            val = 0
        samples.append(val)
        
    save_wav("digital.wav", samples)


def generate_chime() -> None:
    """Generate a soft, cascading bell chime melody."""
    samples = []
    duration = 6.0
    num_samples = int(SAMPLE_RATE * duration)
    
    # Musical note frequencies: C5, E5, G5, C6
    notes = [523.25, 659.25, 783.99, 1046.50]
    
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        val = 0.0
        
        # We trigger notes sequentially every 1.5 seconds
        for note_idx, note_freq in enumerate(notes):
            trigger_time = note_idx * 1.2
            if t >= trigger_time:
                # Decay envelope: starts at trigger, decays exponentially
                dt = t - trigger_time
                envelope = math.exp(-2.0 * dt)  # decays fast
                if envelope > 0.01:
                    # Fundamental frequency + some harmonics for a bell sound
                    val += 0.4 * envelope * math.sin(2 * math.pi * note_freq * dt)
                    val += 0.15 * envelope * math.sin(2 * math.pi * (note_freq * 2) * dt)
                    val += 0.05 * envelope * math.sin(2 * math.pi * (note_freq * 3) * dt)
                    
        # Clip volume to safe levels
        val = max(-1.0, min(1.0, val))
        samples.append(int(VOLUME_MAX * 0.7 * val))
        
    save_wav("chime.wav", samples)


def generate_soothing() -> None:
    """Generate a calm, swelling ambient wave sound."""
    samples = []
    duration = 6.0
    num_samples = int(SAMPLE_RATE * duration)
    
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        # Low frequency swelling wave (440Hz / 444Hz binaural-like pulse)
        # Slow volume swell: a sine wave modulating amplitude over 3 seconds cycles
        amplitude_swell = 0.5 + 0.5 * math.sin(2 * math.pi * (1 / 3) * t)
        
        # Mix 220Hz and 222Hz to create a natural acoustic beating/chorus effect
        wave1 = math.sin(2 * math.pi * 220 * t)
        wave2 = math.sin(2 * math.pi * 222 * t)
        
        val = 0.5 * amplitude_swell * (wave1 + wave2)
        samples.append(int(VOLUME_MAX * 0.6 * val))
        
    save_wav("soothing.wav", samples)


def generate_buzzer() -> None:
    """Generate a classic retro buzzer pulse."""
    samples = []
    duration = 5.0
    num_samples = int(SAMPLE_RATE * duration)
    
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        # Pulse every 0.8 seconds (0.4s on, 0.4s off)
        cycle = t % 0.8
        if cycle < 0.4:
            # 120Hz square wave (harsh tone)
            # Math.sin based square wave: sign(sin(2*pi*f*t))
            sin_val = math.sin(2 * math.pi * 120 * t)
            val = 0.4 if sin_val >= 0 else -0.4
            
            # Mix in a 180Hz buzz harmonic
            val += 0.2 * (1.0 if math.sin(2 * math.pi * 180 * t) >= 0 else -1.0)
        else:
            val = 0.0
            
        samples.append(int(VOLUME_MAX * 0.5 * val))
        
    save_wav("buzzer.wav", samples)


def generate_silent() -> None:
    """Generate a silent WAV file."""
    samples = [0] * int(SAMPLE_RATE * 5.0)
    save_wav("silent.wav", samples)


if __name__ == "__main__":
    generate_digital()
    generate_chime()
    generate_soothing()
    generate_buzzer()
    generate_silent()
