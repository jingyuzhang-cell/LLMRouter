"""Continued offline content review; no API or inference."""
import json,time
from kdx_execution_adapter import ROOT,Corpus,sha
c=Corpus();out=ROOT/('kdx_t2_content_followup_'+str(time.time_ns()));out.mkdir()
checks=[('kdx_inquiry_2018','2019 年 5 月 14 日','收到2018年报问询函','2019-05-14'),('kdx_inquiry_2019','2020 年 7 月 6','收到2019年报问询函','2020-07-06'),('kdx_penalty_2020','分别采取终身','钟玉、王瑜终身禁入；徐曙、张丽雄10年禁入','2020决定; 自宣布决定日起生效')]
rows=[]
for d,needle,claim,when in checks:
 s=(ROOT/'v3_evidence/A_kangdexin/text'/f'{d}.txt').read_text();i=s.find(needle);start=max(0,i-120);end=min(len(s),i+500)
 rows.append({'document_id':d,'required_claim':claim,'applicable_time':when,'status':'COVERED' if i>=0 else 'MISSING','start':start,'end':end,'original_text':s[start:end],'source_hash':c.documents[d]['text_sha256'],'chunks':[x['fragment_id'] for x in c.chunks if x['document_id']==d and x['start']<end and x['end']>start],'limitation':'source content claim, not independent truth; announcement time is not proof of precise regulator decision date'})
(out/'CONTENT_UPDATE.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
parent=ROOT/'kdx_t2_final_prepare_1791803256988715710';inp=json.loads((parent/'INPUT_V2.json').read_text());existing={x['fragment_id'] for x in inp['payload']['evidence_fragments']}
(out/'INPUT_DELTA_PROPOSAL.json').write_text(json.dumps({'parent_input_sha256':sha((parent/'INPUT_V2.json').read_bytes()),'additional_fragments':[x for x in c.chunks if x['fragment_id'] in {i for r in rows for i in r['chunks']} and x['fragment_id'] not in existing],'admission':'NOT_FROZEN_FOR_EXECUTION; Token envelope must be remeasured','original_graph_changed':False},ensure_ascii=False,indent=2))
(out/'REPORT.md').write_text('''# t2零调用继续核查

已在原文确认三项：2019-05-14收到2018年报问询函；2020-07-06收到2019年报问询函；2020决定对钟玉/王瑜终身、徐曙/张丽雄10年市场禁入。出处和准确字符位置见CONTENT_UPDATE.json。禁入期限由UNKNOWN变为上述有限命题COVERED；不改写历史审计或消除2019/2020认定差异。

重要范围纠正：t2原目标是提取问询回复、告知书、处罚决定书关键事实，并非逐问题完整复述所有问询。此前“全部问询逐问题覆盖”是过宽的审计要求，不应单独成为硬阻塞。任务相关关键事实和上游/下游所需证据仍须逐项确认，不因缩正范围就自动判PASS。

额外段落与旧V2比较已记录新增片段建议；未覆盖旧输入、未重新生成图。建议输入尚未重新测量Token，不能沿用9232。生命周期仍有真实部署和GPU释放验证缺口，因此NO-GO不变。

本轮没有模型/HTTP调用，未改节点合同、历史超额或评分，未提交推送。不自动启动真实实验。
''')
print(out)
