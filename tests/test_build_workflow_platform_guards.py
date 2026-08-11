from pathlib import Path
import unittest


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build.yml"
SYNC_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "sync.yml"
MATRIX_PATH = Path(__file__).resolve().parents[1] / "config" / "build_matrix.json"


def _step_block(workflow: str, step_name: str) -> str:
    marker = f"      - name: {step_name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start:] if end == -1 else workflow[start:end]


class BuildWorkflowPlatformGuardsTests(unittest.TestCase):
    def test_production_workflows_use_the_shared_torch_pin(self) -> None:
        import json

        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(matrix["torch_version"], "2.11.0")

        build_workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        sync_workflow = SYNC_WORKFLOW_PATH.read_text(encoding="utf-8")
        for workflow in (build_workflow, sync_workflow):
            self.assertIn("jq -r '.torch_version' config/build_matrix.json", workflow)
            self.assertIn('--version-override "${', workflow)

    def test_every_torch_build_explicitly_disables_native_cpu_tuning(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        build_steps = (
            "Build libtorch (Linux CPU)",
            "Build wheel from libtorch (Linux CPU)",
            "Build libtorch (Linux CUDA)",
            "Build wheel from libtorch (Linux CUDA)",
            "Build libtorch (macOS arm64 MPS)",
            "Build wheel from libtorch (macOS arm64 MPS)",
            "Build torch wheel (macOS x86_64 CPU)",
            "Build torch wheel (Windows CPU)",
            "Build libtorch (Windows CUDA)",
            "Build wheel from libtorch (Windows CUDA)",
        )

        for step_name in build_steps:
            with self.subTest(step=step_name):
                step = _step_block(workflow, step_name)
                self.assertIn('USE_NATIVE_ARCH: "0"', step)

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
