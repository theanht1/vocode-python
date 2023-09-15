import asyncio
import audioop
import logging
import os
import secrets
from typing import Any
import wave
from string import ascii_letters, digits

from ..models.audio_encoding import AudioEncoding

logger = logging.getLogger(__name__)
custom_alphabet = ascii_letters + digits + ".-_"

custom_alphabet = ascii_letters + digits + ".-_"

def create_loop_in_thread(loop: asyncio.AbstractEventLoop, long_running_task=None):
    asyncio.set_event_loop(loop)
    if long_running_task:
        loop.run_until_complete(long_running_task)
    else:
        loop.run_forever()


def convert_linear_audio(
    raw_wav: bytes,
    input_sample_rate=24000,
    output_sample_rate=8000,
    output_encoding=AudioEncoding.LINEAR16,
    output_sample_width=2,
):
    # downsample
    if input_sample_rate != output_sample_rate:
        raw_wav, _ = audioop.ratecv(
            raw_wav, 2, 1, input_sample_rate, output_sample_rate, None
        )

    if output_encoding == AudioEncoding.LINEAR16:
        return raw_wav
    elif output_encoding == AudioEncoding.MULAW:
        return audioop.lin2ulaw(raw_wav, output_sample_width)


def convert_wav(
    file: Any,
    output_sample_rate=8000,
    output_encoding=AudioEncoding.LINEAR16,
):
    with wave.open(file, "rb") as wav:
        raw_wav = wav.readframes(wav.getnframes())
        return convert_linear_audio(
            raw_wav,
            input_sample_rate=wav.getframerate(),
            output_sample_rate=output_sample_rate,
            output_encoding=output_encoding,
            output_sample_width=wav.getsampwidth(),
        )


def get_chunk_size_per_second(audio_encoding: AudioEncoding, sampling_rate: int) -> int:
    if audio_encoding == AudioEncoding.LINEAR16:
        return sampling_rate * 2
    elif audio_encoding == AudioEncoding.MULAW:
        return sampling_rate
    else:
        raise Exception("Unsupported audio encoding")


def create_conversation_id() -> str:
    return secrets.token_urlsafe(16)

def remove_non_letters_digits(text):
    return ''.join(i for i in text if i in custom_alphabet)

def save_as_wav(path, audio_data: bytes, sampling_rate: int):
    if len(audio_data) == 0:
        logger.error(f"Cannot save an empty WAV file to {path}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        wav_file = wave.open(f, "wb")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sampling_rate)
        wav_file.writeframes(audio_data)
        wav_file.close()
    logger.debug(f"Saved {len(audio_data)} audio bytes to {path}")
