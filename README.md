# hwp2html

HWP/HML 문서를 HTML, GTree, TikZ로 변환하기 위한 작업 폴더입니다.

현재 이 폴더의 핵심 목표는 두 가지입니다.

1. HWP/HML의 그림 요소를 최대한 손실 없이 `web-image-editor-object`에서 다시 편집할 수 있는 `.gtree`로 변환
2. 필요하면 그 결과를 다시 `TikZ .wtkiz`로 내보내기

참고:

- `.gtree`는 전용 바이너리 포맷이 아니라, 사실상 `web-image-editor-object`가 읽고 쓰는 JSON 파일입니다.
- `.wtikz`도 전용 바이너리 포맷이 아니라, `web-tikz`가 읽고 쓰는 JSON 파일입니다.
- 즉 두 형식 모두 “확장자만 다를 뿐 내부는 JSON”이라고 보면 됩니다.

HTML 변환 실험도 남아 있지만, 현재 실사용 중심 파이프라인은 아래 흐름입니다.

`HWP -> HML -> GTree -> web-image-editor-object -> TikZ`

## 현재 남은 파이썬 스크립트

### 1. `hml_to_gtree.py`

이 폴더에서 가장 중요한 변환기입니다.

- 역할: `HML/XML(+XSL) -> .gtree`
- 대상: HWP 그림, 도형, 선, 곡선, 호, 텍스트, 이미지
- 출력: `web-image-editor-object`에서 바로 불러올 수 있는 JSON 기반 `.gtree`

현재 이 스크립트는 다음 용도로 보는 것이 가장 자연스럽습니다.

- `graph1.hml`, `graph3.hml`, `graph4.hml`, `graph5.hml`, `graph6.hml` 같은 그림 테스트 파일 변환
- HWP 그림을 편집 가능한 오브젝트 구조로 옮기기

예시:

```bash
python hml_to_gtree.py graph1.hml graph1.gtree
python hml_to_gtree.py graph6.hml graph6.gtree
```

### 2. `gtree_to_tikz.py`

`.gtree`를 TikZ 코드로 바꾸는 후단 변환기입니다.

- 역할: `.gtree -> .tex`
- 좌표계: `40px = 1cm`
- 사용처: `web-image-editor-object`에서 만든 결과를 TikZ로 내보내기

예시:

```bash
python gtree_to_tikz.py graph6.gtree graph6.tex
```

### 3. `hml2html.py`

가장 범용적인 HML -> HTML 변환기입니다.

- 역할: 본문, 제목, 수식, 표, 각주, 이미지까지 포함한 전체 문서 HTML 변환
- 특징: 수식은 KaTeX 기반, 표는 `hml_table_renderer.py`를 사용
- 용도: “그림만”이 아니라 문서 전체를 HTML로 보고 싶을 때

예시:

```bash
python hml2html.py input.hml output.html
```

### 4. `hml_table_renderer.py`

표 렌더링 전용 보조 모듈입니다.

- 역할: HML 표의 열 너비, 행 높이, 셀 병합, 테두리, 패딩, 정렬 계산
- 직접 실행용이라기보다 `hml2html.py`에서 import 해서 사용

즉 이 파일은 단독 스크립트라기보다 `hml2html.py`의 표 엔진입니다.

### 5. `resume_hml_to_html.py`

HTML 변환의 별도 실험판입니다.

- 역할: HML -> HTML
- 특징: 페이지 크기, 여백, 문단 스타일, 글꼴, 표 정렬 등 레이아웃 충실도를 더 세밀하게 맞추려는 버전
- 용도: `hml2html.py`와 결과를 비교하거나, 특정 문서에서 더 나은 HTML 결과가 나오는지 실험할 때

즉 이 파일은 현재 “보조/실험용 HTML 변환기”에 가깝습니다.

## 추천 사용 순서

### 그림 편집이 목적일 때

1. HWP를 HML로 변환
2. `hml_to_gtree.py`로 `.gtree` 생성
3. `web-image-editor-object`에서 `.gtree` 불러오기
4. 필요하면 `gtree_to_tikz.py` 또는 에디터의 TikZ 저장 기능 사용

### 문서 전체 HTML이 목적일 때

1. HWP를 HML로 변환
2. `hml2html.py` 실행
3. 결과가 부족하면 `resume_hml_to_html.py`와 비교
