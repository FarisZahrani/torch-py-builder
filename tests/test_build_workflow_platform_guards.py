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

        for step_name in (
            "Build libtorch (macOS x86_64 CPU)",
            "Build wheel from libtorch (macOS x86_64 CPU)",
        ):
            self.assertIn('USE_MPS: "0"', _step_block(workflow, step_name))

    def test_windows_wheel_build_reuses_libtorch_configuration(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = _step_block(workflow, "Build wheel from libtorch (Windows CPU)")

        self.assertNotIn("CMAKE_FRESH", step)


if __name__ == "__main__":
    unittest.main()
