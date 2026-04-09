import unittest

from tofuri import get_completion_usage


class _Obj:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class OpenAICompatTests(unittest.TestCase):
    def test_usage_from_legacy_prompt_completion_tokens_object(self) -> None:
        completion = _Obj(usage=_Obj(prompt_tokens=10, completion_tokens=20, total_tokens=30))
        usage = get_completion_usage(completion)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 20)
        self.assertEqual(usage["total_tokens"], 30)

    def test_usage_from_legacy_prompt_completion_tokens_dict(self) -> None:
        completion = _Obj(usage={"prompt_tokens": 7, "completion_tokens": 9, "total_tokens": 16})
        usage = get_completion_usage(completion)
        self.assertEqual(usage["input_tokens"], 7)
        self.assertEqual(usage["output_tokens"], 9)
        self.assertEqual(usage["total_tokens"], 16)


if __name__ == "__main__":
    unittest.main()
