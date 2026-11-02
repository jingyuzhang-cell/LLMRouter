#!/usr/bin/env python3
"""真实模式时钟单位测试（操作者 2026-11-02 裁定要求）。

验证四项：
  C1 --real → scale=1.0（1 真实秒 ≈ 1 虚拟秒）
  C2 180s 截止期在真实模式下不会被解释为 0.18 真实秒
  C3 mock 模式保持 scale=1000（dry-run 行为不变）
  C4 修复前的缺陷可复现（scale=1000 时 0.18 真实秒即达 180 虚拟秒），证明测试有区分力
"""
import time

import pytest

from stage_d_executor import VirtualClock, make_clock

DEADLINE = 180.0


def _advance(clock, real_s):
    """等待 real_s 真实秒，返回时钟推进的虚拟秒。"""
    t0 = clock.now()
    time.sleep(real_s)
    return clock.now() - t0


def test_c1_real_clock_is_one_to_one():
    clock = make_clock(real=True, mock_scale=1000)
    assert clock.scale == 1.0
    dv = _advance(clock, 0.20)
    assert 0.15 <= dv <= 0.45, f"1 真实秒应≈1 虚拟秒，实测 {dv:.3f}"


def test_c2_deadline_not_compressed_in_real_mode():
    clock = make_clock(real=True, mock_scale=1000)
    dv = _advance(clock, 0.20)
    assert dv < DEADLINE, "0.2 真实秒不得被判为超过 180s 截止期"
    assert DV_ratio(clock) < 1.0


def DV_ratio(clock):
    return clock.now() / DEADLINE


def test_c3_mock_clock_unchanged():
    clock = make_clock(real=False, mock_scale=1000)
    assert clock.scale == 1000.0
    dv = _advance(clock, 0.20)
    assert 150 <= dv <= 400, f"mock 应放大 1000×，实测 {dv:.1f}"


def test_c4_bug_is_reproducible_with_mock_scale():
    """修复前：--real 也用 scale=1000 → 0.18 真实秒即达 180 虚拟秒。"""
    buggy = VirtualClock(1000.0)
    dv = _advance(buggy, 0.20)
    assert dv >= DEADLINE, "该用例应证明 scale=1000 会把 0.2s 真实压缩成 ≥180 虚拟秒"


def test_c5_mock_scale_from_config_respected():
    for s in (1.0, 100.0, 1000.0):
        assert make_clock(False, s).scale == s
    assert make_clock(True, 1000.0).scale == 1.0
    assert make_clock(True, 1.0).scale == 1.0
