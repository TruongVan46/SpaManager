import unittest

from utils.navigation import safe_return_url


class SafeReturnUrlTestCase(unittest.TestCase):

    def test_internal_path_is_preserved(self):
        self.assertEqual(safe_return_url('/statistics'), '/statistics')

    def test_internal_query_string_is_preserved(self):
        self.assertEqual(
            safe_return_url('/statistics?page=1'),
            '/statistics?page=1',
        )

    def test_nested_return_url_is_preserved_without_recursive_decoding(self):
        value = '/statistics/service/4?return_url=%2Fstatistics%3Fpage%3D1'
        self.assertEqual(safe_return_url(value), value)

    def test_trailing_bare_question_mark_is_removed(self):
        self.assertEqual(
            safe_return_url('/statistics/service/4?'),
            '/statistics/service/4',
        )

    def test_query_value_question_mark_is_not_removed(self):
        value = '/invoices?note=?'
        self.assertEqual(safe_return_url(value), value)

    def test_external_absolute_url_is_rejected(self):
        self.assertIsNone(safe_return_url('https://evil.example'))

    def test_scheme_relative_url_is_rejected(self):
        self.assertIsNone(safe_return_url('//evil.example/path'))

    def test_backslash_host_bypass_is_rejected(self):
        self.assertIsNone(safe_return_url(r'\\evil.example\path'))

    def test_credentials_and_host_are_rejected(self):
        self.assertIsNone(safe_return_url('//user:pass@evil.example/path'))
        self.assertIsNone(safe_return_url('https://user:pass@evil.example'))

    def test_whitespace_is_normalized_before_validation(self):
        self.assertEqual(safe_return_url('  /invoices?page=2  '), '/invoices?page=2')


if __name__ == '__main__':
    unittest.main()
