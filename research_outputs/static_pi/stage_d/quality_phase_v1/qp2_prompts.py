"""QP2 round-2 prompts (zero calls). Arms differ by exactly one factor:

  A Baseline : round-1 Baseline prompts (reuses round-1 cache keys)
  B ChainFix : E1 evidence-constrained extraction + verified-table relay to SINK
  C = B + amount module (e-node amount contract; SINK value parity)
  D = C + strict terminal (only verified facts answerable; else abstain)
"""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import qp1_prompts as P1
import qp2_amount as AM
import qp2_chain as CH

MAXTOK = P1.MAXTOK
EVIDENCE_REQ = P1.EVIDENCE_REQ


def arm_factor(arm):
    """Single-factor ladder for the separation audit."""
    return dict(A=dict(chain=False, amount=False, strict=False),
                B=dict(chain=True, amount=False, strict=False),
                C=dict(chain=True, amount=True, strict=False),
                D=dict(chain=True, amount=True, strict=True))[arm]


def e_system(arm):
    return P1.E_SYS


def e_user(contract, doc_ids, arm):
    u = P1.e_user(contract, doc_ids, 'E1')
    if arm_factor(arm)['amount']:
        u += '\n\n' + AM.AMOUNT_PROMPT_BLOCK
    return u


def t_m_r_prompts(arm):
    """t/m/r unchanged across B/C/D (models see identical mid-pipeline prompts)."""
    return P1.M_SYS, P1.M_SYS, P1.R_SYS


def sink_system(arm):
    return P1.P_SYS


def sink_user(contract, merged, relations, verified, arm, strict_note=''):
    u = P1.p_user(contract, merged, relations, verified, 'E3' if arm_factor(arm)['strict'] else 'E1')
    table = CH.build_sink_instruction(verified) if arm_factor(arm)['chain'] else ''
    extra = ''
    if arm_factor(arm)['amount']:
        extra = ('\n金额规则：value 可与证据表一致或做单位换算，但数值不得改变；'
                 '优先引用证据表的 raw 形式。')
    if arm_factor(arm)['strict']:
        extra += ('\n严格终端规则：answers 只能来自证据表；证据表没有的槽位一律写 abstentions，'
                  '并给出"证据表中无该槽位证据"的理由。')
    return u + '\n\n' + table + extra + strict_note
