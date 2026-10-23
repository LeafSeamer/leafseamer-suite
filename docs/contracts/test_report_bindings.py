"""报告绑定检查的反例；合成内存文件，不改真实报告。"""
import hashlib
import json
import unittest

from check_report_bindings import check_report


class ReportBindingsTests(unittest.TestCase):
    def setUp(self):
        self.spec = ('report.json', 'input_sha256', 'docs')
        self.source = b'{"n":1}\n'
        self.report = {'all_passed': True, 'input_sha256': {
            'source.json': hashlib.sha256(self.source).hexdigest()}}

    def check(self, report=None, source=None):
        raw = json.dumps(self.report if report is None else report).encode()
        files = {'report.json': raw, 'docs/source.json': self.source if source is None else source}
        def read(path):
            if path not in files:
                raise FileNotFoundError(path)
            return files[path]
        return check_report(self.spec, read)

    def test_exact_bytes(self):
        self.assertEqual(self.check(), 1)

    def test_line_endings_are_not_normalized(self):
        with self.assertRaisesRegex(ValueError, '输入字节不匹配'):
            self.check(source=b'{"n":1}\r\n')

    def test_semantically_equal_json_is_not_same_artifact(self):
        with self.assertRaises(ValueError):
            self.check(source=b'{ "n": 1 }\n')

    def test_changed_input(self):
        with self.assertRaises(ValueError):
            self.check(source=b'{"n":2}\n')

    def test_missing_input(self):
        self.report['input_sha256']['missing.json'] = '0' * 64
        with self.assertRaises(FileNotFoundError):
            self.check()

    def test_unsafe_paths(self):
        for name in ('../outside', '/absolute', 'C:/private', 'a\\b', './source.json', 'a//b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check({'all_passed': True, 'input_sha256': {name: '0' * 64}})

    def test_missing_or_empty_hashes(self):
        for data in ({'all_passed': True}, {'all_passed': True, 'input_sha256': {}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.check(data)

    def test_bad_hash_or_success_marker(self):
        for value in ('0' * 63, 'A' * 64, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check({'all_passed': True, 'input_sha256': {'source.json': value}})
        with self.assertRaises(ValueError):
            self.check({'all_passed': 1, 'input_sha256': self.report['input_sha256']})

    def test_duplicate_keys_rejected(self):
        raw = b'{"all_passed":false,"all_passed":true,"input_sha256":{}}'
        with self.assertRaisesRegex(ValueError, '重复JSON键'):
            check_report(self.spec, lambda path: raw)


if __name__ == '__main__':
    unittest.main()
