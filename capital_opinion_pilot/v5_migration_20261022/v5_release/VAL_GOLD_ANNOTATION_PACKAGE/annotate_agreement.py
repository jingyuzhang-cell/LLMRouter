"""Dual-annotation agreement: fact-level match, Cohen's kappa, disagreement list.
Usage: python3 annotate_agreement.py annA.json annB.json"""
import json,sys,re
def norm(s): return re.sub(r'[\s,，。;；:：、"\'''"（）()\[\]【】]+','',str(s))
def key(f): return norm(f['question'])[:30]
def kappa(a,b):
    aK={key(f) for f in a}; bK={key(f) for f in b}
    both=len(aK&bK); nA,nB=len(aK),len(bK); N=max(1,max(nA,nB))
    po=both/N; pe=(nA/N)*(nB/N)
    return (po-pe)/max(1e-9,1-pe), {'A_only':sorted(aK-bK),'B_only':sorted(bK-aK),'both':both}
def tset(rs): return {(norm(r['subject']),norm(r['relation']),norm(r['object'])) for r in rs}
if __name__=='__main__':
    A=json.load(open(sys.argv[1])); B=json.load(open(sys.argv[2]))
    k,dis=kappa(A.get('facts',[]),B.get('facts',[]))
    ta,tb=tset(A.get('relations',[])),tset(B.get('relations',[]))
    print('facts kappa=%.3f A=%d B=%d both=%d'%(k,len(A.get('facts',[])),len(B.get('facts',[])),dis['both']))
    print('A_only:',dis['A_only'][:8]); print('B_only:',dis['B_only'][:8])
    print('relations Jaccard=%.3f'%(len(ta&tb)/max(1,len(ta|tb))))
    print('>> 分歧项进入 adjudication.json（第三标注员裁决并记录理由）')
