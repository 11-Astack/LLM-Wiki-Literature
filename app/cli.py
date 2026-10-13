"""Fixed entry for the isolated single-paper candidate; no public skip gate."""
import argparse
import json
import sys
from pathlib import Path
from . import core as c, documents as d, environment, storage


def _initial_categories(args):
    if getattr(args, 'categories', None):
        c.require(getattr(args, 'confirmation', None) is not None and
                  getattr(args, 'authorization', None) is None, 'CATEGORY_INPUT_MODE_CONFLICT')
        return c.read_json(c.absolute(args.categories)), c.read_json(c.absolute(args.confirmation))
    c.require(getattr(args, 'confirmation', None) is None, 'CATEGORY_INPUT_MODE_CONFLICT')
    authorization = getattr(args, 'authorization', None)
    c.require(isinstance(authorization, str) and bool(authorization.strip()), 'CATEGORY_AUTHORIZATION_REQUIRED')
    if getattr(args, 'demo', False):
        categories, scope = [{'id': 'DEMO', 'label': '合成演示'}], 'SYNTHETIC_DEMO'
    else:
        selected = getattr(args, 'category', None)
        c.require(type(selected) is list and bool(selected), 'CATEGORY_SELECTION_REQUIRED')
        categories = []
        for item in selected:
            c.require(isinstance(item, str) and '=' in item, 'CATEGORY_ID_LABEL_REQUIRED')
            identifier, label = item.split('=', 1)
            categories.append({'id': identifier, 'label': label})
        scope = 'USER_CONFIRMED'
    storage._categories(categories)
    return categories, {'confirmed': True, 'categories_sha256': c.sha(c.encode(categories)),
                        'scope': scope, 'authorization': authorization}


def _owner(run):
    run=c.absolute(run)
    c.require(run.parent.name=='runs' and run.parent.parent.name=='.work','RUN_LOCATION')
    instance=run.parents[2]
    storage._library(instance)
    return instance,run


def _context(path):
    value=c.read_json(c.absolute(path))
    c.require(set(value)=={'root','turn','allowed_log_paths'},'HOST_CONTEXT_SCHEMA')
    c.require(type(value['allowed_log_paths']) is list and bool(value['allowed_log_paths']),'HOST_LOG_ALLOWLIST')
    return value


def _startup(run):
    seal=c.read_json(c.safe(run,'STARTUP_COMMIT.json'))
    c.require(set(seal)=={'files'} and len(seal['files'])==2 and
              {x['path'] for x in seal['files']}=={'STARTUP_CONTEXT.json','STARTUP_PROBE.json'},'STARTUP_SEAL_SCHEMA')
    for ref in seal['files']:c.check_ref(run,ref)
    return c.read_json(c.safe(run,'STARTUP_CONTEXT.json')),c.read_json(c.safe(run,'STARTUP_PROBE.json'))


def _preflight(package,obsidian_cli,context):
    from . import client
    runtime=environment.doctor(package)
    c.require(runtime.get('software_checks_passed') is True,'BUNDLED_SOFTWARE_CHECK_FAILED')
    clients=client.prereq(package,Path(obsidian_cli),context)
    c.require(clients.get('ok') is True,'REQUIRED_CLIENT_CHECK_FAILED')
    return {'software':runtime,'clients':clients,'obsidian_cli':str(c.absolute(obsidian_cli)),
            'scope':'Installed capability only; document reading remains separately unverified.'}


def _review_bundle(package,run,active=True):
    from . import review
    seal=c.read_json(c.safe(run,'REVIEW_EVIDENCE_COMMIT.json'))
    bundle=c.loads(c.check_ref(run,seal['bundle']))
    c.require(set(bundle)=={'schema','files','report','author_capture','reviewer_capture','context','result'},'REVIEW_EVIDENCE_SCHEMA')
    c.require(bundle['schema']=='singlepaper.review_evidence.v1','REVIEW_EVIDENCE_SCHEMA')
    for ref in bundle['files']:c.check_ref(run,ref)
    context=c.loads(c.check_ref(run,bundle['context']))
    startup,_=_startup(run)
    c.require(context['root']==startup['root'] and context['turn']==startup['turn'],'HOST_TASK_CHANGED')
    c.require(set(startup['allowed_log_paths'])<=set(context['allowed_log_paths']),'HOST_PARENT_LOG_CHANGED')
    author=c.loads(c.check_ref(run,bundle['author_capture']))
    reviewer=c.loads(c.check_ref(run,bundle['reviewer_capture']))
    result=review.check(package,run,c.safe(run,bundle['report']['path']),author,reviewer,context,active=active)
    c.require(result==bundle['result'],'REVIEW_EVIDENCE_CHANGED')
    return result,context


def _bundle_bytes(package,run):
    result,context=_review_bundle(package,run)
    inp,source,_=d.source_record(package,run)
    names=['source.pdf','source.md','translation_zh.md','summary.md','science_notes.md']
    names += [f"figures/Figure-{x['number']:02d}.png" for x in source['inventory']['figures']]
    output={name:c.safe(run,name).read_bytes() for name in names}
    output['provenance.json']=c.encode({'schema':'singlepaper.provenance.v1','document_id':inp['document_id'],
        'run_id':inp['run_id'],'pdf_sha256':inp['pdf_sha256'],'input_sha256':c.digest(run/'INPUT.json'),
        'review_input_sha256':c.digest(run/'REVIEW_INPUTS.json'),'report_sha256':result['report_sha256'],
        'evidence_record':f".work/runs/{inp['run_id']}/REVIEW_EVIDENCE.json",
        'scientific_acceptance':'NONE','client_reading':'NOT_VERIFIED',
        'actors':[{key:identity[key] for key in ('task_path','child_thread_id','model','effort')} for identity in result['identities']]})
    return inp,output,result,context


def _gate(package,run):
    inp,expected,result,context=_bundle_bytes(package,run)
    _,startup=_startup(run)
    _preflight(package,startup['obsidian_cli'],context)
    for name,data in expected.items():
        c.require(c.safe(run/'bundle',name).read_bytes()==data,'PUBLICATION_BUNDLE_CHANGED')
    return {'schema':'singlepaper.publish_gate.v1','input_sha256':c.digest(run/'INPUT.json'),
        'review_input_sha256':c.digest(run/'REVIEW_INPUTS.json'),
        'evidence_sha256':c.digest(run/'REVIEW_EVIDENCE.json'),
        'report_sha256':result['report_sha256'],'instance_id':inp['instance_id'],
        'assets':[c.ref(run/'bundle',c.safe(run/'bundle',name)) for name in sorted(expected)],
        'client_reading':'NOT_VERIFIED','scientific_acceptance':'NONE'}


def _plan(run):
    seal=c.read_json(c.safe(run,'PUBLICATION_PLAN_COMMIT.json'))
    saved=c.loads(c.check_ref(run,seal['plan_record']))
    c.require(set(saved)=={'schema','plan'} and saved['schema']=='singlepaper.run_plan.v1','RUN_PLAN_SCHEMA')
    instance,_=_owner(run)
    inp=c.loads(c.check_ref(run,c.read_json(c.safe(run,'INPUT_COMMIT.json'))['input']))
    plan=c.loads(c.check_ref(instance,saved['plan']))
    c.require(plan['schema']=='singlepaper.storage_plan.v2' and inp['run_id']==run.name,'RUN_PLAN_OWNER')
    c.require(Path(plan['bundle_root']).absolute()==run/'bundle','RUN_PLAN_BUNDLE')
    for key in ('title','category_id','pdf_sha256','page_count','run_id','deadline_utc','instance_id'):
        c.require(plan['metadata'][key]==inp[key],'RUN_PLAN_METADATA')
    c.require(plan['instance_id']==inp['instance_id'] and plan['metadata']['input_sha256']==c.digest(run/'INPUT.json'),'RUN_PLAN_INPUT')
    c.require(plan['gate_receipt']['input_sha256']==c.digest(run/'INPUT.json'),'RUN_PLAN_GATE')
    return saved['plan']


def execute(package,args):
    command=args.command
    if command=='host-context':
        from . import host
        context, proof=host.create_context(package,extra_days=args.day_dir,parent_log=args.parent_log,
            run=args.run,author_thread=args.author_thread,reviewer_thread=args.reviewer_thread)
        return {'ok':True,'status':'CURRENT_HOST_CONTEXT_PREPARED',**host.write_output(args.output,context),**proof}
    if command=='capture-current':
        from . import host
        capture,identity=host.capture_current(package,c.absolute(args.run),args.role,
            extra_days=args.day_dir,parent_log=args.parent_log)
        return {'ok':True,'status':'CURRENT_CHILD_IDENTITY_CAPTURED',**host.write_output(args.output,capture),
            'identity':identity,'child_thread_id':identity['child_thread_id']}
    if command in ('role-brief','role-final'):
        from . import workflow
        run=c.absolute(args.run)
        if command=='role-brief':return workflow.brief(package,run,args.role)
        return workflow.final_claims(package,run,args.role,args.report)
    if command in (None,'requirements'):
        return {'status':'REQUIREMENTS_FIRST','required':['Windows','可正常运行的 Codex','已启用命令行的 Obsidian'],
            'bundled':['Python','PDF 文字提取与页面渲染','图片处理','公式转换'],
            'next':'先运行 doctor，软件与两个客户端实际检查通过后才能导入。首次完整阅读还须独立验证。',
            'release_status':'RELEASE_STATUS_SEE_RELEASE_NOTES',
            'release_note':'doctor 只报告环境核验；实际发行情况请查看 RELEASE_NOTES。'}
    if command=='doctor':return _preflight(package,args.obsidian_cli,_context(args.host_context))
    if command=='init':
        context=_context(args.host_context);probe=_preflight(package,args.obsidian_cli,context)
        categories,confirmation=_initial_categories(args)
        value=storage.initialize(Path(args.instance),categories,confirmation)
        c.write_json_new(Path(args.instance)/'.system/initial-probe.json',probe)
        return value
    if command=='intake':
        instance=c.absolute(args.instance);storage.verify(instance)
        context=_context(args.host_context);probe=_preflight(package,args.obsidian_cli,context)
        result=d.intake(package,instance,Path(args.pdf),args.title,args.category,args.minutes)
        run=Path(result['run'])
        c.write_json_new(run/'STARTUP_CONTEXT.json',context);c.write_json_new(run/'STARTUP_PROBE.json',probe)
        c.write_json_new(run/'STARTUP_COMMIT.json',{'files':[c.ref(run,run/name) for name in ('STARTUP_CONTEXT.json','STARTUP_PROBE.json')]})
        return result
    if command in ('verify','read-index'):
        instance=c.absolute(args.instance)
        if command=='verify':return storage.verify(instance)
        from . import client
        return client.read_index(instance,Path(args.obsidian_cli))
    instance,run=_owner(args.run)
    if command=='status':
        inp,_=d.input_record(package,run,False)
        return {'run_id':inp['run_id'],'deadline_utc':inp['deadline_utc'],
            'time_remaining_seconds':max(0,int((c.parse_time(inp['deadline_utc'])-c.utcnow()).total_seconds())),
            'accepted_pages':[n for n in range(1,inp['page_count']+1) if (run/f'receipts/page-{n:03d}.commit.json').exists()],
            'review_frozen':(run/'REVIEW_INPUTS.json').exists(),'storage_planned':(run/'PUBLICATION_PLAN_COMMIT.json').exists(),
            'reading_status':'SEPARATE_CLIENT_CHECK_REQUIRED'}
    if command=='review-verify':return _review_bundle(package,run,False)[0]
    if command=='publish':return storage.publish(instance,_plan(run),lambda:_gate(package,run))
    if command=='recover':return storage.recover(instance,_plan(run))
    if command=='prepare-publish':
        with c.writer(instance):
            inp,output,_,_=_bundle_bytes(package,run)
            for name,data in output.items():c.put(c.safe(run/'bundle',name,False),data)
            metadata={key:inp[key] for key in ('title','category_id','pdf_sha256','page_count','run_id','deadline_utc','instance_id')}
            metadata['input_sha256']=c.digest(run/'INPUT.json')
            metadata['assets']=[c.ref(run/'bundle',c.safe(run/'bundle',name)) for name in sorted(output)]
        plan=storage.prepare(instance,run/'bundle',metadata,lambda:_gate(package,run))
        c.write_json_new(run/'PUBLICATION_PLAN.json',{'schema':'singlepaper.run_plan.v1','plan':plan})
        c.write_json_new(run/'PUBLICATION_PLAN_COMMIT.json',{'plan_record':c.ref(run,run/'PUBLICATION_PLAN.json')})
        return {'ok':True,'plan':plan,'status':'READY_TO_SAVE'}
    with c.writer(instance):
        _startup(run)
        if command=='prepare-source':return d.prepare_source(package,run,Path(args.source),Path(args.inventory))
        if command=='validate-page':return d.validate_page(package,run,args.page,Path(args.candidate))
        if command=='assemble':return d.assemble(package,run)
        if command=='review-check':
            from . import review
            context=_context(args.host_context)
            startup,_=_startup(run)
            c.require(context['root']==startup['root'] and context['turn']==startup['turn'],'HOST_TASK_CHANGED')
            c.require(set(startup['allowed_log_paths'])<=set(context['allowed_log_paths']),'HOST_PARENT_LOG_CHANGED')
            report=c.absolute(args.report)
            c.require(report.is_relative_to(run),'REPORT_OUTSIDE_RUN')
            captures=[c.read_json(c.absolute(path)) for path in (args.author_capture,args.reviewer_capture)]
            result=review.check(package,run,report,captures[0],captures[1],context)
            paths=['evidence/author.json','evidence/reviewer.json','evidence/context.json']
            for name,value in zip(paths,captures+[context]):c.write_json_new(run/name,value)
            refs=[c.ref(run,run/name) for name in paths]
            bundle={'schema':'singlepaper.review_evidence.v1','files':refs+[c.ref(run,report)],
                'author_capture':refs[0],'reviewer_capture':refs[1],'context':refs[2],
                'report':c.ref(run,report),'result':result}
            c.write_json_new(run/'REVIEW_EVIDENCE.json',bundle)
            c.write_json_new(run/'REVIEW_EVIDENCE_COMMIT.json',{'bundle':c.ref(run,run/'REVIEW_EVIDENCE.json')})
            return result
    raise c.Rejected('UNSUPPORTED_COMMAND')


def main(package):
    parser=argparse.ArgumentParser(description='文献单篇候选：先检查软件，再逐页处理、检查和保存。')
    sub=parser.add_subparsers(dest='command')
    sub.add_parser('requirements')
    for name in ('host-context','capture-current'):
        p=sub.add_parser(name);p.add_argument('--output',required=True)
        p.add_argument('--day-dir',action='append',default=[]);p.add_argument('--parent-log')
        p.add_argument('--run',required=name=='capture-current')
        if name=='host-context':
            p.add_argument('--author-thread');p.add_argument('--reviewer-thread')
        else:p.add_argument('--role',choices=('AUTHOR','REVIEWER'),required=True)
    for name in ('role-brief','role-final'):
        p=sub.add_parser(name);p.add_argument('--run',required=True)
        p.add_argument('--role',choices=('AUTHOR','REVIEWER'),required=True)
        if name=='role-final':p.add_argument('--report')
    for name in ('doctor','init','intake'):
        p=sub.add_parser(name);p.add_argument('--obsidian-cli',required=True);p.add_argument('--host-context',required=True)
        if name!='doctor':p.add_argument('--instance',required=True)
        if name=='init':
            mode=p.add_mutually_exclusive_group(required=True)
            mode.add_argument('--categories');mode.add_argument('--category',action='append');mode.add_argument('--demo',action='store_true')
            p.add_argument('--confirmation');p.add_argument('--authorization')
        if name=='intake':
            p.add_argument('--pdf',required=True);p.add_argument('--title',required=True);p.add_argument('--category',required=True)
            p.add_argument('--minutes',type=int,default=60)
    for name in ('prepare-source','validate-page','assemble','review-check','review-verify','prepare-publish','publish','recover','status'):
        p=sub.add_parser(name);p.add_argument('--run',required=True)
        if name=='prepare-source':
            p.add_argument('--source',required=True);p.add_argument('--inventory',required=True)
        if name=='validate-page':
            p.add_argument('--page',required=True,type=int);p.add_argument('--candidate',required=True)
        if name=='review-check':
            for flag in ('report','author-capture','reviewer-capture','host-context'):p.add_argument('--'+flag,required=True)
    for name in ('verify','read-index'):
        p=sub.add_parser(name);p.add_argument('--instance',required=True)
        if name=='read-index':p.add_argument('--obsidian-cli',required=True)
    args=parser.parse_args()
    try:
        value=execute(Path(package),args)
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 2 if isinstance(value,dict) and value.get('ok') is False else 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'ok':False,'status':'REJECTED','error':str(exc),'exception_type':type(exc).__name__},ensure_ascii=False));return 2

