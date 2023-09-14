import hashlib
import os
import re
import redis
from typing import Any, AsyncGenerator, Callable, Optional, List
from vocode.streaming.agent.bot_sentiment_analyser import BotSentiment
from vocode.streaming.models.agent import FillerAudioConfig
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.models.synthesizer import SynthesizerConfig
from vocode.streaming.synthesizer.base_synthesizer import BaseSynthesizer, FillerAudio, SynthesisResult, encode_as_wav


def get_voice_id(synthesizer_config: SynthesizerConfig) -> str:
    voice = None
    if synthesizer_config.type == "synthesizer_azure" or synthesizer_config.type == "synthesizer_google":
        voice = synthesizer_config.voice_name  # type: ignore
    elif synthesizer_config.type in ["synthesizer_eleven_labs", "synthesizer_play_ht", "synthesizer_coqui"]:
        voice = synthesizer_config.voice_id  # type: ignore
    return voice or synthesizer_config.type


def cache_key(text, synthesizer_config: SynthesizerConfig) -> str:
    config_text = synthesizer_config.json()
    # lowercase, remove leading/trailing whitespace
    cleaned_text = text.lower().strip()
    # replace whitespace with underscore
    cleaned_text = re.sub(r'\s+', '_', cleaned_text)
    # cleaned_text = re.sub(r'[|<>"?*:\\.$[\]#/@]', '', cleaned_text) # this method does not handle escape characters
    # defined as alphanumeric only and underscore, convert to dash
    cleaned_text = re.sub(r'\W+', '-', cleaned_text)
    voice_id = get_voice_id(synthesizer_config)
    hash_value = hashlib.md5(
        (cleaned_text + config_text).encode()).hexdigest()[:8]
    return f"{synthesizer_config.type}_{voice_id}_{synthesizer_config.audio_encoding}_{synthesizer_config.sampling_rate}/{cleaned_text[:32]}_{hash_value}"


class AsyncGeneratorWrapper(AsyncGenerator[SynthesisResult.ChunkResult, None]):
    def __init__(self, generator, when_finished: Callable, remove_wav_header: bool):
        self.generator = generator
        self.all_bytes = bytearray()
        self.when_finished = when_finished
        self.remove_wav_header = remove_wav_header

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk_result = await self.generator.__anext__()
            if chunk_result and chunk_result.chunk:
                self.all_bytes += chunk_result.chunk[44:
                                                     ] if self.remove_wav_header else chunk_result.chunk
            return chunk_result
        except StopAsyncIteration:
            self.when_finished(self.all_bytes)
            self.all_bytes = None
            raise

    async def aclose(self):
        self.when_finished(self.all_bytes)
        self.all_bytes = None
        await self.generator.aclose()

    async def asend(self, value):
        return await self.generator.asend(value)

    async def athrow(self, type, value=None, traceback=None):
        return await self.generator.athrow(type, value, traceback)


class CachingSynthesizer(BaseSynthesizer):

    def __init__(self, inner_synthesizer: BaseSynthesizer, redis_url: str = os.environ.get("REDIS_URL")):
        assert redis_url is not None, "Redis URL must be set"
        self.inner_synthesizer = inner_synthesizer
        self.redisClient = redis.from_url(redis_url)
        self.should_close_session_on_tear_down = False

    @property
    def filler_audios(self) -> List[FillerAudio]:
        return self.inner_synthesizer.filler_audios

    def get_synthesizer_config(self) -> SynthesizerConfig:
        return self.inner_synthesizer.get_synthesizer_config()

    def get_typing_noise_filler_audio(self) -> FillerAudio:
        return self.inner_synthesizer.get_typing_noise_filler_audio()

    async def set_filler_audios(self, filler_audio_config: FillerAudioConfig):
        await self.inner_synthesizer.set_filler_audios(filler_audio_config)

    async def get_phrase_filler_audios(self) -> List[FillerAudio]:
        return await self.inner_synthesizer.get_phrase_filler_audios()

    def ready_synthesizer(self):
        return self.inner_synthesizer.ready_synthesizer()

    def get_message_cutoff_from_total_response_length(
        self, message: BaseMessage, seconds: int, size_of_output: int
    ) -> str:
        return self.inner_synthesizer.get_message_cutoff_from_total_response_length(message, seconds, size_of_output)

    def get_message_cutoff_from_voice_speed(
        self, message: BaseMessage, seconds: int, words_per_minute: int
    ) -> str:
        return self.inner_synthesizer.get_message_cutoff_from_voice_speed(message, seconds, words_per_minute)

    async def create_speech(
        self,
        message: BaseMessage,
        chunk_size: int,
        bot_sentiment: Optional[BotSentiment] = None,
    ) -> SynthesisResult:
        result = None
        key = cache_key(
            message.text, self.inner_synthesizer.get_synthesizer_config())
        if self.redisClient.exists(key):
            result = self.create_synthesis_result_from_bytes(
                self.redisClient.get(key), message=message, chunk_size=chunk_size)
        if not result:
            result = await self.inner_synthesizer.create_speech(message, chunk_size, bot_sentiment)
            result.chunk_generator = AsyncGeneratorWrapper(
                result.chunk_generator,
                lambda all_bytes: self.redisClient.set(
                    cache_key(message.text, self.inner_synthesizer.get_synthesizer_config()), bytes(all_bytes)),
                self.inner_synthesizer.synthesizer_config.should_encode_as_wav
            )
        return result

    def create_synthesis_result_from_bytes(self, output_bytes: Any, message: BaseMessage, chunk_size: int):
        if self.get_synthesizer_config().should_encode_as_wav:
            def chunk_transform(chunk): return encode_as_wav(
                chunk, self.synthesizer_config
            )
        else:
            def chunk_transform(chunk): return chunk

        async def chunk_generator(output_bytes):
            for i in range(0, len(output_bytes), chunk_size):
                if i + chunk_size > len(output_bytes):
                    yield SynthesisResult.ChunkResult(
                        chunk_transform(output_bytes[i:]), True
                    )
                else:
                    yield SynthesisResult.ChunkResult(
                        chunk_transform(output_bytes[i: i + chunk_size]), False
                    )

        return SynthesisResult(
            chunk_generator(output_bytes),
            lambda seconds: self.get_message_cutoff_from_total_response_length(
                message, seconds, len(output_bytes)
            ),
        )

    def create_synthesis_result_from_wav(
        self, file: Any, message: BaseMessage, chunk_size: int
    ) -> SynthesisResult:
        return self.inner_synthesizer.create_synthesis_result_from_wav(file, message, chunk_size)
