import unittest

from agent.speech_interpretation_providers import (
    SpeechInterpretationProviderFactory,
)


class FakeSTT:
    instances = []

    def __init__(self, cfg):
        self.cfg = cfg
        self.transcribed = []
        FakeSTT.instances.append(self)

    def transcribe(self, pcm: bytes) -> str:
        self.transcribed.append(pcm)
        return self.cfg.get("name", "text")


class FakeLLM:
    instances = []

    def __init__(self, cfg):
        self.cfg = cfg
        FakeLLM.instances.append(self)


class SpeechInterpretationProviderFactoryTests(unittest.TestCase):
    def setUp(self):
        FakeSTT.instances = []
        FakeLLM.instances = []
        self.messages = []
        self.factory = SpeechInterpretationProviderFactory(
            stt_client_cls=FakeSTT,
            llm_editor_cls=FakeLLM,
            log=self.messages.append,
        )

    def test_dictation_mode_requires_api_key_for_default_provider(self):
        stt = self.factory.create_dictation_stt({"provider": "openai"})

        self.assertIsNone(stt)
        self.assertEqual(FakeSTT.instances, [])
        self.assertEqual(
            self.messages,
            [
                "[agent] 未配置 stt.api_key，跳过音频 STT",
                "[agent] 提示: cp config.yaml.example config.yaml 然后填入 API Key",
            ],
        )

    def test_dictation_mode_preserves_typeup_login_gate(self):
        stt = self.factory.create_dictation_stt({
            "provider": "typeup_backend",
            "api_base_url": "http://localhost:8000",
        })

        self.assertIsNone(stt)
        self.assertEqual(
            self.messages,
            ["[typeup-auth-required] 请先登录 TypeUp 后端账号，跳过音频 STT"],
        )

    def test_creates_dictation_mode_provider_when_ready(self):
        stt = self.factory.create_dictation_stt({
            "provider": "openai",
            "api_key": "test-api-key",
        })

        self.assertIsInstance(stt, FakeSTT)
        self.assertEqual(stt.cfg["api_key"], "test-api-key")

    def test_text_operation_editor_uses_existing_readiness_rules(self):
        self.assertIsNone(self.factory.create_text_operation_editor({}))

        editor = self.factory.create_text_operation_editor({
            "provider": "openai",
            "api_key": "test-api-key",
        })

        self.assertIsInstance(editor, FakeLLM)
        self.assertEqual(self.messages, ["[agent] LLM 编辑功能已启用"])

    def test_instruction_mode_speech_recognition_defaults_to_dictation_provider(self):
        dictation_stt = FakeSTT({"name": "dictation"})

        instruction_stt = self.factory.create_instruction_stt({}, dictation_stt)

        self.assertIs(instruction_stt, dictation_stt)

    def test_instruction_mode_speech_recognition_can_use_separate_provider(self):
        dictation_stt = FakeSTT({"name": "dictation"})

        instruction_stt = self.factory.create_instruction_stt(
            {"provider": "glm_asr_2512", "api_key": "test-ai-key"},
            dictation_stt,
        )

        self.assertIsInstance(instruction_stt, FakeSTT)
        self.assertIsNot(instruction_stt, dictation_stt)
        self.assertEqual(instruction_stt.cfg["api_key"], "test-ai-key")
        self.assertEqual(
            self.messages,
            ["[agent] AI 键 STT 使用独立 provider: glm_asr_2512"],
        )

    def test_micro_polish_wraps_dictation_provider_without_changing_base_transcribe(self):
        dictation_stt = FakeSTT({"name": "dictation"})

        utterance_stt = self.factory.create_utterance_stt(
            dictation_stt,
            {"provider": "glm_asr_2512", "api_key": "test-polish-key", "name": "polished"},
            {},
        )

        self.assertEqual(utterance_stt.transcribe(b"base"), "dictation")
        self.assertEqual(utterance_stt.transcribe_polished(b"polish"), "polished")
        self.assertEqual(
            self.messages,
            ["[agent] 微润色 STT 使用独立 provider: glm_asr_2512"],
        )

    def test_micro_polish_does_not_infer_provider_from_llm_config(self):
        dictation_stt = FakeSTT({"name": "dictation"})

        utterance_stt = self.factory.create_utterance_stt(
            dictation_stt,
            {},
            {"provider": "zhipuai", "api_key": "test-zhipu-key"},
        )

        self.assertIs(utterance_stt, dictation_stt)
        self.assertEqual(len(FakeSTT.instances), 1)

    def test_provider_set_concentrates_all_configured_construction(self):
        providers = self.factory.create_provider_set({
            "stt": {"provider": "openai", "api_key": "test-dictation-key"},
            "llm": {"provider": "openai", "api_key": "test-llm-key"},
            "ai_stt": {"provider": "glm_asr_2512", "api_key": "test-ai-key"},
            "polish_stt": {"provider": "glm_asr_2512", "api_key": "test-polish-key"},
        })

        self.assertIsNotNone(providers)
        self.assertIsInstance(providers.dictation_stt, FakeSTT)
        self.assertIsInstance(providers.instruction_stt, FakeSTT)
        self.assertIsInstance(providers.text_operation_editor, FakeLLM)
        self.assertIsNot(providers.utterance_stt, providers.dictation_stt)


if __name__ == "__main__":
    unittest.main()
