"""Generic page boundaries tested with invented strings only."""
import copy
import json
import unittest

from app import page_protocol as pp


BODY = 'The invented sample declines under the stated conditions [1].'
REFERENCE = r'- \[1\] A. Example, B. Sample, "Invented Sample", Fictional Journal (2024).'
FORMULA = '<!-- LIT_FORMULA_TRANSCRIPTION {"formula_id":"EQ001","pdf_page":1} -->\n$$\nx + y = 3\n$$'
TAIL = 'The complete reference list ends here. This ordinary paragraph keeps 7 labels [1].'


def reference_end(page=1, reference=REFERENCE):
    return {'pdf_page': page, 'last_reference_number': int(pp.REFERENCE_LINE_RE.fullmatch(reference)['number']),
            'last_reference_sha256': pp.sha256_text(reference.strip())}


def end_marker(meta):
    return '<!-- LIT_REFERENCE_END ' + json.dumps(meta, separators=(',', ':')) + ' -->'


def translated(source, page=1, value='这个虚构样本在所述条件下呈现下降趋势 [1]。', **kwargs):
    page_input, record = pp.make_page_contract('SYNTHETIC', page, source, **kwargs)
    def replace(match):
        meta = json.loads(match['meta'])
        text = value(meta) if callable(value) else value
        return ('<!-- LIT_TRANSLATED_SPAN ' + json.dumps(meta, ensure_ascii=False) + ' -->\n'
                + text + '\n<!-- LIT_TRANSLATED_SPAN_END ' + meta['id'] + ' -->')
    return '## PDF 第 ' + str(page) + ' 页\n\n' + pp.SPAN_INPUT_RE.sub(replace, page_input), record


class PageProtocolTests(unittest.TestCase):
    def assertReject(self, code, function, *args):
        with self.assertRaisesRegex(ValueError, code):
            function(*args)

    def test_complete_page_roundtrip_preserves_formula_figure_reference(self):
        source = BODY + '\n\n' + FORMULA + '\n\n![Figure 1](figures/Figure-01.png)\n\n# References\n\n' + REFERENCE
        def choose(meta):
            return '参考文献' if meta['kind'] == 'heading' else '这个虚构样本在所述条件下呈现下降趋势 [1]。'
        text, record = translated(source, value=choose)
        elements, metrics = pp.validate(text, 1, record)
        assembled = pp.assemble_page(elements, record)
        self.assertEqual([p['kind'] for p in record['protected_blocks']], ['formula', 'figure', 'reference'])
        self.assertIn(FORMULA, assembled)
        self.assertIn(REFERENCE, assembled)
        self.assertIn('![Figure 1](figures/Figure-01.png)', assembled)
        self.assertEqual(metrics['translate_spans'], 2)
        self.assertNotIn('LIT_PROTECTED', assembled)

    def test_split_exact_pages(self):
        self.assertEqual(pp.split_pages('<!-- PDF_PAGE: 1 -->\nFirst\n<!-- PDF_PAGE: 2 -->\nSecond\n', 2), {1: 'First', 2: 'Second'})

    def test_unowned_prefix_rejected(self):
        self.assertReject('SOURCE_UNOWNED_PREFIX', pp.split_pages, 'Lost prose\n<!-- PDF_PAGE: 1 -->\nBody', 1)

    def test_missing_duplicate_reordered_pages_rejected(self):
        for text in ('<!-- PDF_PAGE: 2 -->\nBody', '<!-- PDF_PAGE: 1 -->\nOne\n<!-- PDF_PAGE: 1 -->\nTwo'):
            self.assertReject('SOURCE_PAGE_COVERAGE', pp.split_pages, text, 2)

    def test_bool_and_page_boundaries(self):
        for count in (True, 0, 1000, 1.0):
            self.assertReject('PAGE_COUNT', pp.split_pages, '<!-- PDF_PAGE: 1 -->\nBody', count)
        for page in (True, 0, 1000):
            self.assertReject('PAGE_NUMBER', pp.make_page_contract, 'SYNTHETIC', page, BODY)

    def test_source_format(self):
        for body in (BODY + '\r\n', '\ufeff' + BODY, BODY + '\x00'):
            with self.assertRaises(ValueError):
                pp.make_page_contract('SYNTHETIC', 1, body)

    def test_reserved_source_tokens(self):
        for body in ('{{LIT_PROTECTED:P001-B001}}', '{{FOREIGN_PROTECTED:P001-B001}}', '<!-- fabricated -->'):
            self.assertReject('SOURCE_RESERVED_MARKER', pp.make_page_contract, 'SYNTHETIC', 1, body)

    def test_no_automatic_short_word_exemption(self):
        _, record = pp.make_page_contract('SYNTHETIC', 1, 'No')
        self.assertEqual(record['translate_span_count'], 1)
        self.assertEqual(record['protected_blocks'], [])

    def test_body_reference_without_heading_rejected(self):
        self.assertReject('REFERENCE_WITHOUT_HEADING', pp.make_page_contract, 'SYNTHETIC', 1, r'- \[1\] Ordinary scientific text must be translated.')

    def test_bibliographic_reference_without_heading_rejected(self):
        self.assertReject('REFERENCE_WITHOUT_HEADING', pp.make_page_contract, 'SYNTHETIC', 1, REFERENCE)

    def test_fake_reference_under_heading_rejected(self):
        self.assertReject('REFERENCE_BIBLIOGRAPHIC_SIGNALS', pp.make_page_contract, 'SYNTHETIC', 1, '# References\n\n' + r'- \[1\] Ordinary scientific text must be translated.')

    def test_reference_sequence_rejected(self):
        self.assertReject('REFERENCE_SEQUENCE', pp.make_page_contract, 'SYNTHETIC', 1, '# References\n\n' + REFERENCE + '\n' + REFERENCE.replace(r'\[1\]', r'\[3\]'))

    def test_reference_continuation_rejected(self):
        self.assertReject('REFERENCE_CONTINUATION_OR_STYLE_UNSUPPORTED', pp.make_page_contract, 'SYNTHETIC', 1, '# References\n\n' + REFERENCE + '\ncontinued author or title')

    def test_noncanonical_numeric_reference_lines_never_become_paragraphs(self):
        body = pp.REFERENCE_LINE_RE.fullmatch(REFERENCE)['body']
        prefixes = ('- [1]', r'- \[1]', r'- [1\]', r'- \\[1\\]',
                    r'- \\[1\]', r'- \[1\\]', r'\[1\]', r'+ \[1\]',
                    r'-  \[1\]', r'- \[01\]', r'- \[1\]no-separator')
        meta = reference_end()
        ended = '# References\n' + REFERENCE + '\n\n' + end_marker(meta) + '\n\n' + TAIL + '\n\n'
        for prefix in prefixes:
            bad = prefix + ' ' + body
            for before, binding in (('# References\n', None), (BODY + '\n\n', None), (ended, [meta])):
                with self.subTest(prefix=prefix, before=before), self.assertRaisesRegex(ValueError, '^REFERENCE_STYLE_UNSUPPORTED$'):
                    pp.make_page_contract('SYNTHETIC', 1, before + bad, reference_ends=binding)
            with self.subTest(first_following=prefix), self.assertRaisesRegex(ValueError, 'REFERENCE_END_FOLLOWING_PARAGRAPH'):
                pp.make_page_contract('SYNTHETIC', 1, ended[:ended.index(TAIL)] + bad, reference_ends=[meta])

    def test_escaped_reference_bytes_and_unescaped_body_citations_are_preserved(self):
        source = BODY + '\n\n# References\n\n' + REFERENCE
        text, record = translated(source, value=lambda m:
                                  '参考文献' if m['kind'] == 'heading' else '这个虚构样本在所述条件下呈现下降趋势 [1]。')
        protected = record['protected_blocks'][0]
        self.assertEqual(protected['source'], REFERENCE)
        self.assertEqual(protected['source_sha256'], pp.sha256_text(REFERENCE))
        self.assertNotEqual(protected['source_sha256'], pp.sha256_text(REFERENCE.replace(r'\[1\]', '[1]')))
        elements, _ = pp.validate(text, 1, record)
        assembled = pp.assemble_page(elements, record)
        self.assertIn(REFERENCE, assembled)
        self.assertIn('下降趋势 [1]。', assembled)
        self.assertNotIn('下降趋势 ' + r'\[1\]', assembled)
        self.assertNotIn('reference_end', record)

    def test_reference_end_cannot_reuse_legacy_unescaped_line_hash(self):
        meta = reference_end()
        old_hash = pp.sha256_text(REFERENCE.replace(r'\[1\]', '[1]'))
        old_meta = dict(meta, last_reference_sha256=old_hash)
        wrong_source = '# References\n' + REFERENCE + '\n\n' + end_marker(old_meta) + '\n\n' + TAIL
        with self.assertRaisesRegex(ValueError, 'REFERENCE_END_POSITION'):
            pp.make_page_contract('SYNTHETIC', 1, wrong_source, reference_ends=[old_meta])
        right_source = '# References\n' + REFERENCE + '\n\n' + end_marker(meta) + '\n\n' + TAIL
        with self.assertRaisesRegex(ValueError, 'REFERENCE_END_BINDING'):
            pp.make_page_contract('SYNTHETIC', 1, right_source, reference_ends=[old_meta])

    def test_reference_end_keeps_following_whole_paragraph_in_normal_contract(self):
        meta = reference_end()
        source = '# References\n\n' + REFERENCE + '\n\n' + end_marker(meta) + '\n\n' + TAIL
        page_input, record = pp.make_page_contract('SYNTHETIC', 1, source, reference_ends=[meta])
        spans = list(pp.SPAN_INPUT_RE.finditer(page_input))
        self.assertEqual([m['body'].strip() for m in spans], ['# References', TAIL])
        self.assertEqual(json.loads(spans[-1]['meta'])['kind'], 'paragraph')
        self.assertEqual(record['reference_end'], meta)
        self.assertEqual(record['protected_blocks'][0]['source'], REFERENCE)
        self.assertNotIn('LIT_REFERENCE_END', page_input)
        text, record = translated(source, reference_ends=[meta], value=lambda m:
                                  '参考文献' if m['kind'] == 'heading' else '这份完整参考列表在这里结束。这段普通正文保留全部 7 个标记 [1]。')
        elements, _ = pp.validate(text, 1, record)
        assembled = pp.assemble_page(elements, record)
        self.assertIn(REFERENCE, assembled)
        self.assertTrue(assembled.index(REFERENCE) < assembled.index('这份完整参考列表'))
        self.assertNotIn('LIT_REFERENCE_END', assembled)

    def test_reference_end_needs_exact_inventory_binding(self):
        meta = reference_end()
        source = '# References\n' + REFERENCE + '\n' + end_marker(meta) + '\n\n' + TAIL
        for binding in (None, [], [dict(meta, pdf_page=2)], [dict(meta, last_reference_sha256='0' * 64)]):
            with self.subTest(binding=binding), self.assertRaisesRegex(ValueError, 'REFERENCE_END_BINDING'):
                pp.make_page_contract('SYNTHETIC', 1, source, reference_ends=binding)
        with self.assertRaisesRegex(ValueError, 'REFERENCE_END_MISSING'):
            pp.make_page_contract('SYNTHETIC', 1, '# References\n' + REFERENCE, reference_ends=[meta])

    def test_reference_end_rejects_unknown_duplicate_and_wrong_metadata(self):
        meta = reference_end()
        variants = [dict(meta, unknown=True), dict(meta, pdf_page=True), dict(meta, last_reference_number=True),
                    dict(meta, pdf_page=2), dict(meta, last_reference_number=2),
                    dict(meta, last_reference_sha256='0' * 64)]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'REFERENCE_END_(BINDING|POSITION)'):
                pp.make_page_contract('SYNTHETIC', 1, '# References\n' + REFERENCE + '\n' + end_marker(changed)
                                      + '\n\n' + TAIL, reference_ends=[meta])
        duplicate = end_marker(meta).replace('"pdf_page":1', '"pdf_page":1,"pdf_page":1')
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON_KEY'):
            pp.make_page_contract('SYNTHETIC', 1, '# References\n' + REFERENCE + '\n' + duplicate
                                  + '\n\n' + TAIL, reference_ends=[meta])
        for binding in ({}, [dict(meta, unknown=True)], [meta, meta], [dict(meta, pdf_page=True)],
                        [dict(meta, last_reference_number=True)], [dict(meta, last_reference_sha256='bad')],
                        [dict(meta, last_reference_sha256=meta['last_reference_sha256'].lower())]):
            with self.subTest(binding=binding), self.assertRaisesRegex(ValueError, 'REFERENCE_END_INVENTORY'):
                pp.make_page_contract('SYNTHETIC', 1, BODY, reference_ends=binding)

    def test_reference_end_rejects_orphan_misplacement_and_wrong_last_reference(self):
        meta = reference_end()
        marker = end_marker(meta)
        for before in ('', '# References\n', '# Other heading\n' + BODY + '\n',
                       '# References\n' + REFERENCE + '\n# Other heading\n',
                       '# References\n' + REFERENCE + '\n' + REFERENCE.replace(r'\[1\]', r'\[2\]') + '\n'):
            with self.subTest(before=before), self.assertRaisesRegex(ValueError, 'REFERENCE_END_POSITION'):
                pp.make_page_contract('SYNTHETIC', 1, before + marker + '\n\n' + TAIL, reference_ends=[meta])
        wrong = dict(meta, last_reference_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'REFERENCE_END_POSITION'):
            pp.make_page_contract('SYNTHETIC', 1, '# References\n' + REFERENCE + '\n' + end_marker(wrong)
                                  + '\n\n' + TAIL, reference_ends=[wrong])

    def test_reference_end_requires_first_plain_paragraph_and_forbids_later_refs(self):
        meta = reference_end()
        prefix = '# References\n' + REFERENCE + '\n\n' + end_marker(meta) + '\n\n'
        for following in ('', '# Invented heading\n' + TAIL, FORMULA + '\n\n' + TAIL,
                          '![Figure 1](figures/Figure-01.png)\n\n' + TAIL, REFERENCE,
                          '1. ' + REFERENCE, end_marker(meta) + '\n\n' + TAIL):
            with self.subTest(following=following), self.assertRaisesRegex(ValueError, 'REFERENCE_END_FOLLOWING_PARAGRAPH'):
                pp.make_page_contract('SYNTHETIC', 1, prefix + following, reference_ends=[meta])
        for later, code in ((end_marker(meta), 'REFERENCE_END_DUPLICATE'),
                            (REFERENCE, 'REFERENCE_END_LATER_REFERENCE'),
                            ('# References\n' + REFERENCE, 'REFERENCE_END_LATER_REFERENCE')):
            with self.subTest(later=later), self.assertRaisesRegex(ValueError, code):
                pp.make_page_contract('SYNTHETIC', 1, prefix + TAIL + '\n\n' + later, reference_ends=[meta])

    def test_reference_end_does_not_exempt_language_conversion_or_modify_old_records(self):
        _, old = pp.make_page_contract('SYNTHETIC', 1, '# References\n' + REFERENCE)
        self.assertNotIn('reference_end', old)
        meta = reference_end()
        long_tail = 'The ordinary invented paragraph must still be translated faithfully. ' * 12
        source = '# References\n' + REFERENCE + '\n\n' + end_marker(meta) + '\n\n' + long_tail
        text, record = translated(source, reference_ends=[meta], value=lambda m:
                                  '参考文献' if m['kind'] == 'heading' else long_tail)
        with self.assertRaisesRegex(ValueError, 'target-language conversion missing'):
            pp.validate(text, 1, record)

    def test_reference_state_does_not_cross_pages(self):
        body = '<!-- PDF_PAGE: 1 -->\n# References\n' + REFERENCE + '\n<!-- PDF_PAGE: 2 -->\n' + REFERENCE.replace(r'\[1\]', r'\[2\]')
        pages = pp.split_pages(body, 2)
        pp.make_page_contract('SYNTHETIC', 1, pages[1])
        self.assertReject('REFERENCE_WITHOUT_HEADING', pp.make_page_contract, 'SYNTHETIC', 2, pages[2])

    def test_reference_end_does_not_authorize_cross_page_continuation(self):
        meta = reference_end()
        source = ('<!-- PDF_PAGE: 1 -->\n# References\n' + REFERENCE + '\n\n' + end_marker(meta)
                  + '\n\n' + TAIL + '\n<!-- PDF_PAGE: 2 -->\n' + REFERENCE.replace(r'\[1\]', r'\[2\]'))
        pages = pp.split_pages(source, 2)
        pp.make_page_contract('SYNTHETIC', 1, pages[1], reference_ends=[meta])
        with self.assertRaisesRegex(ValueError, 'REFERENCE_WITHOUT_HEADING'):
            pp.make_page_contract('SYNTHETIC', 2, pages[2], reference_ends=[meta])

    def test_reference_style_plain_numbering_rejected(self):
        self.assertReject('REFERENCE_CONTINUATION_OR_STYLE_UNSUPPORTED', pp.make_page_contract, 'SYNTHETIC', 1, '# References\n\n' + REFERENCE.replace(r'- \[1\]', '1.'))

    def test_unregistered_formula_rejected(self):
        self.assertReject('UNREGISTERED_FORMULA', pp.make_page_contract, 'SYNTHETIC', 1, BODY + '\n\n$$\nx+y=3\n$$')

    def test_wrong_page_and_duplicate_formula_id_rejected(self):
        for body in (FORMULA.replace('"pdf_page":1', '"pdf_page":2'), FORMULA + '\n\n' + FORMULA):
            self.assertReject('FORMULA_METADATA', pp.make_page_contract, 'SYNTHETIC', 1, BODY + '\n\n' + body)

    def test_unknown_and_duplicate_formula_metadata_fields_rejected(self):
        for bad in (FORMULA.replace('"pdf_page":1', '"pdf_page":1,"ignore":true'), FORMULA.replace('"pdf_page":1', '"pdf_page":1,"pdf_page":1')):
            with self.assertRaises(ValueError):
                pp.make_page_contract('SYNTHETIC', 1, BODY + '\n\n' + bad)

    def test_unclosed_empty_and_inline_delimiter_formula_rejected(self):
        for bad in (FORMULA[:-2], FORMULA.replace('x + y = 3', ''), FORMULA.replace('x + y = 3', 'x $$ y')):
            with self.assertRaises(ValueError):
                pp.make_page_contract('SYNTHETIC', 1, BODY + '\n\n' + bad)

    def test_unsupported_zero_span_page(self):
        self.assertReject('ZERO_SPAN_OR_PAGE_SPAN_LIMIT', pp.make_page_contract, 'SYNTHETIC', 1, FORMULA)

    def test_figure_identity_and_inline_image_rejected(self):
        for image in ('![Figure 2](figures/Figure-01.png)', 'prose ![Figure 1](figures/Figure-01.png)'):
            with self.assertRaises(ValueError):
                pp.make_page_contract('SYNTHETIC', 1, BODY + '\n\n' + image)

    def test_citation_change_rejected(self):
        text, record = translated(BODY)
        with self.assertRaisesRegex(ValueError, 'citation group drift'):
            pp.validate(text.replace('[1]', '[2]'), 1, record)

    def test_span_hash_and_metadata_kind_drift_rejected(self):
        text, record = translated(BODY)
        for key, wrong in (('source_sha256', '0' * 64), ('kind', 'protected')):
            meta = json.loads(pp.SPAN_OUTPUT_RE.search(text)['meta'])
            changed = dict(meta, **{key: wrong})
            altered = text.replace(json.dumps(meta, ensure_ascii=False), json.dumps(changed, ensure_ascii=False))
            self.assertReject('SPAN_METADATA_BINDING', pp.validate, altered, 1, record)

    def test_protected_token_drop_and_reorder_rejected(self):
        text, record = translated(BODY + '\n\n' + FORMULA)
        token = record['protected_blocks'][0]['token']
        for bad in (text.replace(token, ''), text.replace(token, '') + token + token):
            with self.assertRaisesRegex(ValueError, 'element sequence'):
                pp.validate(bad, 1, record)

    def test_uncontracted_prose_rejected(self):
        text, record = translated(BODY)
        with self.assertRaisesRegex(ValueError, 'uncontracted trailing'):
            pp.validate(text + '额外未登记正文', 1, record)

    def test_new_formula_or_token_inside_translation_rejected(self):
        for value in ('真实测试文字 [1] $$x=2$$', '真实测试文字 [1] {{LIT_PROTECTED:P001-B001}}'):
            text, record = translated(BODY, value=value)
            self.assertReject('TRANSLATION_UNREGISTERED_STRUCTURE', pp.validate, text, 1, record)

    def test_short_translation_rejected(self):
        text, record = translated('Long scientific sentence. ' * 30, value='短句')
        with self.assertRaisesRegex(ValueError, 'too short'):
            pp.validate(text, 1, record)

    def test_original_long_span_language_trigger(self):
        source = 'Invented scientific prose. ' * 10
        text, record = translated(source, value=source)
        with self.assertRaisesRegex(ValueError, 'target-language conversion missing'):
            pp.validate(text, 1, record)

    def test_original_page_language_trigger(self):
        source = '\n\n'.join(['English fragment of several words.'] * 6)
        text, record = translated(source, value='English fragment of several words.')
        with self.assertRaisesRegex(ValueError, 'not predominantly a Chinese translation'):
            pp.validate(text, 1, record)

    def test_assembly_rejects_protected_bytes_drift(self):
        text, record = translated(BODY + '\n\n' + FORMULA)
        elements, _ = pp.validate(text, 1, record)
        bad = copy.deepcopy(record)
        bad['protected_blocks'][0]['source'] = 'altered'
        self.assertReject('ASSEMBLY_PROTECTED_DRIFT', pp.assemble_page, elements, bad)

    def test_assembly_rejects_element_reorder(self):
        text, record = translated(BODY + '\n\n' + FORMULA)
        elements, _ = pp.validate(text, 1, record)
        self.assertReject('ASSEMBLY_ELEMENT_SEQUENCE', pp.assemble_page, elements[::-1], record)


if __name__ == '__main__':
    unittest.main()
