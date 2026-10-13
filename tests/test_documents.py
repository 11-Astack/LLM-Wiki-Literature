"""Synthetic module-mechanism tests; neither release nor scientific acceptance.

The real A/B example PDFs exercise intake. A separate, explicitly invented
two-page component source exercises protected structures and failure gates.
Its translations are technical test strings, never semantic review evidence.
"""
from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app import core as c, documents as d, page_protocol as pp


PACKAGE = Path(__file__).resolve().parents[1]
SCRATCH = PACKAGE / 'tests/.scratch/documents'
REFERENCE = r'- \[1\] A. Example, B. Sample, "Invented component", Fictional Journal (2024).'
FORMULA = '<!-- LIT_FORMULA_TRANSCRIPTION {"formula_id":"EQ001","pdf_page":1} -->\n$$\nx + y = 3\n$$'
CAPTION = 'Figure 1. The invented component rectangle identifies a crop for technical testing.'
SOURCE = ('<!-- PDF_PAGE: 1 -->\n# Component mechanism\n\n'
          'This invented numeric component uses .5, -2.5, 3e-4 and \u22126E+2 for a technical gate only [1].\n\n'
          + FORMULA + '\n\n![Figure 1](figures/Figure-01.png)\n\n' + CAPTION
          + '\n\n<!-- PDF_PAGE: 2 -->\n# Second component\n\n'
          'This separate invented paragraph checks that every page must be accepted in order before assembly.\n\n'
          '# References\n\n' + REFERENCE + '\n')
REFERENCE_TAIL = 'This ordinary paragraph after the complete reference list keeps 7 labels [1].'


def source_with_reference_end():
    meta = {'pdf_page': 2, 'last_reference_number': 1,
            'last_reference_sha256': pp.sha256_text(REFERENCE.strip())}
    source = SOURCE + '\n<!-- LIT_REFERENCE_END ' + json.dumps(meta, separators=(',', ':')) + ' -->\n\n' + REFERENCE_TAIL + '\n'
    return source, meta


def minimal_library(root):
    """Native _library shape only; complete storage integration is test_cli's job."""
    root.mkdir(parents=True)
    (root / '.system').mkdir()
    (root / '.work' / 'runs').mkdir(parents=True)
    instance_id = '11111111-1111-4111-8111-111111111111'
    vault = 'Reading-' + instance_id[:8]
    categories = [{'id': 'DEMO', 'label': '纯合成技术测试'}]
    confirmation = root / '.system/category-confirmation.json'
    confirmation.write_bytes(c.encode({'confirmed': True, 'categories_sha256': c.sha(c.encode(categories)),
                                      'scope': 'SYNTHETIC_DEMO', 'authorization': '纯合成机制测试夹具'}))
    overview = root / vault / 'indexes/Library-000000.md'
    overview.parent.mkdir(parents=True)
    overview.write_bytes('# 纯合成机制测试索引\n'.encode())
    value = {'schema': 'singlepaper.library.v1',
             'instance_id': instance_id, 'vault_dir': vault, 'revision': 0,
             'storage_layout': 'immutable-reading.v2', 'created_utc': c.utcnow().isoformat(),
             'root_binding': str(root.resolve()), 'categories': categories, 'works': [],
             'category_confirmation': c.ref(root, confirmation), 'overview': c.ref(root, overview)}
    (root / '.system' / 'library.json').write_bytes(c.encode(value))
    return root


def invented_pdf(path, texts):
    """Create a new valid text-layer PDF without a network or real source."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref})})
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream = DecodedStreamObject()
        # The long single line is deliberate: threshold tests count extracted text.
        stream.set_data(('BT /F1 7 Tf 30 700 Td (' + escaped + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as output:
        writer.write(output)
    return path


class DocumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='synthetic-', dir=SCRATCH)
        cls.base = Path(cls.temporary.name)
        # Stable descriptor deliberately isolates module checks from parallel
        # release work. It is not advertised as a launchable release package.
        cls.descriptor = cls.base / 'module-descriptor'
        (cls.descriptor / 'app').mkdir(parents=True)
        (cls.descriptor / 'launch.py').write_bytes(b'# Synthetic module descriptor only\n')
        (cls.descriptor / 'RUNTIME_MANIFEST.json').write_bytes(c.encode({'synthetic_descriptor_only': True}))
        for name in ('documents.py', 'page_protocol.py', 'core.py'):
            shutil.copyfile(PACKAGE / 'app' / name, cls.descriptor / 'app' / name)
        seed_instance = minimal_library(cls.base / 'seed-instance')
        result = d.intake(cls.descriptor, seed_instance,
                          PACKAGE / 'examples' / 'SYNTHETIC_READABLE_TWO_PAGES.pdf',
                          '纯合成两页组件测试', 'DEMO')
        cls.seed_run = Path(result['run'])
        cls.assert_seed_pages = result['page_count']
        cls.ordinal = 0

    @classmethod
    def tearDownClass(cls):
        # Verify the exact owned target before TemporaryDirectory recursively
        # removes it; no application instance or parent directory is eligible.
        if not cls.base.resolve().is_relative_to(SCRATCH.resolve()) or not cls.base.name.startswith('synthetic-'):
            raise RuntimeError('TEST_CLEANUP_TARGET_OUTSIDE_OWNED_SCRATCH')
        cls.temporary.cleanup()

    def setUp(self):
        type(self).ordinal += 1
        self.case = self.base / ('case-' + str(self.ordinal))
        self.case.mkdir()
        self.instance = minimal_library(self.case / 'component-instance')
        self.run = self.instance / '.work' / 'runs' / self.seed_run.name
        shutil.copytree(self.seed_run, self.run)
        self.package = self.descriptor
        self.assertEqual(self.assert_seed_pages, 2)

    def reject(self, code, function, *args, **kwargs):
        with self.assertRaises(ValueError) as raised:
            function(*args, **kwargs)
        self.assertEqual(str(raised.exception), code)

    def intake(self, pdf, name='fresh', **kwargs):
        instance = minimal_library(self.case / name)
        return d.intake(self.package, instance, pdf, '纯合成通用入口', 'DEMO', **kwargs)

    def drafts(self, source=SOURCE, change=None):
        from PIL import Image, ImageChops
        inp, input_sha = d.input_record(self.package, self.run)
        with Image.open(self.run / inp['pages'][0]['image']['path']) as image:
            rgb = image.convert('RGB')
            ink_bbox = ImageChops.difference(rgb, Image.new('RGB', image.size, 'white')).getbbox()
            self.assertIsNotNone(ink_bbox, 'The component crop must include real rendered ink.')
        inventory = {'schema': 'singlepaper.inventory.v1', 'input_sha256': input_sha,
                     'source_sha256': c.sha(source.encode()), 'page_count': 2,
                     'reviewed_pages': [1, 2],
                     'formulas': [{'id': 'EQ001', 'page': 1, 'latex': 'x + y = 3', 'printed_label': None}],
                     'figures': [{'number': 1, 'page': 1, 'bbox_pixels': list(ink_bbox), 'caption': CAPTION}],
                     'references': [{'number': 1, 'page': 2, 'text': REFERENCE}]}
        if change:
            change(inventory)
        directory = self.run / 'draft'
        directory.mkdir(exist_ok=True)
        source_path, inventory_path = directory / 'source.md', directory / 'inventory.json'
        source_path.write_bytes(source.encode('utf-8'))
        inventory_path.write_bytes(c.encode(inventory))
        return source_path, inventory_path

    def prepare(self, source=SOURCE, change=None):
        return d.prepare_source(self.package, self.run, *self.drafts(source, change))

    def candidate(self, page):
        _, frozen, source_sha = d.source_record(self.package, self.run)
        text = (self.run / f'page-inputs/page-{page:03d}.md').read_text(encoding='utf-8')
        def technical(match):
            metadata = json.loads(match['meta'])
            # This text intentionally does NOT purport to translate the source.
            # It only meets visible-character and numeric/citation gates.
            numbers = d.NUMBER_RE.findall(match['body'])
            citations = pp.citation_groups(match['body'])
            citation_numbers = []
            for group in citations:
                citation_numbers.extend(d.NUMBER_RE.findall(group))
            for number in citation_numbers:
                numbers.remove(number)
            value = '技术测试专用句子用于检查页面结构和数字保真并不声明科学语义通过。' * 2
            value += ' ' + ' '.join(numbers)
            value += ''.join(' [' + group + ']' for group in citations)
            return ('<!-- LIT_TRANSLATED_SPAN ' + json.dumps(metadata, ensure_ascii=False) + ' -->\n'
                    + value + '\n<!-- LIT_TRANSLATED_SPAN_END ' + metadata['id'] + ' -->')
        text = f'<!-- LIT_SESSION_SHA256 {source_sha} -->\n## PDF 第 {page} 页\n\n' + pp.SPAN_INPUT_RE.sub(technical, text)
        target = self.run / f'candidates/technical-{page:03d}.md'
        target.write_bytes(text.encode('utf-8'))
        return target

    def accept_all(self):
        self.prepare()
        for page in (1, 2):
            d.validate_page(self.package, self.run, page, self.candidate(page))

    def supplements(self):
        for name in ('summary.md', 'science_notes.md'):
            (self.run / name).write_bytes('这是纯合成技术机制测试说明，不代表任何科学语义审核结论。\n'.encode())

    def assembled(self):
        self.accept_all()
        self.supplements()
        return d.assemble(self.package, self.run)

    def test_reference_end_freezes_whole_tail_and_uses_normal_acceptance_and_assembly(self):
        source, meta = source_with_reference_end()
        self.prepare(source, lambda inventory: inventory.update(reference_ends=[meta]))
        _, frozen, _ = d.source_record(self.package, self.run)
        self.assertNotIn('reference_end', frozen['records'][0])
        self.assertEqual(frozen['records'][1]['reference_end'], meta)
        page_input = (self.run / 'page-inputs/page-002.md').read_text(encoding='utf-8')
        spans = list(pp.SPAN_INPUT_RE.finditer(page_input))
        self.assertEqual(spans[-1]['body'].strip(), REFERENCE_TAIL)
        self.assertEqual(json.loads(spans[-1]['meta'])['kind'], 'paragraph')
        self.assertNotIn('LIT_REFERENCE_END', page_input)
        for page in (1, 2):
            d.validate_page(self.package, self.run, page, self.candidate(page))
        self.supplements()
        d.assemble(self.package, self.run)
        self.assertEqual((self.run / 'source.md').read_bytes(), source.encode())
        translated = (self.run / 'translation_zh.md').read_text(encoding='utf-8')
        self.assertNotIn('LIT_REFERENCE_END', translated)
        self.assertIn(REFERENCE, translated)
        self.assertIn(' 7', translated)
        self.assertTrue(translated.index(REFERENCE) < translated.rindex('技术测试专用句子'))

    def test_reference_end_inventory_mismatches_cannot_freeze_source(self):
        source, meta = source_with_reference_end()
        cases = [(None, 'REFERENCE_END_BINDING'),
                 ([], 'REFERENCE_END_BINDING'),
                 ([dict(meta, last_reference_sha256='0' * 64)], 'REFERENCE_END_BINDING'),
                 ([meta, dict(meta, pdf_page=3)], 'REFERENCE_END_INVENTORY'),
                 ([dict(meta, pdf_page=3)], 'REFERENCE_END_BINDING'),
                 ([dict(meta, unknown=True)], 'REFERENCE_END_INVENTORY'),
                 ([meta, meta], 'REFERENCE_END_INVENTORY')]
        for binding, code in cases:
            change = None if binding is None else lambda inventory, binding=binding: inventory.update(reference_ends=binding)
            with self.subTest(binding=binding):
                self.reject(code, self.prepare, source, change)
                self.assertFalse((self.run / 'SOURCE.json').exists())
                self.assertFalse((self.run / 'source.snapshot.md').exists())
        self.reject('REFERENCE_END_MISSING', self.prepare, SOURCE,
                    lambda inventory: inventory.update(reference_ends=[meta]))

    def test_reference_end_cannot_hide_missing_reference_inventory(self):
        source, meta = source_with_reference_end()
        self.reject('INVENTORY_COMPLETE_SEQUENCE', self.prepare, source,
                    lambda inventory: inventory.update(reference_ends=[meta], references=[]))
        self.assertFalse((self.run / 'SOURCE.json').exists())

    def test_old_reference_line_is_rejected_with_or_without_end_marker(self):
        old = REFERENCE.replace(r'\[1\]', '[1]')
        self.reject('REFERENCE_STYLE_UNSUPPORTED', self.prepare, SOURCE.replace(REFERENCE, old))
        source, meta = source_with_reference_end()
        self.reject('REFERENCE_STYLE_UNSUPPORTED', self.prepare, source.replace(REFERENCE, old),
                    lambda inventory: inventory.update(reference_ends=[meta]))
        self.assertFalse((self.run / 'SOURCE.json').exists())
        self.assertFalse((self.run / 'source.snapshot.md').exists())

    def test_canonical_reference_requires_exact_new_inventory_text_and_end_hash(self):
        source, meta = source_with_reference_end()
        old = REFERENCE.replace(r'\[1\]', '[1]')
        self.reject('REFERENCE_INVENTORY', self.prepare, source,
                    lambda inventory: inventory.update(reference_ends=[meta],
                        references=[{'number': 1, 'page': 2, 'text': old}]))
        old_hash = pp.sha256_text(old)
        old_meta = dict(meta, last_reference_sha256=old_hash)
        self.reject('REFERENCE_END_POSITION', self.prepare, source.replace(meta['last_reference_sha256'], old_hash),
                    lambda inventory: inventory.update(reference_ends=[old_meta]))
        self.assertFalse((self.run / 'SOURCE.json').exists())
        self.assertFalse((self.run / 'source.snapshot.md').exists())

    def test_reference_end_must_bind_the_final_reference_of_the_whole_document(self):
        pages = pp.split_pages(SOURCE, 2)
        meta = {'pdf_page': 1, 'last_reference_number': 1,
                'last_reference_sha256': pp.sha256_text(REFERENCE)}
        second = REFERENCE.replace(r'\[1\]', r'\[2\]')
        marker = '<!-- LIT_REFERENCE_END ' + json.dumps(meta, separators=(',', ':')) + ' -->'
        source = ('<!-- PDF_PAGE: 1 -->\n' + pages[1] + '\n\n# References\n' + REFERENCE
                  + '\n\n' + marker + '\n\n' + REFERENCE_TAIL
                  + '\n<!-- PDF_PAGE: 2 -->\n' + pages[2].replace(REFERENCE, second) + '\n')
        references = [{'page': 1, 'number': 1, 'text': REFERENCE},
                      {'page': 2, 'number': 2, 'text': second}]
        self.reject('REFERENCE_END_FINAL_REFERENCE', self.prepare, source,
                    lambda inventory: inventory.update(reference_ends=[meta], references=references))
        self.assertFalse((self.run / 'SOURCE.json').exists())
        self.assertFalse((self.run / 'source.snapshot.md').exists())

    def test_reference_end_tail_keeps_original_prose_number_gate(self):
        source, meta = source_with_reference_end()
        self.prepare(source, lambda inventory: inventory.update(reference_ends=[meta]))
        d.validate_page(self.package, self.run, 1, self.candidate(1))
        candidate = self.candidate(2)
        def drift(match):
            if json.loads(match['meta'])['source_sha256'] != pp.sha256_text(REFERENCE_TAIL):
                return match[0]
            self.assertIn(' 7', match['body'])
            return match[0].replace(match['body'], match['body'].replace(' 7', ' 8'))
        text = candidate.read_text(encoding='utf-8')
        candidate.write_bytes(pp.SPAN_OUTPUT_RE.sub(drift, text).encode())
        self.reject('PROSE_NUMBER_DRIFT', d.validate_page, self.package, self.run, 2, candidate)
        self.assertFalse((self.run / 'receipts/page-002.commit.json').exists())

    def replace_json(self, name, change):
        target = self.run / name
        value = c.read_json(target)
        change(value)
        target.write_bytes(c.encode(value))
        return value

    def reseal_receipt(self, page):
        receipt = self.run / f'receipts/page-{page:03d}.json'
        self.replace_json(f'receipts/page-{page:03d}.json',
                          lambda x: x.update(accepted=c.ref(self.run, self.run / f'accepted/page-{page:03d}.md')))
        (self.run / f'receipts/page-{page:03d}.commit.json').write_bytes(c.encode({'receipt': c.ref(self.run, receipt)}))

    def test_arbitrary_different_real_synthetic_pdfs_use_actual_page_counts(self):
        hashes = []
        for key, expected in (('A', 3), ('B', 2)):
            path = PACKAGE / 'examples' / f'SYNTHETIC_WORKFLOW_{key}.pdf'
            result = self.intake(path, key)
            run = Path(result['run'])
            inp, _ = d.input_record(self.package, run)
            self.assertEqual(inp['page_count'], expected)
            self.assertEqual(len(inp['pages']), expected)
            self.assertEqual(inp['pdf_sha256'], c.digest(path))
            self.assertEqual((run / 'source.pdf').read_bytes(), path.read_bytes())
            self.assertTrue(all(len(c.check_ref(run, row['text']).decode().strip()) > 80 for row in inp['pages']))
            self.assertEqual(inp['scientific_acceptance'], 'NONE')
            hashes.append(inp['pdf_sha256'])
        self.assertEqual(len(set(hashes)), 2)

    def test_new_unlisted_synthetic_pdf_not_fixed_hash(self):
        text = 'Invented generic entry test uses no prior hash whitelist and has enough visible extracted text. '
        path = invented_pdf(self.case / 'new.pdf', [text, text + 'Another page.', text + 'Final page.'])
        result = self.intake(path)
        self.assertEqual(result['page_count'], 3)
        self.assertNotEqual(c.digest(path), c.digest(PACKAGE / 'examples' / 'SYNTHETIC_READABLE_TWO_PAGES.pdf'))

    def test_raw_text_threshold_80_rejected_81_accepted(self):
        from pypdf import PdfReader
        for count in (80, 81):
            path = invented_pdf(self.case / f'chars-{count}.pdf', ['A' * count])
            self.assertEqual(len(PdfReader(path).pages[0].extract_text().strip()), count)
            if count == 80:
                self.reject('TEXT_LAYER_PROFILE_UNSUPPORTED', self.intake, path, 'short')
            else:
                self.assertEqual(self.intake(path, 'long')['page_count'], 1)

    def test_61_raw_pages_and_blank_page_rejected(self):
        path = invented_pdf(self.case / 'many.pdf', ['Synthetic'] * 61)
        self.reject('PDF_PROFILE_UNSUPPORTED', self.intake, path, 'many')
        path = invented_pdf(self.case / 'blank.pdf', [''])
        self.reject('TEXT_LAYER_PROFILE_UNSUPPORTED', self.intake, path, 'blank')

    def test_header_encryption_and_budget_rejected(self):
        from pypdf import PdfWriter
        bad = self.case / 'bad.pdf'
        bad.write_bytes(b'Not a PDF')
        self.reject('PDF_SIZE_OR_HEADER', self.intake, bad, 'header')
        writer = PdfWriter(); writer.add_blank_page(width=612, height=792); writer.encrypt('synthetic')
        encrypted = self.case / 'encrypted.pdf'
        with encrypted.open('wb') as output: writer.write(output)
        self.reject('PDF_PROFILE_UNSUPPORTED', self.intake, encrypted, 'encrypted')
        valid = PACKAGE / 'examples' / 'SYNTHETIC_WORKFLOW_B.pdf'
        for minutes in (True, 0, 61):
            self.reject('BUDGET_LIMIT', self.intake, valid, 'budget-' + str(minutes), minutes=minutes)

    def test_active_pdf_javascript_action_and_chained_action_rejected(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject
        original = PACKAGE / 'examples' / 'SYNTHETIC_READABLE_TWO_PAGES.pdf'
        for kind in ('catalog-js', 'annotation-js', 'uri-next-js'):
            writer = PdfWriter(); writer.clone_document_from_reader(PdfReader(original))
            js = DictionaryObject({NameObject('/S'): NameObject('/JavaScript'), NameObject('/JS'): TextStringObject('void(0)')})
            if kind == 'catalog-js':
                writer.add_js('void(0)')
            else:
                action = js
                if kind == 'uri-next-js':
                    action = DictionaryObject({NameObject('/S'): NameObject('/URI'), NameObject('/URI'): TextStringObject('https://example.invalid/'), NameObject('/Next'): js})
                annotation = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                    NameObject('/Rect'): ArrayObject([FloatObject(n) for n in [10, 10, 20, 20]]), NameObject('/A'): action})
                writer.pages[0][NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
            path = self.case / (kind + '.pdf')
            with path.open('wb') as output: writer.write(output)
            self.reject('ACTIVE_PDF_UNSUPPORTED', self.intake, path, kind)

    def test_source_inventory_and_crop_bind_real_pixels(self):
        from PIL import Image
        result = self.prepare()
        inp, frozen, _ = d.source_record(self.package, self.run)
        self.assertEqual(result['figures'], 1)
        self.assertEqual([b['kind'] for r in frozen['records'] for b in r['protected_blocks']], ['formula', 'figure', 'reference'])
        with Image.open(self.run / inp['pages'][0]['image']['path']) as original, Image.open(self.run / 'figures/Figure-01.png') as crop:
            bbox = frozen['inventory']['figures'][0]['bbox_pixels']
            expected = original.crop(bbox)
            self.assertEqual(crop.size, (bbox[2] - bbox[0], bbox[3] - bbox[1]))
            self.assertEqual(crop.tobytes(), expected.tobytes())
            self.assertTrue(any(low != high for low, high in crop.convert('RGB').getextrema()))

    def test_inventory_bindings_missing_rows_and_reviewed_pages_rejected(self):
        cases = [('INVENTORY_BINDING', lambda x: x.update(input_sha256='0' * 64)),
                 ('INVENTORY_BINDING', lambda x: x.update(reviewed_pages=[1])),
                 ('INVENTORY_COMPLETE_SEQUENCE', lambda x: x.update(formulas=[]))]
        for error, change in cases:
            with self.subTest(error=error): self.reject(error, self.prepare, SOURCE, change)
        self.assertFalse((self.run / 'SOURCE_COMMIT.json').exists())

    def test_formula_and_reference_exact_structure_rejected(self):
        cases = [('FORMULA_SOURCE_BYTES', lambda x: x['formulas'][0].update(latex='x+y=4')),
                 ('FORMULA_INVENTORY', lambda x: x['formulas'][0].update(id='EQ002')),
                 ('REFERENCE_INVENTORY', lambda x: x['references'][0].update(text=REFERENCE + ' changed')),
                 ('FIGURE_CAPTION_MISSING', lambda x: x['figures'][0].update(caption='Absent caption'))]
        for error, change in cases:
            with self.subTest(error=error): self.reject(error, self.prepare, SOURCE, change)

    def test_crop_outside_image_inverted_empty_and_bool_rejected(self):
        width, height = d.input_record(self.package, self.run)[0]['pages'][0]['image_pixels']
        for box in ([-1, 0, 10, 10], [0, 0, width + 1, height], [10, 0, 5, 10], [0, 0, 0, 10], [False, 0, 10, 10]):
            with self.subTest(box=box):
                self.reject('FIGURE_BOUNDS', self.prepare, SOURCE, lambda x: x['figures'][0].update(bbox_pixels=box))

    def test_source_html_external_image_and_unowned_page_rejected(self):
        for old, new, code in [('# Component mechanism', '<img src="https://example.invalid/a.png">', 'ACTIVE_HTML_UNSUPPORTED'),
                               ('figures/Figure-01.png', 'https://example.invalid/a.png', 'UNREGISTERED_FIGURE'),
                               ('<!-- PDF_PAGE: 2 -->', '<!-- PDF_PAGE: 3 -->', 'SOURCE_PAGE_COVERAGE')]:
            self.reject(code, self.prepare, SOURCE.replace(old, new))

    def test_citation_without_registered_reference_rejected(self):
        self.reject('CITATION_WITHOUT_REFERENCE', self.prepare, SOURCE.replace('only [1]', 'only [2]'))

    def test_page_order_and_old_session_candidates_rejected(self):
        self.prepare()
        self.reject('FILE_MISSING', d.validate_page, self.package, self.run, 2, self.candidate(2))
        candidate = self.candidate(1)
        candidate.write_bytes(candidate.read_bytes().replace(c.digest(self.run / 'SOURCE.json').encode(), b'0' * 64, 1))
        self.reject('FOREIGN_SESSION_CANDIDATE', d.validate_page, self.package, self.run, 1, candidate)
        self.assertFalse((self.run / 'accepted/page-001.md').exists())
        self.assertTrue(list((self.run / 'attempts/page-001').glob('*.failure.json')))

    def test_decimal_sign_and_exponent_drift_rejected(self):
        self.prepare()
        for old, new in [('.5', '5'), ('-2.5', '2.5'), ('3e-4', '3e4'), ('\u22126E+2', '6E+2')]:
            candidate = self.candidate(1)
            candidate.write_bytes(candidate.read_bytes().replace(old.encode(), new.encode()))
            with self.subTest(old=old): self.reject('PROSE_NUMBER_DRIFT', d.validate_page, self.package, self.run, 1, candidate)

    def test_unicode_minus_and_exponent_case_are_normalized(self):
        self.prepare()
        candidate = self.candidate(1)
        candidate.write_bytes(candidate.read_bytes().replace('\u22126E+2'.encode(), b'-6e+2'))
        self.assertEqual(d.validate_page(self.package, self.run, 1, candidate)['status'], 'PAGE_TECHNICALLY_ACCEPTED')

    def test_translated_html_and_external_image_rejected(self):
        self.prepare()
        for text, code in [('<img src="https://example.invalid/a.png">', 'ACTIVE_HTML_UNSUPPORTED'),
                           ('![bad](https://example.invalid/a.png)', 'TRANSLATION_UNREGISTERED_STRUCTURE')]:
            candidate = self.candidate(1)
            candidate.write_bytes(candidate.read_bytes().replace('技术测试专用句子'.encode(), ('技术测试专用句子' + text).encode(), 1))
            self.reject(code, d.validate_page, self.package, self.run, 1, candidate)

    def test_accepted_bytes_rechecked_and_page_reaccept_rejected(self):
        self.accept_all()
        self.reject('PAGE_ALREADY_ACCEPTED', d.validate_page, self.package, self.run, 1, self.candidate(1))
        path = self.run / 'accepted/page-001.md'
        path.write_bytes(path.read_bytes() + b'\n')
        self.reject('REFERENCE_DRIFT', d.accepted, self.package, self.run, 1)

    def test_accepted_numeric_rule_reapplied_even_with_rebound_hashes(self):
        self.accept_all()
        path = self.run / 'accepted/page-001.md'
        path.write_bytes(path.read_bytes().replace(b'.5', b'.6', 1))
        self.reseal_receipt(1)
        self.reject('PROSE_NUMBER_DRIFT', d.accepted, self.package, self.run, 1)

    def test_accepted_metrics_and_previous_chain_revalidated(self):
        self.accept_all()
        self.replace_json('receipts/page-002.json', lambda x: x.update(previous_receipt_sha256='0' * 64))
        self.reseal_receipt(2)
        self.reject('PAGE_ORDER_BINDING', d.accepted, self.package, self.run, 2)
        self.replace_json('receipts/page-001.json', lambda x: x['metrics'].update(translate_spans=999))
        self.reseal_receipt(1)
        self.reject('PAGE_METRICS_CHANGED', d.accepted, self.package, self.run, 1)

    def test_complete_assembly_preserves_protected_blocks_and_review_coverage(self):
        result = self.assembled()
        inp, review, digest = d.verify_review_inputs(self.package, self.run, result['review_inputs']['sha256'])
        text = (self.run / 'translation_zh.md').read_text(encoding='utf-8')
        self.assertIn(FORMULA, text); self.assertIn(REFERENCE, text)
        self.assertIn('![Figure 1](figures/Figure-01.png)', text)
        self.assertLess(text.index('## PDF 第 1 页'), text.index('## PDF 第 2 页'))
        self.assertNotIn('LIT_PROTECTED:', text)
        self.assertEqual(review['formula_ids'], ['EQ001'])
        self.assertEqual(review['figure_numbers'], [1]); self.assertEqual(review['reference_numbers'], [1])
        self.assertEqual(review['status'], 'READY_FOR_INDEPENDENT_REVIEW')
        self.assertEqual(inp['scientific_acceptance'], 'NONE')
        self.assertEqual(digest, result['review_inputs']['sha256'])

    def test_missing_page_or_summary_does_not_freeze_review(self):
        self.prepare()
        d.validate_page(self.package, self.run, 1, self.candidate(1))
        self.supplements()
        self.reject('FILE_MISSING', d.assemble, self.package, self.run)
        d.validate_page(self.package, self.run, 2, self.candidate(2))
        (self.run / 'summary.md').unlink()
        self.reject('FILE_MISSING', d.assemble, self.package, self.run)
        self.assertFalse((self.run / 'REVIEW_INPUTS.json').exists())

    def test_short_or_html_summary_rejected(self):
        self.accept_all(); self.supplements()
        for value, code in [('太短', 'SUPPLEMENT_REQUIRED'), ('<img src="https://example.invalid/a.png">', 'ACTIVE_HTML_UNSUPPORTED')]:
            (self.run / 'summary.md').write_bytes(value.encode())
            self.reject(code, d.assemble, self.package, self.run)

    def test_source_asset_and_software_drift_rejected(self):
        self.prepare()
        target = self.run / 'figures/Figure-01.png'
        target.write_bytes(target.read_bytes() + b'drift')
        self.reject('REFERENCE_DRIFT', d.source_record, self.package, self.run)
        alternate = self.case / 'alternate-descriptor'; shutil.copytree(self.package, alternate)
        (alternate / 'launch.py').write_bytes(b'# changed\n')
        self.reject('REFERENCE_DRIFT', d.input_record, alternate, self.run)

    def test_expired_rejects_live_verification_and_allows_explicit_archival_check(self):
        self.assembled()
        inp = d.input_record(self.package, self.run)[0]
        future = c.parse_time(inp['deadline_utc']) + timedelta(seconds=1)
        with patch.object(c, 'utcnow', return_value=future):
            self.reject('SESSION_EXPIRED_OR_CLOCK_CHANGED', d.verify_review_inputs, self.package, self.run)
            # Explicit archival verification is read-only and can outlive the run.
            d.verify_review_inputs(self.package, self.run, active=False)

    def test_expired_rejects_new_acceptance_without_creating_receipt(self):
        self.prepare()
        candidate = self.candidate(1)
        inp = d.input_record(self.package, self.run)[0]
        future = c.parse_time(inp['deadline_utc']) + timedelta(seconds=1)
        with patch.object(c, 'utcnow', return_value=future):
            self.reject('SESSION_EXPIRED_OR_CLOCK_CHANGED', d.validate_page, self.package, self.run, 1, candidate)
        self.assertFalse((self.run / 'receipts/page-001.commit.json').exists())

    def test_expired_rejects_new_assembly_without_freezing_review(self):
        self.accept_all(); self.supplements()
        inp = d.input_record(self.package, self.run)[0]
        future = c.parse_time(inp['deadline_utc']) + timedelta(seconds=1)
        with patch.object(c, 'utcnow', return_value=future):
            self.reject('SESSION_EXPIRED_OR_CLOCK_CHANGED', d.assemble, self.package, self.run)
        self.assertFalse((self.run / 'REVIEW_INPUTS.json').exists())

    def test_active_run_registered_pdf_and_unconfirmed_category_rejected(self):
        pdf = PACKAGE / 'examples' / 'SYNTHETIC_WORKFLOW_B.pdf'
        result = self.intake(pdf, 'guards')
        instance = self.case / 'guards'
        other = PACKAGE / 'examples' / 'SYNTHETIC_WORKFLOW_A.pdf'
        self.reject('ACTIVE_RUN_EXISTS', d.intake, self.package, instance, other, '合成标题', 'DEMO')
        self.reject('CATEGORY_NOT_CONFIRMED', d.intake, self.package, instance, other, '合成标题', 'UNCONFIRMED')
        library_path = instance / '.system/library.json'
        library = c.read_json(library_path)
        library['works'].append({'id': 'W0001', 'category_id': 'DEMO', 'status': 'STORED_OUTPUT_VERIFIED',
                                 'pdf_sha256': c.digest(pdf), 'run_id': Path(result['run']).name})
        library_path.write_bytes(c.encode(library))
        self.reject('PDF_ALREADY_REGISTERED', d.intake, self.package, instance, pdf, '合成标题', 'DEMO')

    def test_direct_intake_rejects_pending_commit_under_writer_lock(self):
        instance = minimal_library(self.case / 'pending-instance')
        library_path = instance / '.system/library.json'
        library = c.read_json(library_path)
        library['works'].append({'id': 'W0001', 'category_id': 'DEMO',
                                 'status': 'COMMITTED_READING_PENDING',
                                 'pdf_sha256': '0' * 64, 'run_id': 'Rsyntheticprevious'})
        library_path.write_bytes(c.encode(library))
        before = library_path.read_bytes()
        pdf = PACKAGE / 'examples' / 'SYNTHETIC_WORKFLOW_B.pdf'
        self.reject('PENDING_COMMIT_EXISTS', d.intake, self.package, instance, pdf, '合成标题', 'DEMO')
        self.assertEqual(library_path.read_bytes(), before)
        self.assertEqual(list((instance / '.work/runs').iterdir()), [])

    def test_direct_intake_rejects_copied_root_binding(self):
        origin = minimal_library(self.case / 'bound-original')
        copied = self.case / 'bound-copy'
        shutil.copytree(origin, copied)
        before = (origin / '.system/library.json').read_bytes()
        pdf = PACKAGE / 'examples' / 'SYNTHETIC_WORKFLOW_B.pdf'
        self.reject('ROOT_BINDING_MISMATCH', d.intake, self.package, copied, pdf, '合成标题', 'DEMO')
        self.assertEqual((origin / '.system/library.json').read_bytes(), before)
        self.assertEqual((copied / '.system/library.json').read_bytes(), before)
        self.assertEqual(list((origin / '.work/runs').iterdir()), [])
        self.assertEqual(list((copied / '.work/runs').iterdir()), [])

    def test_review_expected_hash_assets_and_coverage_drift_rejected(self):
        self.assembled()
        self.reject('REVIEW_INPUT_CHANGED', d.verify_review_inputs, self.package, self.run, '0' * 64)
        self.replace_json('REVIEW_INPUTS.json', lambda x: x.update(figure_numbers=[]))
        self.reject('REVIEW_COVERAGE_CHANGED', d.verify_review_inputs, self.package, self.run)

    def test_review_page_count_field_drift_rejected(self):
        self.assembled()
        self.replace_json('REVIEW_INPUTS.json', lambda x: x.update(page_count=999))
        with self.assertRaises(ValueError):
            d.verify_review_inputs(self.package, self.run)

    def test_review_status_field_drift_rejected(self):
        self.assembled()
        self.replace_json('REVIEW_INPUTS.json', lambda x: x.update(status='SCIENTIFICALLY_ACCEPTED'))
        with self.assertRaises(ValueError):
            d.verify_review_inputs(self.package, self.run)

    def test_frozen_review_summary_drift_rejected(self):
        self.assembled()
        (self.run / 'summary.md').write_bytes('冻结以后被修改的纯合成摘要文本不能继续复审。\n'.encode())
        self.reject('REFERENCE_DRIFT', d.verify_review_inputs, self.package, self.run)


if __name__ == '__main__':
    unittest.main(verbosity=2)
