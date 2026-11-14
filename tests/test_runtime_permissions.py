"""Directory-policy regressions; Windows branches here are simulations, not ACL tests."""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from deployments.packages import Packages
from runner import common
from runner.__main__ import main
from runner.execution import Execution, snapshot
from runner.lifecycle import Lifecycle
from runner.store import Store, default_job


@contextlib.contextmanager
def windows_directory_policy():
    """Change only directory creation policy, retaining the host's locks/processes."""
    original = common.private_mkdir

    def mkdir(*args, **kwargs):
        # Replace common's os reference, never pathlib's/global os.name.
        with patch.object(common, "os", SimpleNamespace(name="nt")):
            return original(*args, **kwargs)

    with contextlib.ExitStack() as stack:
        for module in ("runner.common", "runner.store", "runner.execution",
                       "runner.lifecycle", "deployments.packages"):
            stack.enter_context(patch(module + ".private_mkdir", side_effect=mkdir))
        yield


class RuntimePermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sm permissions 한글 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_windows_fresh_install_all_local_data_directories_inherit(self):
        calls = []
        original = Path.mkdir

        def mkdir(path, mode=0o777, parents=False, exist_ok=False):
            calls.append((path, mode))
            return original(path, mode, parents, exist_ok)

        with windows_directory_policy(), patch.object(Path, "mkdir", mkdir):
            store = Store(self.root)
            store.create(default_job("sample"))
            with patch("runner.execution.subprocess.Popen") as launch:
                launch.return_value.wait.return_value = 0
                launch.return_value.pid = 12345  # Public integer metadata for the Windows lease.
                record = Execution(store).start("sample")
            run_id = record["id"]
            self.assertEqual(record["state"], "queued")
            paths = Lifecycle(store).paths("sample", run_id, create=True)
            packages = Packages(store)
            package = packages.create("sample")
            self.assertTrue(packages.archive(package["id"], "sample"))
        self.assertTrue(calls)
        self.assertTrue(all(mode != 0o700 for _, mode in calls), calls)
        for relative in ("runtime", "runtime/locks", "runtime/runs", "runtime/trash",
                         "runtime/schedules", "runtime/deployments", "jobs/sample",
                         "runtime/runs/sample/" + run_id + "/source",
                         "runtime/job-data/sample/state", "workspace", "deployments/packages"):
            self.assertTrue((self.root / relative).is_dir(), relative)
        self.assertTrue(Path(paths["SCRIPT_MANAGER_OUTPUT_DIR"]).is_dir())
        self.assertTrue(any(p.name.startswith(".tmp-") for p, _ in calls))
        self.assertFalse(list((store.runtime / "deployments").iterdir()))

    def seed_existing_data(self):
        store = Store(self.root)
        store.create(default_job("existing"))
        files = {}
        for relative in ("runtime/runs/existing/old/run.json", "runtime/job-data/existing/state/state.json",
                         "runtime/job-data/existing/output/old/result.json", "workspace/work.txt",
                         "runtime/schedules/existing.json", "runtime/deployments/receipt.json",
                         "deployments/packages/old/metadata.json", "runtime/lifecycle/existing.json"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}" if relative.endswith(".json") else "preserve " + relative)
            files[path] = path.read_bytes()
        for path in store.job_dir("existing").iterdir():
            files[path] = path.read_bytes()
        return store, files

    def test_existing_install_preserves_data_and_never_chmods(self):
        store, files = self.seed_existing_data()
        modes = {p: stat.S_IMODE(p.stat().st_mode) for p in self.root.rglob("*") if p.is_dir()}
        with windows_directory_policy(), patch("runner.common.os.chmod") as chmod:
            reopened = Store(self.root)
            Lifecycle(reopened).paths("existing", create=True)
            Packages(reopened)
            self.assertEqual(reopened.get("existing")["config"]["schedules"], [])
            chmod.assert_not_called()
        self.assertEqual(modes, {p: stat.S_IMODE(p.stat().st_mode) for p in modes})
        self.assertEqual({p: p.read_bytes() for p in files}, files)

    def test_denied_existing_runtime_cli_stops_without_repair_or_data_loss(self):
        _, files = self.seed_existing_data()
        original = Path.mkdir
        calls = []

        def denied(path, *args, **kwargs):
            calls.append(path)
            if path == self.root / "runtime/locks":
                raise PermissionError(errno.EACCES, "synthetic denied", str(path))
            return original(path, *args, **kwargs)

        before = set(self.root.rglob("*"))
        error = io.StringIO()
        with windows_directory_policy(), patch.object(Path, "mkdir", denied), \
                patch("runner.common.os.chmod") as chmod, \
                patch("runner.common.shutil.rmtree") as remove, \
                contextlib.redirect_stderr(error):
            self.assertEqual(main(["--root", str(self.root), "list"]), 1)
            chmod.assert_not_called()
            remove.assert_not_called()
        self.assertIn("ACL", json.loads(error.getvalue())["error"])
        self.assertEqual(calls.count(self.root / "runtime/locks"), 1)
        self.assertEqual(before, set(self.root.rglob("*")))
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        # Access restored externally: reopening reuses exactly the existing Job/data.
        with windows_directory_policy():
            self.assertEqual([j["id"] for j in Store(self.root).list()], ["existing"])

    def test_partial_initialization_failure_can_resume_without_deletion(self):
        original = Path.mkdir

        def fail(path, *args, **kwargs):
            if path == self.root / "runtime/trash":
                raise PermissionError(errno.EACCES, "synthetic denied", str(path))
            return original(path, *args, **kwargs)

        with windows_directory_policy(), patch.object(Path, "mkdir", fail):
            with self.assertRaises(common.ManagerError):
                Store(self.root)
        marker = self.root / "runtime/runs/keep.txt"
        marker.write_text("keep partial installation")
        with windows_directory_policy():
            store = Store(self.root)
        self.assertTrue((store.runtime / "deployments").is_dir())
        self.assertEqual(marker.read_text(), "keep partial installation")

    def test_nonpermission_failure_is_not_retried_or_misreported(self):
        failure = OSError(errno.ENOSPC, "synthetic disk full")
        with windows_directory_policy(), patch.object(Path, "mkdir", side_effect=failure) as mkdir:
            with self.assertRaises(OSError) as raised:
                common.private_mkdir(self.root / "new")
            self.assertIs(raised.exception, failure)
            self.assertEqual(mkdir.call_count, 1)

    def test_failed_run_snapshot_preserves_old_runs_output_and_state(self):
        store, files = self.seed_existing_data()
        original = Path.mkdir

        def fail(path, *args, **kwargs):
            if path.name == "source":
                raise PermissionError(errno.EACCES, "synthetic denied", str(path))
            return original(path, *args, **kwargs)

        with windows_directory_policy(), patch.object(Path, "mkdir", fail), \
                patch("runner.execution.subprocess.Popen") as launch:
            with self.assertRaises(common.ManagerError):
                Execution(store).start("existing")
            launch.assert_not_called()
        self.assertEqual([p.name for p in (store.runtime / "runs/existing").iterdir()], ["old"])
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        with windows_directory_policy():
            snapshot(store.job_dir("existing"), store.runtime / "runs/existing/recovered/source")

    def test_job_staging_failure_preserves_existing_job_and_allows_retry(self):
        store, files = self.seed_existing_data()
        with windows_directory_policy(), patch("runner.store.atomic_write", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                store.create(default_job("new"))
        self.assertFalse(list(store.jobs.glob(".create-*")))
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        with windows_directory_policy():
            self.assertEqual(store.create(default_job("new"))["id"], "new")

    def test_package_staging_failure_cleans_only_owned_temporary_directory(self):
        store, files = self.seed_existing_data()
        packages = Packages(store)
        keep = store.runtime / "deployments/keep.txt"
        keep.write_text("existing receipt")
        before = set((store.runtime / "deployments").iterdir())
        with windows_directory_policy(), patch("deployments.packages.snapshot", side_effect=OSError("synthetic copy failure")):
            with self.assertRaises(OSError):
                packages.create("existing")
        self.assertEqual(set((store.runtime / "deployments").iterdir()), before)
        self.assertEqual(keep.read_text(), "existing receipt")
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        with windows_directory_policy():
            self.assertTrue(packages.create("existing")["zip_available"])

    def test_temporary_directory_collision_never_removes_existing_data(self):
        collision = self.root / ".tmp-fixed"
        collision.mkdir()
        marker = collision / "keep.txt"
        marker.write_text("keep")
        with windows_directory_policy(), patch("runner.common.uuid.uuid4", return_value=SimpleNamespace(hex="fixed")):
            with self.assertRaises(FileExistsError):
                with common.private_temporary_directory(self.root):
                    self.fail("must not enter an existing directory")
        self.assertEqual(marker.read_text(), "keep")

    @unittest.skipIf(os.name == "nt", "POSIX mode/umask assertions")
    def test_posix_private_modes_atomic_files_and_existing_modes_unchanged(self):
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)
        store = Store(self.root)
        store.create(default_job("sample"))
        snapshot(store.job_dir("sample"), store.runtime / "snapshot")
        paths = Lifecycle(store).paths("sample", "a" * 32, create=True)
        packages = Packages(store)
        package = packages.create("sample")
        for path in [store.runtime, *(store.runtime / p for p in ("locks", "runs", "trash", "schedules", "deployments")),
                     store.job_dir("sample"), store.runtime / "snapshot", packages.root,
                     packages.root / package["id"],
                     *(Path(p) for k, p in paths.items() if k.endswith(("DIR", "ROOT"))
                       and k != "SCRIPT_MANAGER_JOB_DATA_ROOT")]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700, path)
        # pathlib parents=True retains its prior intermediate-directory policy.
        self.assertEqual(stat.S_IMODE(Path(paths["SCRIPT_MANAGER_JOB_DATA_ROOT"]).stat().st_mode), 0o777)
        self.assertEqual(stat.S_IMODE((store.job_dir("sample") / "job.yaml").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((packages.root / package["id"] / "package.zip").stat().st_mode), 0o400)
        (store.runtime / "locks").chmod(0o750)
        Store(self.root)
        self.assertEqual(stat.S_IMODE((store.runtime / "locks").stat().st_mode), 0o750)

    @unittest.skipIf(os.name == "nt", "POSIX PermissionError propagation")
    def test_posix_denial_preserves_original_error(self):
        failure = PermissionError(errno.EACCES, "synthetic denied")
        with patch.object(Path, "mkdir", side_effect=failure):
            with self.assertRaises(PermissionError) as raised:
                common.private_mkdir(self.root / "new")
        self.assertIs(raised.exception, failure)
