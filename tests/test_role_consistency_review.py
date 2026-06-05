import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "10_role_consistency_review.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("role_review_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RoleConsistencyReviewTests(unittest.TestCase):
    def test_extract_marked_json(self):
        module = load_script_module()
        raw = f"noise\n{module.JSON_BEGIN}\n{{\"status\": \"ok\", \"candidates\": []}}\n{module.JSON_END}\n"
        self.assertEqual(module.extract_marked_json(raw), {"status": "ok", "candidates": []})

    def test_prompt_forbids_hardcoded_rules(self):
        module = load_script_module()
        prompt = module.build_prompt("00:00:01 | A | text", {"source_mp3": "x.mp3"}, {"assignments": {"SPEAKER_00": {"name": "A"}}})
        self.assertIn("Не используй заранее заданные доменные правила", prompt)
        self.assertIn("непрозрачными идентификаторами", prompt)
        self.assertIn("Ответ должен быть валидным JSON", prompt)

    def test_run_hermes_llm_calls_real_runner_shape_and_parses_output(self):
        module = load_script_module()
        completed = mock.Mock()
        completed.returncode = 0
        completed.stdout = f"{module.JSON_BEGIN}\n{json.dumps({'status':'ok','candidates':[]})}\n{module.JSON_END}"
        completed.stderr = ""
        with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
            data, raw = module.run_hermes_llm("prompt", 123)
        self.assertEqual(data["status"], "ok")
        self.assertIn(module.JSON_BEGIN, raw)
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["hermes", "-z"])
        self.assertEqual(args[-1], "--cli")
        self.assertEqual(run.call_args.kwargs["timeout"], 123)


if __name__ == "__main__":
    unittest.main()
