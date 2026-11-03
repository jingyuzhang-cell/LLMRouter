"""V3 stage-2 seed facts: program-authored from downloaded official texts, verbatim
quotes, deterministic grounding only (quote-in-text / date<=cutoff / doc exists).
Cross-model AI verification is DEFERRED to the authorized V3 run; these are seeds,
clearly labelled (not final silver, not gold). Zero model calls."""
import json, re
from pathlib import Path
from pilot_common import all_dates, norm
BASE = Path('/root/capital_opinion_pilot/v5_migration_20261022/v5_acceptance_final/v3_evidence')

FACTS = {
 'A_kangdexin': [
  ('date','公司及实控人收到《行政处罚决定书》的日期','2020-09-27','kdx_penalty_2020',
   '2020年9月27日，公司及公司实际控制人钟玉先生收到了证监会下发的'),
  ('amount','行政处罚决定书对康得新公司处以的罚款金额','60万元','kdx_penalty_2020',
   '对康得新复合材料集团股份有限公司责令改正，给予警告，并处以60万元罚款'),
  ('amount','2015年年度报告虚增利润总额的金额','2,242,745,642.37元','kdx_penalty_2020',
   '虚增利润总额分别为2,242,745,642.37元、2,943,420,778.01元'),
  ('text','康得新财务造假采用的主要方式','虚构销售业务、虚构采购、生产、研发、产品运输费用','kdx_penalty_2020',
   '通过虚构销售业务、虚构采购、生产、研发、产品运输费用等方式'),
  ('text','2015-2018年年度报告中哪类财务数据被认定虚假记载（银行相关）','银行存款余额','kdx_penalty_2020',
   '2015年至2018年年度报告中披露的银行存款余额存在虚假记载'),
  ('text','徐曙、张丽雄被采取的市场禁入措施年限','10年','kdx_penalty_2020',
   '对徐曙、张丽雄分别采取10年证券市场禁入措施'),
  ('text','公司自查发现北京银行《现金管理业务合作协议》未经哪些机构批准','董事会和股东大会','kdx_inquiry_2018',
   '北京银行签订《现金管理业务合作协议》的行为，未经公司董事会和股东大会的批准'),
 ],
 'B_yujingangshi': [
  ('text','《行政处罚及市场禁入事先告知书》的文号','处罚字〔2021〕65号','yjt_notice_2021',
   '《行政处罚及市场禁入事先告知书》（处罚字〔2021〕65号）'),
  ('date','公司收到事先告知书的日期','2021-08-13','yjt_notice_2021','于2021年8月13日收到'),
  ('date','公司收到证监会立案相关文书的日期（2020年）','2020-04-07','yjt_notice_2021','于2020年4月7日收到'),
  ('text','拟对郭留希采取的市场禁入措施','终身市场禁入','yjt_notice_2021','对郭留希采取终身市场禁'),
  ('text','被拟采取10年市场禁入的责任人员（任一）','刘永奇','yjt_notice_2021','对刘永奇采取10年市场禁入措施'),
  ('text','告知书查明的涉嫌违法事实核心表述（2019年末）','虚增净资产','yjt_notice_2021','2019年末虚增净资产'),
 ],
 'C_shijuezhongguo': [
  ('date','天津市网信办约谈公司网站负责人对应的公告日（网友举报日）','2019-04-11','sjzg_suspend_2019',
   '2019年4月11日，经网友举报'),
  ('text','责令公司网站整改的监管主体','天津市互联网信息办公室','sjzg_suspend_2019',
   '天津市互联网信息办公室依法约谈公司网站负责人'),
  ('text','股票异常波动涉及的两个交易日','2019-04-15与2019-04-16','sjzg_abnormal_2019',
   '连续两个交易日内（2019年4月15日、4月16日）跌幅偏离值累计达到20%以上'),
  ('amount','子公司汉华易美被处以的行政罚款金额','三十万元','sjzg_resume_2019',
   '接受罚款三十万元的行政处罚'),
  ('text','收到天津市网信办行政处罚决定书的子公司名称','汉华易美(天津)图像技术有限公司','sjzg_resume_2019',
   '公司全资子公司汉华易美(天津)图像技术有限公司收到天津市互联网信息办公室行政处罚决定书'),
  ('text','对汉华易美的行政处罚决定书文号','津网信罚决字【2019】第1号','sjzg_resume_2019',
   '《津网信罚决字【2019】第1号》'),
 ],
}
manifests = json.load(open(BASE/'v3_manifests.json'))
for ev, facts in FACTS.items():
    cutoff = manifests[ev]['cutoff']
    docmap = {d['doc_id']: d for d in manifests[ev]['documents']}
    out=[]
    for i,(typ,q,a,doc,quote) in enumerate(facts):
        full=''.join((BASE/ev/'text'/f'{doc}.txt').read_text().split())
        grounded = norm(quote) in norm(full)
        pd = docmap[doc].get('public_date','9999-99-99')
        ok_dates = all(d<=cutoff for d in all_dates(a))
        out.append({'fact_id':f'{ev[0].upper()}{i+1}','answer_type':typ,'question':q,'answer':a,
            'evidence_doc':doc,'quote':quote,'public_date':pd,
            'deterministic_check':{'quote_grounded':grounded,'answer_dates_ok':ok_dates,
                                   'evidence_doc_exists':doc in docmap,'public_date_ok':pd<=cutoff,
                                   'pass':grounded and ok_dates and doc in docmap and pd<=cutoff},
            'ai_cross_verification':'PENDING_AUTHORIZED_PHASE',
            'status':'seed (deterministic-grounded; not yet AI cross-verified)'})
    doc_pass = {f['fact_id']: f['deterministic_check']['pass'] for f in out}
    json.dump({'event':manifests[ev]['event'],'cutoff':cutoff,
               'label_type':'v3_seed (deterministic grounding only; silver pending AI verification)',
               'facts':out}, open(BASE/ev/'facts_seed.json','w'), ensure_ascii=False, indent=1)
    print(ev, 'facts:', sum(doc_pass.values()), '/', len(out), 'grounded')
    for f in out:
        print(' ', f['fact_id'], 'OK' if f['deterministic_check']['pass'] else 'FAIL', f['question'][:30], '->', f['answer'][:24])
