"""Pure generic text-PDF page protocol; no IO, dispatch, publication or private rules.

Structural checks do not prove reconstruction or translation fidelity.
The caller must bind source/image/inventory and obtain independent review.
"""
from __future__ import annotations
import hashlib
import html
import json
import re

__all__ = ['split_pages', 'make_page_contract', 'validate', 'assemble_page']

PAGE_RE = re.compile(r'(?m)^<!-- PDF_PAGE: ([1-9][0-9]{0,2}) -->[ \t]*$')
FORMULA_META_RE = re.compile(r'^<!-- LIT_FORMULA_TRANSCRIPTION (?P<meta>\{[^\r\n]+\}) -->$')
REFERENCE_END_RE = re.compile(r'^<!-- LIT_REFERENCE_END (?P<meta>\{[^\r\n]+\}) -->$')
REFERENCE_LINE_RE = re.compile(r'^- \\\[(?P<number>[1-9][0-9]{0,3})\\\] (?P<body>\S.*)$')
REFERENCE_NUMBER_PREFIX_RE = re.compile(r'^\s*(?:[-+*]\s*)?\\*\[\s*\\*\d+')
_RESERVED_RE = re.compile(r'(?:\{\{[A-Z][A-Z0-9]*_|<!--|-->)')


def _text(value: str) -> None:
    if not isinstance(value, str) or '\r' in value or '\ufeff' in value:
        raise ValueError('UTF8_LF_NO_BOM_REQUIRED')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', value):
        raise ValueError('CONTROL_CHARACTERS')
    outside_math=re.sub(r'(?<!\\)\$\$.*?(?<!\\)\$\$|(?<![\\$])\$(?!\$)[^\n$]+(?<!\\)\$(?!\$)', '', value, flags=re.S)
    if re.search(r'</?(?:img|script|iframe|object|embed|svg|math|video|audio|source|link|style|a|form|input)\b',value,re.I):
        raise ValueError('ACTIVE_HTML_UNSUPPORTED')
    if re.search(r'</?[A-Za-z][\w:-]*(?:\s+[^<>]*|/?)>', outside_math):
        raise ValueError('RAW_HTML_UNSUPPORTED')
    if re.search(r'\\(?:href|url|includegraphics|html\w*)\b',value,re.I):
        raise ValueError('ACTIVE_MATH_MARKUP_UNSUPPORTED')
    if re.search(r'(?<!!)\[[^\]\n]*\]\([^\n)]*\)', outside_math) or '[[' in outside_math:
        raise ValueError('UNREGISTERED_LINK_UNSUPPORTED')


def _unique_json(value: str) -> dict:
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key] = item
        return result
    result = json.loads(value, object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    if not isinstance(result, dict):
        raise ValueError('METADATA_OBJECT_REQUIRED')
    return result


def split_pages(text: str, count: int) -> dict[int, str]:
    """Partition every source byte after exact ordered PDF page markers.

    An unowned non-whitespace prefix is rejected, unlike the historic helper.
    Page bodies are stripped exactly as in the reviewed page protocol.
    """
    _text(text)
    if type(count) is not int or not 1 <= count <= 999:
        raise ValueError('PAGE_COUNT')
    markers = list(PAGE_RE.finditer(text))
    if [int(m[1]) for m in markers] != list(range(1, count + 1)):
        raise ValueError('SOURCE_PAGE_COVERAGE')
    if text[:markers[0].start()].strip():
        raise ValueError('SOURCE_UNOWNED_PREFIX')
    result = {}
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        body = text[marker.end():end].strip()
        if not body or 'PDF_PAGE:' in body:
            raise ValueError('EMPTY_OR_MALFORMED_PAGE')
        result[int(marker[1])] = body
    return result


def _reference_end_for_page(reference_ends: list | None, page: int) -> dict | None:
    if reference_ends is None:
        return None
    if not isinstance(reference_ends, list) or len(reference_ends) > 1:
        raise ValueError('REFERENCE_END_INVENTORY')
    selected, previous_page = None, 0
    for item in reference_ends:
        if (not isinstance(item, dict)
                or set(item) != {'pdf_page', 'last_reference_number', 'last_reference_sha256'}
                or type(item['pdf_page']) is not int or not previous_page < item['pdf_page'] <= 999
                or type(item['last_reference_number']) is not int or not 1 <= item['last_reference_number'] <= 9999
                or not isinstance(item['last_reference_sha256'], str)
                or not re.fullmatch(r'[0-9A-F]{64}', item['last_reference_sha256'])):
            raise ValueError('REFERENCE_END_INVENTORY')
        previous_page = item['pdf_page']
        if item['pdf_page'] == page:
            selected = dict(item)
    return selected


def protect_blocks(page: int, text: str, *, reference_end: dict | None = None) -> tuple[str, list[dict]]:
    """Protect only declared formulas, exact figure links and bounded references.

    The caller checks every resulting block against the independently reviewed
    PDF inventory. This parser does not establish that a bibliographic-looking
    line or a declared formula really occurs in the PDF.
    """
    _text(text)
    if reference_end is not None and _reference_end_for_page([reference_end], page) is None:
        raise ValueError('REFERENCE_END_POSITION')
    lines = text.splitlines(keepends=True)
    protected, output = [], []
    in_references = False
    previous_reference = None
    reference_end_seen = False
    formula_ids, figure_ids = set(), set()

    def register(kind, source, identity):
        if len(protected) >= 999:
            raise ValueError('PAGE_BLOCK_LIMIT')
        block_id = f'P{page:03d}-B{len(protected) + 1:03d}'
        token = '{{LIT_PROTECTED:' + block_id + '}}'
        source = source.strip()
        protected.append(dict(id=block_id, kind=kind, identity=identity,
                              token=token, source=source, source_sha256=sha256_text(source)))
        return token + '\n'

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip('\n')
        stripped = raw.strip()
        reference_end_marker = REFERENCE_END_RE.fullmatch(raw)
        if reference_end_marker:
            if reference_end_seen:
                raise ValueError('REFERENCE_END_DUPLICATE')
            meta = _unique_json(reference_end_marker['meta'])
            if (reference_end is None or set(meta) != set(reference_end)
                    or type(meta.get('pdf_page')) is not int
                    or type(meta.get('last_reference_number')) is not int
                    or meta != reference_end):
                raise ValueError('REFERENCE_END_BINDING')
            if (not in_references or previous_reference is None or not protected
                    or protected[-1]['kind'] != 'reference'
                    or meta['pdf_page'] != page or meta['last_reference_number'] != previous_reference
                    or meta['last_reference_sha256'] != protected[-1]['source_sha256']):
                raise ValueError('REFERENCE_END_POSITION')
            following = i + 1
            while following < len(lines) and not lines[following].strip():
                following += 1
            first = lines[following].rstrip('\n') if following < len(lines) else ''
            if (not first or classify(first) != 'paragraph'
                    or _RESERVED_RE.search(first) or '$$' in first or '![' in first
                    or REFERENCE_LINE_RE.fullmatch(first)
                    or REFERENCE_NUMBER_PREFIX_RE.match(first)
                    or looks_like_plain_reference(first)):
                raise ValueError('REFERENCE_END_FOLLOWING_PARAGRAPH')
            reference_end_seen = True
            in_references = False
            previous_reference = None
            i += 1; continue
        if MARKDOWN_HEADING_RE.fullmatch(stripped):
            if _RESERVED_RE.search(raw) or '$$' in raw or '![' in raw:
                raise ValueError('HEADING_UNREGISTERED_STRUCTURE')
            in_references = REFERENCE_HEADING_RE.fullmatch(stripped) is not None
            if reference_end_seen and in_references:
                raise ValueError('REFERENCE_END_LATER_REFERENCE')
            previous_reference = None
            output.append(lines[i]); i += 1; continue
        if not stripped:
            output.append(lines[i]); i += 1; continue
        formula = FORMULA_META_RE.fullmatch(raw)
        if formula:
            if in_references:
                raise ValueError('FORMULA_INSIDE_REFERENCES')
            meta = _unique_json(formula['meta'])
            if (set(meta) != {'formula_id', 'pdf_page'}
                    or type(meta['pdf_page']) is not int or meta['pdf_page'] != page
                    or not isinstance(meta['formula_id'], str)
                    or not re.fullmatch(r'EQ[0-9]{3}', meta['formula_id'])
                    or meta['formula_id'] == 'EQ000' or meta['formula_id'] in formula_ids):
                raise ValueError('FORMULA_METADATA')
            if i + 2 >= len(lines) or lines[i + 1].rstrip('\n') != '$$':
                raise ValueError('FORMULA_DELIMITER')
            end = i + 2
            while end < len(lines) and lines[end].rstrip('\n') != '$$':
                if '$$' in lines[end] or _RESERVED_RE.search(lines[end]):
                    raise ValueError('FORMULA_DELIMITER_OR_RESERVED')
                end += 1
            if end == len(lines) or not ''.join(lines[i + 2:end]).strip():
                raise ValueError('FORMULA_EMPTY_OR_UNCLOSED')
            formula_ids.add(meta['formula_id'])
            output.append(register('formula', ''.join(lines[i:end + 1]), meta['formula_id']))
            i = end + 1; continue
        if '$$' in raw:
            raise ValueError('UNREGISTERED_FORMULA')
        if _RESERVED_RE.search(raw):
            raise ValueError('SOURCE_RESERVED_MARKER')
        figure = FIGURE_RE.fullmatch(raw)
        if figure:
            number = int(figure['label'])
            if (in_references or number < 1 or number != int(figure['file'])
                    or number in figure_ids):
                raise ValueError('FIGURE_IDENTITY')
            figure_ids.add(number)
            output.append(register('figure', raw, f"Figure-{figure['file']}"))
            i += 1; continue
        if '![' in raw:
            raise ValueError('UNREGISTERED_FIGURE')
        reference = REFERENCE_LINE_RE.fullmatch(raw)
        if reference:
            if reference_end_seen:
                raise ValueError('REFERENCE_END_LATER_REFERENCE')
            if not in_references:
                raise ValueError('REFERENCE_WITHOUT_HEADING')
            number = int(reference['number'])
            if not looks_like_plain_reference(reference['body']):
                raise ValueError('REFERENCE_BIBLIOGRAPHIC_SIGNALS')
            if previous_reference is not None and number != previous_reference + 1:
                raise ValueError('REFERENCE_SEQUENCE')
            previous_reference = number
            output.append(register('reference', raw, f'Reference-{number}'))
            i += 1; continue
        if REFERENCE_NUMBER_PREFIX_RE.match(raw):
            raise ValueError('REFERENCE_STYLE_UNSUPPORTED')
        if in_references:
            raise ValueError('REFERENCE_CONTINUATION_OR_STYLE_UNSUPPORTED')
        if re.match(r'^\d{1,4}\.\s+', raw) and looks_like_plain_reference(raw):
            raise ValueError('REFERENCE_WITHOUT_HEADING_OR_STYLE')
        output.append(lines[i]); i += 1
    if reference_end is not None and not reference_end_seen:
        raise ValueError('REFERENCE_END_MISSING')
    return ''.join(output), protected


def make_page_contract(work_id: str, page: int, body: str, *, reference_ends: list | None = None) -> tuple[str, dict]:
    if not isinstance(work_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,63}', work_id):
        raise ValueError('WORK_ID')
    if type(page) is not int or not 1 <= page <= 999:
        raise ValueError('PAGE_NUMBER')
    _text(body)
    if not body.strip() or 'PDF_PAGE:' in body:
        raise ValueError('PAGE_BODY')
    reference_end = _reference_end_for_page(reference_ends, page)
    result, record = _make_page_contract(work_id, page, body, reference_end=reference_end)
    if not 1 <= record['translate_span_count'] <= 999:
        raise ValueError('ZERO_SPAN_OR_PAGE_SPAN_LIMIT')
    return result, record


def validate(text: str, page: int, record: dict) -> tuple[list[dict], dict]:
    """Apply fixed 0.18 / 0.25 / 0.35 checks; caller reconstructs the record."""
    _text(text)
    if type(page) is not int or type(record.get('page')) is not int or record['page'] != page:
        raise ValueError('PAGE_IDENTITY')
    expected = {e['id']: e for e in record['elements'] if e['type'] == 'translate'}
    for match in SPAN_OUTPUT_RE.finditer(text):
        metadata = _unique_json(match['meta'])
        if set(metadata) != {'id', 'source_sha256', 'kind', 'source_visible_chars'}:
            raise ValueError('SPAN_METADATA_FIELDS')
        original = expected.get(metadata['id'])
        if original is None or metadata != {key: original[key] for key in metadata}:
            raise ValueError('SPAN_METADATA_BINDING')
        if _RESERVED_RE.search(match['body']) or '$$' in match['body'] or '![' in match['body']:
            raise ValueError('TRANSLATION_UNREGISTERED_STRUCTURE')
    return _parse_output(text, page, record, min_char_ratio=0.18,
                         min_cjk_letter_share=0.35, min_long_span_cjk_share=0.25)


def assemble_page(elements: list[dict], record: dict) -> str:
    """Reinsert frozen protected bytes in their exact contract order.

    This takes the result of validate, never an author-supplied element list.
    Shape and source hashes are checked again before composing the page.
    """
    expected = record['elements']
    def shape(item):
        return {key: item[key] for key in ('type', 'id', 'token', 'source_sha256') if key in item}
    if [shape(e) for e in elements] != [shape(e) for e in expected]:
        raise ValueError('ASSEMBLY_ELEMENT_SEQUENCE')
    protected = {p['id']: p for p in record['protected_blocks']}
    blocks = []
    for element in elements:
        if element['type'] == 'translate':
            value = element.get('translation')
            if not isinstance(value, str) or not value.strip():
                raise ValueError('ASSEMBLY_EMPTY_TRANSLATION')
            blocks.append(value)
        else:
            item = protected[element['id']]
            if item['token'] != element['token'] or sha256_text(item['source']) != item['source_sha256']:
                raise ValueError('ASSEMBLY_PROTECTED_DRIFT')
            blocks.append(item['source'])
    return f"## PDF 第 {record['page']} 页\n\n" + '\n\n'.join(blocks).strip() + '\n'

FIGURE_RE = re.compile('(?m)^!\\[Figure\\s+(?P<label>\\d+)\\]\\(figures/Figure-(?P<file>\\d{2})\\.png\\)\\s*$')

REFERENCE_HEADING_RE = re.compile('^#{1,6}\\s+(?:references(?:\\s+and\\s+links)?|bibliography|参考文献(?:与链接)?)\\s*$', re.IGNORECASE)

MARKDOWN_HEADING_RE = re.compile('^#{1,6}\\s+\\S.*$')

REFERENCE_YEAR_RE = re.compile('\\((?:18|19|20)\\d{2}[a-z]?\\)', re.IGNORECASE)

PROTECTED_TOKEN_RE = re.compile('\\{\\{LIT_PROTECTED:(?P<id>P\\d{3}-B\\d{3})\\}\\}')

SPAN_INPUT_RE = re.compile('<!-- LIT_TRANSLATION_SPAN (?P<meta>\\{[^\\r\\n]+\\}) -->\\s*\\n(?P<body>.*?)\\n<!-- LIT_TRANSLATION_SPAN_END (?P<id>[A-Za-z0-9-]+) -->', re.DOTALL)

SPAN_OUTPUT_RE = re.compile('<!-- LIT_TRANSLATED_SPAN (?P<meta>\\{[^\\r\\n]+\\}) -->\\s*\\n(?P<body>.*?)\\n<!-- LIT_TRANSLATED_SPAN_END (?P<id>[A-Za-z0-9-]+) -->', re.DOTALL)

OUTPUT_ELEMENT_RE = re.compile('(?P<span><!-- LIT_TRANSLATED_SPAN \\{[^\\r\\n]+\\} -->\\s*\\n.*?\\n<!-- LIT_TRANSLATED_SPAN_END [A-Za-z0-9-]+ -->)|(?P<protected>\\{\\{LIT_PROTECTED:P\\d{3}-B\\d{3}\\}\\})', re.DOTALL)

TRANSLATION_HEADER_RE = re.compile('\\A\\s*## PDF 第\\s*(\\d+)\\s*页\\s*\\n')

CITATION_GROUP_RE = re.compile('\\[\\s*(\\d+(?:\\s*[,;，、\\-–]\\s*\\d+)*)\\s*\\]')

CJK_RE = re.compile('[\\u3400-\\u4dbf\\u4e00-\\u9fff]')

LATIN_RE = re.compile('[A-Za-z]')

FORBIDDEN_TRANSLATION_LABELS = ('【中文翻译候选】', '中文翻译候选', '【标签】', '标签 ')

def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()

def sha256_text(value: str) -> str:
    return digest_bytes(value.encode('utf-8'))

def visible_chars(text: str) -> int:
    text = html.unescape(text)
    text = re.sub('<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub('\\{\\{LIT_[^}]+\\}\\}', '', text)
    text = re.sub('[\\s#*_`>|-]+', '', text)
    return len(text)

def citation_groups(text: str) -> list[str]:
    groups = []
    for match in CITATION_GROUP_RE.finditer(text):
        groups.append(re.sub('\\s+', '', match.group(1)).replace('，', ',').replace('、', ','))
    return groups

def looks_like_plain_reference(text: str) -> bool:
    """Require bibliographic signals before treating ``N. ...`` as a reference."""
    compact = re.sub('\\s+', ' ', text).strip()
    if len(compact) < 24:
        return False
    has_year = REFERENCE_YEAR_RE.search(compact) is not None
    has_quoted_title = re.search('["“][^"”]{3,}["”]', compact) is not None
    has_persistent_id = re.search('\\b(?:doi\\s*:|arXiv\\s*:?)', compact, re.IGNORECASE) is not None
    has_bibliographic_punctuation = compact.count(',') >= 2
    return has_persistent_id or (has_year and (has_quoted_title or has_bibliographic_punctuation))

def classify(block: str) -> str:
    stripped = block.lstrip()
    if stripped.startswith('#'):
        return 'heading'
    if stripped.startswith('FIG.') or stripped.startswith('Figure '):
        return 'caption_or_figure_discussion'
    return 'paragraph'

def _make_page_contract(work_id: str, page: int, source: str, *, reference_end: dict | None = None) -> tuple[str, dict]:
    tokenized, protected = protect_blocks(page, source, reference_end=reference_end)
    protected_by_token = {item['token']: item for item in protected}
    raw_blocks = []
    for paragraph in re.split('\\n\\s*\\n', tokenized):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces = re.split('(\\{\\{LIT_PROTECTED:P\\d{3}-B\\d{3}\\}\\})', paragraph)
        for piece in pieces:
            piece = piece.strip()
            if piece:
                raw_blocks.append(piece)
    elements: list[dict] = []
    rendered: list[str] = []
    span_ordinal = 0
    for raw in raw_blocks:
        if raw in protected_by_token:
            item = protected_by_token[raw]
            elements.append({'type': 'protected', 'id': item['id'], 'token': item['token']})
            rendered.append(item['token'])
            continue
        leftover_tokens = PROTECTED_TOKEN_RE.findall(raw)
        if leftover_tokens:
            raise ValueError(f'protected token shares a paragraph on page {page}; source must be normalized first: {leftover_tokens}')
        span_ordinal += 1
        span_id = f'{work_id}-P{page:03d}-S{span_ordinal:03d}'
        source_hash = sha256_text(raw)
        metrics = {'source_visible_chars': visible_chars(raw), 'source_nonempty_lines': len([line for line in raw.splitlines() if line.strip()]), 'citation_groups': citation_groups(raw)}
        item = {'type': 'translate', 'id': span_id, 'kind': classify(raw), 'source_sha256': source_hash, **metrics}
        elements.append(item)
        meta = {'id': span_id, 'source_sha256': source_hash, 'kind': item['kind'], 'source_visible_chars': metrics['source_visible_chars']}
        rendered.append('<!-- LIT_TRANSLATION_SPAN ' + json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + ' -->\n' + raw + f'\n<!-- LIT_TRANSLATION_SPAN_END {span_id} -->')
    page_input = '\n\n'.join(rendered).rstrip() + '\n'
    page_record = {'page': page, 'source_page_sha256': sha256_text(source), 'input_sha256': sha256_text(page_input), 'elements': elements, 'protected_blocks': protected, 'translate_span_count': span_ordinal}
    if reference_end is not None:
        page_record['reference_end'] = dict(reference_end)
    return (page_input, page_record)

def _parse_output(text: str, page: int, record: dict, *, min_char_ratio: float, min_cjk_letter_share: float=0.35, min_long_span_cjk_share: float=0.25) -> tuple[list[dict], dict]:
    header = TRANSLATION_HEADER_RE.match(text)
    if not header or int(header.group(1)) != page:
        raise ValueError(f'page {page} output lacks the exact Chinese page header')
    body = text[header.end():]
    observed_elements: list[dict] = []
    cursor = 0
    span_metrics: list[dict] = []
    for match in OUTPUT_ELEMENT_RE.finditer(body):
        if body[cursor:match.start()].strip():
            raise ValueError(f'uncontracted output text before an element on page {page}')
        cursor = match.end()
        if match.group('protected'):
            token_match = PROTECTED_TOKEN_RE.fullmatch(match.group('protected'))
            assert token_match is not None
            observed_elements.append({'type': 'protected', 'id': token_match.group('id'), 'token': match.group('protected')})
            continue
        span_match = SPAN_OUTPUT_RE.fullmatch(match.group('span'))
        if span_match is None:
            raise ValueError(f'malformed translated span on page {page}')
        metadata = json.loads(span_match.group('meta'))
        if span_match.group('id') != metadata.get('id'):
            raise ValueError(f'translated span end marker mismatch on page {page}')
        translated = span_match.group('body').strip()
        if not translated:
            raise ValueError(f"empty translated span {metadata.get('id')}")
        if any((label in translated for label in FORBIDDEN_TRANSLATION_LABELS)):
            raise ValueError(f"translation-candidate label detected in {metadata.get('id')}; labels do not prove Chinese translation")
        observed_elements.append({'type': 'translate', 'id': metadata.get('id'), 'source_sha256': metadata.get('source_sha256'), 'translation': translated})
    if body[cursor:].strip():
        raise ValueError(f'uncontracted trailing output text on page {page}')
    expected_elements = record['elements']
    observed_shape = [{key: item.get(key) for key in ('type', 'id', 'token', 'source_sha256') if key in item} for item in observed_elements]
    expected_shape = [{key: item.get(key) for key in ('type', 'id', 'token', 'source_sha256') if key in item} for item in expected_elements]
    if observed_shape != expected_shape:
        raise ValueError(f'page {page} element sequence or source binding mismatch')
    expected_by_id = {item['id']: item for item in expected_elements if item['type'] == 'translate'}
    page_cjk_letters = 0
    page_latin_letters = 0
    for item in observed_elements:
        if item['type'] != 'translate':
            continue
        expected = expected_by_id[item['id']]
        translated_chars = visible_chars(item['translation'])
        source_chars = int(expected['source_visible_chars'])
        minimum = max(2, int(source_chars * min_char_ratio))
        if translated_chars < minimum:
            raise ValueError(f"translated span too short: {item['id']} has {translated_chars}, minimum {minimum}")
        observed_citations = citation_groups(item['translation'])
        if observed_citations != expected.get('citation_groups', []):
            raise ValueError(f"citation group drift in {item['id']}: observed={observed_citations}, expected={expected.get('citation_groups', [])}")
        cjk_letters = len(CJK_RE.findall(item['translation']))
        latin_letters = len(LATIN_RE.findall(item['translation']))
        letter_total = cjk_letters + latin_letters
        cjk_letter_share = cjk_letters / max(1, letter_total)
        if translated_chars >= 80 and letter_total >= 40 and (cjk_letter_share < min_long_span_cjk_share):
            raise ValueError(f"target-language conversion missing in {item['id']}: cjk_share={cjk_letter_share:.3f}, minimum={min_long_span_cjk_share:.3f}")
        page_cjk_letters += cjk_letters
        page_latin_letters += latin_letters
        span_metrics.append({'id': item['id'], 'source_visible_chars': source_chars, 'translation_visible_chars': translated_chars, 'minimum_translation_visible_chars': minimum, 'ratio': round(translated_chars / max(1, source_chars), 3), 'cjk_letters': cjk_letters, 'latin_letters': latin_letters, 'cjk_letter_share': round(cjk_letter_share, 3)})
    page_letter_total = page_cjk_letters + page_latin_letters
    page_cjk_letter_share = page_cjk_letters / max(1, page_letter_total)
    if page_letter_total >= 120 and page_cjk_letter_share < min_cjk_letter_share:
        raise ValueError(f'page {page} is not predominantly a Chinese translation: cjk_share={page_cjk_letter_share:.3f}, minimum={min_cjk_letter_share:.3f}')
    return (observed_elements, {'translate_spans': len(span_metrics), 'protected_blocks': len([item for item in observed_elements if item['type'] == 'protected']), 'span_metrics': span_metrics, 'target_language': {'profile': 'ZH_CN_WITH_TECHNICAL_ENGLISH_V1', 'cjk_letters': page_cjk_letters, 'latin_letters': page_latin_letters, 'cjk_letter_share': round(page_cjk_letter_share, 3), 'minimum_page_cjk_letter_share': min_cjk_letter_share, 'minimum_long_span_cjk_letter_share': min_long_span_cjk_share}})
