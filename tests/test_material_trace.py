from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mapcombiner.material_trace import compare, profile_guid, saved_material, trace_job

GUID = '4ce80190f8d308243a16d19290d0b45b'
BITS = [-2.561971919639766e-29, 2.966984360664403e-17, -1.3195233605987099e-27, 1.0178962540357222e17]

class MaterialTraceTests(unittest.TestCase):
    def evidence(self):
        mat = dict(present=True, name='Leaves', path='Assets/Leaves.mat', guid='a'*32, localId='2100000',
                   shader='HDRP/Lit', shaderGuid='b'*32, shaderLocalId='4800000', materialId=5,
                   hasMaterialId=True, hasProfile=True, profileGuid=GUID, profileHash=1076270218)
        use = dict(hierarchy=['Combined'], renderer='MeshRenderer', component=0, slot=2, material=mat)
        prepared = dict(status='CAPTURED', uses=[use])
        imported = deepcopy(prepared)
        imported['uses'][0]['material'].update(profileGuid='0'*32, profileHash=0)
        mirrored = deepcopy(prepared)
        mirrored['uses'][0]['hierarchy'].insert(0, 'root')
        bundled = deepcopy(mirrored)
        bundled['uses'][0]['material'].update(bundleFile='CAB-local', pathId='88')
        saved = {'a'*32 + ':2100000': dict(mat, status='READ')}
        return imported, prepared, mirrored, bundled, saved

    def test_combined_slot_chain_retains_correct_profile(self):
        report = compare(*self.evidence())
        self.assertEqual(report['status'], 'MATCH')
        self.assertEqual(report['changed_slots'], 1)
        self.assertEqual(report['uses'][0]['slot'], 2)

    def test_profile_lost_in_bundle_is_not_a_match(self):
        evidence = self.evidence()
        evidence[3]['uses'][0]['material']['profileHash'] = 0
        report = compare(*evidence)
        self.assertEqual(report['status'], 'MISMATCH')
        self.assertEqual(report['uses'][0]['issues'][0]['stage'], 'mirrored -> bundled')

    def test_wrong_copy_binding_is_detected_before_bundle(self):
        evidence = self.evidence()
        evidence[2]['uses'][0]['material']['guid'] = 'c'*32
        self.assertEqual(compare(*evidence)['status'], 'MISMATCH')

    def test_duplicate_names_are_not_resolved_by_guessing(self):
        evidence = self.evidence()
        evidence[3]['uses'].append(deepcopy(evidence[3]['uses'][0]))
        self.assertEqual(compare(*evidence)['status'], 'INCOMPLETE')

    def test_missing_and_extra_renderer_slots_are_reported(self):
        for delta in ('missing', 'extra'):
            evidence = self.evidence()
            if delta == 'missing': evidence[3]['uses'].clear()
            else:
                extra = deepcopy(evidence[3]['uses'][0]); extra['slot'] += 1
                evidence[3]['uses'].append(extra)
            with self.subTest(delta=delta):
                self.assertEqual(compare(*evidence)['status'], 'INCOMPLETE')

    def test_saved_file_is_read_by_local_id_and_float_bits(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp); path = repo / 'Assets/Leaves.mat'; path.parent.mkdir()
            path.write_text('%YAML 1.1\n--- !u!21 &2100000\nMaterial:\n'
                '  m_Shader: {fileID: 4800000, guid: ' + 'b'*32 + ', type: 3}\n'
                '  m_SavedProperties:\n    m_Floats:\n    - _MaterialID: 5\n    - _DiffusionProfileHash: 2.6028161\n'
                '    m_Colors:\n    - _DiffusionProfileAsset: {r: ' + str(BITS[0]) + ', g: ' + str(BITS[1]) + ', b: ' + str(BITS[2]) + ', a: ' + str(BITS[3]) + '}\n')
            path.with_suffix('.mat.meta').write_text('guid: ' + 'a'*32 + '\n')
            evidence = self.evidence()
            record = saved_material(repo, evidence[1]['uses'][0]['material'])
            self.assertEqual(record['profileGuid'], GUID)
            self.assertEqual(record['profileHash'], 1076270218)
            evidence[4]['a'*32 + ':2100000'] = record
            self.assertEqual(compare(*evidence)['status'], 'MATCH')
            record['profileHash'] = 0
            self.assertEqual(compare(*evidence)['status'], 'MISMATCH')

    def test_missing_evidence_stays_diagnostic_without_a_false_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            result = trace_job(job, job, job/'missing.bundle')
            self.assertEqual(result['status'], 'INCOMPLETE')
            self.assertTrue(json.loads((job/'material-trace.json').read_text())['diagnostic_only'])

    def test_run_report_exposes_trace_without_changing_build_status(self):
        from mapcombiner.workflow import summary
        from mapcombiner.reports import render_run
        with tempfile.TemporaryDirectory() as temp:
            row = summary({'job_id': 'test', 'status': 'PASS', 'log_directory': temp,
                           'material_trace': {'status': 'MISMATCH'}}, 'steam', Path(temp))
            self.assertEqual(row['status'], 'PASS')
            html = render_run({'run_id': 'test', 'status': 'PASS', 'jobs': [row]})
            self.assertIn('material-trace.txt', html)
            self.assertIn('Материалы: MISMATCH', html)

    def test_public_hdrp_package_path_is_resolved_without_guessing_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            material = dict(path='Packages/com.unity.render-pipelines.high-definition/Default.mat', localId='2100000')
            for version in ('16.0.6', '17.0.3'):
                path = repo / ('Library/PackageCache/com.unity.render-pipelines.high-definition@' + version) / 'Default.mat'
                path.parent.mkdir(parents=True)
                path.write_text('%YAML 1.1\n--- !u!21 &2100000\nMaterial:\n  m_Name: Default\n')
                path.with_suffix('.mat.meta').write_text('guid: ' + 'a'*32 + '\n')
                record = saved_material(repo, material)
                self.assertEqual(record['status'], 'READ' if version == '16.0.6' else 'INCOMPLETE')

if __name__ == '__main__': unittest.main()
