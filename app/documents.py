"""Generic text-layer intake and immutable page processing for a new instance."""
from collections import Counter
from datetime import timedelta
import io,json,re,uuid
from pathlib import Path
from . import core as c
from . import page_protocol as protocol

PROFILE='TEXT_PDF_REVIEWED_CANDIDATE_V1'
MAX_PAGES=60
MAX_PDF_BYTES=25*1024*1024
NUMBER_RE=re.compile(r'[-+\u2212]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+\u2212]?\d+)?')

def _numbers(text):
    return Counter(x.replace('\u2212','-').replace('E','e').rstrip('.') for x in NUMBER_RE.findall(text))

def software(root):
    root=c.absolute(root)
    files=[root/'launch.py',root/'RUNTIME_MANIFEST.json']+sorted((root/'app').glob('*.py'))
    return [c.ref(root,p) for p in files]

def _utf8(data):
    c.require(isinstance(data,bytes) and not data.startswith(b'\xef\xbb\xbf') and b'\r' not in data,'UTF8_LF_REQUIRED')
    text=data.decode('utf-8')
    outside_math=re.sub(r'(?<!\\)\$\$.*?(?<!\\)\$\$|(?<![\\$])\$(?!\$)[^\n$]+(?<!\\)\$(?!\$)', '', text, flags=re.S)
    c.require(not re.search(r'</?(?:img|script|iframe|object|embed|svg|math|video|audio|source|link|style|a|form|input)\b',text,re.I),'ACTIVE_HTML_UNSUPPORTED')
    c.require(not re.search(r'</?[A-Za-z][\w:-]*(?:\s+[^<>]*|/?)>',outside_math),'RAW_HTML_UNSUPPORTED')
    c.require(not re.search(r'\\(?:href|url|includegraphics|html\w*)\b',text,re.I),'ACTIVE_MATH_MARKUP_UNSUPPORTED')
    c.require(not re.search(r'(?<!!)\[[^\]\n]*\]\([^\n)]*\)',outside_math) and '[[' not in outside_math,'UNREGISTERED_LINK_UNSUPPORTED')
    return text

def _supplement(data):
    text=_utf8(data)
    c.require('![' not in text,'SUPPLEMENT_IMAGE_UNSUPPORTED')
    c.require(12<=len(re.findall(r'[\u3400-\u9fff]',text)) and len(data)<=32000,'SUPPLEMENT_REQUIRED')
    return text

def _active(inp):
    start,end=c.parse_time(inp['created_utc']),c.parse_time(inp['deadline_utc'])
    c.require(timedelta(0)<end-start<=timedelta(minutes=60),'DEADLINE_CONTRACT')
    c.require(start<=c.utcnow()<end,'SESSION_EXPIRED_OR_CLOCK_CHANGED')

def input_record(package, run, active=True):
    run=c.absolute(run)
    seal=c.read_json(c.safe(run,'INPUT_COMMIT.json'))
    data=c.check_ref(run,seal['input'])
    inp=c.loads(data)
    fields={'schema','profile','instance_id','run_id','document_id','title','category_id','pdf_sha256','pdf_bytes','page_count','created_utc','deadline_utc','software','files','pages','scientific_acceptance'}
    c.require(set(inp)==fields,'INPUT_SCHEMA')
    c.require(inp['schema']=='singlepaper.input.v1' and inp['profile']==PROFILE,'INPUT_SCHEMA')
    for ref in inp['software']: c.check_ref(package,ref)
    c.require(inp['software']==software(package),'SOFTWARE_INVENTORY_CHANGED')
    for ref in inp['files']: c.check_ref(run,ref)
    c.require(type(inp['page_count']) is int and inp['page_count']==len(inp['pages']) and 1<=inp['page_count']<=MAX_PAGES,'INPUT_PAGE_COUNT')
    c.require(run.name==inp['run_id'] and run.parent.name=='runs' and run.parent.parent.name=='.work','RUN_LOCATION')
    owner=c.read_json(c.safe(run.parents[2],'.system/library.json'))
    c.require(owner['instance_id']==inp['instance_id'],'RUN_INSTANCE_MISMATCH')
    expected={'source.pdf'}
    for n,item in enumerate(inp['pages'],1):
        c.require(set(item)=={'page','text','image','image_pixels'} and type(item['page']) is int and item['page']==n,'INPUT_PAGE_SEQUENCE')
        c.require(item['text']['path']==f'pdf-pages/page-{n:03d}.txt' and item['image']['path']==f'pdf-pages/page-{n:03d}.png','INPUT_PAGE_PATH')
        c.require(type(item['image_pixels']) is list and len(item['image_pixels'])==2 and all(type(x) is int and x>0 for x in item['image_pixels']),'INPUT_IMAGE_SIZE')
        c.check_ref(run,item['text']);c.check_ref(run,item['image'])
        expected.update([item['text']['path'],item['image']['path']])
    c.require(len(inp['files'])==len(expected) and {x['path'] for x in inp['files']}==expected,'INPUT_INVENTORY')
    c.require(c.digest(c.safe(run,'source.pdf'))==inp['pdf_sha256'] and c.safe(run,'source.pdf').stat().st_size==inp['pdf_bytes'],'PDF_INPUT_DRIFT')
    if active:_active(inp)
    return inp,c.sha(data)

def intake(package, instance, pdf, title, category_id, minutes=60, deadline_utc=None):
    from pypdf import PdfReader
    import pypdfium2 as pdfium
    instance,pdf=c.absolute(instance),c.absolute(pdf)
    c.require(type(minutes) is int and 1<=minutes<=60,'BUDGET_LIMIT')
    c.require(isinstance(title,str) and 1<=len(title)<=180 and not re.search(r'[\x00-\x1f]',title),'TITLE_INVALID')
    c.require(pdf.stat().st_size<=MAX_PDF_BYTES,'PDF_SIZE_OR_HEADER')
    with pdf.open('rb') as stream:raw=stream.read(MAX_PDF_BYTES+1)
    c.require(0<len(raw)<=MAX_PDF_BYTES and raw.startswith(b'%PDF-'),'PDF_SIZE_OR_HEADER')
    reader=PdfReader(io.BytesIO(raw),strict=True)
    c.require(not reader.is_encrypted and 1<=len(reader.pages)<=MAX_PAGES,'PDF_PROFILE_UNSUPPORTED')
    top=reader.trailer['/Root']
    c.require(not any(k in top for k in ('/OpenAction','/AA','/AcroForm')),'ACTIVE_PDF_UNSUPPORTED')
    names=top.get('/Names',{})
    if hasattr(names,'get_object'):names=names.get_object()
    c.require(not any(k in names for k in ('/JavaScript','/EmbeddedFiles')),'ACTIVE_PDF_UNSUPPORTED')
    # Arbitrary action-bearing annotations require a separate supported profile.
    for page in reader.pages:
        c.require('/AA' not in page,'ACTIVE_PDF_UNSUPPORTED')
        for annotation in page.get('/Annots',[]):
            obj=annotation.get_object()
            action=obj.get('/A',{})
            if hasattr(action,'get_object'):action=action.get_object()
            c.require(obj.get('/Subtype')=='/Link' and '/AA' not in obj,'ANNOTATION_PROFILE_UNSUPPORTED')
            if action:
                allowed={'/Type','/S','/URI'} if action.get('/S')=='/URI' else {'/Type','/S','/D'}
                c.require(action.get('/S') in ('/URI','/GoTo') and set(action)<=allowed,'ACTIVE_PDF_UNSUPPORTED')
                if action.get('/S')=='/URI':
                    c.require(isinstance(action.get('/URI'),str) and re.match(r'https?://',action['/URI']) is not None,'PDF_URI_UNSUPPORTED')
    started=c.utcnow();end=started+timedelta(minutes=minutes) if deadline_utc is None else c.parse_time(deadline_utc)
    c.require(timedelta(0)<end-started<=timedelta(minutes=minutes),'BUDGET_LIMIT')
    with c.writer(instance):
        from . import storage
        library,_=storage._library(instance)
        c.require(all(w['status']=='STORED_OUTPUT_VERIFIED' for w in library['works']),'PENDING_COMMIT_EXISTS')
        c.require(category_id in {item['id'] for item in library['categories']},'CATEGORY_NOT_CONFIRMED')
        c.require(not any(w.get('pdf_sha256')==c.sha(raw) for w in library['works']),'PDF_ALREADY_REGISTERED')
        for existing in (instance/'.work/runs').glob('*/INPUT.json'):
            old=c.read_json(existing)
            done=any(w.get('run_id')==old['run_id'] for w in library['works'])
            stopped=(existing.parent/'STOPPED.json').exists()
            c.require(done or stopped or c.parse_time(old['deadline_utc'])<=c.utcnow(),'ACTIVE_RUN_EXISTS')
        run_id='R'+uuid.uuid4().hex
        run=c.safe(instance,'.work/runs/'+run_id,False)
        run.mkdir(parents=True,exist_ok=False)
        c.put(run/'source.pdf',raw)
        files=[c.ref(run,run/'source.pdf')];pages=[]
        doc=pdfium.PdfDocument(raw)
        try:
            c.require(len(doc)==len(reader.pages),'PARSER_PAGE_DISAGREEMENT')
            for n in range(1,len(doc)+1):
                c.require(c.utcnow()<end,'SESSION_EXPIRED')
                page=doc[n-1];textpage=page.get_textpage()
                try:
                    width,height=page.get_width()*1.7,page.get_height()*1.7
                    c.require(0<width<=8192 and 0<height<=8192 and width*height<=16000000,'PAGE_RENDER_SIZE_UNSUPPORTED')
                    text=textpage.get_text_range().replace('\r\n','\n').replace('\r','\n')
                    c.require(len(text.strip())>80 and '\ufffd' not in text,'TEXT_LAYER_PROFILE_UNSUPPORTED')
                    base=run/f'pdf-pages/page-{n:03d}'
                    c.put(base.with_suffix('.txt'),text.encode('utf-8'))
                    bitmap=page.render(scale=1.7)
                    try:
                        image=bitmap.to_pil();out=io.BytesIO();image.save(out,format='PNG')
                        size=[image.width,image.height]
                    finally:bitmap.close()
                    c.put(base.with_suffix('.png'),out.getvalue())
                    txt=c.ref(run,base.with_suffix('.txt'));png=c.ref(run,base.with_suffix('.png'))
                    files.extend([txt,png]);pages.append({'page':n,'text':txt,'image':png,'image_pixels':size})
                finally:textpage.close();page.close()
        finally:doc.close()
        inp={'schema':'singlepaper.input.v1','profile':PROFILE,'instance_id':library['instance_id'],
             'run_id':run_id,'document_id':'D'+c.sha(raw)[:12].upper(),'title':title,'category_id':category_id,
             'pdf_sha256':c.sha(raw),'pdf_bytes':len(raw),'page_count':len(pages),
             'created_utc':started.isoformat(),'deadline_utc':end.isoformat(),'software':software(package),
             'files':files,'pages':pages,'scientific_acceptance':'NONE'}
        c.write_json_new(run/'INPUT.json',inp)
        c.write_json_new(run/'INPUT_COMMIT.json',{'input':c.ref(run,run/'INPUT.json')})
        c.write_json_new(run/'DRAFT_GUIDE.json',{'source':'draft/source.md','inventory':'draft/inventory.json',
            'required':'Read every page image; reconstruct complete page text, formulas, figures and references. No special-page exemptions.'})
        return {'ok':True,'run':str(run),'input':c.ref(run,run/'INPUT.json'),'deadline_utc':inp['deadline_utc'],'page_count':len(pages)}

def _inventory(inp, source, inventory, records, input_sha):
    fields={'schema','input_sha256','source_sha256','page_count','reviewed_pages','formulas','figures','references'}
    c.require(isinstance(inventory,dict) and set(inventory) in (fields,fields|{'reference_ends'}),'INVENTORY_SCHEMA')
    c.require(inventory['schema']=='singlepaper.inventory.v1' and inventory['input_sha256']==input_sha
              and inventory['source_sha256']==c.sha(source.encode('utf-8')) and inventory['page_count']==inp['page_count']
              and inventory['reviewed_pages']==list(range(1,inp['page_count']+1)),'INVENTORY_BINDING')
    ends=[r['reference_end'] for r in records if 'reference_end' in r]
    c.require(isinstance(inventory.get('reference_ends',[]),list) and inventory.get('reference_ends',[])==ends,'REFERENCE_END_INVENTORY_MATCH')
    blocks=[(r['page'],b) for r in records for b in r['protected_blocks']]
    formulas=[(page,b) for page,b in blocks if b['kind']=='formula']
    figures=[(page,b) for page,b in blocks if b['kind']=='figure']
    references=[(page,b) for page,b in blocks if b['kind']=='reference']
    c.require(all(isinstance(inventory[k],list) for k in ('formulas','figures','references')),'INVENTORY_LISTS')
    c.require(len(formulas)==len(inventory['formulas']) and len(figures)==len(inventory['figures']) and len(references)==len(inventory['references']),'INVENTORY_COMPLETE_SEQUENCE')
    from latex2mathml.converter import convert
    for ordinal,((page,block),item) in enumerate(zip(formulas,inventory['formulas']),1):
        c.require(set(item)=={'id','page','latex','printed_label'} and item['id']==f'EQ{ordinal:03d}' and type(item['page']) is int and item['page']==page,'FORMULA_INVENTORY')
        c.require(item['printed_label'] is None or isinstance(item['printed_label'],str),'FORMULA_LABEL')
        match=re.search(r'^\$\$\n(.*?)\n\$\$$',block['source'],re.M|re.S)
        c.require(match is not None and match[1]==item['latex'],'FORMULA_SOURCE_BYTES')
        c.require(block['identity']==item['id'],'FORMULA_ID_SEQUENCE')
        c.require(isinstance(item['latex'],str) and 0<len(item['latex'])<=4000,'FORMULA_SIZE')
        c.require('<math' in convert(item['latex']),'FORMULA_RENDER_FAILED')
    figure_seen=set()
    for (page,block),item in zip(figures,inventory['figures']):
        c.require(set(item)=={'number','page','bbox_pixels','caption'} and type(item['number']) is int and item['number']>0
                  and type(item['page']) is int and item['page']==page,'FIGURE_INVENTORY')
        number=item['number'];c.require(number not in figure_seen,'FIGURE_DUPLICATE');figure_seen.add(number)
        c.require(block['source']==f'![Figure {number}](figures/Figure-{number:02d}.png)','FIGURE_SOURCE_BYTES')
        box=item['bbox_pixels'];width,height=inp['pages'][page-1]['image_pixels']
        c.require(isinstance(box,list) and len(box)==4 and all(type(x) is int for x in box) and 0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height,'FIGURE_BOUNDS')
        c.require(isinstance(item['caption'],str) and item['caption'].strip() and item['caption'] in protocol.split_pages(source,inp['page_count'])[page],'FIGURE_CAPTION_MISSING')
    previous=0
    for (page,block),item in zip(references,inventory['references']):
        c.require(set(item)=={'number','page','text'} and type(item['number']) is int and item['number']==previous+1
                  and type(item['page']) is int and item['page']==page and item['text']==block['source'],'REFERENCE_INVENTORY')
        previous=item['number']
    if ends:
        c.require(len(ends)==1 and references and ends[0]=={
            'pdf_page':references[-1][0], 'last_reference_number':previous,
            'last_reference_sha256':references[-1][1]['source_sha256']},'REFERENCE_END_FINAL_REFERENCE')
    cited=[]
    for record in records:
        for element in record['elements']:
            for group in element.get('citation_groups',[]):cited.extend(int(x) for x in re.findall(r'\d+',group))
    c.require(all(1<=n<=len(references) for n in cited),'CITATION_WITHOUT_REFERENCE')

def prepare_source(package, run, source_path, inventory_path):
    run=c.absolute(run);inp,input_sha=input_record(package,run)
    c.require(not (run/'SOURCE.json').exists(),'SOURCE_ALREADY_FROZEN')
    source_path=c.absolute(source_path);inventory_path=c.absolute(inventory_path)
    c.require(source_path.is_relative_to(run) and inventory_path.is_relative_to(run),'DRAFT_MUST_BE_IN_RUN')
    c.require(source_path.stat().st_size<=2*1024*1024,'SOURCE_TOO_LARGE')
    raw=source_path.read_bytes();source=_utf8(raw);inventory=c.read_json(inventory_path)
    c.require(isinstance(inventory,dict),'INVENTORY_SCHEMA')
    bodies=protocol.split_pages(source,inp['page_count']);records=[];page_inputs=[]
    for page,body in bodies.items():
        c.require(len(body)>40,'RECONSTRUCTED_PAGE_TOO_SHORT')
        page_input,record=protocol.make_page_contract(inp['document_id'],page,body,reference_ends=inventory.get('reference_ends',[]))
        c.require(record['translate_span_count']>0,'ZERO_TRANSLATION_SPAN_UNSUPPORTED')
        page_inputs.append(page_input);records.append(record)
    _inventory(inp,source,inventory,records,input_sha)
    files=[]
    c.put(run/'source.snapshot.md',raw);files.append(c.ref(run,run/'source.snapshot.md'))
    c.put(run/'inventory.snapshot.json',c.encode(inventory));files.append(c.ref(run,run/'inventory.snapshot.json'))
    from PIL import Image
    for item in inventory['figures']:
        with Image.open(c.safe(run,inp['pages'][item['page']-1]['image']['path'])) as image:
            crop=image.crop(item['bbox_pixels']);out=io.BytesIO();crop.save(out,format='PNG')
        path=run/f"figures/Figure-{item['number']:02d}.png"
        c.put(path,out.getvalue());files.append(c.ref(run,path))
    for record,page_input in zip(records,page_inputs):
        path=run/f"page-inputs/page-{record['page']:03d}.md"
        c.put(path,page_input.encode('utf-8'));files.append(c.ref(run,path))
    frozen={'schema':'singlepaper.source.v1','input_sha256':input_sha,'files':files,'records':records,
            'inventory':inventory,'page_count':inp['page_count']}
    c.write_json_new(run/'SOURCE.json',frozen)
    source_ref=c.ref(run,run/'SOURCE.json')
    c.write_json_new(run/'SOURCE_COMMIT.json',{'source':source_ref})
    for record,page_input in zip(records,page_inputs):
        text=protocol.SPAN_INPUT_RE.sub(lambda m:m.group(0).replace('LIT_TRANSLATION_SPAN','LIT_TRANSLATED_SPAN').replace(m['body'],'待填写中文译文'),page_input)
        prefix=f"<!-- LIT_SESSION_SHA256 {source_ref['sha256']} -->\n## PDF 第 {record['page']} 页\n\n"
        c.put(run/f"candidates/page-{record['page']:03d}.md",(prefix+text).encode('utf-8'))
    _active(inp)
    return {'ok':True,'source':source_ref,'pages':inp['page_count'],'figures':len(inventory['figures'])}

def source_record(package,run,active=True):
    inp,input_sha=input_record(package,run,active)
    seal=c.read_json(c.safe(run,'SOURCE_COMMIT.json'));data=c.check_ref(run,seal['source']);source=c.loads(data)
    c.require(set(source)=={'schema','input_sha256','files','records','inventory','page_count'} and source['schema']=='singlepaper.source.v1'
              and source['input_sha256']==input_sha and source['page_count']==inp['page_count'],'SOURCE_BINDING')
    for ref in source['files']:c.check_ref(run,ref)
    raw=c.safe(run,'source.snapshot.md').read_bytes();text=_utf8(raw)
    c.require(isinstance(source['inventory'],dict),'INVENTORY_SCHEMA')
    bodies=protocol.split_pages(text,inp['page_count'])
    rebuilt=[protocol.make_page_contract(inp['document_id'],page,body,reference_ends=source['inventory'].get('reference_ends',[]))[1] for page,body in bodies.items()]
    c.require(source['records']==rebuilt,'PAGE_CONTRACT_CHANGED')
    c.require(c.read_json(c.safe(run,'inventory.snapshot.json'))==source['inventory'],'INVENTORY_CHANGED')
    _inventory(inp,text,source['inventory'],rebuilt,input_sha)
    expected={'source.snapshot.md','inventory.snapshot.json'}
    expected.update(f'page-inputs/page-{n:03d}.md' for n in range(1,inp['page_count']+1))
    expected.update(f"figures/Figure-{item['number']:02d}.png" for item in source['inventory']['figures'])
    c.require(len(source['files'])==len(expected) and {x['path'] for x in source['files']}==expected,'SOURCE_FILE_INVENTORY')
    for n,body in bodies.items():
        text_input,_=protocol.make_page_contract(inp['document_id'],n,body,reference_ends=source['inventory'].get('reference_ends',[]))
        c.require(c.safe(run,f'page-inputs/page-{n:03d}.md').read_bytes()==text_input.encode('utf-8'),'PAGE_INPUT_CHANGED')
    return inp,source,c.sha(data)

def _page_translation(data,page,record,source_sha,input_text):
    text=_utf8(data)
    prefix=f'<!-- LIT_SESSION_SHA256 {source_sha} -->\n'
    c.require(text.startswith(prefix),'FOREIGN_SESSION_CANDIDATE')
    elements,metrics=protocol.validate(text[len(prefix):],page,record)
    original={json.loads(m['meta'])['id']:m['body'] for m in protocol.SPAN_INPUT_RE.finditer(input_text)}
    # Repeat numeric protection during acceptance and every later reconstruction.
    for element in elements:
        if element['type']!='translate':continue
        c.require(_numbers(element['translation'])==_numbers(original[element['id']]),'PROSE_NUMBER_DRIFT')
    return elements,metrics

def accepted(package,run,page,source=None,source_sha=None):
    if source is None:_,source,source_sha=source_record(package,run)
    receipt_path=c.safe(run,f'receipts/page-{page:03d}.json')
    commit=c.read_json(c.safe(run,f'receipts/page-{page:03d}.commit.json'))
    data=c.check_ref(run,commit['receipt']);receipt=c.loads(data)
    c.require(set(receipt)=={'schema','page','source_sha256','accepted','metrics','validated_utc','previous_receipt_sha256'} and receipt['schema']=='singlepaper.page_receipt.v1','PAGE_RECEIPT_SCHEMA')
    c.require(data==receipt_path.read_bytes() and receipt['page']==page and receipt['source_sha256']==source_sha,'PAGE_RECEIPT_BINDING')
    output=c.check_ref(run,receipt['accepted'])
    c.require(receipt['accepted']['path']==f'accepted/page-{page:03d}.md','ACCEPTED_PATH')
    elements,metrics=_page_translation(output,page,source['records'][page-1],source_sha,
        c.safe(run,f'page-inputs/page-{page:03d}.md').read_text(encoding='utf-8'))
    c.require(receipt['metrics']==metrics,'PAGE_METRICS_CHANGED')
    expected=None if page==1 else c.digest(c.safe(run,f'receipts/page-{page-1:03d}.json'))
    c.require(receipt['previous_receipt_sha256']==expected,'PAGE_ORDER_BINDING')
    inp,_=input_record(package,run,False)
    c.require(c.parse_time(inp['created_utc'])<=c.parse_time(receipt['validated_utc'])<c.parse_time(inp['deadline_utc']) and c.parse_time(receipt['validated_utc'])<=c.utcnow(),'PAGE_RECEIPT_TIME')
    return elements,receipt

def validate_page(package,run,page,candidate):
    run=c.absolute(run);inp,source,source_sha=source_record(package,run)
    c.require(type(page) is int and 1<=page<=inp['page_count'],'PAGE_OUT_OF_RANGE')
    c.require(not (run/'REVIEW_INPUTS.json').exists(),'REVIEW_ALREADY_FROZEN')
    c.require(not (run/f'accepted/page-{page:03d}.md').exists(),'PAGE_ALREADY_ACCEPTED')
    for previous in range(1,page):accepted(package,run,previous,source,source_sha)
    path=c.absolute(candidate);c.require(path.is_relative_to(run),'CANDIDATE_PATH')
    data=path.read_bytes();attempt=c.sha(data)
    c.put(run/f'attempts/page-{page:03d}/{attempt}.md',data)
    try:
        inputs=c.safe(run,f'page-inputs/page-{page:03d}.md').read_text(encoding='utf-8')
        elements,metrics=_page_translation(data,page,source['records'][page-1],source_sha,inputs)
    except ValueError as error:
        c.write_json_new(run/f'attempts/page-{page:03d}/{attempt}.failure.json',{'status':'REJECTED','error_type':type(error).__name__,'source_sha256':source_sha})
        raise
    source_record(package,run);_active(inp)
    output=run/f'accepted/page-{page:03d}.md';c.put(output,data)
    receipt={'schema':'singlepaper.page_receipt.v1','page':page,'source_sha256':source_sha,
        'accepted':c.ref(run,output),'metrics':metrics,'validated_utc':c.utcnow().isoformat(),
        'previous_receipt_sha256':None if page==1 else c.digest(run/f'receipts/page-{page-1:03d}.json')}
    target=run/f'receipts/page-{page:03d}.json';c.write_json_new(target,receipt)
    c.write_json_new(run/f'receipts/page-{page:03d}.commit.json',{'receipt':c.ref(run,target)})
    return {'ok':True,'page':page,'status':'PAGE_TECHNICALLY_ACCEPTED','receipt':c.ref(run,target)}

def _assembled(package,run,active=True):
    inp,source,source_sha=source_record(package,run,active)
    page_text=[]
    for page in range(1,inp['page_count']+1):
        elements,_=accepted(package,run,page,source,source_sha)
        page_text.append(protocol.assemble_page(elements,source['records'][page-1]))
    return inp,source,('# 中文全文\n\n'+'\n\n'.join(page_text)+'\n').encode('utf-8')

def assemble(package,run):
    run=c.absolute(run);c.require(not (run/'REVIEW_INPUTS.json').exists(),'REVIEW_ALREADY_FROZEN')
    inp,source,translation=_assembled(package,run)
    files=[]
    for name in ('summary.md','science_notes.md'):
        data=c.safe(run,name).read_bytes();_supplement(data)
        files.append(c.ref(run,run/name))
    c.put(run/'source.md',c.safe(run,'source.snapshot.md').read_bytes());c.put(run/'translation_zh.md',translation)
    names=['INPUT.json','INPUT_COMMIT.json','SOURCE.json','SOURCE_COMMIT.json','source.md','translation_zh.md']
    names += [f'{folder}/page-{page:03d}{suffix}' for page in range(1,inp['page_count']+1)
              for folder,suffix in [('accepted','.md'),('receipts','.json'),('receipts','.commit.json')]]
    files += [c.ref(run,run/name) for name in names]+inp['files']+source['files']
    c.require(len({x['path'] for x in files})==len(files),'DUPLICATE_REVIEW_REF')
    for ref in files:c.check_ref(run,ref)
    inventory=source['inventory']
    review={'schema':'singlepaper.review_inputs.v1','input_sha256':c.digest(run/'INPUT.json'),
        'source_sha256':c.digest(run/'SOURCE.json'),'deadline_utc':inp['deadline_utc'],'run_id':inp['run_id'],
        'instance_id':inp['instance_id'],'page_count':inp['page_count'],'files':files,
        'formula_ids':[x['id'] for x in inventory['formulas']], 'figure_numbers':[x['number'] for x in inventory['figures']],
        'reference_numbers':[x['number'] for x in inventory['references']],'status':'READY_FOR_INDEPENDENT_REVIEW'}
    _active(inp);c.write_json_new(run/'REVIEW_INPUTS.json',review)
    return {'ok':True,'status':review['status'],'review_inputs':c.ref(run,run/'REVIEW_INPUTS.json')}

def verify_review_inputs(package,run,expected_sha=None,active=True):
    run=c.absolute(run);path=c.safe(run,'REVIEW_INPUTS.json');data=path.read_bytes();review=c.loads(data)
    if expected_sha is not None:c.require(c.sha(data)==expected_sha,'REVIEW_INPUT_CHANGED')
    inp,source,translation=_assembled(package,run,active)
    c.require(set(review)=={'schema','input_sha256','source_sha256','deadline_utc','run_id','instance_id','page_count','files','formula_ids','figure_numbers','reference_numbers','status'},'REVIEW_SCHEMA')
    c.require(review['schema']=='singlepaper.review_inputs.v1' and review['input_sha256']==c.digest(run/'INPUT.json')
              and review['source_sha256']==c.digest(run/'SOURCE.json') and review['deadline_utc']==inp['deadline_utc']
              and review['run_id']==inp['run_id'] and review['instance_id']==inp['instance_id']
              and type(review['page_count']) is int and review['page_count']==inp['page_count']
              and review['status']=='READY_FOR_INDEPENDENT_REVIEW','REVIEW_SCOPE_CHANGED')
    for ref in review['files']:c.check_ref(run,ref)
    for name in ('summary.md','science_notes.md'):_supplement(c.safe(run,name).read_bytes())
    required={'summary.md','science_notes.md','INPUT.json','INPUT_COMMIT.json','SOURCE.json','SOURCE_COMMIT.json','source.md','translation_zh.md'}
    required.update(x['path'] for x in inp['files']+source['files'])
    required.update(f'{folder}/page-{page:03d}{suffix}' for page in range(1,inp['page_count']+1)
              for folder,suffix in [('accepted','.md'),('receipts','.json'),('receipts','.commit.json')])
    c.require(len(review['files'])==len(required) and {x['path'] for x in review['files']}==required,'REVIEW_INVENTORY_CHANGED')
    c.require(c.safe(run,'translation_zh.md').read_bytes()==translation and c.safe(run,'source.md').read_bytes()==c.safe(run,'source.snapshot.md').read_bytes(),'ASSEMBLY_CHANGED')
    for key,rows,field in [('formula_ids',source['inventory']['formulas'],'id'),('figure_numbers',source['inventory']['figures'],'number'),('reference_numbers',source['inventory']['references'],'number')]:
        c.require(review[key]==[x[field] for x in rows],'REVIEW_COVERAGE_CHANGED')
    return inp,review,c.sha(data)
