from pathlib import Path
import unittest


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build.yml"


def _step_block(workflow: str, step_name: str) -> str:
    marker = f"      - name: {step_name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start:] if end == -1 else workflow[start:end]


class BuildWorkflowPlatformGuardsTests(unittest.TestCase):
    def test_intel_macos_explicitly_disables_mps(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        step = _step_block(workflow, "Build torch wheel (macOS x86_64 CPU)")
        self.assertIn('USE_MPS: "0"', step)
        self.assertIn("python -m build --wheel --no-isolation", step)
        self.assertNotIn("tools/build_libtorch.py", step)

    def test_windows_builds_one_complete_torch_wheel(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = _step_block(workflow, "Build torch wheel (Windows CPU)")

        self.assertIn("python -m build --wheel --no-isolation", step)
        self.assertNotIn("tools/build_libtorch.py", step)
        self.assertNotIn("Build libtorch (Windows CPU)", workflow)
        self.assertNotIn("Build wheel from libtorch (Windows CPU)", workflow)


if __name__ == "__main__":
    unittest.main()
