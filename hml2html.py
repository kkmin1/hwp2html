#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hml2html.py - 한글(HML) → HTML 변환기
지원: 본문 텍스트, 제목(개요), 수식(KaTeX), 표, 각주, 이미지

사용법:
    python3 hml2html.py input.hml output.html
    python3 hml2html.py input.hml output.html
"""

import xml.etree.ElementTree as ET
import sys, re, os, base64, html, json, shutil
from collections import defaultdict

from hml_table_renderer import render_table as render_shared_table

RM_SENTINEL = '\uE000RM\uE000'
ALIGN_MAP = {
    'Left': 'left',
    'Right': 'right',
    'Center': 'center',
    'Justify': 'justify',
    'Distribute': 'justify',
}


# ──────────────────────────────────────────────
# 1. 한글 수식 스크립트 → LaTeX 변환기
# ──────────────────────────────────────────────

def hwp_script_to_latex(script: str, force_bold_math: bool = False) -> str:
    """한글 수식 편집기 스크립트를 LaTeX로 변환"""
    s = script.strip()

    def shrink_uppercase_subscripts(text: str) -> str:
        def repl(m):
            content = m.group(1).strip()
            if '\\scriptscriptstyle' in content:
                return m.group(0)
            if re.search(r'[A-Z]', content):
                return r'_{\scriptscriptstyle {' + content + '}}'
            return m.group(0)
        return re.sub(r'_\{([^{}]+)\}', repl, text)

    def style_lq_matrix_symbols(text: str) -> str:
        # LQ/LQR 문맥에서 단일 대문자 행렬 기호만 굵게 처리
        lq_context = (
            re.search(r'\^\{(?:T|\\top)\}', text) is not None and
            re.search(r'(?<![A-Za-z])(Q|R|P|A|B|F|G|H|K)(?![A-Za-z])', text) is not None
            or re.search(r'(?<![\\A-Za-z])[QRPABFGHK](?=\s*[xyu](?:\b|_|\\|\^|\(|\{)?)', text) is not None
        )
        if not lq_context:
            return text

        def repl_standalone(m):
            sym = m.group(1)
            return rf'\mathbf{{{sym}}}'

        # 단독 기호: P, Q, R 등
        text = re.sub(r'(?<![\\A-Za-z])([QRPABFGHK])(?![A-Za-z])', repl_standalone, text)
        # 벡터/상태변수 앞에 붙은 행렬: Qx, Ru, Ax_t, Bu_t
        text = re.sub(
            r'(?<![\\A-Za-z])([QRPABFGHK])(?=\s*[xyu](?:\b|_|\\|\^|\(|\{)?)',
            repl_standalone,
            text
        )
        return text

    def bold_math_identifiers(text: str) -> str:
        out = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == '\\':
                j = i + 1
                while j < len(text) and text[j].isalpha():
                    j += 1
                command = text[i:j]
                out.append(command)
                if command in (r'\begin', r'\end') and j < len(text) and text[j] == '{':
                    depth = 1
                    k = j + 1
                    while k < len(text) and depth:
                        if text[k] == '{':
                            depth += 1
                        elif text[k] == '}':
                            depth -= 1
                        k += 1
                    out.append(text[j:k])
                    i = k
                    continue
                i = j
                continue
            if ch.isalpha():
                out.append(rf'\mathbf{{{ch}}}')
            else:
                out.append(ch)
            i += 1
        return ''.join(out)

    # ── 0단계: 구조 키워드 먼저 처리 (긴 패턴 우선) ──────────────────

    # 한글 수식 스크립트의 스타일 접두어(rm/bf/it) 처리
    s = re.sub(r'(?<![A-Za-z\\])rm\s+', RM_SENTINEL, s)
    s = re.sub(r'(?<![A-Za-z\\])rm(?=[A-Za-z({])', RM_SENTINEL, s)
    s = re.sub(r'(?<![A-Za-z\\])(bf|it)\s+', '', s)
    s = re.sub(r'(?<![A-Za-z\\])(bf|it)(?=[A-Za-z({])', '', s)

    # lna → \ln a
    s = re.sub(r'(?<![a-zA-Z\\])ln(?=[A-Za-z])', r'\\ln ', s)

    # underline{X} / underline X → \underline{X}
    s = re.sub(r'(?<![a-zA-Z\\])underline\{([^{}]+)\}', r'\\underline{\1}', s)
    s = re.sub(r'(?<![a-zA-Z\\])underline\s+([A-Za-z0-9]+)', r'\\underline{\1}', s)

    # Partial(대소문자 혼용) → \partial 먼저 처리
    s = re.sub(r'(?<![a-zA-Z\\])Partial(?![a-zA-Z])', r'\\partial', s)

    # cosh/sinh/tanh → \cosh/\sinh/\tanh (cos/sin/tan 보다 반드시 먼저)
    # 뒤에 알파벳이 붙어도 치환 (예: coshx → \cosh x)
    s = re.sub(r'(?<![a-zA-Z\\])cosh(?=[^a-zA-Z]|[a-zA-Z])', r'\\cosh ', s)
    s = re.sub(r'(?<![a-zA-Z\\])sinh(?=[^a-zA-Z]|[a-zA-Z])', r'\\sinh ', s)
    s = re.sub(r'(?<![a-zA-Z\\])tanh(?=[^a-zA-Z]|[a-zA-Z])', r'\\tanh ', s)
    # arccos/arcsin/arctan (cos/sin/tan 보다 먼저)
    s = re.sub(r'(?<![a-zA-Z\\])arccos(?![a-zA-Z])', r'\\arccos', s)
    s = re.sub(r'(?<![a-zA-Z\\])arcsin(?![a-zA-Z])', r'\\arcsin', s)
    s = re.sub(r'(?<![a-zA-Z\\])arctan(?![a-zA-Z])', r'\\arctan', s)

    # {A} over {B} → \frac{A}{B}  재귀 파서 (임의 깊이 중첩 처리)
    def convert_over(text):
        """문자열에서 {A} over {B} 패턴을 \frac{A}{B}로 재귀 변환"""
        result = []
        i = 0
        while i < len(text):
            if text[i] == '{':
                # 첫 번째 중괄호 그룹 추출
                depth, j = 1, i + 1
                while j < len(text) and depth:
                    if text[j] == '{': depth += 1
                    elif text[j] == '}': depth -= 1
                    j += 1
                group1 = text[i:j]  # {A}
                inner1 = group1[1:-1]
                # 뒤에 over가 있는지 확인
                rest = text[j:]
                m = re.match(r'\s*over\s*', rest)
                if m:
                    k = j + len(m.group(0))
                    if k < len(text) and text[k] == '{':
                        depth2, l = 1, k + 1
                        while l < len(text) and depth2:
                            if text[l] == '{': depth2 += 1
                            elif text[l] == '}': depth2 -= 1
                            l += 1
                        inner2 = text[k+1:l-1]
                        result.append(f'\\frac{{{convert_over(inner1)}}}{{{convert_over(inner2)}}}')
                        i = l
                        continue
                result.append('{' + convert_over(inner1) + '}')
                i = j
            else:
                result.append(text[i])
                i += 1
        return ''.join(result)

    s = convert_over(s)
    frac_pattern = re.compile(
        r'\{((?:[^{}]|\{[^{}]*\})+)\}\s*over\s*\{((?:[^{}]|\{[^{}]*\})+)\}'
    )

    # bar{X} → \overline{X}
    s = re.sub(r'(?<![a-zA-Z\\])bar\{([^{}]+)\}', r'\\overline{\1}', s)
    s = re.sub(r'(?<![a-zA-Z\\])bar\s+([A-Za-z0-9_\\{]+)', r'\\overline{\1}', s)

    # hat{X} → \hat{X}
    s = re.sub(r'(?<![a-zA-Z\\])hat\{([^{}]+)\}', r'\\hat{\1}', s)

    # tilde{X} → \tilde{X}
    s = re.sub(r'(?<![a-zA-Z\\])tilde\{([^{}]+)\}', r'\\tilde{\1}', s)

    # vec{X} → \vec{X}
    s = re.sub(r'(?<![a-zA-Z\\])vec\{([^{}]+)\}', r'\\vec{\1}', s)

    # dot{X} → \dot{X}
    s = re.sub(r'(?<![a-zA-Z\\])dot\{([^{}]+)\}', r'\\dot{\1}', s)

    # bigg | → \bigg|
    s = re.sub(r'bigg\s*\|', r'\\bigg|', s)
    s = re.sub(r'(?<![a-zA-Z\\])bigg\s*', r'\\bigg ', s)

    # pmatrix{...#...} → \begin{pmatrix}...\end{pmatrix}
    def convert_matrix(m):
        inner = m.group(1)
        # 열 구분자 & 변환, 행 구분자 \\ 변환
        inner = re.sub(r'\s*&\s*', ' & ', inner)
        inner = re.sub(r'\s*#\s*', r' \\\\ ', inner)
        return r'\begin{pmatrix}' + inner + r'\end{pmatrix}'
    s = re.sub(r'(?<![a-zA-Z])pmatrix\{((?:[^{}]|\{[^{}]*\})*)\}', convert_matrix, s)

    # matrix{...} → \begin{matrix}...
    def convert_plain_matrix(m):
        inner = m.group(1)
        inner = re.sub(r'\s*&\s*', ' & ', inner)
        inner = re.sub(r'\s*#\s*', r' \\\\ ', inner)
        return r'\begin{matrix}' + inner + r'\end{matrix}'
    s = re.sub(r'(?<![a-zA-Z])matrix\{((?:[^{}]|\{[^{}]*\})*)\}', convert_plain_matrix, s)

    # pile{...#...} → 열벡터/세로쌓기용 matrix
    def convert_pile(m):
        inner = m.group(1)
        inner = re.sub(r'\s*&\s*', ' & ', inner)
        inner = re.sub(r'\s*#\s*', r' \\\\ ', inner)
        return r'\begin{matrix}' + inner + r'\end{matrix}'
    s = re.sub(r'(?<![a-zA-Z])pile\{((?:[^{}]|\{[^{}]*\})*)\}', convert_pile, s)

    # eqalign{...} → 그냥 내용만 (aligned 환경으로 처리)
    s = re.sub(r'(?<![a-zA-Z])eqalign\{([^{}]*)\}', r'\1', s)

    # TRIANGLE → \triangle
    s = re.sub(r'(?<![a-zA-Z])TRIANGLE(?![a-zA-Z])', r'\\triangle ', s)

    # CONG → \cong
    s = re.sub(r'(?<![a-zA-Z])CONG(?![a-zA-Z])', r'\\cong', s)

    # INF → \infty
    s = re.sub(r'(?<![a-zA-Z])INF(?![a-zA-Z])', r'\\infty', s)

    # -> → \to  (텍스트 화살표)
    s = re.sub(r'\s*->\s*', r' \\to ', s)

    # RARROW → \rightarrow
    s = re.sub(r'(?<![a-zA-Z])RARROW(?![a-zA-Z])', r'\\rightarrow', s)

    # LLFLOOR, RRFLOOR 등 기타
    s = re.sub(r'(?<![a-zA-Z])FLOOR(?![a-zA-Z])', r'\\lfloor', s)
    s = re.sub(r'(?<![a-zA-Z])CEIL(?![a-zA-Z])',  r'\\lceil',  s)

    # VDOTS/DDOTS → \vdots/\ddots (CDOTS보다 먼저, 대문자)
    s = re.sub(r'(?<![a-zA-Z])VDOTS(?![a-zA-Z])', r'\\vdots', s)
    s = re.sub(r'(?<![a-zA-Z])DDOTS(?![a-zA-Z])', r'\\ddots', s)

    # 유니코드 기호 → LaTeX 명령
    s = s.replace('±', r'\pm ')
    s = s.replace('∓', r'\mp ')
    s = s.replace('×', r'\times ')
    s = s.replace('÷', r'\div ')
    s = s.replace('≠', r'\neq ')
    s = s.replace('≤', r'\leq ')
    s = s.replace('≥', r'\geq ')
    s = s.replace('∞', r'\infty ')
    s = s.replace('∂', r'\partial ')
    s = s.replace('∇', r'\nabla ')
    s = s.replace('∑', r'\sum ')
    s = s.replace('∏', r'\prod ')
    s = s.replace('∫', r'\int ')
    s = s.replace('√', r'\sqrt ')
    s = s.replace('→', r'\to ')
    s = s.replace('←', r'\leftarrow ')
    s = s.replace('⇒', r'\Rightarrow ')
    s = s.replace('⇔', r'\Leftrightarrow ')
    s = s.replace('∈', r'\in ')
    s = s.replace('∉', r'\notin ')
    s = s.replace('⊂', r'\subset ')
    s = s.replace('∪', r'\cup ')
    s = s.replace('∩', r'\cap ')
    s = s.replace('∴', r'\therefore ')
    s = s.replace('∵', r'\because ')
    s = s.replace('≈', r'\approx ')
    s = s.replace('≡', r'\equiv ')

    # ── 1단계: 키워드 치환 ────────────────────────────────────────────
    # (순서 중요: 긴 것, 대문자 먼저)
    replacements = [
        # 대문자 연산자 (먼저)
        ('GEQ',      r'\geq'),
        ('LEQ',      r'\leq'),
        ('NEQ',      r'\neq'),
        ('CDOTS',    r'\cdots'),
        ('LDOTS',    r'\ldots'),
        ('TIMES',    r'\times'),
        ('DIV',      r'\div'),
        ('APPROX',   r'\approx'),
        ('EQUIV',    r'\equiv'),
        ('PROPTO',   r'\propto'),
        ('NOTIN',    r'\notin'),
        ('SUBSET',   r'\subset'),
        ('SUPSET',   r'\supset'),
        ('INFTY',    r'\infty'),
        ('NABLA',    r'\nabla'),
        ('PARTIAL',  r'\partial'),
        ('IN',       r'\in'),
        ('CUP',      r'\cup'),
        ('CAP',      r'\cap'),
        # 대문자 그리스 (먼저)
        ('Gamma',    r'\Gamma'),
        ('Delta',    r'\Delta'),
        ('Theta',    r'\Theta'),
        ('Lambda',   r'\Lambda'),
        ('Xi',       r'\Xi'),
        ('Pi',       r'\Pi'),
        ('Sigma',    r'\Sigma'),
        ('Phi',      r'\Phi'),
        ('Psi',      r'\Psi'),
        ('Omega',    r'\Omega'),
        # 소문자 그리스
        ('alpha',    r'\alpha'),
        ('beta',     r'\beta'),
        ('gamma',    r'\gamma'),
        ('delta',    r'\delta'),
        ('epsilon',  r'\epsilon'),
        ('zeta',     r'\zeta'),
        ('eta',      r'\eta'),
        ('theta',    r'\theta'),
        ('iota',     r'\iota'),
        ('kappa',    r'\kappa'),
        ('lambda',   r'\lambda'),
        ('omega',    r'\omega'),
        ('upsilon',  r'\upsilon'),
        ('sigma',    r'\sigma'),
        ('phi',      r'\phi'),
        ('chi',      r'\chi'),
        ('psi',      r'\psi'),
        ('tau',      r'\tau'),
        ('rho',      r'\rho'),
        ('xi',       r'\xi'),
        ('nu',       r'\nu'),
        ('mu',       r'\mu'),
        ('pi',       r'\pi'),
        # 함수 (긴 것 먼저 - 반드시 짧은 것보다 먼저!)
        ('sqrt',     r'\sqrt'),
        ('oint',     r'\oint'),
        ('prod',     r'\prod'),
        ('arctan',   r'\arctan'),
        ('arcsin',   r'\arcsin'),
        ('arccos',   r'\arccos'),
        ('cosh',     r'\cosh'),
        ('sinh',     r'\sinh'),
        ('tanh',     r'\tanh'),
        ('int',      r'\int'),
        ('sum',      r'\sum\limits'),
        ('lim',      r'\lim\limits'),
        ('log',      r'\log'),
        ('exp',      r'\exp'),
        ('max',      r'\max'),
        ('min',      r'\min'),
        ('cos',      r'\cos'),
        ('sin',      r'\sin'),
        ('tan',      r'\tan'),
        ('ln',       r'\ln'),
        # prime → '
        ('prime',    r"'"),
        # 괄호
        ('LEFT',     r'\left'),
        ('RIGHT',    r'\right'),
        ('left',     r'\left'),
        ('right',    r'\right'),
        # 스타일 지시어 제거
    ]

    for hwp_kw, latex_kw in replacements:
        escaped_repl = latex_kw.replace('\\', '\\\\')
        s = re.sub(r'(?<![a-zA-Z\\])' + re.escape(hwp_kw) + r'(?![a-zA-Z])',
                   escaped_repl, s)

    # ── 2단계: 공백 정리 ──────────────────────────────────────────────
    # 백틱 공백 → 실제 공백 (단, 수식 내부에서는 \, 로 처리)
    s = re.sub(r'`{3,}', r'\\;', s)   # 3개 이상 백틱 → 넓은 공백
    s = re.sub(r'`{1,2}', r'\\,', s)  # 1~2개 백틱 → 좁은 공백

    # ── 3단계: 줄바꿈 (#) → \\ ───────────────────────────────────────
    s = re.sub(r'\s*#\s*(?:\\n)?\s*', r' \\\\ ', s)

    # ── 4단계: \left \right 공백 제거 ────────────────────────────────
    s = re.sub(r'\\left\s+\(', r'\\left(', s)
    s = re.sub(r'\\right\s+\)', r'\\right)', s)
    s = re.sub(r'\\left\s+\[', r'\\left[', s)
    s = re.sub(r'\\right\s+\]', r'\\right]', s)
    s = re.sub(r'\\left\s+\.',  r'\\left.',  s)
    s = re.sub(r'\\right\s+\.', r'\\right.', s)
    s = re.sub(r'\\left\s+\{',  r'\\left\{', s)
    s = re.sub(r'\\right\s+\}', r'\\right\}', s)

    # ── 5단계: 기타 정리 ──────────────────────────────────────────────
    # 키워드 치환 후 남은 over 패턴 재처리 (\partial 등이 들어간 경우)
    for _ in range(5):
        new_s = frac_pattern.sub(r'\\frac{\1}{\2}', s)
        if new_s == s:
            break
        s = new_s
    s = re.sub(
        r'(\\partial\s+[A-Za-z])\s+over\s+(\\partial\s+[A-Za-z])',
        r'\\frac{\1}{\2}',
        s,
    )

    # prime(') 뒤에 ^{n} 이 오는 경우 수정
    # KaTeX에서 y' ^{2} 는 오류 → y^{'2} 가 올바른 형태
    # 이중 prime 먼저 처리 (긴 패턴 우선)
    s = re.sub(r"([a-zA-Z\}])\s*' '\s*\^\{([^}]+)\}", r"\1^{''\2}", s)
    s = re.sub(r"([a-zA-Z\}])\s*''\s*\^\{([^}]+)\}", r"\1^{''\2}", s)
    # 단일 prime
    s = re.sub(r"([a-zA-Z\}])\s*'\s*\^\{([^}]+)\}", r"\1^{'\2}", s)
    s = re.sub(r'\\int\s*_\{([a-zA-Z]+)\}', lambda m: r'\int_{\text{' + m.group(1) + '}}', s)

    # 빈 적분 구간 정리: \int _{} ^{} {} → \int (KaTeX 오류 방지)
    s = re.sub(r'\\int\s*_\{\}\s*\^\{\}\s*\{\}', r'\\int', s)
    s = re.sub(r'\\int\s*_\{\}\s*\^\{\}', r'\\int', s)
    # ^{} 빈 위첨자 제거 (KaTeX에서 오류)
    s = re.sub(r'\^\{\s*\}', '', s)
    # 단독 {} 제거 (내용 없는 그룹)
    s = re.sub(r'(?<![\\{])\{\s*\}(?!\s*[_^])', '', s)

    # 함수 뒤에 바로 알파벳/숫자/( 가 붙으면 공백 삽입
    # 주의: \cosh 안의 \cos 가 걸리지 않도록 긴 패턴 먼저
    s = re.sub(
        r'(\\cosh|\\sinh|\\tanh|\\arctan|\\arcsin|\\arccos'
        r'|\\ln|\\log|\\lim(?!its)|\\exp|\\max|\\min|\\partial'
        r'|\\sin(?!h)|\\cos(?!h)|\\tan(?!h))(?=[a-zA-Z0-9(])',
        r'\1 ', s)

    # 첨자(_  ^) 앞의 공백 명령 제거
    # \theta \, _{B} → \theta_{B}  (공백 명령이 첨자를 분리하면 KaTeX 오류)
    s = re.sub(r'(\\[a-zA-Z]+|\}|[a-zA-Z0-9])\s*\\[,;:!]\s*([_^])', r'\1\2', s)
    # prime(') 뒤의 공백 명령 + 첨자: y ' \, ^{2} → y^{'2}
    s = re.sub(r"([a-zA-Z\}])\s*'\s*\\[,;:!]\s*\^\{([^}]+)\}", r"\1^{'\2}", s)
    # 일반 공백만 있는 경우도 정리: \theta  _{B} → \theta_{B}
    s = re.sub(r'(\\[a-zA-Z]+)\s+([_^]\{)', r'\1\2', s)
    # 일반 변수/기호 뒤의 위첨자·아래첨자도 붙여줌: x ^{T} → x^{T}
    s = re.sub(r'([A-Za-z0-9\}])\s+([_^]\{)', r'\1\2', s)

    # lim/sum 아래 첨자가 inline에서도 아래로 붙도록 강제
    s = re.sub(r'\\(lim|sum)(?!\\limits)\b', r'\\\1\\limits', s)

    # 전치행렬 표기: ^{T} → ^{\top}
    s = re.sub(r'\^\{T\}', r'^{\\top}', s)
    s = re.sub(r'\^T(?![a-zA-Z])', r'^{\\top}', s)

    # 대문자 subscript는 더 작게 조판
    s = shrink_uppercase_subscripts(s)

    # 이중 백슬래시 줄바꿈 앞뒤 공백 정리
    s = re.sub(r'\s*\\\\\s*', r' \\\\ ', s)
    # 연속 공백 정리
    s = re.sub(r'  +', ' ', s).strip()

    # LQ 문제의 행렬기호는 굵게 조판
    s = style_lq_matrix_symbols(s)

    if RM_SENTINEL in s:
        parts = s.split(RM_SENTINEL)
        s = parts[0] + ''.join(bold_math_identifiers(part) for part in parts[1:])
    elif force_bold_math:
        s = bold_math_identifiers(s)

    return s


def plain_text_math_to_latex(text: str) -> str:
    """EQUATION이 아닌 일반 텍스트 수식(주로 LQ 섹션)을 LaTeX로 보정"""
    s = text.strip()

    s = s.replace('×', r'\times ')
    s = re.sub(r'\bmin\b', r'\\min', s)
    s = re.sub(r'\bmax\b', r'\\max', s)
    s = re.sub(r'\bint\b', r'\\int', s)
    s = re.sub(r'\bsum\b', r'\\sum\\limits', s)

    # HML 본문에서는 xT 뿐 아니라 x T, x T (t)처럼 잘게 분리된 전치 표기가 많다.
    s = re.sub(
        r'([A-Za-z0-9\)\]\}])\s*T(?=\s*(?:\(|[A-Za-z{]|$|[+\-*/,=\]\}]))',
        r'\1^{\\top}',
        s,
    )

    def bold_matrix(m):
        return rf'\mathbf{{{m.group(1)}}}'

    s = re.sub(r'(?<![\\A-Za-z{])([QRPABFGHKM])(?=\s*[xyu](?:\s*\(|_|\b|$))', bold_matrix, s)
    s = re.sub(r'(?<![\\A-Za-z{])([QRPABFGHKM])(?=\s*\()', bold_matrix, s)
    s = re.sub(r'(?<![\\A-Za-z{])([QRPABFGHKM])(?![A-Za-z])', bold_matrix, s)
    s = re.sub(r'([A-Za-z0-9\)])\s+([_^]\{)', r'\1\2', s)
    s = re.sub(r'\s{2,}', ' ', s)
    return s


# ──────────────────────────────────────────────
# 2. 도형/그래프 → SVG 변환기
# ──────────────────────────────────────────────

HWP_UNIT = 100.0   # HWP 좌표 단위 (1/100mm) → px 변환 비율 (조정 가능)
SVG_SCALE = 0.035  # 적절한 크기로 축소

def hwp_to_px(val):
    return float(val) * SVG_SCALE

def color_from_int(color_int):
    """HWP 색상 정수 → CSS hex"""
    try:
        c = int(color_int)
        if c == 16777215:
            return 'none'  # 흰색 = 투명 처리
        r = c & 0xFF
        g = (c >> 8) & 0xFF
        b = (c >> 16) & 0xFF
        return f'#{r:02x}{g:02x}{b:02x}'
    except:
        return '#000000'

def container_to_svg(container_elem, eq_script_map):
    """CONTAINER 요소 → SVG 문자열"""
    import math

    # ── 헬퍼 함수 ──────────────────────────────────────────────────────
    def px(val):
        return float(val) * SVG_SCALE

    def get_sc(elem):
        """직계 DRAWINGOBJECT 아래의 SHAPECOMPONENT (GroupLevel=1)"""
        do = elem.find('DRAWINGOBJECT')
        if do is None:
            return None
        return do.find('SHAPECOMPONENT')

    def get_lineshape(elem):
        do = elem.find('DRAWINGOBJECT')
        ls = do.find('LINESHAPE') if do is not None else None
        if ls is None:
            return '#000000', 1.5, 'none', 'none'
        color = color_from_int(ls.get('Color', '0'))
        if int(ls.get('Alpha', '0')) == 255:
            color = 'none'
        width = max(0.5, float(ls.get('Width', '141')) * SVG_SCALE * 0.4)
        tail  = ls.get('TailStyle', 'Normal')
        head  = ls.get('HeadStyle', 'Normal')
        me    = 'url(#arr)' if head == 'Arrow' else 'none'
        ms    = 'url(#arr)' if tail == 'Arrow' else 'none'
        return color, width, ms, me

    def get_fill(elem):
        do = elem.find('DRAWINGOBJECT')
        wb = do.find('WINDOWBRUSH') if do is not None else None
        if wb is None:
            return 'none'
        if int(wb.get('Alpha', '0')) == 0:
            return 'none'
        return color_from_int(wb.get('FaceColor', '16777215'))

    def get_label(elem):
        """RECTANGLE/DRAWTEXT 안의 텍스트 또는 수식"""
        labels = []
        for sc2 in elem.iter('SCRIPT'):
            if sc2.text:
                labels.append(('eq', hwp_script_to_latex(sc2.text)))
        if not labels:
            # CHAR들을 하나의 문자열로 합침 (각각 별개 text 태그 방지)
            combined = ''.join(c.text for c in elem.iter('CHAR')
                               if c.text and c.text.strip())
            if combined:
                labels.append(('text', combined))
        return labels

    # ── 1단계: 각 도형의 SVG 요소 생성 ───────────────────────────────
    shapes = []   # (svg_string, x_min, y_min, x_max, y_max)

    for child in container_elem:
        tag = child.tag
        if tag in ('SHAPEOBJECT', 'SHAPECOMPONENT'):
            continue

        sc = get_sc(child)
        if sc is None:
            continue

        xpos = px(sc.get('XPos', '0'))
        ypos = px(sc.get('YPos', '0'))
        cw   = px(sc.get('CurWidth',  sc.get('OriWidth',  '100')))
        ch   = px(sc.get('CurHeight', sc.get('OriHeight', '100')))
        stroke, sw, ms, me = get_lineshape(child)
        fill = get_fill(child)
        me_a = f'marker-end="{me}"'   if me != 'none' else ''
        ms_a = f'marker-start="{ms}"' if ms != 'none' else ''

        svg = ''
        bx1, by1, bx2, by2 = xpos, ypos, xpos+cw, ypos+ch  # bounding box

        if tag == 'LINE':
            ex_raw = float(child.get('EndX', '0'))
            ey_raw = float(child.get('EndY', '0'))
            rev    = child.get('IsReverseHV', 'false') == 'true'
            # EndX/EndY=0이면 CurWidth/CurHeight 방향으로, 아니면 HWP단위 오프셋
            x2 = xpos + (cw if ex_raw == 0 else ex_raw * SVG_SCALE)
            y2 = ypos + (ch if ey_raw == 0 else ey_raw * SVG_SCALE)
            if rev:
                xpos, ypos, x2, y2 = x2, y2, xpos, ypos
            bx1, by1 = min(xpos,x2), min(ypos,y2)
            bx2, by2 = max(xpos,x2), max(ypos,y2)
            # 선 스타일 (점선/파선)
            do_elem = child.find('DRAWINGOBJECT')
            ls_elem = do_elem.find('LINESHAPE') if do_elem is not None else None
            style   = ls_elem.get('Style','Solid') if ls_elem is not None else 'Solid'
            dash    = 'stroke-dasharray="4,4"' if style == 'Dot' else \
                      'stroke-dasharray="8,4"' if style == 'Dash' else ''
            svg = (f'  <line x1="{xpos:.1f}" y1="{ypos:.1f}" '
                   f'x2="{x2:.1f}" y2="{y2:.1f}" '
                   f'stroke="{stroke}" stroke-width="{sw:.2f}" '
                   f'{dash} {me_a} {ms_a}/>')

        elif tag == 'CONNECTLINE':
            # ControlPoint: 0~100 퍼센트 기반 좌표
            cps = child.findall('CONTROLPOINT')
            if len(cps) >= 2:
                x1 = xpos + cw * float(cps[0].get('X', '0')) / 100
                y1 = ypos + ch * float(cps[0].get('Y', '0')) / 100
                x2 = xpos + cw * float(cps[1].get('X', '0')) / 100
                y2 = ypos + ch * float(cps[1].get('Y', '0')) / 100
                bx1, by1 = min(x1,x2), min(y1,y2)
                bx2, by2 = max(x1,x2), max(y1,y2)
                import math as _math
                dist = _math.sqrt((x2-x1)**2 + (y2-y1)**2)
                if dist < 8 and (ms != 'none' or me != 'none'):
                    # 선이 너무 짧아 marker가 잘림 → 화살표 polygon 직접 그리기
                    sz = 7
                    parts_arr = []
                    for (ax, ay, is_tail) in (
                        [(x1, y1, True)]  if ms != 'none' else []
                    ) + (
                        [(x2, y2, False)] if me != 'none' else []
                    ):
                        dx = (x1-x2) if is_tail else (x2-x1)
                        dy = (y1-y2) if is_tail else (y2-y1)
                        d  = _math.sqrt(dx*dx+dy*dy) or 1
                        ux, uy = dx/d, dy/d
                        vx, vy = -uy*sz*0.45, ux*sz*0.45
                        tip = (ax + ux*sz, ay + uy*sz)
                        w1  = (ax + vx,    ay + vy)
                        w2  = (ax - vx,    ay - vy)
                        pts = f"{tip[0]:.1f},{tip[1]:.1f} {w1[0]:.1f},{w1[1]:.1f} {w2[0]:.1f},{w2[1]:.1f}"
                        parts_arr.append(f'  <polygon points="{pts}" fill="{stroke}"/>')
                        bx1 = min(bx1, tip[0], w1[0], w2[0])
                        by1 = min(by1, tip[1], w1[1], w2[1])
                        bx2 = max(bx2, tip[0], w1[0], w2[0])
                        by2 = max(by2, tip[1], w1[1], w2[1])
                    svg = '\n'.join(parts_arr) if parts_arr else ''
                else:
                    svg = (f'  <line x1="{x1:.1f}" y1="{y1:.1f}" '
                           f'x2="{x2:.1f}" y2="{y2:.1f}" '
                           f'stroke="{stroke}" stroke-width="{sw:.2f}" {me_a} {ms_a}/>')

        elif tag == 'ELLIPSE':
            # CurWidth/CurHeight로 rx, ry 계산
            rx = cw / 2
            ry = ch / 2
            cx = xpos + rx
            cy = ypos + ry
            # fill이 없으면 검은 점으로 표시
            ell_fill = fill if fill != 'none' else '#000000'
            svg = (f'  <ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
                   f'rx="{rx:.1f}" ry="{ry:.1f}" '
                   f'fill="{ell_fill}" stroke="{stroke}" stroke-width="{sw:.2f}"/>')

        elif tag == 'RECTANGLE':
            labels = get_label(child)
            cx = xpos + cw / 2
            cy = ypos + ch / 2
            rect_stroke = stroke if stroke != 'none' else 'none'
            rect_fill   = fill   if fill   != 'none' else 'none'
            parts = [f'  <rect x="{xpos:.1f}" y="{ypos:.1f}" '
                     f'width="{cw:.1f}" height="{ch:.1f}" '
                     f'fill="{rect_fill}" stroke="{rect_stroke}" stroke-width="{sw:.2f}"/>']
            for ltype, lval in labels:
                fs = max(9, min(14, ch * 0.5))
                if ltype == 'text':
                    # 여러 글자를 하나의 text 태그로 합침 (중복 방지)
                    safe = html.escape(lval)
                    parts.append(f'  <text x="{cx:.1f}" y="{cy:.1f}" '
                                  f'text-anchor="middle" dominant-baseline="middle" '
                                  f'font-size="{fs:.0f}" fill="#222">{safe}</text>')
                else:  # eq
                    safe = html.escape(lval, quote=False)
                    fw = max(cw, 40)
                    fh = max(ch, 20)
                    parts.append(f'  <foreignObject x="{xpos:.1f}" y="{ypos:.1f}" '
                                  f'width="{fw:.1f}" height="{fh:.1f}">'
                                  f'<div xmlns="http://www.w3.org/1999/xhtml" '
                                  f'style="font-size:{fs:.0f}px;text-align:center;'
                                  f'display:flex;align-items:center;justify-content:center;'
                                  f'height:100%;">'
                                  f'<span class="math">{safe}</span>'
                                  f'</div></foreignObject>')
            svg = '\n'.join(parts)

        elif tag == 'POLYGON':
            points = child.findall('POINT')
            if not points:
                continue
            xs = [xpos + px(p.get('X','0')) for p in points]
            ys = [ypos + px(p.get('Y','0')) for p in points]
            bx1, by1 = min(xs), min(ys)
            bx2, by2 = max(xs), max(ys)
            pts_str = ' '.join(f'{x:.1f},{y:.1f}' for x,y in zip(xs,ys))
            svg = (f'  <polygon points="{pts_str}" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="{sw:.2f}"/>')

        elif tag == 'CURVE':
            segments = child.findall('SEGMENT')
            if not segments:
                continue
            d_parts = []
            for i, seg in enumerate(segments):
                x1s = xpos + px(seg.get('X1','0'))
                x2s = xpos + px(seg.get('X2','0'))
                mid_y = ypos + ch / 2
                if i == 0:
                    d_parts.append(f'M {x1s:.1f} {mid_y:.1f}')
                d_parts.append(f'Q {x1s:.1f} {ypos:.1f} {x2s:.1f} {mid_y:.1f}')
            svg = (f'  <path d="{" ".join(d_parts)}" fill="none" '
                   f'stroke="{stroke}" stroke-width="{sw:.2f}" {me_a}/>')

        if svg:
            shapes.append((svg, bx1, by1, bx2, by2))

    if not shapes:
        return ''

    # ── 2단계: 전체 bounding box 계산 → viewBox ───────────────────────
    pad = 15
    all_x1 = [s[1] for s in shapes]
    all_y1 = [s[2] for s in shapes]
    all_x2 = [s[3] for s in shapes]
    all_y2 = [s[4] for s in shapes]
    vx = min(all_x1) - pad
    vy = min(all_y1) - pad
    vw = max(all_x2) - min(all_x1) + pad * 2
    vh = max(all_y2) - min(all_y1) + pad * 2

    # 표시 크기 (최대 700px 너비로 스케일)
    disp_w = min(700, vw)
    disp_h = vh * (disp_w / vw)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xhtml="http://www.w3.org/1999/xhtml" '
        f'viewBox="{vx:.1f} {vy:.1f} {vw:.1f} {vh:.1f}" '
        f'width="{disp_w:.0f}" height="{disp_h:.0f}" '
        f'style="display:block;margin:1em auto;overflow:visible;">',
        '  <defs>',
        '    <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">',
        '      <path d="M0,0 L0,6 L7,3 z" fill="#000"/>',
        '    </marker>',
        '  </defs>',
    ]
    lines += [s[0] for s in shapes]
    lines.append('</svg>')
    return '\n'.join(lines)


# ──────────────────────────────────────────────
# 3. 메인 변환기 클래스
# ──────────────────────────────────────────────

class HmlConverter:
    def __init__(self, hml_path, render_svg=True, media_dir=None, fallback_images=None):
        self.hml_path  = hml_path
        self.render_svg = render_svg
        # media 폴더: HTML 파일과 같은 디렉토리의 'media' 서브폴더
        self.media_dir = media_dir  # 절대 경로 (None이면 base64 embed 방식)
        self.media_counter = 0      # 미디어 파일 번호
        self.container_counter = 0
        self.fallback_images = list(fallback_images or [])
        self.media_prefix = self._build_media_prefix()
        self.tree = ET.parse(hml_path)
        self.root = self.tree.getroot()

        # 스타일 테이블 로드
        self.para_shapes = {}   # Id → attrib
        self.char_shapes  = {}   # Id → attrib
        self.font_faces   = {}   # (lang, font Id) → name
        self.border_fills = {}   # Id → side styles
        self.styles       = {}   # Id → attrib
        self._load_styles()

        # 수식 InstId → SCRIPT 텍스트 매핑 (전체 문서)
        self.eq_script_map = {}
        self._build_eq_map()

        # 이미지 BinData → base64 매핑
        self.bin_images = {}
        self._load_images()

        # 각주 카운터
        self.footnote_counter = 0
        self.footnotes = []

    def _build_media_prefix(self) -> str:
        base_name = os.path.splitext(os.path.basename(self.hml_path))[0]
        prefix = re.sub(r'\s+', '_', base_name.strip())
        prefix = re.sub(r'[\\/:*?"<>|]+', '_', prefix)
        prefix = re.sub(r'_+', '_', prefix).strip('_')
        return prefix or 'img'

    def _load_styles(self):
        for fontface in self.root.findall('.//FACENAMELIST/FONTFACE'):
            lang = fontface.get('Lang', '')
            for font in fontface.findall('FONT'):
                fid = font.get('Id')
                name = font.get('Name')
                if fid and name:
                    self.font_faces[(lang, fid)] = name
        for ps in self.root.iter('PARASHAPE'):
            self.para_shapes[ps.get('Id')] = ps.attrib
        for border_fill in self.root.iter('BORDERFILL'):
            fill_data = {
                child.tag: dict(child.attrib)
                for child in border_fill
                if child.tag in {'LEFTBORDER', 'RIGHTBORDER', 'TOPBORDER', 'BOTTOMBORDER'}
            }
            fillbrush = border_fill.find('FILLBRUSH')
            if fillbrush is not None:
                window = fillbrush.find('WINDOWBRUSH')
                gradation = fillbrush.find('GRADATION')
                if window is not None:
                    fill_data['__fill__'] = {'type': 'solid', **dict(window.attrib)}
                elif gradation is not None:
                    colors = [c.get('Value', '') for c in gradation.findall('COLOR')]
                    fill_data['__fill__'] = {
                        'type': 'gradient', **dict(gradation.attrib), 'colors': colors
                    }
            self.border_fills[border_fill.get('Id')] = fill_data
        for cs in self.root.iter('CHARSHAPE'):
            attrib = dict(cs.attrib)
            attrib['bold'] = cs.find('BOLD') is not None
            attrib['italic'] = cs.find('ITALIC') is not None
            attrib['subscript'] = cs.find('SUBSCRIPT') is not None
            attrib['superscript'] = cs.find('SUPERSCRIPT') is not None
            fontid = cs.find('FONTID')
            if fontid is not None:
                attrib['hangul_font_id'] = fontid.get('Hangul')
                attrib['latin_font_id'] = fontid.get('Latin')
            self.char_shapes[cs.get('Id')] = attrib
        for st in self.root.iter('STYLE'):
            self.styles[st.get('Id')] = st.attrib

    def _charshape_uses_gothic_math(self, charshape_id: str | None) -> bool:
        cs = self.char_shapes.get(charshape_id or '', {})
        font_names = [
            self.font_faces.get(('Hangul', cs.get('hangul_font_id') or ''), ''),
            self.font_faces.get(('Latin', cs.get('latin_font_id') or ''), ''),
        ]
        return any(
            name and any(keyword in name for keyword in ('고딕', 'Gothic', '돋움'))
            for name in font_names
        )

    def _build_eq_map(self):
        """전체 문서에서 EQUATION > SHAPEOBJECT InstId → SCRIPT 텍스트 매핑"""
        for eq in self.root.iter('EQUATION'):
            so = eq.find('SHAPEOBJECT')
            sc = eq.find('SCRIPT')
            if so is not None and sc is not None:
                inst_id = so.get('InstId')
                if inst_id and sc.text:
                    self.eq_script_map[inst_id] = sc.text

    def _load_images(self):
        """BINDATA 태그에서 base64 이미지 추출 + BINITEM으로 포맷 매핑"""
        # BINITEM: BinData ID → Format 매핑
        fmt_map = {}
        for bi in self.root.iter('BINITEM'):
            bid = bi.get('BinData')
            fmt = bi.get('Format', 'png')
            if bid:
                fmt_map[bid] = fmt

        # BINDATA: Id 속성으로 직접 매핑 (enumerate 순번 아님)
        for bd in self.root.iter('BINDATA'):
            bid = bd.get('Id')  # Id 속성 사용
            if not bid:
                continue
            fmt = fmt_map.get(bid, 'png')
            if bd.text:
                # 줄바꿈/공백 제거 (data URI에 whitespace 있으면 브라우저가 로드 못함)
                clean_b64 = re.sub(r'\s+', '', bd.text)
                self.bin_images[bid] = (fmt, clean_b64)

    # ── 단락(P) 변환 ──────────────────────────────

    def _get_heading_tag(self, p_elem) -> str:
        """P 태그의 CharShape Height/Bold 기반으로 제목 레벨 결정"""
        plain_text = ''.join(
            child.text or ''
            for text_elem in p_elem.findall('TEXT')
            for child in text_elem
            if child.tag == 'CHAR'
        ).strip()
        # 글머리표가 붙은 평문을 굵다는 이유만으로 제목으로 오인하지 않는다.
        if plain_text.startswith(('○', '◦', '●', '•', '·', '■', '□', '◆', '◇')):
            return 'p'
        if any(
            child.tag in {'EQUATION', 'TABLE', 'CONTAINER', 'PICTURE'}
            for text_elem in p_elem.findall('TEXT')
            for child in text_elem
        ):
            return 'p'
        # 첫 번째 TEXT의 CharShape 기준
        for text_elem in p_elem.findall('TEXT'):
            cid = text_elem.get('CharShape', '0')
            cs = self.char_shapes.get(cid, {})
            height = int(cs.get('Height', '1000'))
            bold = cs.get('bold', False)
            if height >= 2000:
                return 'h1'
            elif height >= 1500:
                return 'h2'
            elif height >= 1200:
                return 'h3'
            elif bold and height >= 1000:
                return 'h4'
            break
        return 'p'

    def para_to_html(
        self,
        p_elem,
        *,
        allow_heading: bool = True,
        preserve_empty: bool = True,
    ) -> str:
        """P 태그 → HTML 단락"""
        tag = self._get_heading_tag(p_elem) if allow_heading else 'p'

        # 내용 변환
        content = self.textblock_to_html(p_elem)

        if not content.strip():
            if preserve_empty:
                return '<div class="hml-empty" aria-hidden="true"></div>\n'
            return ''

        # 한글의 표는 문단 안 개체로 저장되지만 HTML에서 <p><table>은 유효하지 않다.
        stripped = content.strip()
        if stripped.startswith('<table') and stripped.endswith('</table>'):
            return content

        style_parts = []
        para_shape = self.para_shapes.get(p_elem.get('ParaShape', ''), {})
        align = ALIGN_MAP.get(para_shape.get('Align', ''))
        if align:
            style_parts.append(f'text-align:{align}')
        if 'class="hml-figure' in content:
            style_parts.append('margin:0.1em 0')
        style_attr = f' style="{";".join(style_parts)}"' if style_parts else ''

        # h 태그 앞에 두 줄 띄기 + <br> (가독성 + 시각적 여백)
        if tag.startswith('h'):
            return f'\n\n<{tag}{style_attr}><br>{content}</{tag}>\n'

        return f'<{tag}{style_attr}>{content}</{tag}>\n'

    def textblock_to_html(self, elem) -> str:
        """TEXT/CHAR/EQUATION/TABLE/CONTAINER 등이 섞인 블록을 HTML로.
        elem은 P 태그. TABLE 등 특수 객체 안의 TEXT는 순회하지 않음.
        """
        parts = []
        # elem.iter('TEXT')는 TABLE 안 TEXT까지 순회하므로
        # P 직계 자식 TEXT만 처리 + 직계 TABLE/CONTAINER/PICTURE는 별도 처리
        self._render_p_children(elem, parts)
        return ''.join(parts)

    def _render_p_children(self, elem, parts):
        """P의 직계 자식을 문단 단위로 렌더링.
        연속된 TEXT 형제는 한 버퍼에 모아 plain-text 수식 보정을 적용한다.
        """
        text_buffer = []

        def flush_text_buffer():
            if text_buffer:
                parts.append(self.char_to_html(''.join(text_buffer)))
                text_buffer.clear()

        for child in elem:
            tag = child.tag

            if tag == 'TEXT':
                for token_type, token_value in self._collect_text_tokens(child):
                    if token_type == 'text':
                        text_buffer.append(token_value)
                    else:
                        flush_text_buffer()
                        parts.append(token_value)

            elif tag == 'TABLE':
                flush_text_buffer()
                parts.append(self.table_to_html(child))

            elif tag == 'CONTAINER':
                flush_text_buffer()
                parts.append(self.container_to_html(child))

            elif tag == 'PICTURE':
                flush_text_buffer()
                parts.append(self.picture_to_html(child))

        flush_text_buffer()

    def _collect_text_tokens(self, text_elem):
        """TEXT 태그 안의 내용을 텍스트/비텍스트 토큰으로 분리한다."""
        char_buffer = []
        char_shape = self.char_shapes.get(text_elem.get('CharShape', ''), {})
        script_tag = (
            'sub' if char_shape.get('subscript')
            else 'sup' if char_shape.get('superscript')
            else None
        )

        def flush_char_buffer():
            if char_buffer:
                yield ('text', ''.join(char_buffer))
                char_buffer.clear()

        for child in text_elem:
            tag = child.tag

            if tag == 'CHAR':
                if child.text:
                    if script_tag:
                        yield from flush_char_buffer()
                        rendered = self.char_to_html(child.text)
                        yield ('html', f'<{script_tag}>{rendered}</{script_tag}>')
                    else:
                        char_buffer.append(child.text)

            elif tag == 'EQUATION':
                yield from flush_char_buffer()
                so = child.find('SHAPEOBJECT')
                sc = child.find('SCRIPT')
                inst_id = so.get('InstId') if so is not None else None
                script_text = sc.text if sc is not None else None
                if not script_text and inst_id:
                    script_text = self.eq_script_map.get(inst_id, '')
                if script_text:
                    latex = hwp_script_to_latex(
                        script_text,
                        force_bold_math=self._charshape_uses_gothic_math(text_elem.get('CharShape')),
                    )
                    safe_latex = html.escape(latex, quote=False)
                    yield ('html', f'<span class="math">{safe_latex}</span>')

            elif tag == 'TABLE':
                yield from flush_char_buffer()
                yield ('html', self.table_to_html(child))

            elif tag == 'CONTAINER':
                yield from flush_char_buffer()
                yield ('html', self.container_to_html(child))

            elif tag == 'PICTURE':
                yield from flush_char_buffer()
                yield ('html', self.picture_to_html(child))

            elif tag == 'FOOTNOTE':
                yield from flush_char_buffer()
                self.footnote_counter += 1
                fn_num = self.footnote_counter
                fn_content = self.paralist_to_html(child.find('PARALIST'))
                self.footnotes.append((fn_num, fn_content))
                yield ('html', f'<sup><a id="fnref{fn_num}" href="#fn{fn_num}">[{fn_num}]</a></sup>')

            elif tag == 'TAB':
                yield from flush_char_buffer()
                yield ('html', '&ensp;')

            elif tag == 'AUTONUM':
                continue

        yield from flush_char_buffer()

    def _is_block_equation(self, parent_p) -> bool:
        """P 단락 전체가 수식 단독인지 판단 (블록 수식 여부).
        의미있는 텍스트가 없고 수식이 정확히 1개면 블록.
        """
        meaningful_text = ''
        eq_count = 0
        for text in parent_p:  # 직계 자식 TEXT만
            if text.tag != 'TEXT':
                continue
            for child in text:
                if child.tag == 'CHAR' and child.text:
                    t = child.text.strip()
                    # 번호 표시(①~㉠ 등), 점선, 화살표 기호, 공백 제외
                    t_clean = re.sub(
                        r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫'
                        r'㉠㉡㉢㉣㉤ⓐⓑⓒ'
                        r'.…·•⇒∴∵≥≤'
                        r'\s\t,]', '', t)
                    meaningful_text += t_clean
                elif child.tag == 'EQUATION':
                    eq_count += 1
        return len(meaningful_text) <= 4 and eq_count == 1

    def char_to_html(self, text: str) -> str:
        # 일반 텍스트는 HML 구조 그대로 평문으로 렌더링한다.
        # 수식 클래스 부여는 EQUATION/SCRIPT 노드에서만 처리한다.
        return html.escape(text)

    def paralist_to_html(self, paralist_elem, *, cell_mode: bool = False) -> str:
        """PARALIST 내 여러 P를 HTML로"""
        if paralist_elem is None:
            return ''
        parts = []
        for p in paralist_elem.findall('P'):
            parts.append(
                self.para_to_html(
                    p,
                    allow_heading=not cell_mode,
                    preserve_empty=True,
                )
            )
        return ''.join(parts)

    # ── 표 변환 ──────────────────────────────────

    def table_to_html(self, table_elem) -> str:
        """TABLE → HTML <table>"""
        return render_shared_table(
            table_elem,
            self.border_fills,
            lambda cell: self.paralist_to_html(cell.find('PARALIST'), cell_mode=True),
        )

    # ── 이미지 변환 ──────────────────────────────

    def _save_media(self, data_bytes: bytes, ext: str) -> str:
        """media 폴더에 파일 저장 후 상대경로 반환"""
        rel_path, fpath = self._next_media_path(ext)
        with open(fpath, 'wb') as f:
            f.write(data_bytes)
        return rel_path

    def _next_media_path(self, ext: str) -> tuple[str, str]:
        """다음 미디어 파일의 상대경로/절대경로 반환"""
        self.media_counter += 1
        fname = f'{self.media_prefix}_{self.media_counter:03d}.{ext}'
        fpath = os.path.join(self.media_dir, fname)
        return f'media/{fname}', fpath

    def picture_to_html(self, pic_elem) -> str:
        """PICTURE → HTML <img>"""
        img = pic_elem.find('.//IMAGE')
        if img is None:
            return ''
        bin_id = img.get('BinItem')
        if not bin_id or bin_id not in self.bin_images:
            return '<div class="img-placeholder">[이미지]</div>\n'
        fmt, b64 = self.bin_images[bin_id]

        if not self.media_dir:
            return '<div class="img-placeholder">[이미지 파일 경로 필요]</div>\n'

        img_bytes = base64.b64decode(b64)
        rel_path = self._save_media(img_bytes, fmt)
        return f'<img src="{rel_path}" style="max-width:100%;">\n'

    def container_to_html(self, ct_elem) -> str:
        """CONTAINER → GTree(편집용) + SVG(표시용), 실패 시 한글 GIF 대체."""
        self.container_counter += 1
        index = self.container_counter
        try:
            from hml_to_gtree import GTreeBuilder
            from gtree_to_svg import render as render_gtree_svg

            builder = GTreeBuilder(sys.modules[__name__])
            builder._root = self.root
            builder.consume_container(ct_elem)
            data = builder.build()
            svg = render_gtree_svg(data)
            if self.media_dir:
                stem = f'{self.media_prefix}_graph_{index:03d}'
                gtree_path = os.path.join(self.media_dir, stem + '.gtree')
                svg_path = os.path.join(self.media_dir, stem + '.svg')
                with open(gtree_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                with open(svg_path, 'w', encoding='utf-8') as f:
                    f.write(svg)
            return f'<span class="hml-figure editable-gtree">{svg}</span>\n'
        except Exception as exc:
            if index <= len(self.fallback_images) and self.media_dir:
                source = self.fallback_images[index - 1]
                ext = os.path.splitext(source)[1] or '.gif'
                name = f'{self.media_prefix}_graph_{index:03d}_fallback{ext}'
                target = os.path.join(self.media_dir, name)
                shutil.copy2(source, target)
                return (
                    '<span class="hml-figure fallback-image">'
                    f'<img src="media/{name}" style="max-width:100%;">'
                    '</span>\n'
                )
            return f'<div class="img-placeholder">[그리기 개체 변환 실패: {html.escape(str(exc))}]</div>\n'

    # ── 메인 변환 루프 ────────────────────────────

    def convert(self) -> str:
        """전체 HML → HTML 변환"""
        body_parts = []

        section = self.root.find('.//SECTION')
        if section is None:
            print("오류: SECTION을 찾을 수 없습니다.")
            return ''

        # 페이지 단위가 아닌 요소 단위로 순회
        for elem in self._iter_body_elements(section):
            tag = elem.tag

            if tag == 'P':
                html_p = self.para_to_html(elem)
                if html_p:
                    body_parts.append(html_p)

            elif tag == 'TABLE':
                body_parts.append(self.table_to_html(elem))

            elif tag == 'PICTURE':
                body_parts.append(self.picture_to_html(elem))

            elif tag == 'CONTAINER':
                body_parts.append(self.container_to_html(elem))

        # 각주 섹션
        if self.footnotes:
            body_parts.append('<hr>\n<section class="footnotes">\n<ol>\n')
            for fn_num, fn_content in self.footnotes:
                body_parts.append(
                    f'<li id="fn{fn_num}">{fn_content}'
                    f'<a href="#fnref{fn_num}">↩</a></li>\n'
                )
            body_parts.append('</ol>\n</section>\n')

        return self._wrap_html(''.join(body_parts))

    def _iter_body_elements(self, section):
        """SECTION 하위를 순회하며 최상위 요소만 yield (재귀 방지)"""
        for child in section:
            yield child

    def _wrap_html(self, body: str) -> str:
        title = '변환된 문서'
        for st in self.root.iter('TITLE'):
            if st.text:
                title = st.text
                break
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>

<!-- KaTeX 수식 렌더링 -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script>
(function() {{
  function renderAllMath() {{
    document.querySelectorAll('span.math').forEach(function(el) {{
      katex.render(el.textContent, el, {{throwOnError: false, displayMode: false}});
    }});
  }}
  var script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js';
  script.onload = renderAllMath;
  document.head.appendChild(script);
}})();
</script>

<style>
  body {{
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 2em;
    line-height: 1.5;
    color: #222;
    background: #fff;
  }}
  h1 {{ font-size: 1.8em; border-bottom: 2px solid #333; padding-bottom: .3em; margin-top: 1.5em; }}
  h2 {{ font-size: 1.5em; border-bottom: 1px solid #999; padding-bottom: .2em; margin-top: 1.3em; }}
  h3 {{ font-size: 1.2em; margin-top: 1.1em; color: #444; }}
  h4, h5, h6 {{ font-size: 1.05em; margin-top: 1em; color: #555; }}
  p  {{ margin: 0; }}
  .hml-empty {{ height: 1.5em; line-height: 1.5em; }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 2em auto;
    font-size: 10pt;
  }}
  td, th {{
    border: 1px solid #aaa;
    padding: 6px 10px;
    vertical-align: top;
  }}
  table p {{
    margin: 0;
  }}
  tr:nth-child(even) td {{ background: #f9f9f9; }}
  .hml-figure {{
    display: block;
    margin: 0.15em auto;
    text-align: center;
    overflow-x: auto;
  }}
  .hml-figure svg {{ margin: 0 auto !important; }}
  .img-placeholder {{
    background: #f0f0f0;
    border: 1px dashed #aaa;
    padding: 1em;
    text-align: center;
    color: #888;
    margin: 1em 0;
  }}
  .footnotes {{
    font-size: 0.85em;
    color: #555;
  }}
  .footnotes li {{ margin-bottom: .4em; }}
  sup a {{ color: #0066cc; text-decoration: none; }}
  sup a:hover {{ text-decoration: underline; }}
  .katex-display {{ overflow-x: auto; overflow-y: hidden; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


# ──────────────────────────────────────────────
# 4. CLI 진입점
# ──────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("사용법: python3 hml2html.py input.hml output.html")
        sys.exit(1)

    hml_path  = sys.argv[1]
    html_path = sys.argv[2]

    if not os.path.exists(hml_path):
        print(f"오류: 파일을 찾을 수 없습니다 - {hml_path}")
        sys.exit(1)

    # HTML 파일 위치 기준으로 media 서브폴더 생성
    html_dir   = os.path.dirname(os.path.abspath(html_path))
    media_dir  = os.path.join(html_dir, 'media')
    os.makedirs(media_dir, exist_ok=True)

    print(f"변환 중: {hml_path}")
    converter = HmlConverter(hml_path, media_dir=media_dir)

    html_output = converter.convert()

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_output)

    print(f"완료: {html_path}")
    print(f"  - 수식 {len(converter.eq_script_map)}개")
    print(f"  - 각주 {converter.footnote_counter}개")
    print(f"  - 이미지 {len(converter.bin_images)}개")
    print(f"  - 미디어 파일 {converter.media_counter}개 → {media_dir}")

if __name__ == '__main__':
    main()
