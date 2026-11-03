"""Phase RQ2 offline feasibility (zero calls, SYNTHETIC).

Uses the frozen R4/R5 cost/latency constants read-only and extends them with an
explicitly labelled restructured-DAG model. Every number here is a mechanism
calculation, not a model experiment.

Configurations:
  A  Static            all-DS, 7 nodes
  B  Serial-m+v        m,v = GLM (R5's +0.0781 point), 7 nodes
  C1 Parallel-m+v/code m,v_post = GLM, v_pre = deterministic code pre-check (no model call)
  C2 Parallel-m+v/ds   m,v_post = GLM, v_pre = DS model call (extra call)
  D  m-only + reserve  m = GLM, recovery budget kept in reserve
  E  C1 + recovery     parallel split with whatever headroom remains

Latency model (frozen BASE_LAT/LAT; v split with m-independent share p and
coordination overhead):
  L_t   = lat_e + lat_t
  L_m   = max(lat_e0, lat_e1) + lat_m
  L_vpre= max(L_t, lat_e1) + p*lat_v
  L_vpost = max(L_m, L_vpre) + (1-p)*lat_v + overhead
  L_r   = L_m + lat_r
  L_p   = max(L_r, L_vpost) + lat_p
Cost is TOTAL price units (sum over executions); the 20% cap is
1.20 * Static total (7 DS nodes = 4.2 units) = 5.04 units.
"""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
from rq1_v1_8_2_r4_p0_calibration import BASE_LAT, LAT, PRICE

DS, GLM = 1, 0
STATIC_UNITS = float(PRICE[DS].sum() if hasattr(PRICE[DS], 'sum') else 7 * PRICE[DS])
STATIC_UNITS = 7 * float(PRICE[DS])            # 4.2
CAP20 = 1.20 * STATIC_UNITS                    # 5.04
CAP10 = 1.10 * STATIC_UNITS                    # 4.62


def lat(model, node):
    return float(BASE_LAT[node] * LAT[model])


def makespan_serial(assign7):
    l = [lat(assign7[i], i) for i in range(7)]
    L2 = l[0] + l[2]
    L3 = max(l[0], l[1]) + l[3]
    L4 = L3 + l[4]
    L5 = max(L3, L2) + l[5]
    return max(L4, L5) + l[6]


def makespan_parallel(assign7, vpre_model, vpost_model, p, overhead):
    le0, le1 = lat(assign7[0], 0), lat(assign7[1], 1)
    lt, lm, lr, lp = lat(assign7[2], 2), lat(assign7[3], 3), lat(assign7[4], 4), lat(assign7[6], 6)
    lv_glm = lat(GLM, 5)
    lv_ds = lat(DS, 5)
    L_t = le0 + lt
    L_m = max(le0, le1) + lm
    # v's work is split p / (1-p). The pre-share runs on its own executor
    # (deterministic code is charged the GLM latency share as a conservative bound;
    #  a DS pre-check uses the DS latency share). The post-share is always GLM.
    lvpre = p * (lv_ds if vpre_model == DS else lv_glm)
    lvpost = (1 - p) * lv_glm + overhead
    L_vpre = max(L_t, le1) + lvpre
    L_vpost = max(L_m, L_vpre) + lvpost
    L_r = L_m + lr
    return max(L_r, L_vpost) + lp


def units(assign, extra_calls):
    total = sum(float(PRICE[m]) for m in assign)
    for m in extra_calls:
        total += float(PRICE[m])
    return total


def main():
    base7 = [DS] * 7
    m_only = [DS, DS, DS, GLM, DS, DS, DS]
    m_v = [DS, DS, DS, GLM, DS, GLM, DS]

    out = {}
    out['A_static'] = dict(makespan=makespan_serial(base7), units=units(base7, []),
                           dq=0.0)
    out['B_serial_mv'] = dict(makespan=makespan_serial(m_v), units=units(m_v, []),
                              dq=0.0781)
    for p in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        for overhead in (0.0, 0.1, 0.2):
            key = f'C1_parallel_code_p{p}_o{overhead}'
            out[key] = dict(makespan=makespan_parallel(m_v, None, GLM, p, overhead),
                            units=units(m_v, []),  # deterministic pre-check adds no model call
                            dq=0.0781, note='v_pre = code (no model call)')
            key = f'C2_parallel_ds_p{p}_o{overhead}'
            out[key] = dict(makespan=makespan_parallel(m_v, DS, GLM, p, overhead),
                            units=units(m_v, [DS]),  # extra DS call
                            dq=0.0781, note='v_pre = DS model call (+1 call)')
    out['D_m_only_reserve'] = dict(makespan=makespan_serial(m_only),
                                   units=units(m_only, []), dq=0.0479)
    # recovery affordability (all configurations)
    for name, r in out.items():
        if 'makespan' not in r:
            continue
        r['headroom_units'] = round(CAP20 - r['units'], 3)
        r['headroom_pct_of_static'] = round((CAP20 - r['units']) / STATIC_UNITS * 100, 2)
        r['retry_ds_affordable'] = r['headroom_units'] >= float(PRICE[DS])
        r['retry_glm_affordable'] = r['headroom_units'] >= float(PRICE[GLM])
        r['strict10_ok'] = r['makespan'] <= makespan_serial(base7) * 1.10
    # quality retention needed to stay above MVS (1/13)
    MVS = 1 / 13
    v_inc = 0.0781 - 0.0479
    out['quality_threshold'] = dict(
        MVS=MVS, m_only=0.0479, serial_mv=0.0781, v_increment=v_inc,
        max_v_quality_loss_to_stay_above_MVS=round(1 - (MVS - 0.0479) / v_inc, 4),
        note='parallel split must retain >=96% of v\'s incremental quality to keep Q above MVS')
    json.dump(dict(batch='RQ2_OFFLINE_FEASIBILITY', model_calls=0,
                   constants=dict(BASE_LAT=BASE_LAT.tolist(), LAT=LAT.tolist(),
                                  PRICE=PRICE.tolist(), static_units=STATIC_UNITS,
                                  cap20=CAP20, cap10=CAP10),
                   configs=out),
              open('/root/research_outputs/static_pi/stage_d/RQ2_OFFLINE_FEASIBILITY.json', 'w'),
              ensure_ascii=False, indent=1)

    print(f"{'config':30s} {'makespan':>9s} {'Δms%':>7s} {'units':>7s} {'Δcost%':>8s} "
          f"{'headroom':>9s} {'strict10':>9s}")
    base_ms = out['A_static']['makespan']
    for k in ('A_static', 'B_serial_mv', 'C1_parallel_code_p0.3_o0.1',
              'C1_parallel_code_p0.5_o0.1', 'C1_parallel_code_p0.6_o0.2',
              'C2_parallel_ds_p0.5_o0.1', 'D_m_only_reserve'):
        r = out[k]
        print(f"{k:30s} {r['makespan']:9.3f} {(r['makespan']/base_ms-1)*100:6.1f}% "
              f"{r['units']:7.2f} {(r['units']/STATIC_UNITS-1)*100:7.1f}% "
              f"{r['headroom_units']:9.3f} {str(r['strict10_ok']):>9s}")
    print('\nquality threshold:', json.dumps(out['quality_threshold'], ensure_ascii=False))


if __name__ == '__main__':
    main()
