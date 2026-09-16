import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mapcombiner.contracts import PipelineError
from mapcombiner.package_import import Package, validate_asset_path
from mapcombiner.packaging import archive, verify_bundles, verify_archive
from mapcombiner.workspace_transaction import Transaction, git, index_snapshot, skip_existing_assets

def make_package(path, entries, extra=None):
    with tarfile.open(path, "w:gz") as output:
        for i, (name, payload) in enumerate(entries, 1):
            guid = f"{i:032x}"
            for kind, data in (("pathname", name.encode()), ("asset", payload),
                               ("asset.meta", f"fileFormatVersion: 2\nguid: {guid}\n".encode())):
                member = tarfile.TarInfo(f"{guid}/{kind}")
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
        if extra:
            output.addfile(extra)

class PackageTests(unittest.TestCase):
    def test_filter_executable_preserve_native_models_and_guid(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "map.unitypackage"
            make_package(source, [("Assets/MapResources/A/A.unity", b"scene"),
                                  ("Assets/MapResources/A/code.cs", b"evil"),
                                  ("Assets/MapResources/A/model.blend", b"native model"),
                                  ("Assets/MapResources/A/image.png", b"image")])
            pkg = Package(source).inspect()
            self.assertEqual(sum(e.allowed for e in pkg.entries), 3)
            sanitized = pkg.repack(Path(temp) / "sanitized.unitypackage")
            fresh = Package(sanitized).inspect()
            self.assertEqual([e.path for e in fresh.entries],
                             ["Assets/MapResources/A/A.unity", "Assets/MapResources/A/image.png", "Assets/MapResources/A/model.blend"])
            self.assertEqual(fresh.entries[0].guid, pkg.entries[0].guid)

    def test_traversal_windows_reserved_and_separators(self):
        for path in ("Assets/../outside.cs", "C:/outside", "/Assets/a", "Assets/CON.txt",
                     "Assets/a. ", "Assets/a:stream", "Assets//a", "Assets\\a.png"):
            with self.subTest(path=path), self.assertRaises(PipelineError):
                validate_asset_path(path)

    def test_links_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "bad.unitypackage"
            link = tarfile.TarInfo("0" * 32 + "/asset")
            link.type = tarfile.SYMTYPE
            link.linkname = "C:/outside"
            make_package(source, [], link)
            with self.assertRaises(PipelineError):
                Package(source).inspect()

    def test_case_collisions_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "bad.unitypackage"
            make_package(source, [("Assets/A.png", b"a"), ("Assets/a.png", b"b")])
            with self.assertRaises(PipelineError):
                Package(source).inspect()

    def test_infrastructure_overwrite_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "bad.unitypackage"
            make_package(source, [("Assets/Resources/MapManagerConfig.asset", b"state")])
            with self.assertRaises(PipelineError):
                Package(source).inspect()

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / ".gitignore").write_text("*.tgz\nLibrary/\nobj/\n")
        (self.repo / "Assets/MapResources").mkdir(parents=True)
        self.tracked = self.repo / "Assets/MapResources/baseline.asset"
        self.tracked.write_text("staged platform configuration")
        git(self.repo, "add", ".")
        self.snapshot, _ = index_snapshot(self.repo)
        self.tracked.write_text("unstaged map modifications")
        (self.repo / "Assets/MapResources/map.asset").write_text("discard map")
        (self.repo / "platform.tgz").write_bytes(b"NDA ignored canary")
        (self.repo / "platform.config").write_bytes(b"untracked protected canary")
        (self.repo / "Assets/MapResources/Map/obj").mkdir(parents=True)
        (self.repo / "Assets/MapResources/Map/obj/keep").write_bytes(b"ignored nested")
        self.job = Path(self.temp.name) / "job"

    def tearDown(self):
        self.temp.cleanup()

    def test_index_baseline_preserves_staging_sdk_and_ignored(self):
        with patch("mapcombiner.workspace_transaction.require_idle"):
            transaction = Transaction(self.repo, self.job)
            transaction.begin(["Assets/Imported/new.asset", "Assets/Imported/new.asset.meta"])
            self.assertEqual(self.tracked.read_text(), "staged platform configuration")
            self.assertFalse((self.repo / "Assets/MapResources/map.asset").exists())
            destination = self.repo / "Assets/Imported"
            destination.mkdir()
            (destination / "new.asset").write_text("new")
            self.tracked.write_text("worker edit")
            transaction.finish()
        self.assertEqual(index_snapshot(self.repo)[0], self.snapshot)
        self.assertEqual(self.tracked.read_text(), "staged platform configuration")
        self.assertEqual((self.repo / "platform.tgz").read_bytes(), b"NDA ignored canary")
        self.assertEqual((self.repo / "platform.config").read_bytes(), b"untracked protected canary")
        self.assertTrue((self.repo / "Assets/MapResources/Map/obj/keep").exists())
        self.assertFalse((self.repo / "Assets/Imported/new.asset").exists())

    def test_detect_index_change_without_resetting_it(self):
        with patch("mapcombiner.workspace_transaction.require_idle"):
            transaction = Transaction(self.repo, self.job)
            transaction.begin([])
            self.tracked.write_text("new staged config")
            git(self.repo, "add", ".")
            with self.assertRaises(PipelineError):
                transaction.finish()
            self.assertEqual(git(self.repo, "show", ":Assets/MapResources/baseline.asset"),
                             b"new staged config")

    def test_recovery_uses_recorded_index(self):
        with patch("mapcombiner.workspace_transaction.require_idle"):
            transaction = Transaction(self.repo, self.job)
            transaction.begin([])
            self.tracked.write_text("crashed worker")
            Transaction.recover(self.job)
        self.assertEqual(self.tracked.read_text(), "staged platform configuration")
        self.assertFalse(json.loads((self.job / "recovery.json").read_text())["cleanup_required"])

    def test_skip_baseline_guid_for_same_or_different_path_and_payload(self):
        for package_path in ("Assets/MapResources/base.mat", "Assets/MapResources/renamed.mat"):
            with self.subTest(package_path=package_path):
                baseline = self.repo / "Assets/MapResources/base.mat"
                baseline.write_bytes(b"baseline version")
                baseline.with_suffix(".mat.meta").write_text("guid: " + "0" * 31 + "1" + "\n")
                source = Path(self.temp.name) / "package.unitypackage"
                make_package(source, [(package_path, b"different package version"),
                                      ("Assets/New.unity", b"scene reference")])
                package = Package(source).inspect()
                skipped = skip_existing_assets(self.repo, package.entries)
                self.assertEqual(len(skipped), 1)
                self.assertEqual(skipped[0]["baseline_paths"], ["Assets/MapResources/base.mat"])
                self.assertEqual(baseline.read_bytes(), b"baseline version")
                destination = Path(self.temp.name) / ("filtered-" + Path(package_path).stem + ".unitypackage")
                filtered = Package(package.repack(destination)).inspect()
                self.assertEqual([e.path for e in filtered.entries], ["Assets/New.unity"])

    def test_reject_outside_cleanup(self):
        with patch("mapcombiner.workspace_transaction.require_idle"):
            transaction = Transaction(self.repo, self.job)
            with self.assertRaises(PipelineError):
                transaction.begin(["../outside"])
        self.assertEqual(self.tracked.read_text(), "unstaged map modifications")

class PackagingTests(unittest.TestCase):
    def test_zip_has_exact_payloads_and_versions_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            external = root / "external"
            external.mkdir()
            (external / "ShadowValley.bundle").write_bytes(b"UnityFS\x00scene")
            (external / "meta").write_bytes(b"UnityFS\x00metadata")
            first = archive(external, "ShadowValley", root / "output")
            original = first.read_bytes()
            second = archive(external, "ShadowValley", root / "output")
            self.assertEqual(second.name, "ShadowValley_Steam_v2.zip")
            self.assertEqual(first.read_bytes(), original)
            with zipfile.ZipFile(first) as z:
                self.assertEqual(z.namelist(), ["ShadowValley.bundle", "meta"])

    def test_missing_empty_or_nonbundle_outputs_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(PipelineError):
                verify_bundles(root, "A")
            (root / "A.bundle").write_bytes(b"UnityFS\x00map")
            (root / "meta").write_bytes(b"")
            with self.assertRaises(PipelineError):
                verify_bundles(root, "A")
            (root / "meta").write_bytes(b"not a bundle")
            with self.assertRaises(PipelineError):
                verify_bundles(root, "A")

if __name__ == "__main__":
    unittest.main()
