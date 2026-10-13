"""Derive AI task instructions and exact final claims without semantic claims."""
from pathlib import Path

from . import core as c, documents, review


def brief(package, run, role):
    c.require(role in ('AUTHOR', 'REVIEWER'), 'ROLE_REQUIRED')
    inp, input_sha = documents.input_record(package, run)
    value = {'role': role, 'run': str(run), 'deadline_utc': inp['deadline_utc'],
             'input_sha256': input_sha, 'task_name': 'author_' + input_sha,
             'dispatch_note': '由协调者实际创建对应 task_name；作者与检查者必须是两个不同任务。',
             'capture_command': ['capture-current', '--run', str(run), '--role', role, '--output', '<新的绝对证据路径>'],
             'trust_boundary': 'Same-user host evidence; no backend attestation or scientific acceptance.'}
    if role == 'AUTHOR':
        value['required_work'] = ['逐页核原 PDF 的题名、文字、全部公式、式号、图与引用。',
            'prepare-source → 每页填写和 validate-page → assemble；前页未通过不得跳页。',
            '原稿与逐页译文完整保留；摘要与科学说明分别写真实中文内容。',
            '保存本任务 capture；assemble 后用 role-final 生成最终哈希标记。']
        value['final_command'] = ['role-final', '--run', str(run), '--role', role]
    else:
        _, inputs, review_sha = documents.verify_review_inputs(package, run)
        value.update(input_sha256=review_sha, task_name='reviewer_' + review_sha,
                     review_inputs=str(run / 'REVIEW_INPUTS.json'))
        value['required_checks'] = {key: inputs[key] for key in ('page_count', 'formula_ids', 'figure_numbers', 'reference_numbers')}
        value['required_work'] = ['按冻结 REVIEW_INPUTS 核全部页、公式、图、引用、跨页续接、摘要和科学说明。',
            '实际完成后填写以下报告；模板没有任何已检查或 PASS 声明。',
            '将报告写在本 run 内；保存本实际任务 capture；用 role-final 校验并生成最终标记。']
        value['report_template'] = {'schema': 'singlepaper.semantic_review.v1', 'input_sha256': review_sha,
            'checked_pages': [], 'checked_formula_ids': [], 'checked_figure_numbers': [],
            'checked_reference_numbers': [], 'cross_page_checked': False, 'verdict': 'BLOCK',
            'findings': ['尚未完成独立检查。'], 'scope_note': '这是未完成检查的报告模板。'}
        value['final_command'] = ['role-final', '--run', str(run), '--role', role, '--report', '<run 内实际报告路径>']
    return value


def final_claims(package, run, role, report_path=None):
    c.require(role in ('AUTHOR', 'REVIEWER'), 'ROLE_REQUIRED')
    _, inputs, review_sha = documents.verify_review_inputs(package, run)
    if role == 'AUTHOR':
        c.require(report_path is None, 'AUTHOR_REPORT_NOT_ACCEPTED')
        claims = {'INPUT_SHA256': inputs['input_sha256'], 'AUTHOR_OUTPUT_SHA256': review_sha}
    else:
        c.require(report_path is not None, 'REVIEW_REPORT_REQUIRED')
        path = c.absolute(report_path)
        c.require(path.is_relative_to(run), 'REPORT_MUST_BE_IN_RUN')
        path = c.safe(run, path.relative_to(run).as_posix())
        data = path.read_bytes()
        review._report(c.loads(data), inputs, review_sha)
        claims = {'INPUT_SHA256': review_sha, 'REPORT_SHA256': c.sha(data)}
    return {'role': role, 'claims': claims, 'final_message': '\n'.join(key + '=' + value for key, value in claims.items()),
            'instruction': '将 final_message 的两行原样各输出一次到本实际子任务最终答复。不要把命令回执当作最终任务证据。'}
