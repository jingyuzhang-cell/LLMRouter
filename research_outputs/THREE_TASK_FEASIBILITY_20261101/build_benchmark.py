"""Source-constrained reference drafts and contract DAGs. No inference API; no Gold self-certification."""
from pathlib import Path
import json,hashlib,re
from decimal import Decimal
R=Path('/root/research_outputs/CAPITAL_PUBLIC_DATA_20261031');O=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((R/'SOURCE_MANIFEST.json').read_text()); tasks=json.loads((R/'TASK_INPUTS.json').read_text()); oldrefs=json.loads((R/'REFERENCE_CANDIDATES.json').read_text())
docs={(d['event'],d['source_id']):d for d in manifest if d['status']=='DOWNLOADED'}
protected={str(R/f):sha(R/f) for f in ['SOURCE_MANIFEST.json','TASK_INPUTS.json','REFERENCE_CANDIDATES.json']}
for t in tasks:
 for d in t['source_scope']['documents']:
  assert sha(R/d['file'])==d['sha256'];protected[str(R/d['file'])]=sha(R/d['file'])
  for p in d.get('pages',[]):
   assert sha(R/p['file'])==p['sha256'];protected[str(R/p['file'])]=sha(R/p['file'])
  if d.get('text_file'):
   assert sha(R/d['text_file'])==d['text_sha256'];protected[str(R/d['text_file'])]=sha(R/d['text_file'])
def norm(s):return ''.join(c for c in s if not c.isspace())
def ev(task,source,page,quote,occurrence=None,subdocument=None):
 d=docs[task,source]
 f=next(p['file'] for p in d['pages'] if p['page']==page) if page is not None else d['text_file']
 text=(R/f).read_text();chars=[i for i,c in enumerate(text) if not c.isspace()];n=norm(text);q=norm(quote)
 hits=[m.start() for m in re.finditer(re.escape(q),n)]
 assert hits,(task,source,page,quote)
 assert len(hits)==1 or occurrence is not None,('ambiguous',task,source,quote,len(hits))
 pos=hits[occurrence or 0];a=chars[pos];b=chars[pos+len(q)-1]+1
 return {'source_id':source,'page':page,'page_type':'PDF_PAGE' if page is not None else 'HTML_TEXT_NOT_PDF_PAGE','file':str(R/f),'start':a,'end':b,'offset_unit':'unicode_codepoint','quote':text[a:b],'source_sha256':d['sha256'],'text_sha256':sha(R/f),'url':d['url'],'subdocument':subdocument}
def meta(task,source):
 d=docs[task,source];return {'kind':'ARCHIVED_DISCLOSURE_LISTING_DATE_NOT_BODY_DATE','source_id':source,'value':d['publication_date_from_listing'],'file':str(R/'SOURCE_MANIFEST.json'),'sha256':sha(R/'SOURCE_MANIFEST.json'),'independently_verified':False}
refs=[]
def add(task,num,answer,atoms,evs,unknowns,method='direct_source_reading',calc=None,limits=None,metadata=None):
 old=next(x for x in oldrefs if x['id']==f'{task}_T{num}')
 refs.append({'id':old['id'],'question':old['question'],'answer':answer,'required_answer_components':atoms,'evidence':evs,'calculations':calc or [],'UNKNOWN_boundaries':unknowns,'question_relevance':{'status':'SOURCE_RELEVANT_WITH_STATED_LIMITS','basis':'Question mapped to quoted source assertions; not a credentialed assessment of future model answers'},'verification':{'method':method,'compiler':'assistant_source_review','independent_reviewers':0,'independent_adjudication':'PENDING','evidence_grade':'SOURCE_CONSTRAINED_SILVER_DRAFT','gold_eligible':False,'uses_experimental_model_output':False},'limitations':limits or [],'date_metadata':metadata or []})
J='JIAYUAN_202610';P='CSRC_PENALTY';C='ACCOUNTING_CORRECTION'
add(J,1,'中国证监会〔2026〕52号决定对佳缘科技责令改正、给予警告并罚款600万元。个人另罚：王进300万元；朱伟华、柳絮各200万元；尹明君150万元。公司罚款不得与个人罚款混为一项。',{'company':'佳缘科技股份有限公司','sanctions':['责令改正','警告'],'company_fine':{'value':'600','unit':'万元'},'decision_no':'〔2026〕52号','persons_fines_万元':{'王进':'300','朱伟华':'200','柳絮':'200','尹明君':'150'}},[ev(J,P,None,'〔2026〕52号'),ev(J,P,None,'一、对佳缘科技股份有限公司责令改正，给予警告，并处以600万元罚款；\n二、对王进给予警告，并处以300万元罚款；\n三、对朱伟华、柳絮给予警告，并分别处以200万元罚款；\n四、对尹明君给予警告，并处以150万元罚款。')],['实际缴款、复议诉讼结果、处罚是否另有变更均未由本任务材料确认。'])
add(J,2,'两项违法行为合计影响2019—2022年营业收入和利润总额，正号表示披露虚增、负号表示披露虚减。受影响披露为招股说明书2019/2020年数据及2021/2022年年度报告。',{'years':[2019,2020,2021,2022],'revenue_misstatement_万元':['2015.60','-687.65','2803.38','-2562.47'],'profit_misstatement_万元':['1613.84','-1569.60','1803.93','-1634.45'],'sign_semantics':'positive=虚增;negative=虚减;not correcting journal entry'},[ev(J,P,None,'上述两项违法行为导致佳缘科技2019年至2022年营业收入分别虚增2,015.60万元、虚减687.65万元、虚增2,803.38万元、虚减2,562.47万元，占当期披露营业收入绝对值的15.39%、3.61%、8.85%、9.51%；利润总额分别虚增1,613.84万元、虚减1,569.60万元、虚增1,803.93万元、虚减1,634.45万元，占当期披露利润总额绝对值的44.02%、25.80%、16.95%、24.43%。佳缘科技披露的《招股说明书》中2019年、2020年财务数据及2021年和2022年年度报告内容存在虚假记载。')],['不能把披露虚增/虚减数当作同符号更正分录；未从本题推算所有报表科目影响。'])
add(J,3,'是不同事项：客户A相关合同不满足收入确认条件而提前确认；另为2020年介入装备公司与科技公司业务链的不具商业实质交易。应分项后再作年度合计。',{'items':['客户A业务提前确认收入','2020年无商业实质购销交易'],'same_issue':False},[ev(J,P,None,'在不符合收入确认条件的情况下提前确认收入，导致公司2019年至2022年营业收入分别虚增2,015.60万元、虚减2,015.60万元、虚增2,803.38万元、虚减2,562.47万元'),ev(J,P,None,'2020年，佳缘科技介入某装备有限公司（以下简称装备公司）与某科技有限公司（以下简称科技公司）之间正在履行的购销业务链条，相关交易不具备商业实质，导致公司虚增营业收入1,327.95万元，虚增利润总额44.24万元。')],['客户A及匿名装备/科技公司的真实身份未披露，不得自行识别。'])
add(J,4,'不完全相等。证监会52号决定中的两项行为影响2019—2022年；更正公告另据四川证监局69号决定，覆盖2019、2020、2021、2022及2024年。公告称2023/2025年度报表无重大影响，不另更正；不能改写成绝无影响。',{'penalty_52_affected_years':[2019,2020,2021,2022],'correction_years':[2019,2020,2021,2022,2024],'not_separately_corrected_years':[2023,2025],'additional_2024_source':'发行人公告转述四川证监局〔2026〕69号；该监管决定原件未在包内'},[ev(J,C,2,'根据公司于2026年10月16日收到四川证监局下发的《关于对佳缘科技股份有限公司采取责令改正措施并对王进等相关责任人采取出具警示函措施的决定》（〔2026〕69号）认定：'),ev(J,C,2,'2021年公司与某客户开展网络信息安全业务，在不符合收入确认条件的情形下提前确认收入，导致公司2024年度虚减营业收入766,400元，虚减利润总额565,276.28元。'),ev(J,C,2,'公司已对上述前期会计差错进行了更正，并对上市前2019年度、2020年度、2021年度及上市后2022年度、2024年度合并及母公司财务报表进行了追溯调整。同时鉴于2023年度、2025年度的合并财务报表及母公司单体财务报表无重大影响，不另进行会计差错更正。'),ev(J,P,None,'上述两项违法行为导致佳缘科技2019年至2022年营业收入')],['69号决定原件未取得，2024事项只能归属为公告转述，不冒充已独立核实监管原件。'],'cross_source_scope_reconciliation')
add(J,5,'发行人公告明确记载2026-10-16收到52号处罚决定；更正公告落款同为2026-10-16。冻结披露记录给出该公告公开日2026-10-17，监管网页公开日2026-10-23；后两项是档案元数据，不能等同收到日、决定作出日或首次公开时刻。',{'receipt_date':'2026-10-16','correction_signature_date':'2026-10-16','correction_listing_date':'2026-10-17','regulator_listing_date':'2026-10-23','decision_issue_date':None},[ev(J,C,1,'根据公司于2026年10月16日收到中国证监会下发的《行政处罚决定书》'),ev(J,C,12,'佳缘科技股份有限公司\n董事会\n2026年10月16日')],['决定正式作出日、精确发布时间UNKNOWN；10月17日/23日仅有冻结列表元数据支持，未独立核验发布记录。'],'source_body_plus_separate_archive_metadata',metadata=[meta(J,C),meta(J,P)])
add(J,6,'2020年提前确认事项收入影响−2015.60万元，加无商业实质事项+1327.95万元，合计−687.65万元；利润−1613.84+44.24=−1569.60万元。不可把无商业实质事项的单项虚增当作2020年总虚增；不可重复将单项和合计相加。',{'year':2020,'revenue_total_万元':'-687.65','profit_total_万元':'-1569.60'},[ev(J,P,None,'导致公司2019年至2022年营业收入分别虚增2,015.60万元、虚减2,015.60万元、虚增2,803.38万元、虚减2,562.47万元，利润总额分别虚增1,613.84万元、虚减1,613.84万元、虚增1,803.93万元、虚减1,634.45万元。'),ev(J,P,None,'导致公司虚增营业收入1,327.95万元，虚增利润总额44.24万元。'),ev(J,P,None,'上述两项违法行为导致佳缘科技2019年至2022年营业收入分别虚增2,015.60万元、虚减687.65万元')],['使用万元和披露错报方向；未经逐科目核对不得推出报表调整总额。'],'decimal_calculation_and_source_crosscheck',[{'operands':['-2015.60','1327.95'],'operator':'sum','result':'-687.65','unit':'万元'},{'operands':['-1613.84','44.24'],'operator':'sum','result':'-1569.60','unit':'万元'}])
B='RONBAY_202601';I='INQUIRY';A='REPLY'
add(B,1,'公司记载2026-01-13收到上证科创公函【2026】0017号问询；问询披露公告落款2026-01-14，冻结公开记录亦为该日；回复公告落款及冻结公开记录为2026-01-19。不得混同收到问询与公开公告日期。',{'inquiry_receipt':'2026-01-13','inquiry_notice_signature':'2026-01-14','reply_signature':'2026-01-19'},[ev(B,I,1,'于2026年1月13日收到上海证券交易所科创板公司管理部下发的上证科创公函【2026】0017号'),ev(B,I,2,'宁波容百新能源科技股份有限公司董事会\n2026年1月14日'),ev(B,A,8,'宁波容百新能源科技股份有限公司董事会\n2026年1月19日')],['当日公开时刻及合同实际签署时刻未由这些日期确定。'],metadata=[meta(B,I),meta(B,A)])
add(B,2,'1200亿元是公司估算，不是协议约定采购金额。实际销售规模取决于实际订单签订时的原料价格与数量，存在不确定性；不能视为确定收入。',{'contract_amount_fixed':False,'company_estimate_亿元':'1200','statement_owner':'公司回复','revenue_guaranteed':False},[ev(B,I,1,'协议中并未对总销售金额进行约定，公司未公告销售金额的确定依据。'),ev(B,A,8,'协议未约定采购金额，“1200亿元合同总金额”是公司估算得出，最终实际销售规模需根据实际订单签订时的原材料价格以及数量确定，销售金额具有不确定性。原公告对合同总金额表述不严谨。')],['无法从估算确定最终成交金额、收入确认或利润；不得用未来处罚公告填补本截止点。'],'inquiry_reply_crosscheck')
add(B,3,'305万吨是6年预测需求，不是无条件保证采购量。回复另披露：满足甲方综合竞争力要求前提下有最低采购量约定；具体最低量未披露，最终采购量仍以后续框架、年度或单笔合同为准。不能写成完全没有采购承诺。',{'predicted_total_万吨':'305','horizon_years':6,'unconditional_guarantee':False,'conditional_minimum_exists':True,'minimum_quantity':None},[ev(B,A,3,'本次签约305万吨是预测需求量，将分6年分步实施。'),ev(B,A,4,'在乙方满足甲方综合竞争力（综合竞争力特指：同时满足政策要求、商务条件、产品质量、材料性能指标及产品交付时间及数量等条件）要求前提下，双方有最低采购量约定。'),ev(B,A,4,'最终采购量及乙方'),ev(B,A,5,'的需求保障以双方后续签订的框架性、年度性的或者单笔采购合同为准。')],['最低采购量具体数值、条件实际是否满足UNKNOWN；存在附条件约定不等于305万吨全部强制采购。'],'multi_span_conditional_semantics')
add(B,4,'贵州新仁现有年产6万吨产线与6年305万吨预测需求分别是年度产能和多年需求，不能直接相比判已具备或绝无履约能力。静态均摊需求约50.8333万吨/年，约现有名义年产能8.4722倍，仅为口径示例；扩产和并购尚有不确定性。',{'existing_capacity_万吨每年':'6','forecast_demand_万吨':'305','horizon_years':6,'annualized_forecast_万吨每年':'50.833333','ratio_to_existing_capacity':'8.472222','actual_supply_capacity_sufficiency':None},[ev(B,A,3,'本次签约305万吨是预测需求量，将分6年分步实施。'),ev(B,A,3,'贵州新仁目前拥有年产6万吨磷酸铁锂产线。后续产能建设受项目审批、资金投入、施工进度、市场环境等多重因素影响，能否按时按量达成产能目标存在一定不确定性。')],['年度实际需求分布、产能利用率、未来扩产落地未知；均摊不是公司年度承诺，比例不是履约概率。'],'unit_aligned_illustrative_calculation',[{'operands':['305','6'],'operator':'divide','result':'50.833333','unit':'万吨/年','tolerance':'0.000001','assumption':'six-year arithmetic average, not forecast annual schedule'},{'operands':['50.833333333333333333','6'],'operator':'divide','result':'8.472222','unit':'倍','tolerance':'0.000001'}])
add(B,5,'2026年商务条件已确定，产品销售价格=碳酸锂成本+加工费；2027年及以后、5代以上产品商务条件另行约定。不能把当年公式外推为六年固定价格。',{'fixed_year':2026,'formula':'碳酸锂成本+加工费','future_years_pending':'2027及以后','products_pending':'5代以上（保留原文口径）'},[ev(B,A,5,'双方就2026年磷酸铁锂产品价格要素约定计价公式，产品销售价格=碳酸锂成本+加工费'),ev(B,A,5,'协议双方对2026年产品销售商务条件已确定，2027年及以后商务条件双方另行约定。5代以上产品的商务条件双方另行约定。')],['未来实际单价、未来商务条件及5代以上精确产品范围的另行定义未提供。'])
add(B,6,'仍有产能不足、原材料价格波动、订单不及预测、产品开发/量产进展风险；3/4代尚未规模化稳定量产、5代仍开发。因此不能推定预测销售必然转化收入。公司表示具备履约综合能力属于公司判断，不是外部验证保证。',{'risks':['产能不足','原料价格波动','订单量不及预测','产品开发量产不及预期'],'generation_3_4':'未规模化稳定量产','generation_5':'开发阶段','guaranteed_revenue':False},[ev(B,A,3,'1、产能不能满足需求的风险'),ev(B,A,3,'2、原材料价格波动的风险'),ev(B,A,3,'3、最后实际订单量不及预测需求量的风险'),ev(B,A,3,'4、产品开发及量产风险'),ev(B,A,4,'公司目前磷酸铁锂正极材料第三代及第四代产品尚未实现规模化稳定量产，第五代产品仍处于开发阶段。'),ev(B,A,2,'公司具备履行相关协议的综合能力')],['不能预测履约结果、利润或股价反应；不得将公司自查意见当监管已确认事实。'],'risk_attribution_and_non_entailment')
K='JCZ_202605';N='REPLY_CNSTOCK'
add(K,1,'公司于2026-05-18收到上证科创公函【2026】0187号问询。问询公告公开日依冻结披露记录；回复公告2026-05-26公开且落款同日。收到日与公开日分列，不推断同日。',{'inquiry_receipt':'2026-05-18','inquiry_listing_date':docs[K,I]['publication_date_from_listing'],'reply_publication_and_signature':'2026-05-26'},[ev(K,I,1,'于2026年5月18日收到上海证券交易所科创板公司管理部'),ev(K,N,None,'2026-05-26\n来源：上海证券报'),ev(K,N,None,'特此公告。\n北京金橙子科技股份有限公司董事会\n2026年5月26日',occurrence=0,subdocument='2026-030')],['公开时间精度仅到日；网页签章日期不自动等于首次披露时刻。'],metadata=[meta(K,I),meta(K,N)])
add(K,2,'拟收购主体为长春萨米特光电科技有限公司，收购55.00%股权，方案由发行股份及支付现金调整为全部现金；回复披露交易价17875.00万元。拟议交易不能表述为已交割，100%股权评估值不能当55%交易价。',{'target':'长春萨米特光电科技有限公司','equity_percent':'55.00','payment':'全部现金','cash_price_万元':'17875.00','transaction_status':'拟议，待上市公司股东会'},[ev(K,I,1,'公司拟调整发行股份及支付现金购买长春萨米特光电科技有限公司（以下简称“标的公司”）55%股权并募集配套资金的收购方案，改为全部以支付现金的方式收购。'),ev(K,N,None,'同意以17,875.00万元现金收购萨米特55.00%股权，本次交易尚需经上市公司股东会审议通过。',subdocument='2026-030')],['最终付款、交割、股东会后续结果UNKNOWN；不能将预测协同视为已实现。'])
add(K,3,'100%股权本次收益法评估值32525.46万元，前次34236.71万元，下降1711.25万元，下降比例约5.00%。回复将调整归因于基准日更新及最新数据、预测单价/盈利率等变化；这是评估师解释，不能据此独立确认估值公允。',{'valuation_scope_percent':'100','current_万元':'32525.46','previous_万元':'34236.71','decrease_万元':'1711.25','decrease_percent_rounded':'5.00','valuation_explanation_owner':'评估师回复'},[ev(K,I,1,'标的公司100%股权收益法评估值为32,525.46万元，较前次评估值下降1,711.25万元。'),ev(K,N,None,'综合上述差异分析，本次评估因基准日更新，结合最新经营数据、行业政策、实际盈利情况进行合理调整，收入略有上调、毛利率/净利率审慎下调，本次评估结论为32,525.46万元，前次评估结论为34,236.71万元，评估值下调1,711.25万元，下降比例为5.00%，调整依据较为充分。',subdocument='2026-030')],['网页部分明细表为图片占位，不能独立重建DCF或验证全部预测参数；不等同交易价。'],'decimal_calculation_and_attributed_explanation',[{'operands':['34236.71','32525.46'],'operator':'subtract','result':'1711.25','unit':'万元'},{'operands':['1711.25','34236.71','100'],'operator':'percent','result':'5.00','unit':'%','tolerance':'0.005','rounding':'2 decimal places'}])
add(K,4,'本次评估基准日2025-12-31，回复公告日期2026-05-26，是不同时间口径。前者是估值时点，后者是披露回复时点；不可相互替换。',{'valuation_date':'2025-12-31','reply_date':'2026-05-26'},[ev(K,I,1,'截至评估基准日2025年12月31日'),ev(K,N,None,'2026-05-26\n来源：上海证券报')],['前次评估基准日不由本题已定位文字确定；不得自行补日期。'])
add(K,5,'截至回复，标的公司股东会已审议通过，回复称上市公司董事会通过调整方案，但交易仍需上市公司股东会审议。不能写成收购已完成。关于军工前置审批及控制权变更后报告为公司对程序的说明，非本研究独立法律结论。',{'target_shareholders_approval':'披露已通过','listed_board_approval':'披露已通过，日期争议另列','listed_shareholders_approval':'尚需通过','completed_acquisition':None},[ev(K,N,None,'萨米特作为本次交易的标的公司，其控制权变更事项已经标的公司股东会审议通过。',subdocument='2026-030'),ev(K,N,None,'本次交易尚需经上市公司股东会审议通过。',subdocument='2026-030'),ev(K,N,None,'本次交易控制权变更完成后，标的公司将作为报告主体，在规定期限内向所属保密主管部门提交控制权变更情况报告',subdocument='2026-030')],['未取得交割证明；不把材料未证明完成写成未来永不完成，不推断所有审批都已获得。'])
add(K,6,'存在日期冲突：回复公告2026-030正文写2025-05-14召开第四届董事会第二十三次会议；同一保存网页另载2026-029自查报告写2026-05-14召开同届同次会议。保留两个来源身份和冲突，真实会议日期待权威更正/原会议文件核定，不能擅改成2026。',{'reply_030_date':'2025-05-14','separate_notice_029_date':'2026-05-14','meeting':'第四届董事会第二十三次会议','adjudicated_actual_date':None,'conflict':True},[ev(K,N,None,'上市公司作为收购方，已于2025年5月14日召开第四届董事会第二十三次会议',subdocument='2026-030'),ev(K,N,None,'2026年5月14日，公司召开第四届董事会第二十三次会议，审议通过了《关于调整购买资产方案的议案》',subdocument='2026-029'),ev(K,I,1,'2026年5月15日，公司披露了《关于调整购买资产方案的公告》')],['同网页不等于同公告；可识别冲突但不得自裁笔误。2026-029不计独立第三来源；若实验只允许2026-030，则只报告2025文字与时间线疑点，不能偷用029。'],'cross_notice_conflict_detection',limits=['HTML contains two distinct issuer notices; partition before execution.'])
for x in refs:
 for e in x['evidence']:
  d=docs[x['id'].rsplit('_T',1)[0],e['source_id']]
  e['source_role']=d['document_role']
  e['support_limit']='Direct source assertion, not independent adjudication; issuer forecasts/interpretations remain attributed'
 if x['id']=='RONBAY_202601_T4':
  # Original question asks unit/scope distinction, not a mandatory annual-average forecast.
  x['optional_illustrations']={k:x['required_answer_components'].pop(k) for k in ['annualized_forecast_万吨每年','ratio_to_existing_capacity']}
  x['limitations'].append('均摊及倍数是可选口径示例，不纳入必需事实分母；不用多余计算制造模型错误。')
 for c in x['calculations']:
  a=list(map(Decimal,c['operands']));op=c['operator'];v=sum(a) if op=='sum' else a[0]-a[1] if op=='subtract' else a[0]/a[1] if op=='divide' else a[0]/a[1]*a[2]
  assert abs(v-Decimal(c['result']))<=Decimal(c.get('tolerance','0')),(x['id'],v)
assert len(refs)==18
(O/'REFERENCE_ANSWERS.json').write_text(json.dumps({'status':'SILVER_SOURCE_REVIEW_NOT_GOLD','independent_reviews':0,'experimental_outputs_used':False,'items':refs},ensure_ascii=False,indent=2))
print('references',len(refs),'evidence_spans',sum(len(x['evidence']) for x in refs))
# The graph contracts below are prospective source-derived task definitions, not historical LLM plans.
citation_schema={'type':'object','additionalProperties':False,'required':['source_id','subdocument','page','start','end','quote','source_sha256','text_sha256'],'properties':{'source_id':{'type':'string'},'subdocument':{'type':['string','null']},'page':{'type':['integer','null']},'start':{'type':'integer','minimum':0},'end':{'type':'integer','minimum':0},'quote':{'type':'string'},'source_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'text_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}}}
claim_props={'claim_id':{'type':'string','minLength':1},'subject':{'type':'string'},'predicate':{'type':'string'},'value':{'type':['string','number','boolean','array','object','null']},'unit':{'type':['string','null']},'time_scope':{'type':['string','null']},'statement_kind':{'enum':['REGULATOR_FINDING','ISSUER_ASSERTION','CONTRACT_REPORTED_TERM','ESTIMATE','FORECAST','DERIVED','CONFLICT','UNKNOWN']},'status':{'enum':['ASSERTED','UNKNOWN','CONFLICT']},'evidence':{'type':'array','items':citation_schema},'parent_claim_ids':{'type':'array','items':{'type':'string'}},'unknown_reason':{'type':['string','null']}}
claim_schema={'type':'object','additionalProperties':False,'required':list(claim_props),'properties':claim_props}
claim_props['calculation']={'type':'object','required':['operator','operand_claim_ids','unit','rounding'],'properties':{'operator':{'enum':['sum','subtract','divide','percent']},'operand_claim_ids':{'type':'array','items':{'type':'string'},'minItems':1},'unit':{'type':'string'},'rounding':{'type':'string'}}}
output_schema={'type':'object','additionalProperties':False,'required':['node_id','task_id','evidence_manifest_sha256','input_fingerprint','parent_output_hashes','claims','complete'],'properties':{'node_id':{'type':'string'},'task_id':{'type':'string'},'evidence_manifest_sha256':{'type':'string'},'input_fingerprint':{'type':'string'},'parent_output_hashes':{'type':'object','additionalProperties':{'type':'string'}},'claims':{'type':'array','items':claim_schema},'complete':{'type':'boolean'}}}
common={'schema_version':'SOURCE_DAG_CONTRACT_1','input':{'required':['task_id','node_id','question','cutoff','evidence_manifest_sha256','allowed_source_ids','source_records','upstream_outputs','upstream_hashes'],'source_records':'Exact frozen text plus raw/page hashes; HTML page=null; known subdocuments are explicit','upstream_outputs':'Only declared parents with matching immutable hashes; no reference answers or experimental scores'},'output_schema':output_schema,'guards':['All source spans exact and hash-consistent; ambiguity remains failure, not first-match repair','Every parent_claim_id resolves to a declared parent; upstream fingerprints match','ASSERTED requires source evidence or validated derivation with source-grounded operands','UNKNOWN uses value=null and nonempty reason; CONFLICT retains conflicting sourced alternatives','No unsupported assertion can be committed as fact; explicit UNKNOWN may propagate as unknown','Never silently change source dates, normalize an unresolved conflict or turn forecasts into guarantees','Stable source/parent/contract versions required for cache reuse; invalidate only actually affected downstream results'],'validation_limit':'Schema and hashes validate provenance, NOT semantic truth; semantic support needs separately validated review.','terminal_scoring':'Frozen scorer unchanged; these drafts are Silver, not formal Gold. Formal Q remains unavailable until admissible references and relevance assessments exist.'}
(O/'NODE_CONTRACT.json').write_text(json.dumps(common,ensure_ascii=False,indent=2))
node_contract_sha=sha(O/'NODE_CONTRACT.json')
def node(i,parents,kind,role,sources,deliverables,rationale,outputs):
 return {'id':i,'parents':parents,'executor_kind':kind,'role':role,'allowed_sources':sources,'input_contract':{'common_contract_sha256':node_contract_sha,'consume_parent_ids':parents,'upstream_contract_required':True,'reference_answers_access':False},'output_contract':{'common_contract_sha256':node_contract_sha,'mandatory_deliverables':deliverables,'terminal_items_served':outputs},'edge_rationale':rationale,'llm_candidates':['qwen-plus-2025-12-01','deepseek-flash'] if kind=='LLM' else [],'model_contract_measurements':'UNKNOWN_CURRENT_TASK' if kind=='LLM' else 'NOT_APPLICABLE_DETERMINISTIC','failure_action':'BLOCK invalid assertions; preserve reason, cost and elapsed; allow evidenced minimal recovery only'}
graphs={}
graphs[J]=[
 node('PENALTY',[],'LLM','Regulatory finding extraction',[P],['主体及公司/个人处罚','两项行为各年收入及利润的有符号万元值','处罚文号、来源措辞，不补决定日期'],{},['T1','T2','T3','T6']),
 node('CORRECTION',[],'LLM','Issuer correction scope extraction',[C],['更正年份及不另更正年份','收到日期、落款、不同监管决定身份','2024事项作为发行人转述'],{},['T4','T5']),
 node('YEAR_SCOPE',['PENALTY','CORRECTION'],'LLM','Reconcile periods and authority',[P,C],['分别列出52号与69号转述的期间和报表范围','区分错报方向和更正方向，不把无重大影响等同无影响'],{'PENALTY':'提供监管52号事项及受影响年度','CORRECTION':'提供更正年度及69号转述'},['T3','T4']),
 node('ARITHMETIC',['PENALTY'],'DETERMINISTIC','Signed decimal sums',[P],['逐项同年度同单位相加','保存操作数claim_id、符号及单位；输入未知则结果UNKNOWN'],{'PENALTY':'必须消费从原文提取的两事项操作数，不能硬编码参考值'},['T6']),
 node('TIMELINE',['PENALTY','CORRECTION'],'LLM','Separate receipt/signature/publication',[P,C],['日期种类与来源身份分列','档案公开日与正文日期分级，未证实日期UNKNOWN'],{'PENALTY':'处罚文号/监管来源','CORRECTION':'收到、落款和档案公开记录'},['T5']),
 node('FINAL',['PENALTY','YEAR_SCOPE','ARITHMETIC','TIMELINE'],'LLM','Evidence-preserving final answer',[P,C],['完成六问且不越过限定范围','逐条结论保留来源或操作数链','相关性、UNKNOWN和冲突单独列示'],{'PENALTY':'终端罚款和单项行为原始事实','YEAR_SCOPE':'跨文档年度比较','ARITHMETIC':'合计及不可混用依据','TIMELINE':'日期口径'},['T1','T2','T3','T4','T5','T6'])]
graphs[B]=[
 node('INQUIRY',[],'LLM','Inquiry requirement and premise extraction',[I],['接收/公开日期','监管要求核实的问题与前提','监管提问不等同最终认定'],{},['T1','T2','T3','T4','T5','T6']),
 node('REPLY',[],'LLM','Attributed reply facts extraction',[A],['公司估算与协议转述分开','预测量、附条件最低采购、计价与未来条款','产能及代际量产状态、风险和日期'],{},['T1','T2','T3','T4','T5','T6']),
 node('OBLIGATIONS',['REPLY'],'LLM','Classify conditional commitments',[A],['金额估算与约定量分离','保留附条件最低采购且具体量UNKNOWN','未来商务条款待定；公司能力判断不作保证'],{'REPLY':'必须消费承诺条件、最终采购规则及计价记录'},['T2','T3','T5','T6']),
 node('CAPACITY',['REPLY'],'DETERMINISTIC','Unit-aware illustrative capacity comparison',[A],['区分多年需求与年产能','必须完成单位与期间比较；均摊/比例仅为可选示例，操作数和单位有效才计算','输出明确不是年度承诺或实际履约概率'],{'REPLY':'原始需求、年数、产能和不确定性来自同一冻结回复'},['T4']),
 node('CROSSCHECK',['INQUIRY','REPLY','OBLIGATIONS','CAPACITY'],'LLM','Inquiry-response coverage and limits',[I,A],['逐项问题对应回复、遗漏或UNKNOWN','保留估算/保证边界和四类风险','区分客观披露与公司解释'],{'INQUIRY':'需要回答的问询及日期','REPLY':'回复的来源事实与日期','OBLIGATIONS':'合同条件语义','CAPACITY':'一致单位的可核验计算'},['T1','T2','T3','T4','T5','T6']),
 node('FINAL',['CROSSCHECK'],'LLM','Six-question final deliverable',[I,A],['输出六项结论及逐项引用','未披露最低采购量不得补值','保留跨页证据链与截止时点'],{'CROSSCHECK':'已携带原始父claim及引用链的六问核对结果'},['T1','T2','T3','T4','T5','T6'])]
graphs[K]=[
 node('NOTICE_BOUNDARIES',[],'DETERMINISTIC','Partition archived HTML notices',[N],['按公告编号划定2026-030回复及2026-029自查报告区间','导航和图片表格占位不作正文事实','不把两公告当两独立发行人来源'],{},['T6']),
 node('INQUIRY',[],'LLM','Acquisition inquiry facts',[I],['问询收到日及方案变化','估值时点、比例、金额和问题范围'],{},['T1','T2','T3','T4']),
 node('REPLY',['NOTICE_BOUNDARIES'],'LLM','Reply facts with notice identity',[N],['拟收购主体/支付/比例','两次估值、价格和归属为评估师的解释','审批状态、两公告日期冲突，缺表UNKNOWN'],{'NOTICE_BOUNDARIES':'实际允许读取区间和公告身份；严禁跨公告无标记拼接'},['T1','T2','T3','T4','T5','T6']),
 node('VALUATION',['INQUIRY','REPLY'],'DETERMINISTIC','Comparable 100-percent equity values',[I,N],['同范围估值差及四舍五入降幅','不把100%评估值当55%成交价','冲突数值时拒绝选边计算'],{'INQUIRY':'评估范围、基准日及本次值','REPLY':'前次值及差额核对，保留公司/评估师解释'},['T3','T4']),
 node('APPROVAL',['REPLY'],'LLM','Separate approval from completion',[N],['标的股东会、上市公司董事会、上市公司股东会分别判断','预期协同不是已实现；军工程序只归属为公司说明'],{'REPLY':'带公告编号及证据的审批和条件句'},['T2','T5']),
 node('DATE_CONFLICT',['INQUIRY','REPLY'],'LLM','Date-type and conflict analysis',[I,N],['估值时点/收到日/披露日分列','2025与2026董事会日期原样呈现，实际日期UNKNOWN'],{'INQUIRY':'2026问询及方案披露背景','REPLY':'两个公告的会议日期和回复落款'},['T1','T4','T6']),
 node('FINAL',['REPLY','VALUATION','APPROVAL','DATE_CONFLICT'],'LLM','Scoped acquisition answer',[I,N],['六问完整、引用所属公告明确','不自行修复日期、不重建缺失表格','估值合理性仅报告评估师判断'],{'REPLY':'主体和方案原始事实','VALUATION':'同口径计算','APPROVAL':'未完成与待批状态','DATE_CONFLICT':'时间口径与争议'},['T1','T2','T3','T4','T5','T6'])]
def closure(nodes,seed):
 c=set(seed)
 for n in nodes:
  if set(n['parents'])&c:c.add(n['id'])
 return sorted(c)
# Exact HTML partition for this archived container; no downloads and no source mutation.
text=(R/docs[K,N]['text_file']).read_text();start=text.index('证券代码：688291 证券简称：金橙子 公告编号：2026-030');other=text.index('证券代码：688291 证券简称：金橙子 公告编号：2026-029');end=text.index('上一版：7：信息披露',other)
partition={'source_id':N,'source_sha256':docs[K,N]['sha256'],'text_sha256':sha(R/docs[K,N]['text_file']),'parts':[{'id':'2026-030','start':start,'end':other},{'id':'2026-029','start':other,'end':end}],'offset_unit':'unicode_codepoint','image_table_placeholders':text[start:other].count('■'),'table_values_missing':True,'independent_source_count':1}
(O/'NOTICE_PARTITION.json').write_text(json.dumps(partition,ensure_ascii=False,indent=2))
Dagresults=[]
for t in tasks:
 tid=t['task_id'];nodes=graphs[tid];seen=set();allitems=set()
 for n in nodes:
  assert set(n['parents'])<=seen;assert len(n['parents'])==len(set(n['parents']));seen.add(n['id']);allitems.update(n['output_contract']['terminal_items_served'])
 assert allitems=={f'T{i}' for i in range(1,7)}
 scopes=[{'source_id':d['source_id'],'file':str(R/d['file']),'sha256':d['sha256'],'publication_date_from_archive':d['publication_date_from_listing']} for d in t['source_scope']['documents']]
 spec={'task_id':tid,'origin':'MANUALLY_SOURCE_DERIVED_CONTRACT_DAG_NOT_LLM_GENERATED_OR_EXECUTED','cutoff':t['source_scope']['cutoff'],'original_broad_question':t['source_scope']['question'],'scoring_scope':'Only the six explicit source-grounded questions; not general sentiment or all material conclusions','public_questions':[{'id':x['id'],'question':x['question']} for x in oldrefs if x['id'] in t['reference_ids']],'reference_answers_accessible_to_scheduler':False,'evidence_manifest':scopes,'Z':'FIXED_FOR_NEXT_COMPARISON','nodes':nodes,'edges':[[p,n['id']] for n in nodes for p in n['parents']],'semantic_dependency_basis':'Each edge has explicit consumed deliverable and rationale in the destination node; not page-order rotation','cache_key_components':['task_id','node_id','node_contract_sha256','source_text_hashes','parent_output_hashes','model_version','prompt_hash'],'cache_rule':'Re-executing a node does not invalidate healthy independent branches. Descendants invalidated only if their consumed input/version changes; same output hash permits reuse.','natural_feedback':[
 {'trigger':'SOURCE_ID_OR_SPAN_MISMATCH','observable_without_gold':True,'action':'If owning extractor output invalid, retry that node within reserved budget; invalidate affected committed descendants only. Valid source records in other branches remain cached.'},
 {'trigger':'DERIVATION_OPERAND_OR_UNIT_MISMATCH','observable_without_gold':True,'action':'Check typed operands and provenance; no LLM rerun for a deterministic arithmetic formatting issue; repair failed source node only if independently evidenced.'},
 {'trigger':'SOURCE_CONFLICT','observable_without_gold':True,'action':'Preserve UNKNOWN/CONFLICT. If conflict is already present in source, no repeated model calls to force resolution.'},
 {'trigger':'TIMEOUT_OR_SLOTS_DELAY','observable_without_gold':True,'action':'Stop or legally reassign future nodes within remainder; unresolved billed/cancelled calls remain UNKNOWN. No automatic API retries.'},
 {'trigger':'SEMANTIC_UNSUPPORTED','observable_without_gold':'ONLY_WITH_VALIDATED_GUARD','action':'Current semantic guard not calibrated for these contracts; cannot use private reference to trigger repair.'}],
 'recovery_analysis':{'observed_natural_failures':0,'actual_R_candidates':None,'guaranteed_R_count':None,'minimal_legal_recovery':'For a known invalid node, that node plus actually affected already-committed descendant outputs; pending descendants are first executions, not extra retries','structural_dependency_closures':{n['id']:closure(nodes,[n['id']]) for n in nodes},'closure_note':'These are possible dependency invalidation sets, not observed faults or multiple competing R actions at the same state','identifiability':'With one required legal R, R-only may coincide with Static recovery and Joint with pi-only. Different failure locations do not prove two R choices at one state. No larger R added without evidence.'},
 'pi_analysis':{'candidate_models':['qwen-plus-2025-12-01','deepseek-flash'],'identity_basis':'Archived real calibration model labels only; current provider version not revalidated','contract_compatible_current_measurements':0,'Q':'UNKNOWN','C':'UNKNOWN_CURRENT_CONTRACT','L':'UNKNOWN_CURRENT_CONTRACT','reliability':'UNKNOWN_CURRENT_CONTRACT','dynamic_opportunity':'At source-branch completion, remaining LLM merge/synthesis nodes may be reassigned; no observed ranking reversal or benefit yet','independent_confirmatory_status':'NOT_CERTIFIED; current source/reference/DAG design is recorded development exposure'},
 'optimizations_not_applied':{'merge':'May combine interpretation/finalization only if all typed outputs, source lineage, explicit UNKNOWN and six deliverables retained. No measured saving asserted.','split':'Split only on separately sourced responsibilities or independently checkable calculations; not arbitrary page slicing.','remove_edges':'Only if destination contract demonstrably no longer consumes parent; cannot remove compulsory source comparison.','Z_testing':'NOT_TESTED'},'admission':{'dag_acyclic_contract_complete':True,'execution_validated':False,'formal_Gold':False,'formal_Q_calculable':False,'five_arm_identifiable':False}}
 (O/f'DAG_{tid}.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2));Dagresults.append(spec)
# Historical measurements stay attached to their original cell/task and are never inserted as new task performance.
profile_path=Path('/root/research_outputs/DYNAMIC_PI_FIXED_CALIBRATION_RUN/ANALYSIS.json');protected[str(profile_path)]=sha(profile_path)
measure=json.loads(profile_path.read_text())['rows']
profile=[{'historical_node':r['node'],'model':r['model'],'samples':r['samples'],'Q':r['Q'],'K':r['original_verdict']['K'],'provenance_contract_E':r['original_verdict']['E'],'observed_wall_s':r['wall_s'],'input_tokens':r['input_tokens'],'output_tokens':r['output_tokens'],'public_price_estimate':r['public_price_estimate'],'settlement':r['actual_cash_settlement'],'source_request_sha256':r['request_sha256'],'source_response_sha256':r['response_sha256'],'transfer_to_current_nodes':'NOT_ALLOWED_AS_MEASURED_PROFILE','reliability_probability':None} for r in measure]
(O/'CAPABILITY_EVIDENCE.json').write_text(json.dumps({'source':str(profile_path),'sha256':sha(profile_path),'measurements':profile,'current_task_matches':0,'limitations':['One measurement per historical cell; no statistical reliability lower bound','K/E provenance passing is not semantic correctness','Historical failed request time not a successful-node prediction','No current prices queried; no new calls; anonymous adaptive DS version risk remains','No demonstrated cross-task model capability crossover']},ensure_ascii=False,indent=2))
assert all(sha(Path(p))==h for p,h in protected.items())
(O/'MANIFEST.json').write_text(json.dumps({'inputs':protected,'historical_unchanged':True,'new_model_calls':0,'new_fees':0,'reference_questions':18,'source_grounded_drafts':len(refs),'independent_Gold':0,'DAGs':[{'task':s['task_id'],'nodes':len(s['nodes']),'edges':len(s['edges']),'LLM_nodes':sum(n['executor_kind']=='LLM' for n in s['nodes'])} for s in Dagresults],'prior_tasks_now_development_exposed':True,'code_changes_to_ZCode':False,'frozen_scorer_changed':False},ensure_ascii=False,indent=2))
print('DAGs',[(s['task_id'],len(s['nodes']),len(s['edges'])) for s in Dagresults])
feas=[]
for s in Dagresults:
 tid=s['task_id'];status={'task':tid,'reference_drafts_complete':'6/6','Gold_completeness':'0/6 independently adjudicated; all Silver drafts','terminal_Q':'NOT_FORMALLY_SCORABLE; PENDING/UNKNOWN not imputed','DAG':{'nodes':len(s['nodes']),'edges':len(s['edges']),'acyclic':True,'contracts_defined':True,'historical_planner_or_execution_proof':False},'heterogeneity':{'available_historical_model_identities':2,'matched_current_node_measurements':0,'quality_crossover':'UNKNOWN','Q_C_L_reliability_guarantee':'UNKNOWN'},'R_space':'At least a conditional minimal repair can be specified for a proven invalid node; no observed same-state multiple R candidates','pi_space':'Two candidate model identities on LLM nodes, but current-contract capability ranking and post-feedback action divergence unmeasured','five_arm':'HOLD_NOT_IDENTIFIABLE_YET','real_run_now':False}
 if tid==J:status.update(priority=2,main_opportunity='Separated authority/time/period reconciliation; arithmetic is deterministic shared tool, not LLM scheduling contribution',reference_gap='Independent review + publication-date provenance; 69号 original absent, only issuer quotation',not_repairable_by_more_model_calls='Missing source decision cannot be reconstructed; mathematical sum alone does not justify R/pi')
 elif tid==B:status.update(priority=1,main_opportunity='Conditional obligation vs forecast vs realized revenue, multi-span and cross-document consistency',reference_gap='Independent semantic review of minimum purchase conditions + task relevance; full original agreement absent, scope limited to disclosed terms',not_repairable_by_more_model_calls='Undisclosed minimum purchase quantity and future prices remain UNKNOWN')
 else:status.update(priority=3,main_opportunity='Source-boundary and date-conflict handling; valuation calculation shared deterministic tool',reference_gap='Independent review; missing image tables preclude full valuation review; actual board date unresolved',not_repairable_by_more_model_calls='Issuer date conflict and absent tables cannot be resolved by choosing whichever model agrees with preferred date')
 feas.append(status)
(O/'FEASIBILITY_MATRIX.json').write_text(json.dumps({'rows':feas,'priority_experiment':{'task':B,'arms':['Static','pi-only'],'Z':'fixed','R':'same mandatory minimal repair; no optional R expansion','hypothesis':'Under naturally observed runtime/contract feedback, reassignment of remaining conditional-reasoning and final synthesis nodes improves correctly sourced terminal answers or reduces observed cost/makespan without quality degradation','primary_quality':'complete frozen Q only after reference and relevance assessment binding; no partial-Silver score substituted','eligibility':'References reviewed; two real models calibrated on independent contract-matched tasks; legal runtime action and frozen cost/deadline limits','no_feedback_rule':'Retain no-trigger/no-switch units; do not inject faults or select test events for positive effects','R_and_Joint':'Do not claim R or interaction gains unless same-state multiple justified legal R plans are actually demonstrated','evidence_level':'PROPOSED_EXPERIMENT_NOT_RUN'},'new_calls':0},ensure_ascii=False,indent=2))
report=['# 三个真实任务：参考答案、合同 DAG 与科学可行性','',
'2026-11-01（Asia/Shanghai）。本轮完成的是源证据约束的任务基准草案，不是模型实验；零新增模型调用、零付费。原任务/参考文件、冻结评分器、ZCode和历史结果未修改。',
'', '## 1. 实质交付与证据等级','',
'18个原有问题全部写出非空参考答案，并分解为必要答案字段、原文证据、计算规则和UNKNOWN边界；共有48条精确证据跨度，逐项核对原文子串和SHA-256。全部仍是 **SOURCE_CONSTRAINED_SILVER_DRAFT**：由助手直接阅读冻结原文编制、算术由Decimal核对，没有独立人工裁决，未使用任何待评模型输出，不标为Gold。',
'证据可信度分层：①监管原文直接陈述；②发行人公告陈述/对监管的转述；③公司或评估师预测、条件性意见；④显式操作数推导；⑤仅档案元数据支持的公开日期；⑥冲突或缺失项UNKNOWN。第①级是来源权威性，不等于本次编制者取得独立裁决资格。PDF引用页码为文件页码；HTML page=null，不伪造PDF页码。',
'现有三任务已在本轮参与参考和DAG设计，须记录开发曝光。没有历史模型输出证明其独立确认集身份；若后续使用，只能按透明的开发性/机制探索解释。',
'', '## 2. 18项参考答案（全文及原文跨度见机读文件）','',
'|任务/题|参考答案摘要|证据位置与验证|UNKNOWN/限制|','|---|---|---|---|']
for x in refs:
 loc=[]
 for e in x['evidence']:
  z=e['source_id']+(' p'+str(e['page']) if e['page'] is not None else ' HTML')+(' /'+e['subdocument'] if e.get('subdocument') else '')
  if z not in loc:loc.append(z)
 linestr=f"|{x['id']}|{x['answer']}|{'; '.join(loc)}；{x['verification']['method']}|{'；'.join(x['UNKNOWN_boundaries'])}|"
 report.append(linestr)
report += ['',
'**六问限定范围与完整Q的区别**：这些答案用于冻结的六项业务交付，不覆盖整份公告的所有结论，更不覆盖一般舆情、股价或投资收益。后续任务提问应明确限定六问；不能用其评分宣称宽泛原问题的完整任务质量。问题与材料的相关性已逐项给出依据，但这不等于未来模型回答已获得冻结评分器要求的有效相关性审阅。',
'', '## 3. 改变可行性判断的源材料发现','',
'1. **佳缘期间不能混用。** 52号处罚涉及2019—2022；公告更正还包括2024，来自四川局69号转述。该原件不在包内。2019—2022金额是监管认定的错报方向，不能直接与更正报表的调整金额同号相加。2020两项收入−2015.60+1327.95=−687.65万元，利润−1613.84+44.24=−1569.60万元。监管页公开日、公告公开日与收到日来自不同证据层。',
'2. **容百不能把条件承诺抹掉。** 305万吨是预测需求；但回复p4明确说满足综合竞争力前提下有最低采购量约定。具体最低量未披露，应UNKNOWN。1200亿元为公司估算，2027年以后商务条件未定。该任务存在真实的跨页、跨文档条件逻辑，适合区分事实抽取与语义核验能力。公司自称具备履约能力不能当作外部已验证保证。',
'3. **金橙子保存容器不是单一公告。** 网页正文同时包含2026-030问询回复和2026-029自查报告。030写2025-05-14，029写2026-05-14，同届同次董事会日期冲突。两份公告都可从冻结容器定位，但不算两个独立机构来源。已输出精确公告分区，允许T6显式使用两者；禁止无身份拼接。',
f'4. **金橙子表格缺失是真实材料限制。** 030正文含{partition["image_table_placeholders"]}处“■”表格占位。叙述保留两次100%股权估值及差额，足以复核本轮六问中相关数值；不能由此认为全部估值表、关联关系/预测参数均完整。不得重建不存在的表格数值。',
'', '## 4. 真实合同 DAG：不是示意图','',
'三个DAG由任务语义推导；没有声称由LLM自动生成，也没有伪称已经远端执行。节点输入输出合同含公共JSON Schema、必需交付字段、父节点依赖、允许来源、证据版本与缓存指纹。节点不能读取参考答案；引用来源可用于查证，不能将Gold值用于恢复触发。',
'', '|任务|节点及真实并行|依赖与分工|可合并/拆分边界|','|---|---|---|---|',
'|佳缘：6节点9边|PENALTY与CORRECTION独立；之后年度核对、算术、时间核对可按依赖并行|FINAL消费罚款/原始事实、年度核对、算术和日期结果；必须区分两个监管来源|时间核对可与最终汇总合并但必须保留日期来源；算术用确定性工具，不能人为变成LLM收益|',
'|容百：6节点7边|INQUIRY与REPLY独立；OBLIGATIONS与CAPACITY消费REPLY后并行|CROSSCHECK同时消费问询、回复、条件判断、同单位计算，FINAL消费完整核对记录|义务解释与核对可合并但会降低故障定位粒度；不能去掉问询依赖后声称逐项答复完整|',
'|金橙子：7节点10边|公告边界解析与问询抽取可并行；估值计算、审批解释、日期冲突分析按上游就绪并行|REPLY必须消费公告身份边界；FINAL汇合估值、审批与冲突，并保留原始主体信息|可合并审批和最终解释但不丢公告身份；不按任意页拆分同一条件句|',
'',
'合同层规则：已确定来源的原子事实、推导操作数和UNKNOWN都带稳定claim_id与父claim引用；UNKNOWN可以合法传播，但不得作为已知操作数。无效断言不得提交为健康缓存。版本或实际父输出改变才失效相关后继；其他分支复用。依赖闭包只是候选失效范围，未执行的后继是首次执行，不应记为重复执行收益。',
'', '## 5. 模型能力与动作空间：不虚构迁移','',
'已读取8条原有真实校准记录：Qwen-Plus-2025-12-01与DeepSeek-Flash各在timeline、relations、verify、report上一次。Qwen原合同通过1/4，DeepSeek通过4/4；这是该旧输入下的合同观测，**不是模型可靠性概率、语义Q或当前任务画像**。两模型report均通过但实际墙钟分别约12.054s、4.252s；其他失败耗时不作成功完成预测。所有8条Q=null、实际结算=null。逐行Token、历史公开价估费、时延和请求/响应哈希保存在CAPABILITY_EVIDENCE.json。',
'当前每个LLM节点有两个真实存在的历史模型身份作为待校准候选，但没有与新节点合同一致的测量。因此Q/C/L/可靠性全部保留UNKNOWN，不把旧时延直接灌入新优化器，也不宣称能力交叉已经存在。确定性算术和公告分区节点不需要异构模型分配。',
'',
'|反馈|合法动作|不能做什么|','|---|---|---|',
'|某抽取输出来源ID/跨度无效|只修复已确定不合法的源节点，若输出改变再失效实际依赖它的已提交后继|不能重跑健康独立分支制造节省对照|',
'|下游漏引用，但父记录完整有效|仅修复该下游；源抽取缓存继续有效|不能据下游错误直接归罪上游模型|',
'|操作数/单位缺失|回到被证明缺失的源记录；若只是确定性计算问题，不追加模型重试|不根据参考答案替模型补数|',
'|金橙子源文日期冲突或容百未披露最低量|保留CONFLICT/UNKNOWN|不循环重执行直到某模型给出偏好的确定答案|',
'|实际超时、队列占用或预算余量变化|在可用资源内调整未执行LLM节点；计入已发费用与不确定结算|不伪造延迟、失效或模型排名改变|',
'',
'**R的识别性限制**：不同节点可能有不同闭包，不等于同一反馈状态存在多个合理R方案。本轮没有自然运行状态，actual_R_candidates=null；对于明确一个坏节点且其他缓存健康的情形，通常只有一个必要最小R。此时R-only可能与强Static恢复一致，Joint可能与π-only一致。不得人为增大恢复范围或禁用Static缓存来产生差异。π有候选身份差异，但动作和收益差异尚未实测。',
'', '## 6. 最终任务可行性矩阵','',
'|任务|Gold完整性|终端Q可计算性|DAG合法性|模型异构性|R动作空间|π动作空间|五臂实验|','|---|---|---|---|---|---|---|',
'|佳缘|6/6参考草案；独立Gold 0/6|正式Q不可计算|6节点9边；合同/拓扑已定义，未实跑|两模型候选；匹配画像0|条件性局部修复可定义；同状态多R未证|5个LLM节点可选，实际排序未知|HOLD；更适合期间核对/确定性算术强基线|',
'|容百|6/6参考草案；独立Gold 0/6|正式Q不可计算|6节点7边；合同/拓扑已定义，未实跑|两模型候选；匹配画像0|局部失效闭包明确；同状态多R未证|5个LLM节点，语义核验/汇总有待校准空间|HOLD；优先静态与π-only，而非强凑五臂|',
'|金橙子|6/6参考草案，冲突显式UNKNOWN；独立Gold 0/6|正式Q不可计算；缺表限制范围|7节点10边，先分公告身份；未实跑|两模型候选；匹配画像0|源冲突不可由重复模型执行解决|5个LLM节点，模型切换不能补原始材料|HOLD；适合冲突保留能力诊断|',
'',
'本轮无需再补18题的空白答案；仍需独立复核其事实解释，尤其容百附条件承诺、佳缘公开日期元数据、金橙子日期冲突。三任务均不能立即进入满足完整Q要求的真实收益实验。原文材料可信、参考草案齐全、DAG可定义，是三个不同条件，不合并为GO。',
'', '## 7. 最优先的一个科学实验','',
'优先 **容百合同问询/回复任务的Static vs π-only同状态配对探索**：固定本轮DAG与同一必要R，比较相同自然反馈后保留原分配或调整剩余条件核验/汇总节点。主假设是：合同匹配校准揭示的模型差异能改善“估算、附条件承诺、已实现事实”的终端区分，或在质量不降时减少实际成本/Makespan。完整Q必须在原评分器所需参考及相关性评估可用后计算。',
'为什么有机会：任务确有互补的监管问题与公司回复、跨页条件和多个不确定性，而不是单个金额抄写；局部错误修复可保留无关分支。但是当前没有证据证明哪个模型更好，不能把“任务有区分度”当“异构必有收益”。价格/速度潜在改善也必须用真实同输入测量验证。',
'为什么先不做五臂：同状态多个有依据R尚未出现；先用两臂隔离π，避免Joint与π-only同动作却被解释为联合增益。若后续自然反馈显示多个合理R且代价不同，再按事前新协议加入R-only/Joint，不能中途追加。若没有反馈或模型不切换，保留无动作差异结果；不人为注入异常。',
'容百仅为一个已参与设计的开发任务，重复运行不构成独立事件；只能给出机制探索结果，不能支持跨事件总体优越性或可靠性下界。佳缘和金橙子保留为无收益/边界场景，不能为获得正结果从数据集中删掉。',
'', '## 8. 工件','',
'- REFERENCE_ANSWERS.json：18份非空答案、48处证据跨度、计算与UNKNOWN；私有参考，禁止模型输入或策略读取。',
'- DAG_*.json + NODE_CONTRACT.json：实际节点输入输出合同、边的理由、缓存和恢复规则；公共任务只含问题/来源，无参考值。',
'- NOTICE_PARTITION.json：金橙子两个公告在同一冻结文本内的边界，不新建假来源。',
'- CAPABILITY_EVIDENCE.json：原测量逐条来源与禁止迁移边界。',
'- FEASIBILITY_MATRIX.json + MANIFEST.json：机读裁决及源文件不变校验。',
'完成后停止：没有模型调用，没有修改评分规则，没有创建后续付费批次。']
(O/'TASK_FEASIBILITY.md').write_text('\n'.join(report)+'\n')
print('matrix',len(feas),'formal_Gold',0,'new_calls',0)
